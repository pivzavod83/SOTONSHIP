# Synthetic pilot: batch 02 audit

The user's generated batch is preserved unchanged as `input-batch.json`, SHA-256
`f08dc2a1dffeb19ef75e4ac0750c8942b1cd30da3c5086269d9137e6f91507b9`.
This is synthetic data, separate from the original 143-pair matching corpus and
the natural translation-defect evidence. No model was trained or selected.

F003 is a training family for two-stage currency conversion. F004 is a
validation family for a quantity-weighted inventory average. Each supplies two
nominally equivalent Java candidates and two deliberately defective candidates.
F004 must stay out of model parameter fitting. Auditing generated labels is not
an unseen model evaluation.

## Actual runtime results

After inspecting the sources for their input/arithmetic/output-only behavior,
`replay.py` compiled both unchanged COBOL references and all eight unchanged Java
variants using GnuCOBOL 3.2 and Java 21. Neutral `Program` classes compile into
separate temporary directories. The script refuses unreviewed input hashes and
existing evidence directories; no submitted-source execution API was added.

The `runtime-audit-2026-10-18/` directory retains the plan, source hashes, exact
commands, raw stdin/stdout/stderr, exit codes, normalized results and artifact
hashes. It records **100 actual program executions**: 12 supplied reference
executions, 48 supplied Java executions, eight added reference probes and 32
added Java probes. All supplied proposed numeric results and mismatch flags
matched execution. All four nominally equivalent candidates agreed with the
reference on tested inputs; all four deliberately defective candidates had
actual differing-output witnesses. Finite agreement does not prove equivalence.

The additional probes include highly unequal lot quantities, exact half-cent
rounding, adjacent conversion-rate bounds and a case where rounding masks the
wrong weighting formula. They are explicit data-quality probes, not independent
held-out evaluation inputs.

`annotation-audit.json` records 30 valid source spans and 24 valid alignment
references, plus 113 source/evidence consistency checks. This checks structure
and source binding; semantic segment labels remain AI-proposed annotations.

## Required metadata correction

**F004-V4 is a weighting/formula error**, despite its generated
`DECIMAL_ROUNDING_AND_SCALE` defect category. It computes `(cost1 + cost2) / 2`
instead of weighting unit costs by quantities. Suggested specific category:
`ARITHMETIC_FORMULA`, declared consistently in the eventual defect taxonomy.
The family's broad focus can remain decimal rounding. The binary defective
label is supported by runtime witnesses; the subtype needs a versioned repair.

Its explanation also overstates that differing prices and quantities always
produce a different output. Case F004-A4 uses quantities 1/2 and prices 10.00/10.01;
both the reference and F004-V4 round to 10.01. Correct the wording to "can differ"
and retain the actual supplied mismatch witnesses. Original labels and rationale
are preserved for traceability.

## Before generating the remaining corpus

- Obtain the still-missing 20-family algorithm/category/split plan.
- Specify canonical ASCII numeric inputs without exponent notation or padding,
  integer spelling for quantities, and at most 20 characters per input line.
  Executed cases satisfy this; the supplied contracts do not state it.
- Mix implementation styles across labels. In F001–F004, all four scaled-integer
  rewrites are positive and all deliberately defective candidates use BigDecimal.
  Repeating that pattern gives a learner an incidental type/style shortcut.
- Add genuine mapping variety. All 24 mappings in this batch pair C1→J1, C2→J2
  and C3→J3 in order. Include justified reordering of independent operations and
  split/combined segments if the intended task is learned structural alignment.
- Exclude variant IDs, ordering, split metadata, defect annotations, rationale
  and expected test outputs from model input features. Preserve surrounding
  PIC/type and dependency information when representing source segments.

No source or label was silently changed. Corrections must produce a separate
derived version. Existing natural-data reports, original model weights and
reserved evaluation families remain untouched.

## Reproduction

Use a new evidence directory and actual installed compiler paths:

```sh
python3 ml-engine/evaluation/synthetic-pilot/batch-02/replay.py \
  --output /tmp/sotonship-batch02-new-audit \
  --cobc /path/to/cobc \
  --java /path/to/java \
  --javac /path/to/javac
```

The audit code, documentation and annotation assessment are AI-assisted. No
human reviewer votes, production reliability or model accuracy are claimed.
