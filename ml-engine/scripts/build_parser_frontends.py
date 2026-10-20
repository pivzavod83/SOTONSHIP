#!/usr/bin/env python3
"""Build the pinned offline parser worker in a repository-local cache.

This builds the parser tools, never any submitted COBOL or Java program.
No Python dependencies, user-wide Maven installation, or global Maven cache is
required. Maven and a full JDK >=17 must already be available.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
from datetime import datetime, timezone
import xml.etree.ElementTree as ET
import zipfile


ENGINE_ROOT = Path(__file__).resolve().parents[1]
MODULE = ENGINE_ROOT / "parser-frontends"
CACHE = ENGINE_ROOT / "evaluation" / "corpora" / "parser-v3"
PROLEAP_REPOSITORY = "https://github.com/uwol/proleap-cobol-parser.git"
PROLEAP_COMMIT = "d1bfe75bdd6d480f70c74c6345bcc02610ac30d3"
DEPENDENCY_PLUGIN = "org.apache.maven.plugins:maven-dependency-plugin:3.8.1"


def digest(path: Path) -> str:
    value = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def run(arguments: list[str], *, cwd: Path | None = None,
        environment: dict[str, str] | None = None, capture: bool = False) -> str:
    print("+ " + shlex.join(arguments), file=sys.stderr, flush=True)
    result = subprocess.run(arguments, cwd=cwd, env=environment, check=True,
                            text=True, capture_output=capture)
    return (result.stdout + result.stderr).strip() if capture else ""


def verify_source(source: Path) -> dict[str, object]:
    root = Path(run(["git", "-C", str(source), "rev-parse", "--show-toplevel"], capture=True)).resolve()
    if root != source.resolve():
        raise ValueError(f"ProLeap source must be a checkout root: {source}")
    actual = run(["git", "-C", str(source), "rev-parse", "HEAD"], capture=True)
    if actual != PROLEAP_COMMIT:
        raise ValueError(f"Refusing to modify/use checkout at {actual}; expected {PROLEAP_COMMIT}.")
    tracked_changes = run(["git", "-C", str(source), "status", "--porcelain=v1",
                           "--untracked-files=no"], capture=True)
    if tracked_changes:
        raise ValueError("ProLeap checkout has tracked modifications; refusing to overwrite them.")
    license_path = source / "LICENSE"
    return {
        "repository": PROLEAP_REPOSITORY,
        "commit": actual,
        "trackedSourceClean": True,
        "license": "MIT",
        "licenseSha256": digest(license_path) if license_path.is_file() else None,
        "sourceDirectory": str(source),
    }


def prepare_source(supplied: Path | None) -> tuple[Path, dict[str, object]]:
    source = supplied.expanduser().resolve() if supplied else CACHE / "proleap-source"
    if not source.exists():
        if supplied:
            raise ValueError(f"Explicit ProLeap source does not exist: {source}")
        source.parent.mkdir(parents=True, exist_ok=True)
        # Never reset or replace an existing checkout. Fetching/checking out is
        # permitted only in this new, private build-cache directory.
        run(["git", "clone", "--no-checkout", "--filter=blob:none", PROLEAP_REPOSITORY, str(source)])
        run(["git", "-C", str(source), "fetch", "--depth", "1", "origin", PROLEAP_COMMIT])
        run(["git", "-C", str(source), "checkout", "--detach", PROLEAP_COMMIT])
    return source, verify_source(source)


def dependency_receipt(jar: Path, local_repository: Path) -> list[dict[str, object]]:
    """Read exact artifact identities embedded in the shaded runtime jar."""
    dependencies: list[dict[str, object]] = []
    with zipfile.ZipFile(jar) as archive:
        for name in sorted(archive.namelist()):
            if not name.startswith("META-INF/maven/") or not name.endswith("/pom.properties"):
                continue
            properties = {}
            for line in archive.read(name).decode("utf-8").splitlines():
                if line and not line.startswith("#") and "=" in line:
                    key, value = line.split("=", 1)
                    properties[key.strip()] = value.strip()
            if not {"groupId", "artifactId", "version"} <= properties.keys():
                continue
            group, artifact, version = (properties[key] for key in ("groupId", "artifactId", "version"))
            if group == "org.omul" and artifact == "parser-frontends":
                continue
            artifact_path = local_repository / group.replace(".", "/") / artifact / version / f"{artifact}-{version}.jar"
            dependencies.append({
                "coordinate": f"{group}:{artifact}:{version}",
                "sha256": digest(artifact_path) if artifact_path.is_file() else None,
                "jarMetadata": name,
            })
    return dependencies


def test_counts() -> dict[str, int]:
    counts = {"tests": 0, "failures": 0, "errors": 0, "skipped": 0}
    for report in (MODULE / "target" / "surefire-reports").glob("TEST-*.xml"):
        suite = ET.parse(report).getroot()
        for key in counts:
            counts[key] += int(suite.attrib.get(key, "0"))
    if not counts["tests"] or counts["failures"] or counts["errors"]:
        raise ValueError(f"Expected passing frontend tests; got {counts}")
    return counts


def build(options: argparse.Namespace) -> Path:
    maven = shutil.which(options.maven)
    if not maven:
        raise ValueError("Maven was not found; provide --maven /path/to/mvn.")
    environment = os.environ.copy()
    if options.java_home:
        environment["JAVA_HOME"] = str(options.java_home.expanduser().resolve())
    java_home = environment.get("JAVA_HOME")
    java = str(Path(java_home) / "bin" / "java") if java_home else shutil.which("java")
    javac = str(Path(java_home) / "bin" / "javac") if java_home else shutil.which("javac")
    if not java or not javac or not Path(java).is_file() or not Path(javac).is_file():
        raise ValueError("A full JDK >=17 is required; provide --java-home /path/to/jdk.")
    java_version = run([java, "-version"], environment=environment, capture=True)
    javac_version = run([javac, "-version"], environment=environment, capture=True)
    matched = re.search(r"javac\s+(\d+)", javac_version)
    if not matched or int(matched.group(1)) < 17:
        raise ValueError(f"JDK >=17 is required, found {javac_version}")
    maven_version = run([maven, "--version"], environment=environment, capture=True)
    source, source_receipt = prepare_source(options.proleap_source)
    repository = CACHE / "m2"
    repository.mkdir(parents=True, exist_ok=True)
    common = [maven, "--batch-mode", "--no-transfer-progress", f"-Dmaven.repo.local={repository}"]
    run(common + ["-Dmaven.test.skip=true", "clean", "install"], cwd=source, environment=environment)
    # Catch source-generating tools that unexpectedly edit tracked files.
    verify_source(source)
    run(common + ["clean", "package"], cwd=MODULE, environment=environment)
    tests = test_counts()
    jar = MODULE / "target" / "parser-frontends-3.0.0.jar"
    if not jar.is_file():
        raise ValueError(f"Packaged worker is missing: {jar}")
    # Store the resolved dependency tree as additional, local provenance.
    tree_path = MODULE / "target" / "runtime-dependencies.txt"
    run(common + [f"{DEPENDENCY_PLUGIN}:tree", "-Dscope=runtime", "-DoutputType=text",
                  f"-DoutputFile={tree_path}"], cwd=MODULE, environment=environment)
    receipt = {
        "schemaVersion": 1,
        "artifact": "experimental-parser-frontends-v3-bootstrap",
        "builtAt": datetime.now(timezone.utc).isoformat(),
        "proleap": source_receipt,
        "toolchain": {"java": java, "javac": javac, "javaVersion": java_version,
                      "javacVersion": javac_version, "maven": maven, "mavenVersion": maven_version},
        "mavenRepository": str(repository),
        "pomSha256": digest(MODULE / "pom.xml"),
        "moduleSources": {
            str(path.relative_to(MODULE)): digest(path)
            for path in sorted((MODULE / "src").rglob("*.java"))
        },
        "jar": {"path": str(jar), "sha256": digest(jar), "bytes": jar.stat().st_size},
        "runtime": {"command": [java, "-Xmx768m", "-jar", str(jar)],
                    "classpath": [str(jar)], "dependencies": dependency_receipt(jar, repository),
                    "dependencyTreeSha256": digest(tree_path)},
        "tests": tests,
        "upstreamTestsRun": False,
        "submittedProgramsExecuted": False,
        "bitForBitReproducibilityClaimed": False,
    }
    serialized = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    for destination in (CACHE / "build-receipt.json", MODULE / "target" / "toolchain.json"):
        destination.write_text(serialized, encoding="utf-8")
    return jar


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maven", default="mvn", help="Maven executable; default: mvn on PATH")
    parser.add_argument("--java-home", type=Path, help="Full JDK home (17 or newer)")
    parser.add_argument("--proleap-source", type=Path,
                        help="Optional existing clean checkout at the exact pinned commit")
    options = parser.parse_args()
    try:
        jar = build(options)
    except (OSError, ValueError, subprocess.CalledProcessError, ET.ParseError, zipfile.BadZipFile) as error:
        print(f"Parser frontend bootstrap failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps({"jar": str(jar), "receipt": str(MODULE / "target" / "toolchain.json")}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
