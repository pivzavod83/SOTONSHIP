# SOTONSHIP Verification for VS Code

Compare a COBOL routine with a manually supplied Java implementation from your editor. This extension sends the selected sources and an explicit input contract to the existing SOTONSHIP backend, then shows the proof result, failing transactions and proposed-fix comparison.

The extension is a client for the existing verifier. It does not translate COBOL or connect an LLM.

## Install and start

Start the backend, PostgreSQL and Python engine using the [repository setup instructions](../README.md). The backend must be reachable before verification. The extension defaults to `http://127.0.0.1:3001`; if you are using the existing localhost walkthrough, its API may be on port `3002`. Set `sotonship.backendUrl` in VS Code settings to match the API port, rather than the walkthrough page’s port. This MVP accepts local loopback API URLs only. The default `sotonship.requestTimeoutMs` is `120000`.

Build a local installer from this directory:

```sh
npm ci
npm run compile
npm test
npm run package
```

In VS Code, run **Extensions: Install from VSIX…** and select `sotonship-financial-verifier-0.1.0.vsix` in this directory. Reload VS Code if prompted.

For development, open `vscode-extension/` as the workspace folder and press **F5**. In the new Extension Development Host window, open your source folder and use the commands below.

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

GNN alignment and risk scores are experimental inspection aids. Their accuracy on real migrations has not been validated, and they do not authorize the Z3 proof.

## Files and data

The extension uses a local API without authentication. It uploads the selected source text only when you invoke verification, a fix check or application of a verified fix; opening VS Code or a workspace does not upload files. No LLM or external translation provider is connected.

[examples/penny-drift.json](examples/penny-drift.json) copies the FX fixture’s source pair, proposed fix and proof inputs from `ml-engine/data/seed-verifications.json`. The fixture is AI-generated demonstration code, not production bank code. Its reference rate is the Bank of England EUR-per-GBP observation **1.183** from **2026-10-15**, collected **2026-10-17**, under **OGL-UK-3.0**. See [data-sources](../data-sources/README.md) for the upstream records, licences and attribution.

The extension implementation, example banking sources, tests and documentation were AI-generated and require human review. Upstream data retains its separate attribution.
