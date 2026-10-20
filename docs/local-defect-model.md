# Local learned defect review

The local detector is implemented, trained and connected to the browser UI.
It examines an already supplied COBOL/Java pair and ranks suspicious source
locations. It requires no LLM API key. **It failed the held-out pilot evaluation:
1/8 correct (12.5%), versus 4/8 for both baselines.** Treat this version as a
demonstration of an experimental learned workflow, not a reliable verifier.

## Use the workbench

Start the API with the existing PostgreSQL configuration, then start the UI:

```sh
cd backend
npm run build
HOST=127.0.0.1 PORT=3003 npm start
# In another terminal, from backend/:
BACKEND_ORIGIN=http://127.0.0.1:3003 npm run ui
```

Open **http://127.0.0.1:3000**. The default signed-balance example belongs to the
training set and is labelled accordingly. Click **Run local defect model**.
Its actual learned top-ranked location is Java line 10, corresponding to COBOL
line 23. Java incorrectly applies `.abs()` to the final signed balance.
Click the finding to jump to and select the highlighted lines.

Red `!` locations are separately recorded, source-bound execution evidence;
amber `M` locations are `MODEL_HYPOTHESIS`. A line with both keeps the red
confirmed marker. The example's actual offline execution gives COBOL `-100`
and Java `100` for opening balance `500`, adjustment `-800`, fee `400`.
This is an AI-generated educational program with a real observed discrepancy,
not a production-bank incident or unseen model evaluation.

Select **Reviewed correction** and rerun: the prewritten control preserves the
signed output and scores below the model's 0.5 threshold. A lower score is not
proof. Edit either source to clear every stale finding, witness and proof.
Recorded evidence reappears only when exact source hashes match the fixture.
No editor source is compiled or executed by this UI.

The signed-balance program is outside the existing Z3 grammar and stays
`UNKNOWN`. Select the FX example for the supported bounded Z3 demonstration.
The optional cloud action is separate and sends source externally only when
explicitly requested with a configured provider. Local analysis stays local.

## Learned model and measured limits

The extractor builds heuristic statement/dependency graphs carrying arithmetic,
rounding, receiving-field, scale, sign and literal features. Source-derived
candidate correspondences include missing and extra operations. Each fold learns
two regularized logistic heads: a span ranker and a pair classifier. The model is
**a graph-feature classifier, not a trained GNN or complete compiler**. Learned
coefficients determine both the review score and location order.

The frozen dataset contains ten synthetic families / forty pairs. Six training
families supply 24 pairs; validation and testing each contain two families /
eight pairs. Three grouped fold checkpoints each fit four training families /
16 pairs; runtime averages them. There was no final full-training refit.
Preprocessing and localization supervision stay inside the fitting fold.
Architecture/regularization selection used training-only out-of-fold results;
validation selected the threshold. Pre-test validation exploration is disclosed.
The selected artifact and implementation were frozen before final testing.

| Assessment | Correct | Accuracy | Precision | Recall | F1 |
| --- | ---: | ---: | ---: | ---: | ---: |
| Grouped OOF model selection | 16/24 | 66.7% | 70.0% | 58.3% | 63.6% |
| Validation threshold selection | 4/8 | 50.0% | 50.0% | 50.0% | 50.0% |
| Frozen final test | 1/8 | 12.5% | 20.0% | 25.0% | 22.2% |

Final counts are TP1, TN0, FP4, FN3: four correct translations were flagged and
three defects were missed. Both constant no-defect and source graph-distance
baselines achieved 50% accuracy. Weak-annotation location Hit@1 and Hit@3 were
both 1/4 defective test pairs, including classification misses. Locations are
AI-proposed supervision, not independently reviewed gold labels.

A separate read-only audit confirmed the stored confusion counts and found no
obvious reversed labels, scoring-sign error or split leakage. Each fold fits
398 classifier features from just 16 pairs. The heuristic extractor also has
known blind spots, including some COBOL `FUNCTION ABS`/`MOD` features and Java
spacing or multiline statements. These representation limits remain in the
frozen evaluated version; correcting them requires a new model version and
independent evaluation.

No model tuning followed the final assessment. The UI exposes the failure
prominently through a hash-bound aggregate report; it does not modify the frozen
weights to add metrics. The source/labels had already undergone quality review,
so this is not a pristine blind benchmark. Two test families are far too few for
a reliable generalization claim. Future improvements need a new independent
evaluation set or explicit disclosure of test reuse.

## API, evidence and reproduction

`POST /api/defect-reviews` accepts only the supplied source pair, optional display
name and `FREE`/`FIXED` format. `GET /api/defect-reviews/status` reports the loaded
weight/dataset hashes. The readonly Nest module follows presentation → QueryBus
→ handler → domain/application port → shared bounded Python worker. It has no
persistence table or authority over verification/patch commands.

Responses carry exact UTF-8 source hashes, raw LF line spans and excerpts,
uncalibrated scores and `MODEL_HYPOTHESIS` findings. Both `aiIsProof` and
`counterexamplesExecuted` are false. Missing model and unsupported sources stay
explicit; a low score or empty result never establishes equivalence. Labels,
IDs, variant ordering, split metadata, explanations, supplied alignment labels,
test inputs and test outputs are not inference features.

Portable runtime weights: `ml-engine/ml_engine/models/defect_model_v1.json`.
Inference uses the project's pinned NumPy only. Training used NumPy 2.3.4 and
scikit-learn 1.7.2; training-only pins, fold models, exact implementation snapshots,
protocol, selection history, freeze record and per-pair results are in the
[immutable experiment directory](../ml-engine/evaluation/synthetic-pilot/defect-model-v1/README.md).
The trainer refuses another final assessment or retraining of this completed
version. Reproduction or improvement requires a separately versioned output and
disclosure that these test outcomes are known.

Useful checks, from the indicated directories:

```sh
cd ml-engine
.venv/bin/python -m pytest -q
cd ../backend
npm run build
npm test
npm run test:ui
node test/local-defect.live.mjs
```

The live check requires the API on port 3003 (`API_URL` overrides it). The
original 143-pair matcher, reserved 23 families, proof engine and frozen source
datasets are unchanged. All new extractor, training, integration, interface and
documentation work is AI-assisted and needs human review.

## Post-hackathon audit: 20 October 2026

The cleanup on `post-hackathon-ideas` removes the retired private node/risk
evaluator, its rejection-only test, an unused matching-module constant, an orphaned
backend value object, write-only editor state and an unused browser demo alias.
Active review, matching, verification and correction workflows remain. Historical
trainers and models are still referenced by reproducibility tools, shared
training utilities and compatibility tests; they are not dead code. Frozen
datasets, weights, source snapshots, reports and once-only evaluation markers
are retained unchanged.

Cleanup validation: 413 Python tests, 165 backend tests, 27 extension tests and
nine UI tests pass; the backend build and strict TypeScript unused-code checks
pass. The Python total is one lower because the removed evaluator's rejection
test was also removed. All 22 frozen defect-artifact hashes still match.

The model's failure is not evidence that its binary labels should be flipped or
that a larger model will work. Forty pairs represent ten source families. Only
six families supply training examples; each retained fold fits 398 classifier
features to 16 pairs from four families. The localizer has 135 features, and its
many statement candidates are correlated observations. None of the training
COBOL families contains a loop; the known final-test GCD family introduces one.
These are coverage and representation limitations, not a new benchmark result.

A source-only diagnostic, using newly written illustrative snippets rather than
the evaluation set, found that both versions below produce identical candidate
and program feature arrays in the frozen extractor:

```java
BigDecimal result = amount.subtract(fee);
return result;
```

```java
BigDecimal result = amount.subtract(fee);
return result.abs();
```

The parser ignores the return statements, so a model receiving those features
cannot distinguish these implementations even with more training examples.
These snippets were not executed or added to training. Other source inspection
found missing COBOL `FUNCTION ABS`/`MOD` features, dropped multiline remainder
definitions, missing unary-negation features, incomplete receiving-variable/type
tracking and width comparisons expressed in different units. The pair classifier
also learns from in-sample localizer predictions; inner grouped cross-fitting is
a candidate remedy for that stacking mismatch. The frozen v1 extractor has not
been changed: fixes require a separately versioned implementation and evaluation.

### Recommended next experiment

1. Repair and independently check a v2 representation: statement boundaries,
   declarations, signedness, decimal precision, storage behavior, return values,
   unary operations, data dependencies and loop/control relationships. Preserve
   source locations; compare function or dependency slices with their context.
2. Review the six reproduced natural discrepancy families before admitting them
   as labelled training data. Keep behavioral mismatches, compiler errors,
   unsupported interfaces and inconclusive runs separate. Test agreement alone
   is scoped evidence, not a universal equivalence label. Keep weak location
   annotations separate from reviewed fault locations.
3. Add independent source families and defect types, including harmless
   equivalent rewrites. Group all translations, variants, fragments and near
   clones of a source together. Ten variants of one algorithm are not ten
   independent algorithms. Build learning curves by family count rather than
   assume a required sample count or accuracy gain.
4. Compare a compact, strongly regularized logistic baseline with shallow
   gradient-boosted trees and, if feasible, frozen code embeddings plus a small
   trained classifier. Select features, preprocessing and settings within the
   fitting folds. Cross-fit localization scores used by the pair classifier.
   Learn the ranker separately from the pair-level defect decision, and add
   explicit unsupported/abstention behavior.
5. Preserve the known eight-pair test as a regression set. Obtain new independent
   holdout families before a new final assessment, freeze the representation,
   weights and threshold, then evaluate once. Report precision, recall, false
   alerts, localization Hit@k, per-family counts and abstention coverage. Compare
   with constant predictions, semantic rules and the current frozen model.

For this project, compiler-backed differential checks and supported Z3 queries
should establish evidence; ML should prioritize suspicious functions and source
locations for review. Inputs outside the current parser's coverage must not be
treated as harmless. Future offline execution must retain the existing bounded,
reviewed corpus workflow rather than expose arbitrary code execution through the
HTTP API.

Research supports these as candidates to test, not guaranteed improvements:

- [Grinsztajn et al., NeurIPS 2022](https://proceedings.neurips.cc/paper_files/paper/2022/hash/0378c7692da36807bdec87ab043cdadc-Abstract-Datasets_and_Benchmarks.html)
  motivate tree baselines for tabular features. Their medium-sized datasets do
  not establish performance on our tiny COBOL corpus.
- [Prokhorenkova et al., NeurIPS 2018](https://proceedings.neurips.cc/paper/2018/hash/14491b756b3a51daac41c24863285549-Abstract.html)
  describe CatBoost, one candidate for nonlinear feature interactions.
- [Northcutt et al., JAIR 2021](https://jair.org/index.php/jair/article/view/12125)
  provide methods for auditing noisy labels. With this weak model, disagreement
  should trigger review, never automatic relabelling or removal of hard cases.
- [Guo et al., ICLR 2021](https://arxiv.org/abs/2009.08366)
  motivate data-flow-aware pretrained representations. Their results do not
  establish COBOL-to-Java defect detection or justify training a large GNN on
  ten families.

The recommendations above have not been implemented or trained. Cleanup is not
an accuracy improvement, and the recorded final result remains 1/8.
