# Paired-program training and evaluation

The active model learns whole-program COBOL/Java correspondence from the pinned **143-pair COBOL-JavaTrans** benchmark. The random-feature trainer and XGBoost risk classifier were removed. Nothing in this training uses the four generated financial regression fixtures or the old synthetic risk labels.

## Reproduce

From `ml-engine/`:

```sh
.venv/bin/python scripts/fetch_paired_dataset.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_gnn.py
```

The fetcher pins upstream commit `2b14b7bf7e55556205654c6f7657fa60e36251fa`, records the SHA-256 and licence attribution, and puts raw code under ignored `evaluation/corpora/cobol-javatrans/`. Do not add source code to Git or represent it as production bank code. Repository terms are Apache-2.0 with underlying HumanEval MIT attribution; retained notices are linked from `data-sources/paired-code/`.

## Objective and split

`paired-code/task-splits.json` assigns whole original tasks and transitive near-duplicate groups before fitting. There are **85 train / 29 validation / 29 test** tasks. All fragments, renamed versions or other derivatives of a task must remain in its original split. No identifier spelling, comments, task IDs or declared method/program names are model features.

The encoder uses two relation-aware message-passing layers over operation/type/literal graphs with approximate data/control/sequence edges. A contrastive objective rewards paired COBOL/Java programs; selected other tasks act as negatives. Different tasks are not assumed formally inequivalent. This is correspondence learning, not a correctness oracle.

Validation selects checkpoints and the similarity/margin gate. The final test is for reporting, not parameter or threshold selection. The report also discloses prior observed-test results from an implementation reviewed for feature leakage; code-review corrections were made without selecting changes by test score. Treat this as an exploratory pilot, not a pristine external validation study.

## What is reported

Read [training-report.json](paired-code/training-report.json) for actual Top-1/Top-3/Top-5 retrieval and mean reciprocal rank, query counts, candidate counts, model and dataset hashes, training history, selected epochs, thresholds and limitations. Baselines include normalized-name matching, semantic feature histograms and a separately trained encoder of comparable capacity without message passing.

The current GNN does not establish superiority to name matching on the original named benchmark. Numerical cosine similarity is not a bug probability or proof. Small validation samples may fail to support a suggestion gate; the API then deliberately returns `REVIEW_REQUIRED` while still displaying ranked candidates. Financial-domain reliability is unvalidated.

## Separate future work

The old [reviewed node/defect workflow](reviewed-risk-workflow.md), schema and importer are retained for future labelled studies. They are not the active trainer, and the current model does not predict their risk or statement labels. The historically documented 88-pair CodeTransOcean test corpus is separate, is not included in this training, and is not available in this checkout. Do not silently turn reserved test data into training examples.

Exact fault localization, risk classification and patch generation require additional labelled work. Z3 proofs remain independent and limited to their recorded financial scope.

## Frozen renamed-code stress test

Run `.venv/bin/python scripts/evaluate_paired_gnn.py` to evaluate the same stored model and same 29 test tasks after anonymizing Java declaration names. [rename-stress-report.json](paired-code/rename-stress-report.json) preserves both original and anonymized results and the exact candidate order. It does not retrain or retune thresholds. This controlled removal of name information is not a new independent holdout or an estimate of production performance.

Current measured test results: GNN Top-1 11/29 (37.93%), Top-5 20/29 (68.97%), no-message Top-1 8/29 (27.59%), original-name baseline Top-1 27/29 (93.10%). Under controlled declaration anonymization the GNN scores are unchanged and name-only Top-1 is 1/29 (3.45%). The validation gate did not establish reliable suggestions, so the shipped model deliberately requires manual review.
