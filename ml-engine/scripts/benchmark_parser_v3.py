#!/usr/bin/env python3
"""Compare compiler frontend stages on the frozen CodeNet coverage cohort, offline."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml_engine.parser_frontends_v3 import (FrontendWorker, aggregate, compiler_check, compact_frontend,
    DEFAULT_JAR, MAX_SOURCE_BYTES, phase_outcomes, unknown_result, STAGES)


def sha(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def write_new(path: Path, value: dict):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")


def read_source(corpus: Path, record: dict) -> str | None:
    relative = PurePosixPath(record["path"])
    if relative.is_absolute() or ".." in relative.parts or "\\" in record["path"] or len(relative.parts) != 4:
        raise ValueError("Unsafe frozen source path")
    if relative.parts[:3] != ("data", record["problemId"], record["language"]):
        raise ValueError("Source identity/path mismatch")
    path = corpus
    for part in relative.parts:
        path = path / part
        if path.is_symlink():
            raise ValueError("Source symlink is not allowed")
    if not path.is_file() or not path.resolve().is_relative_to(corpus.resolve()):
        raise ValueError("Source missing/outside corpus")
    if path.stat().st_size > MAX_SOURCE_BYTES:
        if sha(path) != record["sha256"]:
            raise ValueError("Frozen source hash changed")
        return None
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != record["sha256"]:
        raise ValueError("Frozen source hash changed")
    try:
        return raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return None


def combined(records: list[dict]) -> dict:
    return {stage: "PASS" if all(r["outcomes"][stage] == "PASS" for r in records) else
                   "FAIL" if any(r["outcomes"][stage] == "FAIL" for r in records) else "UNKNOWN" for stage in STAGES}


def run(args):
    output, corpus = args.output, args.corpus.resolve()
    if output.exists():
        raise ValueError("Experiment output already exists; use a new version")
    if not args.jar.is_file():
        raise ValueError("Build the versioned parser frontend JAR first")
    baseline_path = ROOT / "evaluation/codenet/import-v1/extractor-coverage.json"
    baseline_hashes = json.loads((ROOT / "evaluation/codenet/import-v1/artifact-hashes.json").read_text())
    repo = ROOT.parent
    for path, expected in baseline_hashes["files"].items():
        if sha(repo / path) != expected:
            raise ValueError(f"Frozen baseline evidence changed: {path}")
    baseline = json.loads(baseline_path.read_text())
    for path, expected in baseline["implementationHashes"].items():
        if sha(ROOT / path) != expected:
            raise ValueError(f"Historical typed IR implementation changed: {path}")
    inventory_path = corpus / "inventory.json"
    if sha(inventory_path) != baseline["inventorySha256"]:
        raise ValueError("CodeNet inventory differs from frozen coverage cohort")
    source_records = [("JAVA", record) for record in baseline["sourceProbes"]["Java"]]
    source_records += [(profile, record) for profile in ("FREE", "FIXED") for record in baseline["sourceProbes"]["COBOL"][profile]]
    implementation_paths = [Path(__file__), ROOT / "ml_engine/parser_frontends_v3.py", ROOT / "parser-frontends/pom.xml"]
    implementation_paths += sorted((ROOT / "parser-frontends/src").rglob("*.java"))
    implementation_paths += [ROOT / path for path in baseline["implementationHashes"]]
    implementation_hashes = {str(p.relative_to(repo)): sha(p) for p in implementation_paths}
    cobc_version = None
    if args.cobc:
        cobc_version = subprocess.run([str(args.cobc), "-V"], capture_output=True, text=True, check=True).stdout.splitlines()[0]
    protocol = {"schemaVersion": 1, "experimentId": "parser-v3", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
        "sourceArchive": baseline["sourceArchive"], "sourceCoverageReportSha256": sha(baseline_path),
        "cohort": "Exactly the frozen 650 pairs across325 CodeNet problem IDs; all1277 COBOL sources under each explicit FREE/FIXED probe,650 Java sources.",
        "selectionBeforeParsing": True, "sourceFormatInferred": False, "javaLanguageLevel": 17,
        "cobolCompilerProfile": "Configured GnuCOBOL default dialect (actual version in toolchain), explicit FREE/FIXED; upstream compiler contract unknown",
        "semanticLowerer": "Unchanged typed-semantic-ir-v2; per-source coverage reused from hash-verified frozen audit, then gated by V3 syntax/resolution.",
        "metrics": {"syntaxParsed": "Whole-source grammar parsed with no lexer/parser errors; not general compilation validity.",
            "namesTypesResolved": "Java: javac analysis succeeds and recorded bindings are complete. COBOL: complete ProLeap ASG with zero undefined references AND GnuCOBOL static check succeeds. Compiler/profile scoped, not behavioral correctness.",
            "semanticsModeled": "Earlier two stages complete AND existing bounded typed IR lowerer recorded COMPLETE for identical source/hash. Representation coverage only, not proof of faithful behavior or equivalence."},
        "upstreamProgramsExecuted": False, "modelTrained": False, "trainingEligible": False,
        "toolchain": {"jarSha256": sha(args.jar), "java": subprocess.run([args.java,"-version"], capture_output=True,text=True,check=True).stderr.splitlines()[0],
                      "cobol": cobc_version, "proleapCommit": "d1bfe75bdd6d480f70c74c6345bcc02610ac30d3"},
        "implementationHashes": implementation_hashes,
        "budgets": {"sourceBytes": MAX_SOURCE_BYTES, "frontendRequestTimeoutSeconds": args.timeout, "jvmHeapMiB": 768},
        "evaluationReuse": "Existing exposed source-coverage cohort; no classifier training, labels, threshold selection or accuracy evaluation."}
    # Freeze selection and implementation identity before collecting new outcomes.
    write_new(output / "protocol.json", protocol)
    raw_dir = ROOT / "evaluation/corpora/parser-v3" / output.name
    raw_dir.mkdir(parents=True, exist_ok=True)
    raw_path = raw_dir / "frontend-results.jsonl"
    if raw_path.exists():
        raise ValueError("Raw evidence output exists; use a distinct experiment version")
    results, examples = {}, []
    with FrontendWorker(args.jar, args.java, args.timeout) as worker, raw_path.open("x", encoding="utf-8") as raw_file:
        for index, (profile, record) in enumerate(source_records, 1):
            source = read_source(corpus, record)
            result = unknown_result("ENCODING_OR_SOURCE_BUDGET") if source is None else worker.inspect(source, record["language"], profile, record["path"])
            checked = compiler_check(source, profile, str(args.cobc) if args.cobc else None) if source is not None and record["language"] == "COBOL" else None
            item = {key: record[key] for key in ("path","sha256","language","problemId","submissionId","upstreamJudgeStatus")}
            item.update(profile=profile, frontend=compact_frontend(result), staticCompilerCheck=checked,
                        semanticIrV2Status=record["status"], outcomes=phase_outcomes(result, record["status"], record["language"], checked))
            raw_file.write(json.dumps({**item, "fullFrontend": result}, sort_keys=True) + "\n")
            results[(record["path"], profile)] = item
            if item["outcomes"]["syntaxParsed"] != "PASS" or item["outcomes"]["namesTypesResolved"] != "PASS":
                diagnostic = next(iter(result.get("syntax", {}).get("diagnostics", [])), None) or next(iter(result.get("resolution", {}).get("diagnostics", [])), None) or {}
                if len([e for e in examples if e["language"] == record["language"] and e.get("profile") == (profile if profile != "JAVA" else None)]) < 4:
                    examples.append({"language": record["language"], "profile": profile if profile != "JAVA" else None,
                        "path": record["path"], "status": result["syntax"]["status"], "line": diagnostic.get("line"),
                        "message": str(diagnostic.get("message", "Incomplete static resolution; see source result."))[:1200]})
            if index % 100 == 0:
                print(json.dumps({"processed": index, "total": len(source_records), "language": record["language"], "profile": profile}), flush=True)
    profiles, pair_results = {}, []
    for profile in ("FREE", "FIXED"):
        records = []
        for pair in baseline["pairs"]:
            item = {"problemId": pair["problemId"], "cobolSource": pair["cobolSource"], "javaSource": pair["javaSource"], "profile": profile,
                    "outcomes": combined([results[(pair["cobolSource"], profile)], results[(pair["javaSource"], "JAVA")]])}
            records.append(item)
        profiles[profile] = {"pairs": len(records), "metrics": aggregate(records)}
        pair_results.extend(records)
    java_results = [r for r in results.values() if r["language"] == "Java"]
    cobol_profiles = {}
    for profile in ("FREE", "FIXED"):
        members = [r for r in results.values() if r["language"] == "COBOL" and r["profile"] == profile]
        cobol_profiles[profile] = {"sources": len(members), "metrics": aggregate(members),
            "staticCompilerStatuses": dict(Counter((r["staticCompilerCheck"] or {}).get("status", "UNKNOWN") for r in members)),
            "compilerAcceptedButFrontendSyntaxIncomplete": sum((r["staticCompilerCheck"] or {}).get("status") == "ACCEPTED" and r["outcomes"]["syntaxParsed"] != "PASS" for r in members)}
    report = {"schemaVersion": 1, "kind": "PARSER_FRONTEND_COVERAGE", "experimentId": "parser-v3",
        "createdAtUtc": datetime.now(timezone.utc).isoformat(), "sourceArchive": baseline["sourceArchive"],
        "sourceCoverageReportSha256": sha(baseline_path), "protocolSha256": sha(output / "protocol.json"),
        "profiles": profiles, "sourcesByLanguage": {"Java": {"sources": len(java_results), "metrics": aggregate(java_results)}, "COBOL": {"profiles": cobol_profiles}},
        "baseline": {"id": "typed-v2", "profiles": {profile: {"pairs": baseline["selectedPairs"], "metrics": {
            "syntaxParsed": {"count": None,"denominator": baseline["selectedPairs"],"status":"NOT_SEPARATELY_MEASURED"},
            "namesTypesResolved": {"count": None,"denominator": baseline["selectedPairs"],"status":"NOT_SEPARATELY_MEASURED"},
            "semanticsModeled": {"count": baseline["profileResults"][profile]["bothFrontendsComplete"],"denominator": baseline["selectedPairs"],"status":"MEASURED"}}} for profile in ("FREE","FIXED")}},
        "sourceResults": list(results.values()), "pairResults": pair_results, "failureExamples": examples,
        "rawEvidence": {"path": str(raw_path.relative_to(ROOT)), "sha256": sha(raw_path)},
        "sourcesExecuted": False, "modelTrained": False, "modelInferencePerformed": False,
        "accuracy": None, "recall": None, "trainingEligible": False, "semanticLabels": "UNKNOWN",
        "limitations": ["Syntax and compiler acceptance do not prove semantic equivalence; CodeNet same-problem programs are not established translations.",
            "FREE/FIXED are separate explicit probes; Java17 and GnuCOBOL3.2 default are experimental profiles, not inferred original compiler contracts.",
            "ProLeap does not support every GNU/IBM extension, and its ASG alone is not complete type checking.",
            "COPY/REPLACE dependencies require a future explicit copybook contract; preprocessing source maps may be PREPROCESSED_ONLY.",
            "Semantic coverage uses the unchanged bounded V2 IR lowerer; broad grammar ASTs are not complete behavior models.",
            "This reused source-coverage cohort has no reviewed semantic defect labels and cannot produce classifier accuracy."]}
    for path, expected in implementation_hashes.items():
        if sha(repo / path) != expected:
            raise ValueError("Implementation changed during evaluation; incomplete output remains preserved")
    write_new(output / "report.json", report)
    bindings = {**implementation_hashes, str((output / "protocol.json").relative_to(repo)): sha(output / "protocol.json"),
                str((output / "report.json").relative_to(repo)): sha(output / "report.json")}
    write_new(output / "artifact-hashes.json", {"algorithm": "SHA-256", "scope": "Source-only parser coverage identity; no ML performance claim", "files": bindings})
    print(json.dumps({"profiles": profiles, "sourcesByLanguage": report["sourcesByLanguage"]}, sort_keys=True), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jar", type=Path, default=DEFAULT_JAR)
    parser.add_argument("--java", default="java")
    parser.add_argument("--cobc", type=Path)
    parser.add_argument("--timeout", type=float, default=15)
    args = parser.parse_args()
    args.output = args.output.resolve()
    try:
        run(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"Parser experiment stopped: {error}\n")


if __name__ == "__main__":
    main()
