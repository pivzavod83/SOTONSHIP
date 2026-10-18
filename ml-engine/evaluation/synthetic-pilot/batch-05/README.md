# Final batch 05 audit

The uploaded bytes are preserved as input-batch.json, SHA-256
`b77464a12665fd053c9a17bd7cce6956420d19ea374a334acef586cb97547dc3`.
F009 remains validation; F010 remains final testing. Only their twelve supplied
inputs were replayed, with no additional held-out probes.

Both COBOL programs and eight Java candidates compiled successfully. All sixty
runtime executions matched proposed outputs and mismatch flags. F009 negatives
have 2/3 supplied witnesses; F010 negatives have 3/2. GnuCOBOL floating-minus output
preserved negative median values; Java negative gcd defects remained negative
under normalization. Passing finite cases never proves universal equivalence.

Static review validated 68 source spans and 48 alignment records, including inserted
unmatched operations, reordered initializations, loop delimiters and grouped
quotient/product/remainder correspondences. All programs are bounded arithmetic
stdin/stdout programs. Shared sign/remainder primitives do not by themselves make
these algorithms duplicates of the training families; independence is AI-reviewed
structurally and not statistically certified.

F009-V1's bounds explanation incorrectly mentioned the absolute-value insertion
that exists only in V3. Two metadata strings are repaired in pilot-10-r3, with
exact old/new values recorded in metadata-repairs.json. No source, prediction,
label, alignment or split was changed. The original upload is unchanged.

runtime-audit-2026-10-18/ contains the plan, tool versions, commands, raw
stdin/stdout/stderr, exit codes and source/artifact hashes. replay.py accepts
only the inspected input hash and a new output directory; it is an offline
curation tool, not a submitted-source API. No model was trained/evaluated.
The complete dataset and frozen split plan are in ../pilot-10-r3/.
