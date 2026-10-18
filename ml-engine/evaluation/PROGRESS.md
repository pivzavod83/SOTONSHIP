# COBOL-to-Java review corpus progress

## Current state

- Imported the COBOL/Java records from CodeTransOcean NicheTrans `niche_test.json`, pinned to dataset revision `8985d0851100f08e94735b2f2556a795ba8c69bb`.
- The source split contains 95,004 JSONL rows. Eighty-eight rows have both a COBOL and a Java program; those 88 pairs were copied into the local corpus.
- Corpus manifest: `ml-engine/evaluation/corpora/codetransocean_cobol_java_test/review-corpus.json`.
- Source files are under the same directory's `sources/` folder. The folder is ignored by `.gitignore`; source files and the generated manifest are not included in Git commits.
- Every case is assigned to `test`, has source hashes and CodeTransOcean provenance, and remains `UNREVIEWED` with `PENDING` adjudication and no reviewer votes. Formal proof inputs are absent.
- The importer's fixed/free source-layout labels are weak hints only: it marked 66 files `FIXED_CANDIDATE` and 22 `FREE_CANDIDATE`. This is not a compiler-confirmed classification.
- The requested GNU COBOL 3.2 compatibility profile is recorded as a candidate for review, not as a verified dialect claim. CodeTransOcean does not specify the compiler dialect for these COBOL samples.

## What this project can measure now

The current pipeline can compare its advisory COBOL-to-Java code-region alignment and defect-risk ranking against completed human labels. The current application does not generate Java from COBOL. Its model outputs do not prove behavioral equivalence, and its scores must not approve a patch. The formal checker only reports a proof result when the input is within its explicitly supported profile; unsupported behavior stays unknown.

The evaluator will reject this corpus until each selected case has at least two independent reviewer votes and an adjudicated result with a named adjudicator and rationale. Do not fill those fields with model predictions. The corpus currently has only the held-out test split; it is not a training set. Keep it untouched while developing models or choosing thresholds.

## Next work

1. Have COBOL and Java reviewers confirm which pairs correspond, identify any known calculation or behavior defects, and confirm source-format and dialect assumptions. If GNU COBOL 3.2 is not a reasonable compatibility profile for a sample, document the actual compiler profile or leave it unconfirmed.
2. Have two qualified reviewers label each pair independently. Record graph-node mapping IDs, defect decisions, and disagreements. A qualified adjudicator resolves disagreements with a written rationale.
3. Once labels are complete, evaluate the frozen test split with `ml_engine.evaluate_review_set`. Preserve the report, corpus hash, model hash, threshold decision, reviewer protocol, and code revision.
4. Before retraining, assemble separate authorized training and calibration corpora grouped by source application. Do not use these 88 test pairs for training or threshold selection.
5. Add realistic held-out banking/CICS systems and tests for execution behavior. This small public benchmark slice is useful for pilot signal, not evidence of bank-scale coverage.

## Dataset citation and provenance

The manifest records the dataset revision, source URL, input SHA-256, and Apache-2.0 dataset metadata. Cite the dataset as:

```bibtex
@article{yan2023codetransocean,
  title={CodeTransOcean: A Comprehensive Multilingual Benchmark for Code Translation},
  author={Yan, Weixiang and Tian, Yuchen and Li, Yunzhe and Chen, Qian and Wang, Wen},
  journal={arXiv preprint arXiv:2310.04951},
  year={2023}
}
```

## Reproducibility

The native JSONL importer is `ml-engine/ml_engine/prepare_review_corpus.py`. It defaults imports to the test split, preserves the source bytes, calculates per-file hashes, and starts every case with blank human-review fields. Corpus files are deliberately kept under the Git-ignored `ml-engine/evaluation/corpora/` directory. Back up that local folder in an approved storage location before relying on it; do not commit it.
