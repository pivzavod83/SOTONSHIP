# Local paired defect model: synthetic pilot v1

Implemented and trained a local **graph-feature classifier with a learned span ranker**. It examines the supplied COBOL/Java pair; it does not retrieve a Java partner. Inference needs NumPy and the exported JSON weights, not an LLM API, scikit-learn, compilers or network access.

**The implementation works, but this experiment failed to generalize.** The final test accuracy was **1/8 (12.5%)**, below both 50% accuracy baselines. This is an experimental demonstration of a learned review workflow, not a reliable verifier. An AI warning is a hypothesis; a low score does not establish equivalence.

## Data and separation

- Frozen input: `../pilot-10-r3/dataset.json`, SHA-256 `7d6f612855da2e75ee5f552ea0ebc9e0fd95e5f3399a28e6d982f10c194c9dcb`.
- Training: F001, F002, F003, F006, F007, F008 — 6 families / 24 pairs.
- Validation: F004, F009 — 2 families / 8 pairs; used to choose the threshold.
- Final testing: replacement F005-R2 and F010 — 2 families / 8 pairs; used once after freezing the artifact and implementation hashes.
- Every Java variant and fragment stays in its COBOL algorithm-family split.
- The original 143-pair matching corpus, its 23 reserved samples, the matching model and the original synthetic random records were not used.
- These are synthetic AI-generated pairs. Defect labels have finite compiled runtime witnesses from prior dataset curation. Intended-equivalent labels mean agreement on executed inputs, not formal equivalence for the complete input domain. Localization labels remain AI-generated weak annotations, not expert-reviewed gold.
- Validation/test programs were previously inspected for dataset quality, so this is not a pristine blind benchmark.

## What was trained

The fixed extractor builds bounded statement graphs. Nodes carry arithmetic, rounding, scale, sign, receiving-field and literal features; local def/use edges add dependency degrees. Candidate COBOL/Java correspondences are inferred from identifier similarity and operation/dependency overlap. Missing and extra operations have one-sided candidates.

Two regularized logistic heads are learned in each fold:

1. A candidate-span ranker supervised by training-only defect segment annotations.
2. A pair-level defect classifier using pooled graph comparisons and learned ranker scores.

This is **not a trained GNN**. Its graphs and features are extracted heuristically; it does not implement complete COBOL or Java semantics. No hand-written rule makes the final defect decision: exported learned coefficients produce the risk score and span order.

Inference receives source text and its format only. Family/variant IDs, variant order, split assignments, labels, rationales, test cases, runtime outputs and provided alignment annotations are excluded. `moduleName` is ignored. Raw source SHA-256 hashes and one-based raw LF line spans bind findings to submitted text; source code is never executed at inference.

## Training and selection

Three grouped folds hold out respectively:

1. F001 and F006.
2. F002 and F007.
3. F003 and F008.

Each checkpoint fits 16 pairs from four families. Deployment averages the three checkpoint scores. **There is no final refit on all 24 training pairs.**

Six fixed candidates compared a wide graph-feature classifier with a compact learned-score pooling classifier, each at logistic regularization C = 0.1, 1, 10. Candidate selection used grouped out-of-fold balanced accuracy at threshold 0.5, then F1, then lower C and fewer features for exact ties. The selected candidate was the wide graph-feature classifier with **C = 1**.

An initial pre-test experiment tried unrestricted validation thresholds and produced an unstable very low threshold. Its results and weights are preserved under `pretest-exploration-initial/`. A compact architecture comparison and coarse threshold grid were added **before final testing**. Validation had already been inspected during this development; do not describe the revised protocol as pristine preregistration. The final threshold, selected from 0.25 / 0.5 / 0.75 using validation only, was **0.5**.

`protocol.json`, `candidate-selection.json`, the three fold JSON files, and `frozen-artifact.json` record the process. The latter binds the model and exact feature, inference and training code hashes. `final-test-evaluation.json` records the once-only assessment. The trainer refuses retraining or another final assessment for this version once that report exists.

## Measured results

| Assessment | Correct / pairs | Accuracy | Precision | Recall | F1 |
|---|---:|---:|---:|---:|---:|
| Selected grouped out-of-fold candidate | 16 / 24 | 66.7% | 70.0% | 58.3% | 63.6% |
| Validation, threshold selection | 4 / 8 | 50.0% | 50.0% | 50.0% | 50.0% |
| Frozen final test | 1 / 8 | 12.5% | 20.0% | 25.0% | 22.2% |

Final-test raw counts: **TP 1, TN 0, FP 4, FN 3**. F005-R2: 1/4 correct; F010: 0/4 correct. Constant no-defect and source graph-distance baselines both achieved 4/8 (50%) accuracy; the learned model did not outperform either.

Against weak defect-span annotations, final-test localization Hit@1 = 1/4 and Hit@3 = 1/4, assessed over **all four defective test pairs, including classification misses**. Those are ranking diagnostics, not independently validated localization accuracy.

The six training families and two test families are too few to establish broad migration performance. The held-out cash-quantization and GCD algorithms differ from the training families, and the measured scores show that this model does not handle that shift reliably. More independent families and expert-reviewed defects are required before making reliability claims. Do not improve parameters after seeing these test outcomes and reuse them as an unseen estimate; future development needs a new independent evaluation set or explicit test-reuse disclosure.

## Demo and API

The UI's F006-V4 default is explicitly a **training example**. Source-only learned inference gives it risk about 0.968 and ranks COBOL line 23 / Java line 10 first, highlighting Java's `.abs()` on the final signed result. Its correct F006-V2 control scores about 0.391, below the 0.5 threshold. This demonstrates a real learned prediction, not held-out generalization. The separately recorded compiler replay demonstrates an actual behavioral error; it is not fabricated as an AI-generated counterexample.

Status:

```sh
cd ml-engine
printf '%s' '{"action":"status"}' | .venv/bin/python -m ml_engine.defect_detection --stdin
```

Analyze a JSON object on stdin containing `cobolSource`, `javaSource` and `cobolSourceFormat` (`FREE` or `FIXED`). The response includes uncalibrated risk, `MODEL_HYPOTHESIS` findings, exact source hashes/excerpts, and `aiIsProof=false`, `counterexamplesExecuted=false`. At most three ranked areas are displayed when review is required. These are suspected areas, not three asserted errors.

Tests:

```sh
ml-engine/.venv/bin/python -m pytest ml-engine/tests/test_defect_detection.py -q
```

The focused suite covers source-only invariance, one-sided spans, numeric receiving fields, keyword and method operator extraction, constant localization, three disjoint fold checkpoints, raw CRLF excerpts, missing artifacts, unsupported sources, limits and the genuine training-example inference.

## Training dependencies and reproduction

Training used Python 3.13, NumPy 2.3.4 and scikit-learn 1.7.2. Runtime uses the project's existing NumPy pin only. The exact training-only pin is in `training-requirements.txt`.

The commands originally run, before the final report existed, were:

```sh
ml-engine/.venv/bin/python ml-engine/scripts/train_defect_model.py
# Model and implementation hashes frozen and recorded here before final testing.
ml-engine/.venv/bin/python ml-engine/scripts/train_defect_model.py --evaluate-frozen-test
```

They intentionally refuse overwriting the now-assessed experiment. Reproduction or improvements should use a separately versioned output/model destination and disclose that the current test outcomes are known. No source code, labels, splits, original matching artifacts or dataset curation reports were changed by training.

All feature extraction, training/inference integration, synthetic training data and this report were AI-assisted. The observed runtime evidence and evaluation numbers are recorded outputs, not claims of human expert review.
