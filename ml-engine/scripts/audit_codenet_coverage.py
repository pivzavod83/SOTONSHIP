#!/usr/bin/env python3
"""Audit bounded frontend coverage of an inventoried CodeNet subset, source only.

FREE and FIXED are separate COBOL analysis probes, never an automatic compiler
profile decision. No model is loaded, source executed, or semantic label inferred.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

SCHEMA = "codenet-frontend-coverage-v1"
MAX_SOURCE_BYTES = 200_000
MAX_SOURCE_RECORDS = 2_000_000
PROFILES = ("FREE", "FIXED")


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _extract(source: str, language: str, profile: str):
    # The audit imports only text parsers. It deliberately never imports a model,
    # evaluation/training harness, subprocess module, or upstream source module.
    if language == "COBOL":
        from ml_engine.cobol_extractor_v2 import extract_cobol
        return extract_cobol(source, profile)
    from ml_engine.java_extractor_v2 import extract_java
    return extract_java(source)


def _source_path(corpus: Path, record: dict) -> Path:
    relative = record["path"]
    if not isinstance(relative, str) or "\\" in relative or "\x00" in relative:
        raise ValueError("Invalid inventory source path")
    pure = PurePosixPath(relative)
    expected = ("data", record["problemId"], record["language"])
    if pure.is_absolute() or ".." in pure.parts or len(pure.parts) != 4 or pure.parts[:3] != expected:
        raise ValueError("Source path does not match inventory identity")
    current = corpus
    for part in pure.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError("Symlink in corpus source path")
    if not current.is_file() or not current.resolve().is_relative_to(corpus.resolve()):
        raise ValueError("Source file missing or outside corpus")
    return current


def _probe(corpus: Path, record: dict, profile: str) -> dict:
    path = _source_path(corpus, record)
    base = {key: record[key] for key in ("path", "problemId", "language", "submissionId", "upstreamJudgeStatus", "sha256")}
    base.update(profile=profile, compilerContract="UNKNOWN", semanticLabel="UNKNOWN", trainingEligible=False,
                sourceHashVerified=False)
    size = path.stat().st_size
    if size != record["bytes"]:
        raise ValueError(f"Source byte count changed: {record['path']}")
    if size > MAX_SOURCE_BYTES:
        return {**base, "status": "QUARANTINED", "issues": {"SOURCE_BYTE_BUDGET": 1}}
    raw = path.read_bytes()
    if digest(raw) != record["sha256"]:
        raise ValueError(f"Source SHA-256 changed: {record['path']}")
    base["sourceHashVerified"] = True
    try:
        source = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        return {**base, "status": "QUARANTINED", "issues": {"NON_UTF8_REQUIRES_REVIEW": 1}}
    try:
        ir = _extract(source, record["language"], profile)
        issues = Counter(issue.code for issue in ir.issues)
        return {**base, "status": ir.status, "nodes": len(ir.nodes), "edges": len(ir.edges), "issues": dict(sorted(issues.items()))}
    except (ValueError, RecursionError, OverflowError) as error:
        return {**base, "status": "QUARANTINED", "issues": {f"EXTRACTOR_{type(error).__name__.upper()}": 1}}


def _counts(probes: list[dict]) -> dict:
    statuses = Counter(probe["status"] for probe in probes)
    issues = Counter()
    for probe in probes:
        issues.update(probe["issues"])
    return {"sources": len(probes), "statusCounts": dict(sorted(statuses.items())),
            "issueCounts": dict(sorted(issues.items()))}


def audit(corpus: Path) -> dict:
    """Read frozen import identities; choose sources before inspecting parse results."""
    corpus = corpus.resolve()
    manifest_path = corpus / "inventory.json"
    if manifest_path.is_symlink():
        raise ValueError("Inventory must not be a symlink")
    raw_manifest = manifest_path.read_bytes()
    manifest = json.loads(raw_manifest)
    if manifest.get("stage") != "INVENTORIED":
        raise ValueError("Completed INVENTORIED corpus required")
    sources = [*manifest["sourceFiles"],
               *({**record, "upstreamJudgeStatus": "UNKNOWN_MISSING_METADATA"}
                 for record in manifest.get("unmatchedSourceFiles", []))]
    if len(sources) > MAX_SOURCE_RECORDS:
        raise ValueError("Source record budget exceeded")
    by_problem = defaultdict(list)
    identities = set()
    for source in sources:
        if source.get("language") not in {"COBOL", "Java"} or not re.fullmatch(r"p\d{5}", source.get("problemId", "")):
            raise ValueError("Invalid source language/problem identity")
        identity = (source["problemId"], source["language"], source["submissionId"])
        if identity in identities:
            raise ValueError("Duplicate source identity")
        identities.add(identity)
        by_problem[source["problemId"]].append(source)

    cobol = sorted((source for source in sources if source["language"] == "COBOL"), key=lambda source: (source["problemId"], source["submissionId"]))
    # Selection never uses parsing results, test outcomes, source size, identifier
    # similarity, or a model score. Unsupported selected examples remain counted.
    selected = []
    for problem, members in sorted(by_problem.items()):
        anchors = sorted((item for item in members if item["language"] == "COBOL" and item["upstreamJudgeStatus"] == "Accepted"), key=lambda item: item["submissionId"])
        if not anchors:
            continue
        for status in ("Accepted", "Wrong Answer"):
            candidates = sorted((item for item in members if item["language"] == "Java" and item["upstreamJudgeStatus"] == status), key=lambda item: item["submissionId"])
            if candidates:
                selected.append((problem, anchors[0], candidates[0]))

    cache = {}
    def probe(record: dict, profile: str) -> dict:
        key = (record["path"], profile)
        if key not in cache:
            cache[key] = _probe(corpus, record, profile)
        return cache[key]

    cobol_probes = {profile: [probe(record, profile) for record in cobol] for profile in PROFILES}
    java_records = {java["path"]: java for _, _, java in selected}
    java_probes = [probe(record, "JAVA") for _, record in sorted(java_records.items())]
    pairs = []
    for problem, anchor, java in selected:
        jprobe = probe(java, "JAVA")
        profiles = {}
        for profile in PROFILES:
            cprobe = probe(anchor, profile)
            complete = cprobe["status"] == jprobe["status"] == "COMPLETE"
            profiles[profile] = {"cobolStatus": cprobe["status"], "javaStatus": jprobe["status"],
                                 "bothFrontendsComplete": complete,
                                 "coverageDecision": "COMPLETE_FOR_EXPLICIT_PROBE" if complete else "ABSTAIN",
                                 "cobolIssues": cprobe["issues"], "javaIssues": jprobe["issues"]}
        pairs.append({"problemId": problem, "cobolSource": anchor["path"], "javaSource": java["path"],
                      "cobolSha256": anchor["sha256"], "javaSha256": java["sha256"],
                      "javaUpstreamJudgeStatus": java["upstreamJudgeStatus"], "profiles": profiles,
                      "semanticLabel": "UNKNOWN", "trainingEligible": False,
                      "compilerContract": "UNKNOWN", "requiresReview": True})
    summaries = {}
    for profile in PROFILES:
        complete = sum(pair["profiles"][profile]["bothFrontendsComplete"] for pair in pairs)
        summaries[profile] = {"pairs": len(pairs), "bothFrontendsComplete": complete,
                              "abstainedPairs": len(pairs) - complete,
                              "completeFraction": complete / len(pairs) if pairs else None,
                              "cobolSources": _counts(cobol_probes[profile])}
    implementations = {}
    root = Path(__file__).resolve().parents[1]
    for relative in ("scripts/audit_codenet_coverage.py", "ml_engine/cobol_extractor_v2.py", "ml_engine/java_extractor_v2.py", "ml_engine/semantic_ir.py"):
        implementations[relative] = digest((root / relative).read_bytes())
    return {"schemaVersion": SCHEMA, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
            "inventorySha256": digest(raw_manifest), "sourceArchive": manifest.get("sourceArchive"),
            "implementationHashes": implementations,
            "selection": "All COBOL sources; first Accepted COBOL and first Java source of each Accepted/Wrong Answer status by submissionId per problem. Selection precedes parsing.",
            "budgets": {"maxSourceBytes": MAX_SOURCE_BYTES, "maxSourceRecords": MAX_SOURCE_RECORDS},
            "cobolProblemIdCount": len({source["problemId"] for source in cobol}),
            "selectedPairProblemCount": len({pair["problemId"] for pair in pairs}),
            "independentFamilyClaim": "Problem IDs only; duplicate problem clusters and cross-corpus overlaps remain unresolved.",
            "selectedPairs": len(pairs), "atLeastTenPairs": len(pairs) >= 10,
            "upstreamJudgeStatusDistribution": {language: dict(sorted(Counter(source["upstreamJudgeStatus"] for source in sources if source["language"] == language).items())) for language in ("COBOL", "Java")},
            "profileResults": summaries, "selectedJavaSources": _counts(java_probes),
            "sourceProbes": {"COBOL": cobol_probes, "Java": java_probes}, "pairs": pairs,
            "semanticLabelStatus": "UNKNOWN", "defectLabelsAssigned": 0, "trainingEligible": False,
            "sourcesCompiled": False, "sourcesExecuted": False, "modelsLoaded": False,
            "modelInferencePerformed": False, "modelTrained": False, "accuracy": None, "recall": None,
            "limitations": ["Frontend coverage is neither compilation success nor behavioral equivalence.",
                            "FREE/FIXED are explicit probes; a successful probe does not resolve the compiler/source-format contract.",
                            "Same-problem accepted/wrong-answer submissions are independently authored, not established translations.",
                            "Compilation-error metadata stays separate and is not a semantic-defect label.",
                            "All pairs require review; this audit provides no acceptance authority."]}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, required=True, help="Ignored directory containing completed inventory.json")
    parser.add_argument("--output", type=Path, required=True, help="New source-only JSON report; refuses overwrite")
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Completed coverage evidence cannot be overwritten")
    try:
        result = audit(args.corpus)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as handle:
            json.dump(result, handle, indent=2, sort_keys=True)
            handle.write("\n")
        print(json.dumps({key: result[key] for key in ("cobolProblemIdCount", "selectedPairProblemCount", "selectedPairs", "profileResults", "semanticLabelStatus")}, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        parser.exit(1, f"CodeNet coverage audit stopped: {error}\n")


if __name__ == "__main__":
    main()
