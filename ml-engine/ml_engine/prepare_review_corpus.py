"""Prepare a pending-review corpus from authorized COBOL/Java JSONL pairs.

The tool copies the exact source bytes, records hashes and provenance, and
creates empty reviewer labels. It never guesses dialect, matches, defects, or
proof inputs. Run from ml-engine; corpus output must be stored outside Git.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
MAX_SOURCE_CHARS = 100_000
MAX_SOURCE_LINES = 1_500


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_id(value: object, label: str) -> str:
    if value is None:
        raise ValueError(f"{label} is required")
    result = str(value).strip()
    if not result or not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", result):
        raise ValueError(f"{label} must contain only letters, digits, dot, underscore, or hyphen")
    return result


def _read_pairs(path: Path, input_format: str) -> list[dict]:
    pairs = []
    seen = set()
    with path.open(encoding="utf-8") as stream:
        for line_number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise ValueError(f"Invalid JSON on line {line_number}: {error.msg}") from error
            if not isinstance(record, dict):
                raise ValueError(f"Line {line_number} must contain a JSON object")
            if input_format == "codetransocean-niche":
                task_id = _safe_id(record.get("id"), f"id on line {line_number}")
                if not isinstance(record.get("COBOL"), str) or not isinstance(record.get("Java"), str):
                    continue
                cobol, java = record["COBOL"], record["Java"]
                task_name = str(record.get("name") or task_id)
            else:
                task_id = _safe_id(record.get("task_id"), f"task_id on line {line_number}")
                cobol = record.get("COBOL_canonical_solution")
                java = record.get("Java_canonical_solution")
                task_name = task_id
            if task_id in seen:
                raise ValueError(f"Duplicate task_id: {task_id}")
            seen.add(task_id)
            if not isinstance(cobol, str) or not cobol.strip():
                raise ValueError(f"Task {task_id} has no non-empty COBOL_canonical_solution")
            if not isinstance(java, str) or not java.strip():
                raise ValueError(f"Task {task_id} has no non-empty Java_canonical_solution")
            pairs.append({"taskId": task_id, "taskName": task_name, "cobol": cobol, "java": java})
    if not pairs:
        raise ValueError("Input contains no COBOL/Java pairs")
    return pairs


def _source_bytes(source: str, language: str, task_id: str) -> bytes:
    if len(source) > MAX_SOURCE_CHARS or source.count("\n") + 1 > MAX_SOURCE_LINES:
        raise ValueError(
            f"Task {task_id} {language} source exceeds the verifier limit "
            f"({MAX_SOURCE_CHARS} characters / {MAX_SOURCE_LINES} lines)"
        )
    return source.encode("utf-8")


def _format_candidate(source: str) -> str:
    """Return a weak layout hint only; source format always needs human confirmation."""
    lines = [line for line in source.splitlines() if line.strip()]
    if not lines:
        return "UNCONFIRMED"
    fixed_markers = sum(
        len(line) >= 7
        and all(char == " " or char.isdigit() for char in line[:6])
        and line[6] in " -* /Dd"
        for line in lines
    )
    if fixed_markers / len(lines) >= 0.8:
        return "FIXED_CANDIDATE"
    return "FREE_CANDIDATE"


def prepare(args: argparse.Namespace) -> Path:
    input_path = args.input.resolve(strict=True)
    output_dir = args.output_dir.resolve()
    if not input_path.is_file():
        raise ValueError(f"Input is not a file: {input_path}")
    if output_dir == REPO_ROOT or output_dir.is_relative_to(REPO_ROOT):
        raise ValueError("Private review data must be stored outside the repository")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"Output directory is not empty: {output_dir}")

    dataset_id = _safe_id(args.dataset_id, "dataset-id")
    for label, value in (("dialect-profile", args.dialect_profile),
                         ("source-url", args.source_url),
                         ("source-license", args.source_license)):
        if not value.strip():
            raise ValueError(f"{label} must not be empty")
    pairs = _read_pairs(input_path, args.input_format)
    prepared_pairs = []
    for pair in pairs:
        prepared_pairs.append((pair, _source_bytes(pair["cobol"], "COBOL", pair["taskId"]),
                               _source_bytes(pair["java"], "Java", pair["taskId"])))

    output_dir.mkdir(parents=True, exist_ok=True)
    sources_dir = output_dir / "sources"
    sources_dir.mkdir(exist_ok=True)
    cases = []
    for pair, cobol, java in prepared_pairs:
        task_id = pair["taskId"]
        cobol_name, java_name = f"{task_id}.cbl", f"{task_id}.java"
        (sources_dir / cobol_name).write_bytes(cobol)
        (sources_dir / java_name).write_bytes(java)
        cases.append({
            "caseId": task_id,
            "groupId": f"{dataset_id}:{task_id}",
            "split": args.split,
            "dialectProfile": args.dialect_profile,
            "patternTags": ["DIALECT_PROFILE_REVIEW_REQUIRED", "SOURCE_FORMAT_REVIEW_REQUIRED"],
            "request": {
                "moduleName": task_id,
                "description": pair["taskName"],
                "category": "TRANSLATION_PAIR_REVIEW",
                "cobolSource": {"path": f"sources/{cobol_name}", "sha256": _sha256(cobol)},
                "javaSource": {"path": f"sources/{java_name}", "sha256": _sha256(java)},
            },
            "sourceFormat": _format_candidate(pair["cobol"]) if args.source_format == "AUTO" else args.source_format,
            "reviewVotes": [],
            "adjudication": {
                "status": "PENDING", "adjudicatorId": "", "rationale": "",
                "hasDefect": False, "mappings": [],
            },
        })

    manifest = {
        "schemaVersion": 1,
        "datasetId": dataset_id,
        "provenance": {
            "sourceUrl": args.source_url,
            "sourceLicense": args.source_license,
            "inputSha256": _sha256(input_path.read_bytes()),
            "preparedAt": datetime.now(timezone.utc).isoformat(),
            "sourceFormat": args.source_format,
            "reviewStatus": "UNREVIEWED",
            "groupingPolicy": "one benchmark task per group; confirm this is the dataset's independence boundary",
        },
        "cases": cases,
    }
    if args.input_format == "codetransocean-niche":
        manifest["provenance"]["citation"] = (
            "@article{yan2023codetransocean, title={CodeTransOcean: A Comprehensive Multilingual Benchmark for Code Translation}, "
            "author={Yan, Weixiang and Tian, Yuchen and Li, Yunzhe and Chen, Qian and Wang, Wen}, "
            "journal={arXiv preprint arXiv:2310.04951}, year={2023}}"
        )
    manifest_path = output_dir / "review-corpus.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return manifest_path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Authorized JSONL input")
    parser.add_argument("--input-format", choices=("generic-pairs", "codetransocean-niche"), default="generic-pairs",
                        help="Use codetransocean-niche for its native id/name/COBOL/Java records")
    parser.add_argument("--output-dir", type=Path, required=True, help="New or empty private directory outside this repository")
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--dialect-profile", required=True, help="Explicit profile; do not infer from the dataset name")
    parser.add_argument("--source-format", choices=("FIXED", "FREE", "AUTO"), default="AUTO",
                        help="AUTO stores a weak per-file layout hint for reviewer confirmation")
    parser.add_argument("--source-url", required=True)
    parser.add_argument("--source-license", required=True, help="Exact license/authorization reference")
    parser.add_argument("--split", choices=("train", "calibration", "test"), default="test",
                        help="Defaults to test so benchmark pairs do not silently become training data")
    args = parser.parse_args()
    try:
        path = prepare(args)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(f"Created unreviewed draft: {path}")
    print("All labels are pending. Independent review and a task-specific evaluation protocol are required before use.")


if __name__ == "__main__":
    main()
