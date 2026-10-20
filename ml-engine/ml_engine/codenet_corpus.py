"""Offline, selective CodeNet inventory. Never executes code or invents defect labels.

The official archive is scanned twice: COBOL and language-filtered metadata first,
then Java only for discovered COBOL problem families. Raw sources remain outside Git.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
import re
import tarfile
import time
from typing import Any, Callable, Iterable

SCHEMA_VERSION = "codenet-selective-inventory-v1"
SOURCE = re.compile(r"(?:Project_CodeNet/)?data/(p\d{5})/(COBOL|Java)/([A-Za-z0-9_.-]+)$")
METADATA = re.compile(r"(?:Project_CodeNet/)?metadata/(p\d{5})\.csv$")
PROBLEM = re.compile(r"p\d{5}")
REQUIRED_COLUMNS = {"submission_id", "problem_id", "user_id", "date", "language", "filename_ext", "status"}


class CorpusError(ValueError):
    """Archive safety, stage integrity, or inventory contract failure."""


@dataclass(frozen=True)
class Limits:
    max_members: int = 30_000_000
    max_archive_uncompressed_bytes: int = 150 * 1024**3
    max_source_bytes: int = 8 * 1024**2
    max_metadata_bytes: int = 128 * 1024**2
    max_document_bytes: int = 8 * 1024**2
    max_selected_bytes: int = 12 * 1024**3
    max_metadata_rows_per_problem: int = 1_000_000


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024**2), b""):
            digest.update(block)
    return digest.hexdigest()


def _json_write(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _safe_name(name: str) -> PurePosixPath:
    if "\x00" in name or "\\" in name or name.startswith("/"):
        raise CorpusError(f"Unsafe archive member name: {name!r}")
    path = PurePosixPath(name)
    if ".." in path.parts or not path.parts:
        raise CorpusError(f"Unsafe archive member name: {name!r}")
    return path


def _members(archive: Path, limits: Limits, progress: Callable[[dict[str, Any]], None] | None = None) -> Iterable[tuple[tarfile.TarFile, tarfile.TarInfo, str]]:
    total = 0
    start = last_report = time.monotonic()
    # _Stream._read copies its remaining decompressed buffer for each tiny tar
    # header read. A 1 MiB compressed buffer makes a 100k-member scan ~11x slower
    # than tarfile's 10 KiB default on the official archive (15.476s vs 1.368s).
    with tarfile.open(archive, mode="r|gz", bufsize=10_240) as stream:
        count = 0
        while True:
            member = stream.next()
            if member is None:
                break
            # tarfile normally retains every TarInfo even in streaming mode. CodeNet
            # has millions of members; keeping those objects would exhaust memory.
            stream.members.clear()
            count += 1
            if progress and count % 1000 == 0:
                now = time.monotonic()
                if count % 100_000 == 0 or now - last_report >= 30:
                    progress({"members": count, "uncompressedBytesScanned": total,
                              "elapsedSeconds": round(now - start, 1)})
                    last_report = now
            if count > limits.max_members:
                raise CorpusError("Archive member-count budget exceeded")
            path = _safe_name(member.name)
            if member.issym() or member.islnk() or not (member.isfile() or member.isdir()):
                raise CorpusError(f"Unsupported archive member type: {member.name}")
            if member.size < 0:
                raise CorpusError("Negative archive member size")
            total += member.size
            if total > limits.max_archive_uncompressed_bytes:
                raise CorpusError("Archive decompression budget exceeded")
            if member.isfile():
                yield stream, member, str(path)


def _read_member(stream: tarfile.TarFile, member: tarfile.TarInfo, maximum: int) -> bytes:
    if member.size > maximum:
        raise CorpusError(f"Selected member exceeds file budget: {member.name}")
    handle = stream.extractfile(member)
    if handle is None:
        raise CorpusError(f"Cannot read archive member: {member.name}")
    value = handle.read(maximum + 1)
    if len(value) != member.size or len(value) > maximum:
        raise CorpusError(f"Invalid selected member size: {member.name}")
    return value


def _save(output: Path, relative: str, value: bytes, budget: list[int], limits: Limits) -> dict[str, Any]:
    _safe_name(relative)
    destination = output / relative
    if destination.exists():
        raise CorpusError(f"Duplicate selected member or preexisting destination: {relative}")
    budget[0] += len(value)
    if budget[0] > limits.max_selected_bytes:
        raise CorpusError("Selected extraction byte budget exceeded")
    # Refuse a preexisting symlink at any point below the output root, before mkdir.
    current = destination
    while current != output.parent:
        if current.is_symlink():
            raise CorpusError(f"Symlink in extraction destination: {relative}")
        current = current.parent
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb") as handle:
        handle.write(value)
    result = {"path": relative, "sha256": hashlib.sha256(value).hexdigest(), "bytes": len(value)}
    try:
        value.decode("utf-8", errors="strict")
        result["encoding"] = "UTF-8"
    except UnicodeDecodeError:
        result["encoding"] = "NON_UTF8_REQUIRES_REVIEW"
    return result


def _csv_rows(raw: bytes, problem: str, limits: Limits) -> tuple[list[dict[str, str]], list[str], list[str]]:
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise CorpusError(f"Metadata is not UTF-8: {problem}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    fields = reader.fieldnames or []
    if len(fields) != len(set(fields)) or not REQUIRED_COLUMNS.issubset(fields):
        raise CorpusError(f"Missing or duplicate metadata columns: {problem}")
    selected: list[dict[str, str]] = []
    issues: list[str] = []
    for number, row in enumerate(reader, 1):
        if number > limits.max_metadata_rows_per_problem:
            raise CorpusError(f"Metadata row-count budget exceeded: {problem}")
        if None in row or any(value is None for value in row.values()):
            raise CorpusError(f"Malformed metadata row: {problem}:{number}")
        if row["language"] not in {"COBOL", "Java"}:
            continue
        if row["problem_id"] != problem:
            raise CorpusError(f"Metadata problem mismatch: {problem}:{number}")
        if not re.fullmatch(r"[A-Za-z0-9_-]+", row["submission_id"]):
            raise CorpusError(f"Invalid submission ID: {problem}:{number}")
        if not re.fullmatch(r"[A-Za-z0-9]+", row["filename_ext"]):
            raise CorpusError(f"Invalid filename extension: {problem}:{number}")
        selected.append(row)
    seen = [row["submission_id"] for row in selected]
    if len(seen) != len(set(seen)):
        raise CorpusError(f"Duplicate metadata submission ID: {problem}")
    return selected, fields, issues


def _csv_bytes(rows: list[dict[str, str]], fields: list[str]) -> bytes:
    text = io.StringIO(newline="")
    writer = csv.DictWriter(text, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    return text.getvalue().encode("utf-8")


def _document_relative(name: str, families: set[str] | None) -> str | None:
    parts = PurePosixPath(name).parts
    if parts and parts[0] == "Project_CodeNet":
        parts = parts[1:]
    if not parts:
        return None
    if len(parts) == 1 and (parts[0].lower().startswith(("readme", "license", "licence", "notice"))):
        return "upstream/" + parts[0]
    if parts == ("metadata", "problem_list.csv"):
        return "metadata/problem_list.csv"
    # Descriptions precede source data in the official archive. Retain all small
    # descriptions on pass one; no future source family is lost because of order.
    if parts[0] == "problem_descriptions" and len(parts) == 2:
        if families is None or any(match.group() in families for match in PROBLEM.finditer(parts[1])):
            return "/".join(parts)
    if families is not None:
        # Only samples/input-output and duplication metadata are relevant. Never extract benchmark bundles.
        if parts[0] == "derived" and len(parts) > 1:
            is_sample = any(token in parts[1].lower() for token in ("input", "output", "sample"))
            is_cluster = any(token in parts[1].lower() for token in ("duplicate", "cluster"))
            if is_sample and any(match.group() in families for part in parts for match in PROBLEM.finditer(part)):
                return "/".join(parts)
            if is_cluster and len(parts) <= 3:
                return "/".join(parts)
    return None


def _archive_record(archive: Path, expected_sha256: str | None) -> dict[str, Any]:
    if not archive.is_file() or archive.is_symlink():
        raise CorpusError("Archive must be a regular, non-symlink file")
    actual = sha256_file(archive)
    if expected_sha256 is not None and actual != expected_sha256.lower():
        raise CorpusError("Source archive SHA-256 mismatch")
    return {"filename": archive.name, "bytes": archive.stat().st_size, "sha256": actual}


def prepare_cobol(archive: Path, output: Path, *, expected_sha256: str | None = None,
                  collection_date: str, limits: Limits = Limits(),
                  progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """First pass: retain all COBOL, and COBOL/Java rows for COBOL-containing metadata."""
    datetime.strptime(collection_date, "%Y-%m-%d")
    if output.exists():
        raise CorpusError("First-pass output must not already exist; use a new versioned directory")
    source_archive = _archive_record(archive, expected_sha256)
    output.mkdir(parents=True)
    budget = [0]
    sources: list[dict[str, Any]] = []
    metadata: dict[str, dict[str, Any]] = {}
    documents: list[dict[str, Any]] = []
    families: set[str] = set()
    scanned_members = 0
    derived_layout: dict[str, dict[str, Any]] = {}
    for stream, member, name in _members(archive, limits, progress):
        scanned_members += 1
        parts = PurePosixPath(name).parts
        if parts and parts[0] == "Project_CodeNet":
            parts = parts[1:]
        if parts and parts[0] == "derived":
            prefix = parts[1] if len(parts) > 1 else "<root>"
            if prefix not in derived_layout and len(derived_layout) >= 256:
                prefix = "<other-subdirectories>"
            entry = derived_layout.setdefault(prefix, {"regularFiles": 0, "uncompressedBytes": 0, "exampleMembers": []})
            entry["regularFiles"] += 1
            entry["uncompressedBytes"] += member.size
            if len(entry["exampleMembers"]) < 8:
                entry["exampleMembers"].append(name[:512])
        source = SOURCE.fullmatch(name)
        meta = METADATA.fullmatch(name)
        if source and source.group(2) == "COBOL":
            problem, language, filename = source.groups()
            raw = _read_member(stream, member, limits.max_source_bytes)
            saved = _save(output, f"data/{problem}/{language}/{filename}", raw, budget, limits)
            saved.update(problemId=problem, language=language, submissionId=Path(filename).stem,
                         archiveMember=name)
            sources.append(saved)
            families.add(problem)
        elif meta:
            problem = meta.group(1)
            raw = _read_member(stream, member, limits.max_metadata_bytes)
            rows, fields, issues = _csv_rows(raw, problem, limits)
            if any(row["language"] == "COBOL" for row in rows):
                saved = _save(output, f"metadata/{problem}.csv", _csv_bytes(rows, fields), budget, limits)
                saved.update(archiveMember=name, originalSha256=hashlib.sha256(raw).hexdigest(),
                             originalBytes=len(raw), languagesRetained=["COBOL", "Java"], rows=len(rows), issues=issues)
                metadata[problem] = saved
                families.add(problem)
        else:
            document = _document_relative(name, None)
            if document:
                documents.append(_save(output, document, _read_member(stream, member, limits.max_document_bytes), budget, limits))
    result = {
        "schemaVersion": SCHEMA_VERSION, "stage": "COBOL_READY", "collectionDate": collection_date,
        "sourceArchive": source_archive, "sourceFiles": sources, "metadataFiles": metadata,
        "documentFiles": documents, "problemIds": sorted(families), "selectedBytes": budget[0],
        "scannedRegularMembers": scanned_members, "derivedLayoutCensus": derived_layout,
        "notice": "Source inventory only. Judge outcomes are not translation-equivalence labels. No source code executed.",
    }
    _json_write(output / "pass-1.json", result)
    return result


def _timestamp(value: str) -> int | None:
    try:
        return int(value)
    except ValueError:
        try:
            stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if stamp.tzinfo is None:
                return None
            return int(stamp.timestamp())
        except ValueError:
            return None


def _metadata_rows(output: Path, first: dict[str, Any], problem: str, limits: Limits) -> list[dict[str, str]]:
    record = first["metadataFiles"].get(problem)
    if not record:
        return []
    path = output / record["path"]
    if sha256_file(path) != record["sha256"]:
        raise CorpusError(f"First-pass metadata modified: {problem}")
    rows, _, _ = _csv_rows(path.read_bytes(), problem, limits)
    return rows


def build_inventory(output: Path, first: dict[str, Any], sources: list[dict[str, Any]],
                    *, limits: Limits = Limits()) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Join exact metadata/source identities; histories remain unlabelled auxiliary candidates."""
    by_source = {(row["problemId"], row["language"], row["submissionId"]): row for row in sources}
    enriched: list[dict[str, Any]] = []
    missing_sources = Counter()
    statuses: dict[str, Counter] = defaultdict(Counter)
    row_count = Counter()
    family_records: list[dict[str, Any]] = []
    histories: list[dict[str, Any]] = []
    unmatched_sources = set(by_source)
    invalid_dates = 0
    for problem in first["problemIds"]:
        # Read one problem at a time rather than retaining every metadata row.
        rows = _metadata_rows(output, first, problem, limits)
        usable: list[dict[str, Any]] = []
        for row in rows:
            language = row["language"]
            row_count[language] += 1
            statuses[language][row["status"]] += 1
            key = (problem, language, row["submission_id"])
            source = by_source.get(key)
            if source is None:
                missing_sources[language] += 1
                continue
            if Path(source["path"]).suffix != "." + row["filename_ext"]:
                raise CorpusError(f"Filename extension mismatch: {problem}/{row['submission_id']}")
            unmatched_sources.discard(key)
            item = {**source, "upstreamJudgeStatus": row["status"], "userId": row["user_id"],
                    "submissionDate": row["date"], "semanticLabel": None, "trainingEligible": False,
                    "metadataPath": f"metadata/{problem}.csv"}
            enriched.append(item)
            usable.append(item)
        anchors = sorted((row for row in usable if row["language"] == "COBOL" and row["upstreamJudgeStatus"] == "Accepted" and row["encoding"] == "UTF-8"), key=lambda row: row["submissionId"])
        java = [row for row in usable if row["language"] == "Java"]
        accepted_java = [row for row in java if row["upstreamJudgeStatus"] == "Accepted" and row["encoding"] == "UTF-8"]
        users: dict[str, list[tuple[int, dict[str, Any]]]] = defaultdict(list)
        for row in java:
            stamp = _timestamp(row["submissionDate"])
            if stamp is None:
                invalid_dates += 1
            elif row["userId"]:
                users[row["userId"]].append((stamp, row))
        history_count = 0
        if anchors:
            for user, submissions in sorted(users.items()):
                submissions.sort(key=lambda item: (item[0], item[1]["submissionId"]))
                last_wrong: tuple[int, dict[str, Any]] | None = None
                for stamp, row in submissions:
                    if row["upstreamJudgeStatus"] == "Wrong Answer":
                        last_wrong = (stamp, row)
                    elif row["upstreamJudgeStatus"] == "Accepted" and last_wrong and last_wrong[0] < stamp:
                        histories.append({
                            "candidateId": f"{problem}:{last_wrong[1]['submissionId']}:{row['submissionId']}",
                            "problemId": problem, "familyGroup": problem, "userId": user,
                            "kind": "AUXILIARY_JAVA_WRONG_ANSWER_TO_ACCEPTED_HISTORY",
                            "cobolAnchor": anchors[0], "javaBefore": last_wrong[1], "javaAfter": row,
                            "semanticLabel": None, "trainingEligible": False,
                            "relationship": "Independently authored same-problem solutions; not a demonstrated COBOL-to-Java translation.",
                            "requiredEvidence": ["shared input/output contract", "successful COBOL/control replay", "candidate-origin discrepancy", "independent adjudication"],
                        })
                        history_count += 1
                        # Do not count one wrong submission once for every later accepted submission.
                        last_wrong = None
        family_records.append({"problemId": problem, "familyGroup": problem,
                               "cobolAcceptedSources": len(anchors), "javaSources": len(java),
                               "javaAcceptedSources": len(accepted_java), "javaWrongAnswerToAcceptedHistories": history_count,
                               "crossLanguageCandidateEligible": bool(anchors and accepted_java),
                               "semanticLabel": None, "trainingEligible": False})
    eligible = sum(row["crossLanguageCandidateEligible"] for row in family_records)
    counts = Counter(row["language"] for row in sources)
    report = {
        "schemaVersion": SCHEMA_VERSION, "stage": "INVENTORIED", "collectionDate": first["collectionDate"],
        "sourceArchive": first["sourceArchive"], "sourceFiles": enriched,
        "derivedLayoutCensus": first.get("derivedLayoutCensus", {}),
        "sourceFileCount": dict(counts), "metadataRowCount": dict(row_count),
        "metadataStatusDistribution": {language: dict(values) for language, values in statuses.items()},
        "missingSourceCount": dict(missing_sources), "unmatchedSourceCount": len(unmatched_sources),
        "unmatchedSourceFiles": [by_source[key] for key in sorted(unmatched_sources)],
        "missingMetadataProblemCount": sum(problem not in first["metadataFiles"] for problem in first["problemIds"]),
        "invalidJavaSubmissionDateCount": invalid_dates,
        "problemFamilyCount": len(family_records), "crossLanguageCandidateFamilyCount": eligible,
        "atLeastTenCandidateFamilies": eligible >= 10,
        "javaWrongAnswerToAcceptedHistoryCount": len(histories), "families": family_records,
        "metadataFiles": first["metadataFiles"], "documentFiles": first["documentFiles"],
        "sourcesExecuted": False, "modelTrained": False, "defectLabelsAssigned": 0,
        "automaticSplitAssigned": False, "trainingEligible": False,
        "limitations": ["Same-problem submissions are not translation pairs.",
                        "Accepted means the upstream judge accepted a submission, not universal equivalence.",
                        "Wrong Answer to Accepted history is a repair candidate, not a reviewed translation defect.",
                        "Source families and duplicate/task overlap must be grouped before any training split.",
                        "No code was compiled or executed and no semantic labels were inferred."],
    }
    return report, histories


def prepare_java(archive: Path, output: Path, *, expected_sha256: str | None = None,
                 limits: Limits = Limits(),
                 progress: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Second pass: Java/descriptions for COBOL problem families, then emit inventory."""
    if (output / "inventory.json").exists():
        raise CorpusError("Completed inventory cannot be overwritten; use a new versioned directory")
    first = _read_json(output / "pass-1.json")
    if first.get("stage") != "COBOL_READY" or first.get("schemaVersion") != SCHEMA_VERSION:
        raise CorpusError("Invalid first-pass manifest")
    archive_record = _archive_record(archive, expected_sha256 or first["sourceArchive"]["sha256"])
    if archive_record["sha256"] != first["sourceArchive"]["sha256"]:
        raise CorpusError("Archive differs from first pass")
    for record in first["sourceFiles"]:
        if sha256_file(output / record["path"]) != record["sha256"]:
            raise CorpusError("First-pass source modified")
    for record in first["documentFiles"]:
        if sha256_file(output / record["path"]) != record["sha256"]:
            raise CorpusError("First-pass document modified")
    # Verify stage inputs before writing any second-pass source files.
    for problem, record in first["metadataFiles"].items():
        if sha256_file(output / record["path"]) != record["sha256"]:
            raise CorpusError(f"First-pass metadata modified: {problem}")
    families = set(first["problemIds"])
    sources = list(first["sourceFiles"])
    documents = list(first["documentFiles"])
    saved_documents = {row["path"] for row in documents}
    budget = [first["selectedBytes"]]
    for stream, member, name in _members(archive, limits, progress):
        source = SOURCE.fullmatch(name)
        if source and source.group(2) == "Java" and source.group(1) in families:
            problem, language, filename = source.groups()
            saved = _save(output, f"data/{problem}/{language}/{filename}", _read_member(stream, member, limits.max_source_bytes), budget, limits)
            saved.update(problemId=problem, language=language, submissionId=Path(filename).stem, archiveMember=name)
            sources.append(saved)
        else:
            relative = _document_relative(name, families)
            if relative and relative not in saved_documents:
                documents.append(_save(output, relative, _read_member(stream, member, limits.max_document_bytes), budget, limits))
                saved_documents.add(relative)
    first["documentFiles"] = documents
    inventory, histories = build_inventory(output, first, sources, limits=limits)
    inventory["selectedBytes"] = budget[0]
    history_path = output / "candidate-histories.jsonl"
    with history_path.open("x", encoding="utf-8") as handle:
        for history in histories:
            handle.write(json.dumps(history, sort_keys=True) + "\n")
    inventory["candidateHistories"] = {"path": history_path.name, "sha256": sha256_file(history_path), "count": len(histories)}
    _json_write(output / "inventory.json", inventory)
    return inventory


def report_summary(inventory: dict[str, Any]) -> dict[str, Any]:
    """Small versionable report; all raw source and pseudonymous history stay in cache."""
    excluded = {"sourceFiles", "unmatchedSourceFiles", "metadataFiles", "documentFiles"}
    result = {key: value for key, value in inventory.items() if key not in excluded}
    result["rawSourceNotice"] = "Raw upstream source and full provenance are in the ignored corpus cache, not this report."
    result["implementation"] = {"path": "ml_engine/codenet_corpus.py", "sha256": sha256_file(Path(__file__))}
    return result
