# Batch 04 runtime and annotation audit

Original input SHA-256:
`e8207d8200c16ecdb4fb5dd6813c4041cc7c5bd37ed08f0ae4969f37a36f8693`.
The uploaded JSON is preserved unchanged as input-batch.json.

F007 tests unsigned four-digit receiving-field wrap. F008 tests signed quotient
truncation and normalized remainder. Both are training families. AI-assisted
source/annotation inspection found no corrections needed: 28 valid spans and 15
mapping groups, including unmatched omitted/inserted operations and legitimate
many-to-many grouping for the floor-division refactoring.

GnuCOBOL 3.2 and Java 21 compiled all ten programs. The pinned replay completed 100
executions (60 supplied, 40 extra training-boundary runs). All supplied reference
and Java predictions/mismatch flags matched. Every proposed correct variant
agreed on those inputs; every defective candidate has at least two supplied
runtime witnesses. Additional probes cover wrap adjacency and signed remainders.
These checks establish neither universal equivalence nor measured model accuracy.

runtime-audit-2026-10-18/ records tool versions, commands, exact stdin/stdout,
exit codes, source and artifact hashes. The runner refuses changed input hashes
and existing output directories. It is an offline pinned curation tool, not a
submitted-code execution API. No validation/test source or original 143-task
corpus was executed, and no model was trained. AI-proposed localization labels
remain distinct from independently reviewed gold annotations.

The integrated next revision is ../pilot-10-r2/. Previous source/evidence and
active model weights remain untouched.
