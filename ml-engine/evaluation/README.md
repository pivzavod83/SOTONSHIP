# Paired-program training and evaluation

## Local synthetic defect detector (18 October 2026)

The supplied-pair detector is now implemented, trained and evaluated in [synthetic-pilot/defect-model-v1](synthetic-pilot/defect-model-v1/README.md). Its grouped fold ensemble and learned span ranker use six training families/24 pairs, two validation families/eight pairs and two final test families/eight pairs, without a full refit. Final accuracy was **1/8 (12.5%)**, below both 50% baselines, with four false positives and three missed defects. This failed generalization result is preserved and shown in the UI. Training-example localization is a functional demonstration, not unseen performance. Frozen source data, coefficients, code snapshots and selection/test records are separate from all historical matching experiments and the natural-data curation below.

## Real translation-defect corpus audit (18 October 2026)

The natural-data research below concerns defect detection/localization within an already supplied pair. It has not supplied admitted training labels for the separate synthetic detector. Retrieval experiments remain evidence for a different objective.

The subsequent [COBOL-to-Java execution audit](defect-corpus/README.md) inventoried 286 published natural translations, screened the development candidates, and executed all 681 original development COBOL drivers. Bounded shared-input replay covers 19 tasks and reproduces four disagreeing inputs in **two candidate programs/source tasks**. Java screening failures and COBOL reference/oracle disagreements are reported separately. The 23 reserved families were not executed; no replacement model or independently human-reviewed gold labels were produced. Exact counts, contracts, hashes, exclusions and reproduction instructions are in the linked audit.

The [expanded adjudication](defect-corpus/expanded-c2j/README.md) now covers all 23 previously untriaged flagged families: four additional source tasks have control-supported discrepancies, eleven show no mismatch on scoped shared inputs, six have reference/representation conflicts and two remain unsupported. The combined review queue has six candidate programs/source tasks and 25 witnesses; shared replay spans 40 development tasks. All cases remain pending independent human review, with no new model or accuracy claim.

The [source catalogue](../../data-sources/reviewed-translation-defect-candidates.json) records upstream review links, pre-fix/fix commits, regression paths, licences and exclusions. Open-source COBOL 4J provides reviewed COMP-comparison and EXTERNAL-storage defect candidates, plus a conditional PROGRAM-STATUS feature-support change. These are compiler/runtime regressions, not a ready-made enterprise migration dataset. Before admission, reproduce each case with pinned compiler/runtime revisions; none has been locally admitted yet. Syntax failures, runtime-only fixes invisible to the model, original COBOL bugs and policy changes are separate categories.

For an adjacent source, the pinned [Lost in Translation artifact](https://zenodo.org/records/10447705) was downloaded into the ignored corpus cache, its published MD5 verified, and its manual-label workbook inspected without executing source. The [measured inventory](defect-corpus/translation-label-audit-2026-10-18.json) contains **1,748 annotation rows but 1,558 distinct translation identifiers**. Java-target rows comprise **293 annotations for 267 translation identifiers**, including **81 distinct identifiers with a wrong-output annotation**. Impact categories can overlap within one translation, so their counts must not be summed. None involves COBOL. These are naturally occurring model translation failures with author-reviewed categories; repair outputs are not universally human-reviewed fixes. Source/test joins, reproductions, unaffected controls and overlap checks remain pending.

Reproduce the metadata measurement with the exact archive from `https://zenodo.org/api/records/10447705/files/artifacts.zip/content`, running from `ml-engine/`:

```sh
.venv/bin/python scripts/audit_reviewed_translation_labels.py evaluation/corpora/reviewed-defects/lost-in-translation-v4-artifacts.zip --collected-date 2026-10-18
```

This reader validates archive/workbook hashes, normalizes language/impact spelling, and separates annotations from translation IDs. It does not execute code, generate bugs or train. Its output records zero admitted training examples. The archive is CC-BY-4.0 per the publisher, with original code licences retained separately. AlphaTrans supplies developer-repaired Java-to-Python translations; CMS supplies real migration source but no verified reviewed translation-defect triples in this audit. Neither establishes COBOL-to-Java defect accuracy.

The [draft measurement protocol](defect-corpus/measurement-protocol-draft.json) defines evidence units, labels, admission rules, grouped splits, controls and metrics. Split by issue family/project, not assertion or source line. Audit cross-corpus HumanEval/EvalPlus/CodeNet overlap before pretraining, including the existing 23 reserved families. Those 23 remain excluded from fitting, but have no defect labels and do not by themselves constitute a defect-detection test set. A COBOL defect holdout needs eligible independently reviewed cases; do not turn a few issues into a nominal 23-case benchmark by counting repeated assertions. Java-only and compiler-version baselines, paired-input ablations, false negatives, localization and repair-budget measurements test what the AI actually contributes. This audit, its code and the proposed protocol are AI-generated and require human review; upstream review evidence is linked rather than invented.

## Preserved correspondence experiment

The active **v4 graph-regularized GNN ensemble** was selected by development-only cross-validation from four paper-inspired improvements and a freshly trained control. Every candidate retains five separately fitted models, each trained on **96 original COBOL–Java pairs**, and averages their cosine scores. **No model is fitted or refitted on all 120 development pairs.** The same **23 tasks are reserved for final evaluation**, excluded from fitting, preprocessing statistics, checkpoint selection and model selection.

Training uses the pinned **143-pair COBOL-JavaTrans** benchmark. Generated financial fixtures and the deleted synthetic risk labels are excluded. This is whole-program correspondence retrieval, not defect prediction, source generation or formal-equivalence classification. All application, model and experiment code introduced for this work is AI-generated and requires human review; upstream source retains its attribution.

## Four improvements and their supporting papers

All variants retain the unchanged bounded heuristic graph extractor, feature schema and frozen task partitions. These are small-data adaptations to test, not reproductions of the cited systems or guarantees that their published results transfer to COBOL–Java matching.

| Candidate | Implemented change | Research motivation |
| --- | --- | --- |
| `count_readout` | Concatenate each layer's mean, maximum and sum divided by the square root of node count; add an explicit log node-count coordinate before the learned projection. This retains information discarded by a global mean. | [Xu et al., *How Powerful are Graph Neural Networks?*, ICLR 2019](https://arxiv.org/abs/1810.00826) studies aggregation/readout expressiveness. This candidate is not GIN and carries no 1-WL expressivity claim. |
| `language_heads` | Keep the shared GNN backbone but learn separate COBOL and Java projection heads using the paired InfoNCE objective. Heads start identically and then receive their respective language gradients. | [Andrew et al., *Deep Canonical Correlation Analysis*, ICML 2013](https://proceedings.mlr.press/v28/andrew13.html) motivates paired-view representation learning. This candidate uses InfoNCE, not the DCCA objective. |
| `structural_cca` | Extract fixed hashed relation-aware WL counts for rounds 0–2, semantic statistics and graph sizes; fit separate centering/scaling and ridge-regularized linear CCA projections using only the 96 fitting pairs. Ridge is fixed at 0.1, output width 24, and hash width 512. | [Shervashidze et al., *Weisfeiler-Lehman Graph Kernels*, JMLR 2011](https://www.jmlr.org/papers/v12/shervashidze11a.html) motivates multiscale structural features; [Andrew et al.](https://proceedings.mlr.press/v28/andrew13.html) discusses CCA and paired views. This is regularized linear CCA, not deep CCA. |
| `graph_regularized` | During fitting, independently drop 10% of auxiliary sequence links in expectation, keeping both edge directions together and recomputing degree weights. Preserve every data/control edge and numeric feature. Evaluate unmodified graphs. | [You et al., *Graph Contrastive Learning with Augmentations*, NeurIPS 2020](https://proceedings.neurips.cc/paper/2020/hash/3fe230348e9a12c13120749e3f9fa4cd-Abstract.html) motivates graph augmentation. This is GraphCL-inspired regularization, not a full GraphCL reproduction. |

The control is the original two-layer relation-aware GNN with global mean pooling. Neural candidates use hidden/output width 24, symmetric paired InfoNCE at temperature 0.12, Adam at learning rate 0.004, weight decay 0.0001, fresh seed 431 and fresh optimizer state for every fold, and a fixed 250-epoch budget. Identifier spelling, comments, task names and program/method names are excluded from learned features. Graph augmentation creates fitting views of existing pairs; it does not add authentic source pairs or establish behavior-preserving code transformations.

## Five-fold partition and selection

The immutable [partition plan](paired-code/cv-partition-plan.json) reserves **23 final fitting-holdout tasks** and assigns **120 development tasks** to **five validation folds of 24**. Each member fits the other **96** pairs. Five folds retain useful fitting size and a 24-candidate validation gallery; ten folds would leave only 12 validation queries per fold.

Graph partitioning operates on a task-similarity graph: a vertex is an entire COBOL–Java task pair. Tasks are connected when either language has identifier-normalized five-token-shingle Jaccard similarity at least 0.80, or an identical three-round relation-aware Weisfeiler-Lehman graph fingerprint. Whole connected components stay together across the outer split and all folds. There are 142 components: 141 singletons and the near-duplicate pair HumanEval/40 and HumanEval/43. Individual program graphs remain intact; nodes are never divided between fitting and evaluation. This conservative heuristic can miss semantic duplicates and does not establish algorithmic equivalence.

The 23 tasks were originally chosen by fixed seed/hash ordering from v1's 29-task test split, without predictions or metrics. None came from v1 fitting or validation. **All 23 were subsequently evaluated in v1, v2 and v3. The v4 comparison was requested after those results were known.** They remain excluded from every v4 fit and selection decision, but final results are descriptive evidence on a reused benchmark, not pristine unforeseen-data evidence. The other six old test tasks are now in development. Independent new examples are needed for confirmatory generalization claims.

The partition file retains its historical v2 full-development-refit instruction. The v4 [run plan](paired-code/cv-v4-candidates/run-plan.json) explicitly supersedes that policy, reusing only the frozen graph components and assignments. The plan declares all four improvements, the control, fixed hyperparameters, selection rules and research citations before fitting.

Neural checkpoints are recorded at epoch 1 and every ten epochs. For each candidate, select one common epoch across all five trajectories by pooled development **Top-1 accuracy**, then MRR, then lower validation loss, then the earliest epoch. CCA has one closed-form fitting stage, recorded as epoch 1. Select the candidate by pooled Top-1, then MRR, then the declared fixed tie order: control, structural CCA, graph regularization, language heads, count readout. The Top-1-first rule is declared for v4; historical v3 selected its epoch by MRR first.

Each development query is scored only by the member whose fitting set excluded that query's fold. The other four members trained on that query and cannot supply honest out-of-fold scores. CCA centering, scaling and projections fit only the current 96-pair fitting matrices; fixed hashed features require no corpus-fitted vocabulary. No validation or final examples supply preprocessing statistics.

The deployed score is the fixed arithmetic mean of five member cosine scores, with weights **0.2 each**. Independently fitted weights or embeddings are never averaged. Runtime concatenates the five member embeddings, divided by the square root of five, so their dot product equals the mean cosine score. No member is discarded or refitted.

## Development results

Selected-checkpoint out-of-fold results use **120 queries**, each with its **24-candidate validation gallery**:

| Candidate | Common epoch | Top-1 | Top-3 | Top-5 | MRR |
| --- | ---: | ---: | ---: | ---: | ---: |
| Fresh control | 80 | 51/120 (42.50%) | 73/120 (60.83%) | 85/120 (70.83%) | 0.558347 |
| Structural CCA | 1 | 34/120 (28.33%) | 65/120 (54.17%) | 87/120 (72.50%) | 0.466263 |
| **Graph regularization — frozen CV winner** | **80** | **51/120 (42.50%)** | **76/120 (63.33%)** | **87/120 (72.50%)** | **0.565796** |
| Language heads | 50 | 48/120 (40.00%) | 75/120 (62.50%) | 88/120 (73.33%) | 0.556921 |
| Count readout | 20 | 43/120 (35.83%) | 74/120 (61.67%) | 90/120 (75.00%) | 0.529817 |

Graph regularization tied the control on Top-1 and won the declared MRR tie-break. The corresponding five epoch-80 models became the frozen deployment choice **before final evaluation**. These statistics helped select checkpoints and a candidate, so they are exploratory selection evidence, not an unbiased nested-CV estimate. They also evaluate one excluded-fold member per query, not the deployed five-member ensemble.

## Reserved 23-pair evaluation

All five candidate ensembles, selected epochs, member hashes, the fixed review gate and CV report were frozen before learned encoding or scoring of the 23 reserved tasks. The one-shot final evaluator scored every frozen model on the identical **23-query, 23-candidate gallery**. It did not change the deployment decision based on these results.

| Model | Top-1 | Top-3 | Top-5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| **Active graph-regularized ensemble — CV-selected** | **9/23 (39.13%)** | **15/23 (65.22%)** | **17/23 (73.91%)** | **0.563294** |
| Fresh control | 7/23 (30.43%) | 15/23 (65.22%) | 16/23 (69.57%) | 0.494808 |
| Language-head ensemble | 11/23 (47.83%) | 15/23 (65.22%) | 18/23 (78.26%) | 0.608769 |
| Count-readout ensemble | 9/23 (39.13%) | 13/23 (56.52%) | 18/23 (78.26%) | 0.532901 |
| Structural CCA ensemble | 4/23 (17.39%) | 12/23 (52.17%) | 14/23 (60.87%) | 0.392066 |
| Name matching | 22/23 (95.65%) | 22/23 (95.65%) | 22/23 (95.65%) | 0.958810 |
| Semantic histogram | 6/23 (26.09%) | 8/23 (34.78%) | 10/23 (43.48%) | 0.372134 |

The active ensemble improves the observed first-match count by **two queries** over the control: **30.43% to 39.13%**, an **8.70 percentage-point** increase. Top-5 improves by one query and MRR by 0.068486. With only 23 queries, one result changes accuracy by 4.35 percentage points; this does not establish statistical significance or production reliability.

Language heads scored highest among learned candidates on this final set. They remain a reported alternative rather than becoming the active model: switching after seeing final results would use the evaluation set for model selection. Name matching still substantially outperforms every learned candidate on this benchmark and is reported openly. The learned representations exclude name spelling; these results do not establish superiority over that baseline.

Every ranking still requires engineer review. Cosine scores are not calibrated correctness probabilities. The benchmark contains small HumanEval-derived programs, not production banking migrations, and labels task correspondence rather than statement equivalence or defects. Z3 remains independent and uses only its explicit supported financial contract. CV galleries have 24 candidates and final galleries have 23, so changes across those gallery sizes must not be advertised as accuracy gains.

## Evidence and reproduction

The completed [v4 experiment](paired-code/cv-v4-candidates/) is immutable:

- [run-plan.json](paired-code/cv-v4-candidates/run-plan.json): all candidate configurations, 11 source snapshots, fixed selection rules, papers and prior exposure.
- [cv-training-report.json](paired-code/cv-v4-candidates/cv-training-report.json): complete fold histories, selected checkpoints and the CV winner.
- [model-freeze.json](paired-code/cv-v4-candidates/model-freeze.json): all five candidate artifact hashes, 25 member checkpoints and the CV report frozen before final scoring.
- [final-evaluation-report.json](paired-code/cv-v4-candidates/final-evaluation-report.json): exact gallery order, saved per-query scores/ranks, every member and all candidate results.
- [deployment-manifest.json](paired-code/cv-v4-candidates/deployment-manifest.json): active artifact hash and binding to unchanged frozen winning members.

The run ID is `paired-v4-candidates-ee8575e5e10c63c3`; final report SHA-256 is `845efad622d5c43aa7f5719bdf4196d2614dcec2212f81ce07c17dce2f4a7cea`; active model SHA-256 is `8ce9c4392fbdf84553fcc2b734e40e12cb1b819041d477a6627e761559bce055`. The frozen plan SHA-256 is `27a9efb718b9ac8bc24a3eef503cccda8b2239176dd7f2cb3d70cc410c4a6214` and the pre-evaluation model-freeze SHA-256 is `62a9ca1d7cb4303c2aec56ae2666c92f2c861e43504363fe0ab46c83f5a0eccb`.

The completed default stages refuse reruns and overwriting their audit trail. Inspect saved reports. For an explicitly declared reproduction, use a **new empty output directory** and a separate model output for all three stages. From `ml-engine/`, for example:

```sh
.venv/bin/python scripts/fetch_paired_dataset.py
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --prepare --output-dir /tmp/sotonship-v4-reproduction --model-output /tmp/sotonship-v4-reproduction-model.json
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --train --output-dir /tmp/sotonship-v4-reproduction --model-output /tmp/sotonship-v4-reproduction-model.json
OPENBLAS_NUM_THREADS=1 .venv/bin/python scripts/train_paired_candidates.py --evaluate-final --output-dir /tmp/sotonship-v4-reproduction --model-output /tmp/sotonship-v4-reproduction-model.json
```

This reuses the versioned partition; do not edit assignments or overwrite completed records. A new directory does not make the previously observed 23 tasks unforeseen or justify tuning on them. If numerical source later changes, reproduce historical experiments in a separate checkout by restoring the respective `source-snapshot/` files to their original paths and matching the recorded NumPy environment. Snapshots preserve numerical provenance; they are not standalone projects containing dependencies, data or weights.

The fetcher pins upstream commit `2b14b7bf7e55556205654c6f7657fa60e36251fa`, verifies dataset SHA-256 `ff1b2e308ea006d905fd979103f32486c57d586c5fdbc0325a23f8ae23a6530d`, and caches raw source under ignored `evaluation/corpora/cobol-javatrans/`. Repository terms are Apache-2.0 with underlying HumanEval MIT attribution; retain the notices linked from `data-sources/paired-code/`.

## Preserved history and remaining limits

[cv-v3-fold-ensemble/](paired-code/cv-v3-fold-ensemble/) retains the previous five-member no-refit GNN, its no-message ablation and every original artifact unchanged. Its GNN selected epoch 80 by development MRR; the fresh v4 control also selects epoch 80 and reproduces its final metrics. The v3 report SHA-256 remains `db17a859e2a2bfb8096187bc0b1977fd83838f2db8000e96e54a1913f45547e9`; model SHA-256 remains `afd5b36cfd1c0d9b0f8e9f00105216c0d602af7ed2b62948f9120c141657159c`.

[cv-v2/](paired-code/cv-v2/) preserves historical five-fold selection followed by a 120-pair refit, its original model and reports. Its [source snapshot manifest](paired-code/cv-v2/source-snapshot-manifest.json) verifies six archived numerical files against original hashes. Current loader changes do not rewrite historical hashes. `train_paired_gnn_cv.py` is the historical v2 trainer, and `train_paired_gnn_fold_ensemble.py` targets historical v3; their completed default experiments must not be rerun.

Historical comparisons already measured on the same reserved 23-task gallery are retained here for context, without new fitting or inference:

| Historical model | Top-1 | Top-3 | Top-5 | MRR |
| --- | ---: | ---: | ---: | ---: |
| v3 retained-fold GNN | 7/23 (30.43%) | 15/23 (65.22%) | 16/23 (69.57%) | 0.494808 |
| v3 no-message ensemble | 9/23 (39.13%) | 14/23 (60.87%) | 15/23 (65.22%) | 0.532848 |
| v2 GNN, refitted on 120 | 8/23 (34.78%) | 13/23 (56.52%) | 15/23 (65.22%) | 0.494939 |
| Previous v1 GNN | 11/23 (47.83%) | 15/23 (65.22%) | 17/23 (73.91%) | 0.581181 |

These experiments do not isolate a causal effect of full-development refitting or establish that the earlier refit increased weight variance. The v4 choice preserves all five fold models as requested.

[task-splits.json](paired-code/task-splits.json), [training-report.json](paired-code/training-report.json), [rename-stress-report.json](paired-code/rename-stress-report.json) and v1 weights preserve the earlier 85/29/29 pilot. `train_paired_gnn.py` and `evaluate_paired_gnn.py` explicitly target v1. Its old 29-task test cannot be advertised as a v2/v3/v4 holdout because six members now enter development. The declaration-rename stress test is historical evidence, not a new independent holdout.

The [reviewed node/defect workflow](reviewed-risk-workflow.md) remains for future labelled studies and is a different task from active matching. The historical 88-pair CodeTransOcean corpus is unavailable here and unused. Reliable next evidence requires new independently held-out authentic migration pairs, financial-domain evaluation, and labels appropriate to any future defect/localization task. No additional representation, augmentation or hyperparameter search was performed after the v4 final results.
