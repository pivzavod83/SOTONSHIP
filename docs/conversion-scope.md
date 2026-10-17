# COBOL-to-Java conversion scope

## Decision status

This is a proposed pilot scope, not a statement about JPMorganChase's installed compilers or runtime inventory. Confirm the estate against compiler listings, build scripts, copybook libraries, compiler options, transaction monitors, and representative source before accepting production code.

## Target profile

| Phase | Input profile | Treatment |
| --- | --- | --- |
| Pilot | IBM Enterprise COBOL for z/OS 6.x, fixed reference format, with the exact compiler release and options captured per build | Primary dialect profile because the current application targets mainframe banking arithmetic. Start with pure, deterministic calculation paragraphs whose dependencies and input/output contract are explicit. |
| Expansion | IBM Enterprise COBOL programs using approved `COPY`/`REPLACE`, compiler directives, tables, and broader decimal/control-flow features | Add one semantic feature at a time, backed by compiler-generated and human-reviewed expected results. |
| Separate profiles | IBM versions before 6.x; Micro Focus Visual COBOL / Enterprise Server; GnuCOBOL; other vendors | Do not auto-treat these as IBM-compatible. Add an explicit parser/compiler profile per version and dialect. GnuCOBOL is useful for local fixture compilation but is not evidence of IBM runtime equivalence. |
| External behavior | CICS, IMS, DB2, JCL, files, calls, queues, and shared storage | Out of initial proof scope. Model these through explicit contracts or tested adapters before claiming end-to-end equivalence. Otherwise return `UNKNOWN`. |

IBM Enterprise COBOL has its own language reference and compiler-specific extensions. Its z/OS reference format uses sequence, indicator, Area A, and Area B columns; free-format fixtures do not exercise that layout. Micro Focus documents separate fixed, free, variable, and terminal formats, and GnuCOBOL exposes compiler-selected dialect modes. These are separate source and semantic profiles, not interchangeable labels.

## Initial conversion boundary

The pilot converts and verifies one isolated, deterministic calculation unit at a time. Each unit must have:

- compiler identity, release, options, source format, code page, and resolved copybooks;
- explicit entry inputs, output fields, ranges, units, decimal pictures, rounding and truncation rules;
- no unmodeled I/O, external calls, mutable shared state, or environmental dependency;
- a generated Java implementation plus a source map to the COBOL statements and declarations;
- a proof scope that records the exact input domain, runtime assumptions, and output observations.

The current repository is a verifier for a restricted scalar grammar, not a converter. Its first two COBOL fields and first two Java parameters are currently treated as amount and rate; this is a demo contract, not a production interface. No conversion or approval claim should be made for code outside the declared profile.

## Implemented parser profile

New proof requests must declare `IBM_ENTERPRISE_COBOL_ZOS_6_5_SCALAR_SUBSET_V1` and `FREE` or `FIXED` source format. This name selects the verifier's documented scalar grammar; it does **not** attest that a source file was compiled by IBM, validate compiler flags, preprocess copybooks, or model all Enterprise COBOL 6.5 behavior. The parser still accepts only the declarations and statements listed in `ml-engine/README.md`; unsupported dialect labels or syntax return `UNKNOWN`. The supported statement subset now includes `ADD one-expression TO field [ROUNDED]` and `SUBTRACT one-expression FROM field [ROUNDED]`, using the declared receiving field's scale, truncation/rounding and overflow behavior. It does not imply support for all forms of those COBOL verbs.

The graph extractor remains a line-based approximation; its node identifiers are not compiler source maps. Formal parsing and proof are separate from those graph scores. A full IBM dialect claim still requires compiler identity/options, preprocessing, and differential checks against the actual named compiler/runtime.

## Evidence and release gates

1. Inventory target portfolios and confirm the IBM/Micro Focus/GnuCOBOL distribution with the owning teams.
2. Build a licensed, access-controlled corpus stratified by compiler version, subsystem, source format, and business domain. Labels must be reviewed by COBOL and Java SMEs; generated examples are not evaluation evidence.
3. Compare parser output and generated Java against the named production compiler/runtime, including decimal boundaries, overflow, truncation, rounding, paragraph flow, and condition handling.
4. Publish coverage, unsupported-rate, false-positive/false-negative, and proof-time metrics with holdouts split by application or portfolio, not random source lines.
5. Keep model-derived ranking advisory until independent validation and operational approval. Formal proof status must remain separate from model scores.

## Security and operations baseline

Treat source and derived graphs as confidential bank intellectual property. This repository now checks RS256 Bearer tokens against configured issuer, audience, and public key, and applies `verifications:read` / `verifications:write` roles. Analysis subprocesses now run behind a bounded in-process asynchronous worker queue; queued work is not durable across process restarts. Production still needs a JPMC-approved issuer and key-rotation strategy, tenant/portfolio row scoping, durable job state, audit export, transport/storage encryption, retention/deletion policy, and isolated worker containers. The demo's local database credentials are not a deployment configuration.

## Primary references

- [IBM Enterprise COBOL for z/OS documentation library](https://www.ibm.com/support/pages/enterprise-cobol-zos-documentation-library)
- [IBM Enterprise COBOL reference format](https://www.ibm.com/docs/en/cobol-zos/6.5.0?topic=structure-reference-format)
- [Micro Focus source format directive](https://www.microfocus.com/documentation/visual-cobol/30pu9/VC_30PU9_for_VS2012_WH/HRCDRHCDIR63.html)
- [GnuCOBOL Programmer's Guide](https://gnucobol.sourceforge.io/guides.html)
