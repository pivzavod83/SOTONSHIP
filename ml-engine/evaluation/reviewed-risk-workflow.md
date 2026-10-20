# Human-reviewed corpus preparation

The importer and review templates below prepare future human-labelled research data. The obsolete `ml_engine.evaluate_review_set` command was removed on the post-hackathon branch: it targeted a retired node-alignment/risk model and could not evaluate any shipped model. There is no replacement evaluator for this private-corpus schema yet.

The active GNN measures whole-program correspondence. The separate synthetic defect pilot has its own frozen dataset, protocol and failed evaluation. Neither can be evaluated as a human-reviewed statement mapper by using this template. Importing or completing reviewer labels does not train a model or establish accuracy.

## Protecting source code

Keep real COBOL and Java outside Git, in an approved access-controlled location. Obtain authorization for evaluation and ML use, follow the code owner's retention and deletion requirements, and remove secrets and customer data only through an approved process. Do not copy production source into this repository. The corpus JSON references source files by relative path and SHA-256 so reviewers and reports can identify exact versions without embedding their contents in the manifest.

No approved corpus is included with the repository. The JSON template is deliberately incomplete: its source files, hashes, reviewer identities, and adjudications must be replaced with authorized real review data before it is eligible for a future, task-specific evaluation.

Keep the completed manifest and its source files together in the approved access-controlled location. For JSONL datasets, the preparation command can create an **unreviewed draft**. It defaults every case to the test split and rejects output inside this repository. It supports generic paired JSONL and CodeTransOcean NicheTrans rows (`id`, `name`, `COBOL`, `Java`). Example for the CodeTransOcean COBOL-to-Java slice:

```sh
.venv/bin/python -m ml_engine.prepare_review_corpus /path/to/niche_test.json \
  --input-format codetransocean-niche \
  --output-dir /approved/storage/cobol-java-review \
  --dataset-id codetransocean-niche-cobol-java-test \
  --dialect-profile GNUCOBOL_3_2_COMPATIBILITY_CANDIDATE_UNCONFIRMED \
  --source-format AUTO \
  --source-url https://huggingface.co/datasets/WeixiangYan/CodeTransOcean/tree/8985d0851100f08e94735b2f2556a795ba8c69bb/CodeTrans%20Datasets/NicheTrans \
  --source-license "Apache-2.0; CodeTransOcean dataset metadata"
```

The command copies each source file and hashes its exact bytes. `AUTO` gives only a weak per-file `FIXED_CANDIDATE` or `FREE_CANDIDATE` layout hint; the manifest tags the dialect and source format as needing review. It labels every record `PENDING`, leaves reviewer votes empty, adds no proof inputs, and marks the manifest `UNREVIEWED`. Confirm dialect, format, task grouping, and applicability before assigning labels. You can also start manually from `review-corpus.template.json`. Validate the completed manifest against `review-corpus.schema.json`. A case records:

When using CodeTransOcean, cite Yan et al. (2023):

```bibtex
@article{yan2023codetransocean,
  title={CodeTransOcean: A Comprehensive Multilingual Benchmark for Code Translation},
  author={Yan, Weixiang and Tian, Yuchen and Li, Yunzhe and Chen, Qian and Wang, Wen},
  journal={arXiv preprint arXiv:2310.04951},
  year={2023}
}
```

- `groupId`: the application/system boundary used to keep related programs together in one split;
- `dialectProfile` and `patternTags`: compiler profile and features such as `COMP-3`, `PERFORM_THRU`, `ROUNDED`, `COPY`, or `CICS`;
- source file paths and hashes; include `request.proofInputs` when testing the formal checker, but it is optional for model-only alignment/risk evaluation;
- independent `reviewVotes` from at least two qualified reviewers, including each reviewer's defect decision and matched graph-node pairs;
- a final `adjudication` with reviewer identity, rationale, resolved defect decision and resolved matches.

Record disagreements rather than overwriting them. A qualified adjudicator reviews each disagreement, documents the rationale, and supplies the final labels. Cases with `PENDING` adjudication or fewer than two independent reviewer votes are not eligible as reviewed evaluation labels. The schema permits an empty vote list for an unreviewed draft; a future evaluator must enforce the stronger review requirement.

For pair labels, use the node IDs in the exact output graph for that source hash (for example, `cobol:12` and `java:18`). The current graph builder is line-based; these IDs are graph node identifiers, not promised compiler source maps. Keep this limitation visible when reviewing mappings.

The importer enforces a 100,000-character / 1,500-line source limit. These are bounded pilot modules, not arbitrary large enterprise portfolios. When a program is outside the formal proof profile, its proof result must remain `UNKNOWN`; a future model evaluation must distinguish unsupported programs from confirmed defects.

## Plan a compatible evaluation

Assign all modules from one application/system group to exactly one of `train`, `calibration`, or `test`. Never split individual source lines or near-duplicate modules across those groups. Use the calibration split to choose a risk threshold and freeze that threshold before inspecting test results. Keep the final test split untouched until the model and threshold are fixed.

Before evaluating a future model, implement an evaluator for its actual outputs and reviewed labels. Whole-program retrieval, binary defect classification and statement localization are different tasks. Choose operating thresholds using a calibration split before evaluating the test split. Do not substitute the retired legacy numeric risk field or synthetic-pilot labels for reviewed ground truth.

A future report should record the corpus hash, model ID/hash, split, threshold and resolved reviewer disagreements. Report precision/recall/F1, false negatives, simple baselines and results by dialect and pattern for the task actually implemented. A false negative is a reviewed defective case the model fails to flag. Group sizes and class balance must be read alongside every metric. Empty/small subgroups are not evidence of reliable performance.

The score threshold is not automatically optimized. Select it on the calibration set for an agreed review capacity and acceptable miss rate; then run the test report once with that frozen threshold. Do not choose a threshold after looking at test results. Preserve reports, corpus hash, model hash, code revision, reviewer protocol, and threshold decision together in the approved evidence store.

## Retraining gate

Retrain only after the labels and split policy are approved and the current model has a baseline report. Any new model version must record its source corpus hash, training/calibration split hashes, hyperparameters, random seed, evaluation protocol, and artifact hash. Compare it to the current model and baselines on the same untouched test groups, including false negatives by dialect and pattern. A model change affects advisory ranking only. It must never turn `UNKNOWN` into a proof, authorize a patch, or alter the formal solver's result.
