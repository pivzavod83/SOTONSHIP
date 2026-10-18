# F005-R2 cash-quantization replacement audit

`input-batch.json` preserves the exact uploaded bytes, SHA-256
`340dea0c97b2abea74f2e92154954eff1606d68da74ae463d23ff165dc103c53`.
This replaces the old F005 interest family in the active pilot while preserving
that older source and evidence in batch-03. F006 is not regenerated.

The pinned offline replay compiled the one COBOL reference and four Java
candidates with GnuCOBOL 3.2 and Java 21. All 30 executions on six supplied inputs
succeeded. Reference predictions, Java predictions and mismatch flags all match.
V1/V2 agree on those inputs; V3 has two mismatching inputs and V4 has three.
For 12.34 at rate 1.2500, COBOL gives 15.45 while both defective candidates give 15.40.
These are runtime witnesses, not a general equivalence proof or model accuracy.

All 23 source spans and 16 alignment records are valid. Each arithmetic style has
one proposed correct and one defective candidate. AI-assisted structural review
finds a materially different pipeline from F001/F003, not certified statistical
independence. No source/prediction correction is needed. No additional test
probes were generated, and no training occurred.

`runtime-audit-2026-10-18/` records the pinned plan, exact commands, tool versions,
source/artifact hashes, stdin/stdout/stderr and exit codes. `replay.py` refuses
changed input bytes and existing output directories; use fresh output and
explicit --cobc/--java/--javac paths to reproduce it. It is an offline curation
tool, not an uploaded-source API.

Submitted provenance placeholder paths are preserved in the upload and resolved
in the versioned pilot-10-r1 provenance. Actual evidence is used only for exact
source hashes. The original 143-pair corpus/model/reserved 23 families are untouched.
