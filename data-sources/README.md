# Source provenance

The application uses decimal strings for rates and fees. For the financial/reference snapshots below, `collectedDate` is the retrieval date (2026-10-17, Europe/London); `observationDate` and survey collection dates describe the provider's data vintage. They are not interchangeable.

`reference-fx-rates.json` contains the latest observations actually returned in the archived Bank of England responses: **2026-10-15**, with EUR **1.183**, USD **1.3253**, and THB **44.4158** per GBP. The request's end-date parameter was 2026-10-17, to seek the desired demo observation of 2026-10-16. No 2026-10-16 value was returned by this retrieval, and the specification's example **1.2941** was not verified as that day's GBP/EUR rate. The demo must use the observed rate and its actual vintage. The saved HTML is the exact response body; the manifest hashes those bytes. Data attribution: Source: Bank of England. Contains public sector information licensed under the Open Government Licence v3.0. The [Bank's database reuse terms](https://www.bankofengland.co.uk/legal) identify the UK Open Government Licence.

`remittance-corridor.json` records one real GBP/THB survey observation from the [World Bank corridor page](https://remittanceprices.worldbank.org/corridor/United-Kingdom/Thailand): the first Wise Internet row for sending GBP120, collected by the provider survey on 2025-08-08–2025-08-22. The sender fee is GBP1.89; displayed market and provider exchange rates are respectively THB44.01 and THB43.98 per GBP. The dataset is [CC BY 4.0](https://datacatalog.worldbank.org/search/dataset/0037898/remittance-prices-worldwide). Attribution: **The World Bank, Remittance Prices Worldwide, available at http://remittanceprices.worldbank.org**. A small numeric transcription is saved because direct page/workbook downloads returned HTTP403; its checksum protects the local transcription, not an unavailable upstream HTTP body. Fees, the FX margin, and total transaction cost are separate quantities. Rounded survey values do not establish a provider tariff; any verifier tier formula is a clearly marked generated example.

`cobol/` contains small, verbatim, noncontiguous reference extracts from IBM's open-source [Bank-of-Z](https://github.com/IBM/Bank-of-Z), pinned to commit `a570aa467cd41b4400db1d6db168d17e886dd136`. `XFRFUN` illustrates packed decimal balances and transfer arithmetic; `BNK1TFN` illustrates `REDEFINES` storage and CICS screen receive. The source is Apache-2.0; its full licence and IBM copyright notices are retained. Original line ranges and complete upstream-file hashes are in the manifest. The excerpts require upstream copybooks and are not standalone programs. They are reference source material; the four small verifier scenarios and their Java migrations are AI-authored educational fixtures, not extracts of deployed banking systems. The generated FX, mortgage, and remittance business formulas are not claimed to originate in these IBM programs.

Refresh the directly downloadable evidence with:

```sh
python3 data-sources/collect.py --collected-date YYYY-MM-DD
```

The collector intentionally pins source revision and requested FX window for repeatable evidence. Review and update those parameters deliberately when collecting a new vintage. It does not overwrite the manually checked World Bank row. `provenance.json` describes every source and `checksums.sha256` covers the delivered local evidence. No source endorses this verifier.

## Paired-code learning corpus

The [paired-code source inventory](paired-code/README.md) records the separately collected 143-task COBOL-JavaTrans training/evaluation benchmark, commit, hash, notices and provenance. It is used for whole-program correspondence, not financial rates or Z3 proof obligations.

## Reviewed translation-defect research

The [candidate source catalogue](reviewed-translation-defect-candidates.json), collected **18 October 2026**, separates reviewed COBOL compiler regressions, author-reviewed failures in other languages, developer repairs and migration source without defect labels. It records exact review URLs and commit pairs for three prioritized COBOL 4J families, with a feature-support caveat for one; all remain pending local reproduction. Compiler/tests are GPL-3.0 and the Java runtime LGPL-3.0 per the upstream declaration; this catalogue contains metadata and pointers rather than copied regression source.

The [annotation audit](../ml-engine/evaluation/defect-corpus/translation-label-audit-2026-10-18.json) measures the pinned Lost in Translation archive (Zenodo CC-BY-4.0, with additional original code licences retained). AlphaTrans tooling is NCSA-licensed and its source projects retain their own notices. CMS source reuse terms were not established here; public availability is not treated as an explicit source licence.

The subsequent [natural COBOL-to-Java audit](../ml-engine/evaluation/defect-corpus/README.md) uses two published model outputs per original benchmark task: 286 candidates across 143 families. Files are pinned to the same upstream commit, source/raw execution logs stay ignored, and Apache-2.0 plus underlying HumanEval MIT notices are preserved. Development-only execution screened 239 candidates, quarantined one interface mapping, and ran 681 original COBOL drivers. Bounded same-input replay reproduced discrepancies in two candidate programs/source tasks; four failing inputs are not four independent defects. The reserved 23 families were not executed.

The [expanded adjudication](../ml-engine/evaluation/defect-corpus/expanded-c2j/README.md) preserves that evidence and classifies the remaining 23 flagged families. Combined shared replay covers 40 development tasks, with strong discrepancies in six source tasks/candidate programs and 25 input witnesses. Reference/representation conflicts and unsupported mappings remain separate. The versioned review queue contains pending human decisions; no approval votes or training labels are invented.

These files remain evidence for curation, not an admitted gold training corpus. No defect model was trained on this natural-data queue and no independent human adjudication is claimed. The [measurement protocol draft](../ml-engine/evaluation/defect-corpus/measurement-protocol-draft.json) requires appropriate controls, source/dependency visibility, grouped splits and overlap checks. The natural-output discrepancies remain pending review and are not represented as reviewed repair histories. AI-generated research text does not substitute for upstream or independent human review.

## Separate synthetic feasibility pilot

The user supplied AI-generated COBOL/Java batches on **18 October 2026**, now preserved in the [ten-family frozen pilot](../ml-engine/evaluation/synthetic-pilot/pilot-10-r3/README.md). It contains forty candidate pairs, deliberately labelled correct/defective variants, proposed segment annotations and actual offline runtime checks. These are generated educational programs, not reviewed production migrations or random numeric records. Original uploads, versioned annotation repairs, exact source hashes and compiler observations remain distinct. No third-party banking dataset or licence is implied by these generated examples.

The [local detector experiment](../ml-engine/evaluation/synthetic-pilot/defect-model-v1/README.md) trained only on six of those families, with two validation and two final-test families. It scored **1/8 correct (12.5%)**, below 50% baselines. This supports a working trained-model demonstration but not reliable defect detection. AI-authored data, training/inference code and UI require human review; neither synthetic labels nor finite runtime agreement establish unrestricted equivalence.
