# Active reduced synthetic pilot, revision 1

`dataset.json` collects the six currently supplied program families: F001-F004,
replacement F005-R2 and F006. It contains 24 candidate pairs (16 training,
four validation and four test), with F007-F010 still missing. The target remains
ten families / 40 pairs, with six training, two validation and two test families.
This partial bundle has not been trained or evaluated as a detector.

## Applied repairs

- F004-V4 now has formula/unweighted-mean defect metadata and a rationale that
  acknowledges rounding can mask the wrong formula. Sources and tests are intact.
- F001-F004 now have an explicitly restricted canonical lexical input contract:
  exact field scales, no exponent/padding/plus/leading zeros, at most 20 characters.
  Numeric value bounds are unchanged. This is a disclosed contract revision;
  no claim is inherited for other lexical forms in the earlier broad contracts.
- Every retained source hash matches its recorded offline runtime evidence.
  Derived execution statuses are EXECUTED with report hashes and finite-test
  assessments; original NOT_EXECUTED upload annotations remain in their archives.
- The active F005 is explicitly revision R2. Its old compounded-interest source
  and evidence remain archived and are not added as another family or candidate.
- Only F001-F010 belong to this scope; F011-F020 remain deferred. Placeholder
  provenance filenames from the submitted F005 batch are not evidence references.

The new F005-R2 compiled and completed 30 actual executions, with no proposed
output/mismatch errors. Each intended-correct variant agreed on all six supplied
inputs; each defective variant has actual differing-output witnesses. No extra
test-family probes were generated. Agreement is not a proof of equivalence.

## Training boundary

Use source text and public contract/type information as inputs. IDs, variant
ordering, split/clone metadata, labels, explanations, tests and runtime outcomes
must not become model features. Alignment annotations may supervise training,
but are not available as inference inputs and remain AI-proposed labels.
Keep all variants/fragments from a family together; preserve final holdouts.

Complete and check F007-F010 before freezing/training this pilot. The existing
143-pair matcher, its model files and reserved 23-family partition are unchanged
and are not defect training labels. No detector model is claimed in this bundle.
All assembly/repair work is AI-assisted. Two planned test families cannot support
reliable generalization or production accuracy claims.
