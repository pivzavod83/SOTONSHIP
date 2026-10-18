# Active ten-family pilot, revision 2

The bundle now contains eight families / 32 candidate pairs: 24 training pairs from
six families, four validation pairs from F004 and four test pairs from F005-R2.
Only F009 (validation) and F010 (test) are missing. The target remains ten families,
40 pairs and a 6/2/2 family split. Every prior family record is preserved from r1.

Batch 04 supplied F007 (odometer receiving-field wrap) and F008 (signed normalized
remainder). Both COBOL references and all eight Java candidates compiled. The
pinned audit records 100 actual runs: 60 supplied-case executions plus 40 additional
training-boundary executions. All predictions and mismatch flags matched.
Every intended-correct candidate agreed on all executed inputs; all four defect
candidates have actual witnesses. No new code or prediction repairs were needed.
Finite agreement does not prove universal equivalence.

`dataset.json` is the current source/annotation bundle; `manifest.json` retains
the planned assignments; `provenance.json` binds exact sources to offline
runtime evidence. `next-generation-prompt.txt` requests only the final two
families. Original uploads, prior revisions and evidence are preserved.

Training-family collection is complete. Finish label/runtime quality checks for
the final two families, freeze grouped splits, then implement/train the new
pairwise defect model and connect it to the UI. Existing trained weights still
perform matching; no new defect model has been trained or evaluated.

All supervision remains synthetic and AI-proposed. Test-source inspection is
only dataset quality control; model selection and feature fitting must not use
test data. IDs, metadata, labels, explanations, provided alignments and test
outputs are not inference inputs. The original 143-pair benchmark and reserved 23
families remain separate and unchanged. Two planned final test families cannot
establish production accuracy or reliable unseen-family generalization.
