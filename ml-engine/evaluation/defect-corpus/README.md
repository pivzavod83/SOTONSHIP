# COBOL-to-Java defect corpus audit

Collected and measured on **18 October 2026**. The [machine-readable summary](natural-c2j-audit-summary-2026-10-18.json) links exact report hashes. This is corpus curation, not a trained defect model or a model-accuracy evaluation.

The [expanded adjudication](expanded-c2j/README.md) subsequently gives all 23 remaining flagged families explicit dispositions. It increases the strong machine-reproduced cases from two to **six source tasks**, with 25 input witnesses, while separating reference-policy conflicts and unsupported mappings. The measurements below preserve the initial audit; its completed reports are unchanged.

## Measured results

| Stage | Result | Interpretation |
| --- | --- | --- |
| Published translations | 286 outputs across 143 original tasks | Two model outputs per task are related examples. Files and original sources are commit/hash pinned. |
| Development Java screening | 198 test-compatible, 16 assertion failures, 24 runtime failures, one compilation failure, one interface quarantine | 239 of 240 development candidates screened; all 120 canonical Java controls passed. A Java test failure alone is not a COBOL mistranslation. |
| COBOL reference health | All 681 development drivers compiled and ran; 648 matched declared answers, 33 disagreed across nine tasks | Source defects, serialization and input-contract differences require adjudication. The declared benchmark answer is not automatically the behavior of the supplied COBOL. |
| Shared scalar replay | 17 tasks, 118 driver cases / 117 unique task-input combinations | All COBOL/canonical Java controls agree; 229 candidate comparisons agree. Seven comparisons are unavailable because one candidate cannot compile. |
| Exploratory text replay | Task 98, six accepted original drivers; one empty input excluded | The 7B candidate disagrees on three inputs. The 14B candidate and canonical Java agree with COBOL on all six. |
| Exploratory array replay | Task 94, three original drivers | The 14B candidate disagrees on one input. The 7B candidate and canonical Java agree with COBOL on all three. |
| Reserved partition | 23 tasks / 46 candidate translations | Inventoried but not compiled, executed, fitted or evaluated by this audit. Historical retrieval exposure remains disclosed in the main evaluation guide. |

Shared-input replay covers **19 of 120 development task families**, 127 driver cases and 126 unique task-input combinations. It yields 247 comparable candidate-input observations: 243 agreements and four disagreements. These four disagreements concern **two candidate programs in two source tasks**, not four independent defects. Twenty-three Java-screen-flagged families still lack behavioral adjudication; 101 development tasks remain outside the bounded shared-replay coverage. Passing screening does not establish source equivalence.

## Concrete discrepancies

| Source task / candidate | Original input | Actual COBOL | Actual candidate Java | AI-inspected cause |
| --- | --- | ---: | ---: | --- |
| `HumanEval/98`, 7B | `"aBCdEf"` | 1 | 0 | One-based COBOL parity calculation retained after moving to zero-based Java indexing. |
| `HumanEval/98`, 7B | `"dBBE"` | 0 | 1 | Same indexing defect. |
| `HumanEval/98`, 7B | `"U"` | 1 | 0 | Same indexing defect. |
| `HumanEval/94`, 14B | `[0,8,1,2,1,7]` | 7 | 8 | Even-number rejection omitted before the odd-divisor primality loop. |

Canonical Java controls match actual COBOL on every listed input. Original programs, inputs and drivers are unchanged; each process starts fresh. These are naturally occurring published model translation failures on HumanEval-derived tasks, not production banking incidents. Local cause inspection and separate-agent checks are AI-generated. **Independent human reviews and admitted gold training labels remain zero.** Suspected source locations are not localization gold labels. There is no reviewed faulty/fixed Java history for these outputs.

The 17-task scalar contract was frozen before execution. Text and array cohorts were selected after development screening and are explicitly exploratory. No defect prevalence or generalization rate can be estimated from this selected subset. The existing narrow financial Z3 parser was not used to label arbitrary benchmark programs.

## Evidence

- [Frozen audit plan](natural-c2j-plan.json): unchanged 120/23 assignments, allowed stages, labels and exclusions.
- [Java screening](natural-c2j-audit/2026-10-18-java-screening-v1/screening-report.json) and [interpretation](natural-c2j-audit/2026-10-18-java-screening-v1/screening-interpretation.json).
- [COBOL reference health](cobol-reference-audit/control-health-summary.json) and [all 681 driver results](cobol-reference-audit/development-120-2026-10-18.json).
- [Scalar replay](scalar-c2j-replay/replay-2026-10-18.json) and [evidence checks](scalar-c2j-replay/evidence-check-2026-10-18.json).
- [Text frozen plan](text-c2j-replay/exploratory-98-2026-10-18/frozen-plan.json), [replay](text-c2j-replay/exploratory-98-2026-10-18/replay-report.json), [hash checks](text-c2j-replay/exploratory-98-2026-10-18/evidence-check.json) and [compilation evidence addendum](text-c2j-replay/exploratory-98-2026-10-18/compilation-evidence-addendum.json). The frozen text runner omitted compilation process objects from its report; the addendum preserves retained log/class hashes without inventing missing return-code/timing records.
- [Array frozen contract](array-c2j-replay/frozen-contract-2026-10-18.json), [replay](array-c2j-replay/replay-2026-10-18.json) and [witness analysis](array-c2j-replay/witness-analysis-2026-10-18.json).
- [Compiler source manifest](cobol-toolchain-source-manifest.json) and [build/runtime manifest](cobol-toolchain-runtime-manifest.json).

Frozen script/test snapshots are stored beside the reports. Original source, class files, compiler binaries and raw logs remain in ignored caches; do not commit those caches. The source repository declares Apache-2.0; retain underlying HumanEval MIT notices. GnuCOBOL/GMP retain their own licences and are not bundled into the application.

## Reproduction

Use Python 3.11–3.13, Java 21 and GnuCOBOL 3.2. The local compiler was built in `/tmp/sotonship-cobol-toolchain/install`, with indexed I/O, screens, XML and JSON disabled. The build/runtime manifest records the original archives, hashes, configure arguments, library hashes and host details. This measures GnuCOBOL on this host, not IBM Enterprise COBOL or mainframe middleware.

Run from `ml-engine/`. Every output directory/file must be new; completed evidence refuses overwrite. For example, screening can be reproduced with:

```sh
.venv/bin/python scripts/audit_natural_c2j_candidates.py --fetch --execute-development --collected-date YYYY-MM-DD --jdk /path/to/jdk-21/bin --output evaluation/defect-corpus/natural-c2j-audit/new-screening-run
.venv/bin/python scripts/audit_cobol_references.py --cobc /path/to/cobc --workers 2 --output evaluation/defect-corpus/cobol-reference-audit/new-run.json --cache evaluation/corpora/natural-c2j/new-cobol-run
```

The scalar command has separate `prepare` and `run` subcommands. The text command has `--prepare` and `--execute`; the array command documents its stages with `--help`. Freeze a new contract before running. Historical results bind the exact snapshots and inputs, so reproduction from snapshots and a new experiment from current scripts must be identified separately. These are offline, bounded, locally inspected corpus tools; application APIs and editor actions do not execute submitted code.

## Training decision

Two reproduced discrepant source tasks support a useful pilot demonstration. They do not provide enough independent defect diversity to justify reliable supervised GNN performance. No replacement model was fitted and no new accuracy was reported. Continue explicit shared-contract adjudication of unresolved families, obtain human review, and collect additional natural COBOL-to-Java translation attempts before model selection. Never substitute the 41 Java screen failures as automatic semantic labels, count input witnesses as independent faulty programs, or infer correctness from a test-compatible control.
