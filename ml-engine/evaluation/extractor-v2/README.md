# Typed extractor v2: fixed exploratory benchmark

This experiment compares two source representations under the **same newly fixed
fitting protocol**: the v1 heuristic extractor refitted as a control, and typed
v2 features with strict parse-coverage abstention. The historical frozen v1
detector's 1/8 result is a separate reference, not a matched experimental arm.
No deployed model, source snapshot or original evaluation is overwritten.

## What the implementation changes

The v2 frontends build a bounded, typed intermediate representation (IR) from
COBOL and Java text. Unlike the frozen v1 line heuristics, it explicitly retains:

- Observable `DISPLAY`, print and return operations, including a final `.abs()`
  or a changed returned variable.
- Ordered operands and receiver/argument relationships. `a.subtract(b)` is
  distinguishable from `b.subtract(a)`.
- Numeric types, decimal precision/scale, signedness and binary width in their
  respective units. COBOL receiving-field storage and rounding attributes remain
  distinct from Java arithmetic and explicit rounding.
- SSA-style versioned definitions and reads, reassignment that kills an earlier
  constant state, and recognized branch/loop control and merge relationships.
- Exact source hashes and raw source spans. Semantic fingerprints can ignore
  layout and identifier spelling; these fingerprints are structural diagnostics,
  never semantic-equivalence decisions.

The full IR retains explicit nodes and edges. The model receives a **lossy
statistical representation** of it: logical statement regions, small adjacent
dependency clusters, operation/type/storage summaries, and 32 semantic-attribute
plus 32 ordered-operand hash bins. Hash bins can collide. The compact vectors
cannot replace the complete IR or formal reasoning. This is not a spectral
partitioner, a learned GNN or a complete COBOL/Java compiler.

Unrecognized operations, incomplete parsing and exceeded budgets produce
`ABSTAIN`; they must not silently become zero features followed by a low score.
`SUPPORTED` means both frontends represented the accepted subset, not that the
program compiles, runs correctly or is equivalent. None of this code executes
the submitted programs. The existing runtime model and browser continue using
frozen v1; v2 is isolated to this benchmark and inspection API.

The accepted subset is deliberately small: scalar COBOL `01`/`77` fields with
supported display/packed-decimal pictures, explicit arithmetic, `IF`/`ELSE` and
inline `PERFORM UNTIL`; Java scalar locals/parameters, recognized numeric library
calls, `if`/`else` and `while`. Examples requiring `COPY`, external `CALL`, CICS,
`REDEFINES`, arrays, Java `for`/exceptions or arbitrary methods require review.
Fixed-format continuation indicators, early/nested COBOL termination and some
nested/loop Java early returns also abstain. This does not replace either
language's compiler frontend. The implementation and illustrative contract
fixtures were AI-generated and still require human review.

## Inspect a pair without training or execution

From `ml-engine/`, using the project virtual environment:

```python
from pathlib import Path
from ml_engine.defect_features_v2 import extract_pair

# Decode bytes directly so file newline conversion cannot alter source binding.
cobol = Path("reference.cbl").read_bytes().decode("utf-8")
java = Path("candidate.java").read_bytes().decode("utf-8")
graph = extract_pair(cobol, java, "FREE")  # Explicit FREE or FIXED source format.
print(graph.status, graph.coverage)
if graph.status != "SUPPORTED":
    print("Human review required; do not assign a low-risk model score.")
else:
    print(graph.global_x.shape, graph.candidate_x.shape)

if graph.java_ir is not None:
    print(graph.java_ir.source_hash)
    for node in graph.java_ir.nodes:
        print(node.id, node.op, node.inputs, node.numeric_type, node.span.to_dict())
```

`graph.cobol_ir` and `graph.java_ir` expose symbols, typed nodes, edges, issues
and `to_dict()`. Region `start`/`end` fields use inclusive one-based raw source
lines; original IR nodes also retain columns where available. Incomplete graphs
can retain useful partial diagnostics, but their status still requires
abstention. `graph.candidates` contains source-derived region correspondences,
not reviewed alignment labels.

## Measurement protocol

The existing forty synthetic pairs retain their six training / two validation /
two regression-test families (24/8/8 pairs). The eight regression pairs are
**already known from the earlier failed pilot and representation audit**. They
cannot establish unseen-data performance. A new independent dataset is required
for a future generalization claim. Contract fixtures check representation
properties; they are not additional training or accuracy examples.

Both arms use L2 logistic regression with `C=0.1`, balanced class weights and a
fixed review threshold of `0.25`. There is no architecture, regularization or
threshold search. Three outer source-family folds retain four fitting families
each. Inner leave-one-fitting-family-out rankers generate every pair-classifier
training row, avoiding training the classifier on in-sample localization scores.
Every scaler is fitted within its own fitting partition. The three retained fold
checkpoints are averaged; there is no fit on all twenty-four training pairs.

Typed v2 parses that are incomplete or unsupported abstain and always require
review. They do not become low-risk predictions. v1 numerical feature production
has no strict parse-coverage guarantee. Reports distinguish these cases and show
covered-only classification separately from review triage including abstentions,
review workload, false positives/negatives, weak-label location Hit@1/3 and
per-family counts. Always reviewing everything trivially gives 100% defect-review
recall; it does not demonstrate useful discrimination or authorize acceptance.
Neither arm can prove equivalence, approve code or authorize a patch.

From `ml-engine/`, the stages are explicit:

```sh
.venv/bin/python -m pip install -r evaluation/extractor-v2/training-requirements.txt
.venv/bin/python scripts/benchmark_extractor_v2.py --prepare --output evaluation/extractor-v2/pilot-r2
.venv/bin/python scripts/benchmark_extractor_v2.py --audit-contracts --output evaluation/extractor-v2/pilot-r2
# Only after reviewing the prepared protocol and representation checks:
.venv/bin/python scripts/benchmark_extractor_v2.py --train --output evaluation/extractor-v2/pilot-r2
# Only after reviewing the frozen model/source hashes:
.venv/bin/python scripts/benchmark_extractor_v2.py --evaluate-regression-test --output evaluation/extractor-v2/pilot-r2
```

Outputs stay in this new experiment tree; use the explicit `pilot-r2/` path above
rather than the script's provisional `pilot-r1/` default. An
existing model/freeze/assessment refuses retraining, and an existing regression
assessment marker refuses another attempt. The implementation, protocol, dataset,
split plan and model hashes must match before assessment. Failed/partial attempts
remain recorded. This script only parses source text; it never compiles or runs
submitted COBOL or Java. Model training is not performed by preparing the protocol
or by the stub-based benchmark tests.

## Recorded stages and results

`pilot-r1/` preserves the provisional pre-fit source-contract audit and a logged
prose-only protocol correction. No model setting or split changed. Frontend
strictness work continued after that audit, so it is not the final implementation
freeze and its source hashes must not authorize fitting a changed extractor.

The completed artifact directory is [`pilot-r2/`](pilot-r2/), using the same fixed
protocol and explicit `--output evaluation/extractor-v2/pilot-r2` at every stage.
Its final source-contract audit passed before fitting. Model, source, protocol,
split, dataset and audit hashes were frozen before the once-only assessment.
The commands above document the completed stages: repeating them against this
directory is refused. Use a separately versioned directory and disclose reuse
for any future reproduction.

| Record | Status |
| --- | --- |
| Provisional source-contract diagnostics | 8/8 properties passed; source-only, not accuracy data |
| Final typed-frontends audit | 8/8 properties passed on stable sources in `pilot-r2/` |
| Matched v1 refit control | Trained/frozen and assessed once under the new fixed protocol |
| Typed v2 benchmark | Trained/frozen and assessed once; no deployed runtime changes |
| Existing runtime detector | Unchanged: 1/8 known held-out pairs correct |

The historical detector had **TP1, TN0, FP4, FN3**: precision 20%, recall 25%,
F1 22.2%, and accuracy 12.5%. Both original constant no-defect and graph-distance
baselines achieved 4/8 (50%). These are the old experiment's results; they must
not be substituted for either new matched arm. The working signed-balance UI
example belongs to training and does not establish generalization.

The matched results are:

| Assessment | Arm | Correct | Defects flagged | Missed defects | Correct programs flagged | Review workload |
| --- | --- | ---: | ---: | ---: | ---: | ---: |
| Grouped OOF | v1 refit control | 15/24 (62.5%) | 10/12 (83.3%) | 2 | 7 | 17/24 |
| Grouped OOF | Typed v2 | 16/24 (66.7%) | 12/12 (100%) | 0 | 8 | 20/24 |
| Validation | v1 refit control | 4/8 (50%) | 2/4 (50%) | 2 | 2 | 4/8 |
| Validation | Typed v2 | 5/8 (62.5%) | 4/4 (100%) | 0 | 3 | 7/8 |
| Reused regression | v1 refit control | 4/8 (50%) | 3/4 (75%) | 1 | 3 | 6/8 |
| Reused regression | Typed v2 | 4/8 (50%) | 3/4 (75%) | 1 | 3 | 6/8 |

Both new arms have regression precision **50%**, recall **75%** and F1 **60%**,
with **TP3, TN1, FP3, FN1**. Both miss `F005-V4`. Of the two unflagged pairs, one
is defective; an unflagged result cannot authorize acceptance. The all-review
baseline gets all four defects reviewed at a workload of 8/8, with 50% accuracy.
The constant no-defect baseline also has 50% accuracy but misses all four defects.
The fixed 0.25 threshold is a triage setting, not a safety guarantee.

Typed v2 represented all forty existing pairs without abstention. This is
source-subset coverage of these examples, not proof of compilation or equivalence.
The v1 control produced numbers for all forty, with no strict coverage guarantee.
Unsupported source-only contract fixtures still abstain in v2. Covered-only and
review-triage metrics coincide here because no accuracy pair abstained.

Weak-label regression localization Hit@1 and Hit@3 are **1/4 for both arms**.
OOF Hit@1 worsened from **6/12** in the control to **4/12** in v2; OOF Hit@3
worsened from 8/12 to 7/12. The better representation did not establish better
fault localization or a regression classification gain over the matched control.

These results support repairing the representation: source-only contracts now
distinguish previously lost return operations, operand order and output selection,
while preserving layout/rename invariance. They **do not establish useful
generalization, zero missed defects or safe automatic acceptance**. The original
12.5% result cannot be used to attribute a gain to extraction alone because its
fitting protocol differs from both new arms. No tuning followed this assessment.
New independent source/defect families and reviewed location labels are needed.

The missed `F005-V4` is a concrete denomination error: Java initializes the cash
step to ten cents instead of the COBOL reference's five cents. Its stored offline
runtime evidence contains three discrepancy witnesses. V2 retains the literal
and its dependencies, but the learned model still fails to flag it. The new
benchmark does not re-execute that evidence or reinterpret passing finite tests
as proof. This separates an extraction repair from the still-unsolved learning
problem.

The next experiment should freeze new, independently reviewed source families
before fitting, normalize monetary units across decimal and scaled-integer
representations, and obtain narrower reviewed location labels. Compare any such
change against this frozen control. Those improvements are proposals, not
implemented features or measured gains. Meanwhile, keep every low-score result
subject to engineering review and scoped verification.

See the [fixed protocol](pilot-r2/protocol.json), [source-contract report](pilot-r2/contract-diagnostics.json),
[frozen artifact](pilot-r2/frozen-artifact.json), [grouped OOF report](pilot-r2/grouped-oof-evaluation.json),
[validation report](pilot-r2/validation-evaluation.json) and
[once-only reused regression report](pilot-r2/regression-test-evaluation.json)
for per-family outcomes, parse diagnostics, dimensions and individual decisions.
Neither arm can automatically accept a translation or change Z3 proof premises.
