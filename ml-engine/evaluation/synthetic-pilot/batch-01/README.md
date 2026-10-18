# Synthetic pilot: batch 01 audit

This is the user's AI-generated batch, preserved byte-for-byte in
`input-batch.json` (SHA-256
`4090c19e8ca05f2edb53c749791dfc34aee25d758fb0da5959cbdcbbb5411fc6`).
It is separate from the original 143-pair matching corpus, its frozen splits,
and the natural translation-defect corpus. No model was trained and no original
labels or sources were silently corrected.

## What was checked

The batch contains **two independent reference families and eight candidate
pairs**, with four proposed positive and four proposed negative labels. All
families are training-only and both address decimal rounding. It is not a
training/validation/test dataset by itself.

`annotation-audit.json` records strict JSON validation, 35 in-bounds source
segments, 28 alignment links, valid identifier references and consistent
proposed witness flags. This establishes structural consistency; alignment
annotations remain AI-proposed, not independently reviewed semantic gold labels.

After inspecting the complete sources, `replay.py` compiled both unchanged
COBOL programs and all eight unchanged Java programs using GnuCOBOL 3.2 and
Java 21. No harness changed the calculation or input/output interface. Only the
exact, inspected batch hash is executable through this offline script.

The retained `runtime-audit-2026-10-18/` contains a recorded audit plan, exact
source hashes, compiler commands, exit codes, raw stdout/stderr, normalized
results and evidence hashes. Twelve supplied COBOL executions and 48 supplied
Java executions matched all their proposed outputs and mismatch flags.

Eight additional valid-domain cases produced another eight COBOL and 32 Java
executions. These were explicitly added domain probes, not unchanged generator
tests or independent held-out evaluation. In total, **100 program executions**
were recorded. None of these finite observations proves universal equivalence.

## Blocking label error

For F002, this input lies inside the stated valid domain:

```text
99999.99
365
0.00
```

The COBOL daily rate is 273.9726. Multiplying by 365 gives 99999.999, which rounds
to 100000.00 when assigned to `GROSS-CHG PIC 9(5)V99`. The five-integer-digit
field discards the high-order digit, and the observed final result is **0.00**.
Both nominally equivalent Java candidates F002-V1 and F002-V2 return
**100000.00**. The actual compiler/runtime outputs are retained in case F002-A1.
Case F002-A2 reproduces the same storage problem with a nonzero credit.

Consequently, **both F002 positive labels are refuted across their declared
domain**, even though every supplied test passes. Correct the Java candidates
to preserve the COBOL storage assignment before credit subtraction, then replay
them under a new version. Any alternative change to the domain or reference
program must be explicit and versioned; do not silently widen the COBOL field
to make a translation pass.

The four intentionally defective candidates all have actual differing-output
witnesses. F001-V1 and F001-V2 match the ten executed inputs for their family;
this is finite runtime agreement, not a proof of equivalence.

## Other required repairs

- Java class names encode their labels: V1/V2 are positive and V3/V4 negative.
  Normalize class names and exclude variant IDs/order and other supervision
  metadata from model inputs. Record any normalization as a derived version.
- Balance implementation styles across labels: both integer-based rewrites in
  this batch are positive. Avoid an incidental "integer code means correct"
  shortcut in the completed corpus.
- Request the missing 20-family plan before checking full category balance,
  family isolation and validation/test allocation.
- Declare canonical numeric input spelling/line length compatible with the
  COBOL `PIC X(20)` input buffers.
- Include PIC/type declarations and data dependencies as segment context.
  The computation statement alone does not specify storage width or scale.

## Reproduction

Use an installed GnuCOBOL 3.2 and JDK 21. Pass their actual paths when they are
not on PATH, and choose a **new** output directory:

```sh
python3 ml-engine/evaluation/synthetic-pilot/batch-01/replay.py \
  --output /tmp/sotonship-batch01-new-audit \
  --cobc /path/to/cobc \
  --java /path/to/java \
  --javac /path/to/javac
```

Existing audit directories are refused. Changed input bytes are refused until
a separately inspected reproduction tool is created. No HTTP endpoint or
general-purpose submitted-code execution was added.

The audit/reproduction code, annotations and this documentation are AI-assisted.
They are not fabricated human reviewer votes, real-company defect data,
production reliability evidence or model accuracy measurements. Training
admission remains blocked pending label, leakage and dataset-plan repairs.
