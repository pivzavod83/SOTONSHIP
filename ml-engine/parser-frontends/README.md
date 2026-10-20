# Experimental compiler frontends (v3)

This separately versioned, offline worker broadens **syntax and binding coverage**. It does not replace the deployed defect model, prove equivalence, or execute submitted programs.

- **Java:** the JDK's public `javac` APIs, using the Java 17 language profile. Parsing and name/type analysis run separately. Annotation processing, external class/source paths, code generation and execution are disabled. The public type's filename is derived from its AST, so a CodeNet submission ID does not cause a spurious filename error.
- **COBOL:** [ProLeap](https://github.com/uwol/proleap-cobol-parser), pinned to commit `d1bfe75bdd6d480f70c74c6345bcc02610ac30d3` (MIT), using its ANTLR grammar and semantic graph. The requested source format remains explicit; FREE/FIXED probes are not compiler-format inference. Unsupported dialects, missing copybooks and incomplete bindings remain visible.
- **Shared semantics:** the existing typed extractor is a separate, conservative measurement. A successful compiler parse does not imply that our graph represents the program's behavior.

## Build

Install a full JDK 17 or newer and Maven. From the repository root:

```sh
python3 ml-engine/scripts/build_parser_frontends.py \
  --java-home /path/to/jdk \
  --maven /path/to/mvn
```

The script fetches the pinned ProLeap source into the ignored `ml-engine/evaluation/corpora/parser-v3/` cache, verifies its commit and clean tracked files, builds it into a **local Maven repository**, then packages this worker and runs its tests. It never changes an existing checkout's revision. To reuse a verified checkout, add `--proleap-source /path/to/proleap-cobol-parser`.

The shaded runtime jar is `target/parser-frontends-3.0.0.jar`. `target/toolchain.json` and the cache's `build-receipt.json` record source/POM hashes, JDK/Maven versions, artifact hashes, resolved dependencies and test counts. Build steps are reproducible; identical jar bytes across builds are not claimed. ProLeap's upstream test suite is skipped during bootstrap; our frontend regression tests run.

## Worker protocol

Send one JSON object per line to the jar's standard input:

```sh
java -Xmx768m -jar ml-engine/parser-frontends/target/parser-frontends-3.0.0.jar
```

```json
{"language":"Java","sourceFormat":"FREE","filename":"Submitted.java","source":"public class Main { int[] values = {1, 2}; }"}
```

Use `"language":"COBOL"` and an explicit COBOL `sourceFormat` for COBOL requests. Each response separates `syntax`, `resolution` and `structure`; diagnostics and bounded AST/symbol details include source locations where available. Requests are capped at 200,000 source characters. The Python benchmark harness additionally controls worker time and memory.

## Three measurements

1. **Syntax parsed:** the selected grammar accepts the supplied source.
2. **Names/types resolved:** Java compiler analysis succeeds; COBOL binding coverage is reported separately and does not claim full compiler type checking.
3. **Semantics represented:** the existing typed extraction covers the operations we model, without unsupported-construct abstentions.

Report language-level and pair-level denominators, source hashes and failures. Neither parse success nor binding coverage is defect-detection accuracy. CodeNet same-problem programs are not established COBOL-to-Java translations, and judge statuses are not equivalence labels.
