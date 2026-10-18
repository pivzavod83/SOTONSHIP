# Source provenance

The application uses decimal strings for rates and fees. `collectedDate` is the retrieval date (2026-10-17, Europe/London); `observationDate` and survey collection dates describe the provider's data vintage. They are not interchangeable.

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
