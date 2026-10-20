# Experimental COBOL frontend

`CobolFrontend.inspect(source, sourceFormat, virtualFilename)` uses the actual
[ProLeap parser](https://github.com/uwol/proleap-cobol-parser), version 4.0.0,
pinned to commit `d1bfe75bdd6d480f70c74c6345bcc02610ac30d3` (MIT). This dependency
is built from pinned upstream source because its coordinate is not available in
Maven Central. Generated binaries and downloaded source stay outside Git.

## Measurements

- **Syntax:** ProLeap preprocessing, lexer and complete `startRule ... EOF`
  parsing. Any lexer/parser diagnostic produces `ERROR`, even if ANTLR recovers
  and returns a partial tree. A missing copybook produces `UNKNOWN`.
- **Names/types:** ProLeap's ASG analysis runs separately after successful
  syntax parsing. We count distinct unwrapped ASG calls and distinguish
  `UNDEFINED_CALL` from bound call kinds. These are partial name bindings, not
  complete compiler type checking. Successful ASG construction alone returns
  `UNKNOWN`, never `RESOLVED`. An analysis failure preserves the successful
  syntax result and reports a separate resolution error. A compiler check may
  provide additional evidence at the orchestration layer.
- **Semantics:** This frontend exposes syntax-node kinds, counts, bounded
  source spans and reference bindings. These do not establish complete control
  flow, library effects, decimal behavior or equivalence. Semantic support is
  measured separately by the downstream representation.

## Source formats and locations

ProLeap supports `FIXED`, `VARIABLE` and `TANDEM`; it has no native `FREE` enum.
Our explicit `FREE` adapter inserts one blank indicator column per line and
selects ProLeap's `TANDEM` preprocessor. It preserves all original source
characters. Matching `>>SOURCE FORMAT [IS] FREE` declarations become blank
lines, preserving line numbers. This adapter is not a full implementation of
every vendor's free-format directives or continuation conventions.

The frontend does not infer a source format or claim a specific compiler
dialect. `FREE` and `FIXED` results must be reported as separate probes when
the source's compiler contract is unknown.

Positions use one-based lines/columns and an exclusive end column. Original
coordinates are used only when preprocessing preserves corresponding lines
and content. Continuations, substitutions or other rewrites that defeat this
check leave positions explicitly in `PREPROCESSED` coordinates. These spans
must not be used to highlight original source without a mapping.

## Dependencies and known limits

Input is supplied as a string. Copybook file, directory and extension
allowlists are empty. The frontend never searches the current directory,
the virtual filename's parent or arbitrary local paths for `COPY` targets.
Copybook dependency support needs a separate explicit input interface.

ProLeap accepts many COBOL constructs omitted by our earlier handwritten
extractor, including groups, `OCCURS`, packed decimal declarations, paragraphs,
`PERFORM` and `EVALUATE`. It still does not cover every dialect. For example,
the GnuCOBOL `REPOSITORY. FUNCTION ALL INTRINSIC.` clause is rejected by the
pinned grammar. We retain that diagnostic rather than deleting valid source
to manufacture a successful parse. Embedded SQL/CICS parsing or preprocessing
does not mean their effects are understood. No submitted program is executed.

`CobolFrontendTest` exercises broad syntax, explicit fixed/free profiles,
malformed input, missing copybooks, unresolved names, original source positions
and the known unsupported repository clause.
