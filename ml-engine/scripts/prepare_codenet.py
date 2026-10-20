#!/usr/bin/env python3
"""Selectively inventory a local official CodeNet tar.gz without executing sources."""
from __future__ import annotations

import argparse
from datetime import date
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ml_engine.codenet_corpus import CorpusError, prepare_cobol, prepare_java, report_summary


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New ignored corpus directory")
    parser.add_argument("--report", type=Path, help="New small JSON inventory report (never raw source)")
    parser.add_argument("--stage", choices=("cobol", "java", "all"), default="all")
    parser.add_argument("--archive-sha256", help="Expected full archive SHA-256")
    parser.add_argument("--collection-date", required=True, help="Actual client collection date, YYYY-MM-DD")
    args = parser.parse_args()
    date.fromisoformat(args.collection_date)
    if args.report and args.report.exists():
        parser.error("Report already exists; completed evidence cannot be overwritten")
    def progress(event):
        print(json.dumps({"event": "archive-scan-progress", **event}), file=sys.stderr, flush=True)

    try:
        if args.stage in {"cobol", "all"}:
            result = prepare_cobol(args.archive, args.output, expected_sha256=args.archive_sha256,
                                   collection_date=args.collection_date, progress=progress)
            print(json.dumps({"stage": result["stage"], "cobolFiles": len(result["sourceFiles"]),
                              "problemFamilies": len(result["problemIds"]), "selectedBytes": result["selectedBytes"]}), flush=True)
        if args.stage in {"java", "all"}:
            result = prepare_java(args.archive, args.output, expected_sha256=args.archive_sha256, progress=progress)
            summary = report_summary(result)
            if args.report:
                args.report.parent.mkdir(parents=True, exist_ok=True)
                with args.report.open("x", encoding="utf-8") as handle:
                    json.dump(summary, handle, indent=2, sort_keys=True)
                    handle.write("\n")
            print(json.dumps({key: summary[key] for key in ("stage", "sourceFileCount", "problemFamilyCount",
                              "crossLanguageCandidateFamilyCount", "javaWrongAnswerToAcceptedHistoryCount",
                              "defectLabelsAssigned", "trainingEligible")}), flush=True)
    except (CorpusError, OSError, ValueError) as exc:
        parser.exit(1, f"CodeNet preparation stopped: {exc}\n")


if __name__ == "__main__":
    main()
