#!/usr/bin/env python3
"""Freeze the 120/23 grouped five-fold plan before fitting any new weights."""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ml_engine.cv_partition import PINNED_DATASET_SHA256, build_partition_plan, validate_partition_plan


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=ROOT / "evaluation/corpora/cobol-javatrans/COBOL-JavaTrans.jsonl")
    parser.add_argument("--prior-split", type=Path, default=ROOT / "evaluation/paired-code/task-splits.json")
    parser.add_argument("--output", type=Path, default=ROOT / "evaluation/paired-code/cv-partition-plan.json")
    parser.add_argument("--seed", type=int, default=431)
    args = parser.parse_args()
    raw = args.dataset.read_bytes()
    dataset_sha256 = hashlib.sha256(raw).hexdigest()
    if dataset_sha256 != PINNED_DATASET_SHA256:
        raise ValueError("Pinned dataset SHA-256 mismatch")
    rows = [json.loads(line) for line in raw.decode("utf-8").splitlines() if line.strip()]
    prior_raw = args.prior_split.read_bytes()
    plan = build_partition_plan(rows, json.loads(prior_raw), args.seed,
                                dataset_sha256=dataset_sha256,
                                prior_split_sha256=hashlib.sha256(prior_raw).hexdigest())
    # An existing plan is immutable: rerunning validates/reproduces it instead of
    # silently replacing a partition after the experiment has begun.
    if args.output.exists():
        existing = json.loads(args.output.read_text())
        validate_partition_plan(existing, rows)
        if existing != plan:
            raise ValueError("Existing frozen partition differs; do not overwrite an experiment plan")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        # Exclusive creation prevents a concurrent process from replacing a plan.
        with args.output.open("x", encoding="utf-8") as output:
            output.write(json.dumps(plan, indent=2) + "\n")
    print(json.dumps({"plan": str(args.output), "planSha256": hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      "development": len(plan["developmentTaskIds"]), "finalHoldout": len(plan["finalHoldoutTaskIds"]),
                      "folds": [{"fold": fold["fold"], "train": len(fold["trainTaskIds"]), "validation": len(fold["validationTaskIds"])} for fold in plan["folds"]],
                      "graphComponents": len(plan["graphPartitioning"]["groups"]),
                      "previouslyObservedHoldout": plan["exposureAudit"]["priorRunObserved"]}))


if __name__ == "__main__":
    main()
