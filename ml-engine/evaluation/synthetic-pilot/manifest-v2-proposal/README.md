# Synthetic pilot: proposed v2 manifest reconciliation

The submitted manifest is preserved unchanged as `input-manifest.json`, SHA-256
`e41c0712731cfd15c1feaf453773bc3d0e95e33cd62c1c42e3f636144613dc83`.
It is a proposal, not an adopted dataset revision. `reconciliation.json` records
counts, actual source-backed family definitions, archive/source hashes and
required corrections. `generator-revision-prompt.txt` is a self-contained prompt
for obtaining the smallest repair without losing audited source identities.

## Result

Strict JSON and allocation arithmetic pass: 20 unique family IDs, 10 training,
five validation and five test families; five proposed categories each have four
families with a 2/1/1 split. Its declared clone groups stay within splits, but
there are only 19 distinct groups because it incorrectly duplicates F006's
algorithm under F002. Group names do not establish source independence.

The manifest is not authoritative yet:

- F001's final operation adds tax; the proposal incorrectly says subtract.
- F002 is pro-rata subscription charging, not unsigned balance adjustment.
- F003 is triangulated FX, not tiered branching.
- F004 is weighted inventory cost and remains validation, not a training date task.
- New F005 FX cash rounding is a description only; no replacement program,
  Java variants, mappings, contract or tests were supplied.
- The proposal changes the original four-category, five-family-per-category,
  12/4/4 split protocol. Keeping actual F001-F004 plus decimal/test replacement
  F005 fills the original decimal category exactly (three train, one validation,
  one test), so restoring that protocol is the smallest correction.

The original categories are DECIMAL_ROUNDING_AND_SCALE, NUMERIC_STORAGE_AND_SIGN,
CONTROL_FLOW_AND_BOUNDARIES and INDEXING_AND_LOOP_BOUNDS. New calendar/string
categories would broaden scope and some proposed outputs conflict with the
existing single-scalar numeric contract and decimal runtime comparator.

The generator honestly marked missing-context entries as proposed. That caveat
is retained, but source-backed anchors are necessary before adoption. Calendar
helpers and first-match branching also require source-level clone review if
pursued later. No claim of independent held-out generalization is supported by
unique IDs or group strings alone.

## No execution or training

This upload contains no program source. No programs were compiled or run, no
model was trained or evaluated, and no prior source, split, runtime evidence or
model weights were modified. The original 143-pair corpus and its reserved 23
families were not used. The old F005 remains archived with its F001 similarity
issue; a replacement must be versioned separately and checked before admission.

The audit and correction prompt are AI-assisted, not independent human review.
Artifact hashes bind this review to the submitted bytes and archived sources.
