# SOTONSHIP Verification for VS Code

Find candidate COBOL/Java program matches with the paired-source GNN, then compare supported financial behavior from your editor. This extension sends explicitly selected sources to the SOTONSHIP backend, shows the advisory ranking, and lets an engineer confirm the Java counterpart before supplying a proof contract.

The extension is a client for the matching engine and verifier. It does not translate COBOL or connect an LLM. Matching and verification are separate operations: a GNN similarity never establishes equivalence or authorizes a fix.

## Install and start

Start PostgreSQL and the backend using the [repository setup instructions](../README.md). The backend invokes Python automatically for each analysis; there is no separate Python web server. The extension defaults to `http://127.0.0.1:3001`. Set `sotonship.backendUrl` in VS Code settings to match the API port, rather than the walkthrough page’s port. This MVP accepts local loopback API URLs only. The default `sotonship.requestTimeoutMs` is `120000`.

Build a local installer from this directory:

```sh
npm ci
npm run compile
npm test
npm run package
```

In VS Code, run **Extensions: Install from VSIX…** and select `sotonship-financial-verifier-0.2.0.vsix` in this directory. Reload VS Code if prompted.

For development, open `vscode-extension/` as the workspace folder and press **F5**. In the new Extension Development Host window, open your source folder and use the commands below.

## Find the Java counterpart with the GNN

1. Run **SOTONSHIP: Find Java Program Matches with GNN**, then choose a COBOL file and up to 20 distinct Java candidates. Alternatively, use the workbench's candidate selection controls.
2. Check the COBOL source format for matching and request **Rank Java candidates with GNN**. Selection alone does not upload sources. Ranking uses current editor text, including unsaved edits.
3. Inspect the ranked programs, cosine similarities, model hash, training dataset, evaluation and review reason. A cosine is a ranking score, not a calibrated confidence percentage. `MATCH_SUGGESTED` still requires review; `REVIEW_REQUIRED` means the model did not meet its suggestion thresholds.
4. Explicitly **Confirm this Java candidate**. This selects its file as the Java verification input and invalidates older proof evidence. It does not alter either source, infer field mappings, set amount bounds or run Z3.
5. Supply or review the explicit proof contract below and verify the confirmed pair. Program matching supports a broader benchmark-code scope than the verifier's bounded financial arithmetic subset; a good match can still return `UNKNOWN` during verification.

Editing the COBOL, any candidate, matching format or backend makes the ranking stale. Run matching again before confirming a stale candidate. The GNN ranks whole programs; it does not provide reviewed statement correspondences or locate the exact cause of a failed proof. The task-grouped split, measured results and test-exposure audit are documented in the repository's model report. There is no synthetic defect-risk model.

For a complete repository demo, choose `ml-engine/data/fixtures/FX-WIRE-CALC.cbl` and the three Java candidates `FX-WIRE-CALC.java.txt`, `MORTGAGE-INT-CALC.java.txt` and `REMIT-TIER-FEE.java.txt` in that directory. Inspect the ranking and explicitly select the FX Java implementation; these financial fixtures are outside the training set and this is not an accuracy benchmark. Load `examples/penny-drift.verification.json` as the proof contract. Select `FX-WIRE-CALC.patched.java.txt` as the proposed fix, then verify, compare and reverify before applying. No candidate is automatically selected by filename.

## Try the penny drift example

1. Open the Command Palette and run **SOTONSHIP: Try the Penny Drift Demo**. This loads the bundled COBOL, Java and explicit proof inputs into the verification workbench.
2. Run verification. The supplied Java uses binary floating-point multiplication before constructing a `BigDecimal`. A failing transaction with amount **45.00** and the fixed reference rate **1.183** produces **53.24** in the modeled COBOL and **53.23** in Java.
3. Check the proposed fix separately. Its decimal arithmetic also preserves the COBOL field’s modeled width truncation. Inspect the returned proof scope.
4. Run **SOTONSHIP: Compare Java with Proposed Fix**, or use the workbench’s comparison action, to inspect the native VS Code diff.
5. Apply the verified fix. The extension verifies it again, checks that the proof’s source hashes match the current documents, and replaces the Java editor’s contents. The edit supports Undo and remains unsaved until you save it.

The fix check does not change the original Java. Source edits invalidate earlier results; verify again after editing either source or the input contract.

## Verify your own files

Run **SOTONSHIP: Verify COBOL and Java Files**, or **SOTONSHIP: Open Verification Workbench**. Select the COBOL file and corresponding Java file through the file picker. Optionally select a separate Java file containing a proposed fix. Verification reads the current editor text, including unsaved changes.

Select a JSON input-contract file. Copy [examples/penny-drift.verification.json](examples/penny-drift.verification.json) and update these values for your routine:

| Fields | What to supply |
| --- | --- |
| `cobolDialectProfile`, `cobolSourceFormat` | The supported scalar profile and the actual `FREE` or restricted `FIXED` source format. |
| `amountField`, `rateField`, `resultField` | Exact COBOL field names for the two inputs and observed output. |
| `javaAmountParameter`, `javaRateParameter` | Exact Java parameter names corresponding to those COBOL inputs. |
| `amountMinCents`, `amountMaxCents` | Inclusive input bounds in integer cents. |
| `referenceCurrencyPair`, `referenceSource`, `referenceCollectedDate` | The exact identity of a reference-rate record already available in the backend. Collection and observation dates are different concepts. |

The contract is the plain 12-field object, without a `proofInputs` wrapper. The [JSON schema](schemas/proof-inputs.schema.json) describes the accepted fields. Changing the contract changes the problem being verified; choose bounds and a reference record deliberately. Missing fields, mismatched names or unavailable reference data cannot establish equivalence.

Run verification to inspect the current pair. To evaluate a revision, select a proposed Java file and check it separately before comparing or applying it. The original COBOL remains the reference throughout this workflow. Exporting a report opens an untitled JSON document for you to review and save.

## Understand the result

| Result | Meaning |
| --- | --- |
| `SAT_COUNTEREXAMPLE_FOUND` | The verifier found concrete inputs for which the modeled outputs differ. Inspect the witness and relevant source. |
| `UNSAT_PROVEN_SAFE` | The supported model has no differing outputs within the recorded finite proof scope and fixed reference rate. Review that scope before applying a fix. |
| `UNKNOWN_HALTED_LIMIT` | Unsupported constructs, missing contracts or resource limits prevented a conclusion. Human review is required. |

`UNSAT_PROVEN_SAFE` covers the recognized scalar arithmetic subset, explicit bounds and recorded arithmetic semantics. It is not full COBOL/Java language equivalence. External CICS/JCL behavior and other unsupported constructs can return `UNKNOWN_HALTED_LIMIT`; that result is not evidence that a migration is safe.

Learned program matching is an inspection aid. The workbench shows its separate evaluation provenance rather than presenting similarity as defect probability. Defect risk is not estimated. Matching does not authorize a Z3 proof or establish production banking reliability.

## Validation

`npm test` runs source-binding, ranking-contract and HTTP failure/cancellation tests alongside the verification contract tests. With a live verifier running, `LIVE_VERIFIER_URL=http://127.0.0.1:3001 npm run test:host` launches isolated native VS Code tests. Add `LIVE_MATCHING_URL=http://127.0.0.1:3001` to exercise real GNN ranking followed by explicit engineer selection and independent Z3 verification. These tests do not assert financial-domain model accuracy. Matching workflow race tests use clearly labelled protocol fixtures. Every edited test document is untitled.

## Files and data

The extension uses a local API without authentication. It uploads selected source text only when you invoke program matching, verification, a fix check or application of a verified fix; opening VS Code or a workspace does not upload files. Requests use the configured loopback backend with no redirects. No LLM or external translation provider is connected.

[examples/penny-drift.json](examples/penny-drift.json) copies the FX fixture’s source pair, proposed fix and proof inputs from `ml-engine/data/seed-verifications.json`. The fixture is AI-generated demonstration code, not production bank code. Its reference rate is the Bank of England EUR-per-GBP observation **1.183** from **2026-10-15**, collected **2026-10-17**, under **OGL-UK-3.0**. See [data-sources](../data-sources/README.md) for the upstream records, licences and attribution.

The extension implementation, example banking sources, tests and documentation were AI-generated and require human review. Upstream data retains its separate attribution.
