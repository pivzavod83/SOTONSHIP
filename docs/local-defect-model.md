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
