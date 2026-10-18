# Synthetic COBOL-to-Java defect pilot

The complete active revision is **[pilot-10-r3](pilot-10-r3/README.md)**.
It contains ten algorithm families and forty Java candidates, with frozen
family-level training / validation / test assignments of 6 / 2 / 2 families
(24 / 8 / 8 candidate pairs). Generation and offline runtime quality checks
are complete. The separate [trained detector experiment](defect-model-v1/README.md)
is now complete: final accuracy was **1/8 (12.5%)**, below both 50% baselines.
It demonstrates a learned workflow but failed held-out generalization. The
hash-bound dataset README is a preserved snapshot from before model training.

Use `pilot-10-r3/dataset.json` together with its hash-bound `split-plan.json`.
Changes require a new version; do not overwrite historical sources or reports.
The original F005 interest program is archived and excluded; the active test
family is replacement F005-R2. Only the reduced decimal and numeric storage/sign
scope is included; F011-F020 are deferred.

The batch directories preserve original uploads, pinned local replay scripts,
actual compiler/runtime evidence and separately recorded annotation repairs.
`batch-01` is the rejected first version; `batch-01-refined` supplies its accepted
successor. `batch-02-repaired-r1` contains the metadata-only F004 correction.
Prior manifest proposals and partial assembled revisions remain for provenance.

This is explicitly synthetic, AI-assisted feasibility data. Positive labels
have finite-input agreement, not universal equivalence proofs; negative labels
have actual runtime witnesses. Alignment labels remain AI-proposed. Validation
and test sources were inspected for data quality; they are not a pristine blind
benchmark. Two final test families cannot establish reliable production accuracy.
Keep model inputs separate from labels, IDs, ordering, test outputs and curation
metadata, and keep all variants/fragments of a family in the same split.

The original 143-pair program-matching corpus, its model weights and its reserved
23 families remain separate and unchanged. Those correspondence labels are not
defect labels for this pilot.
