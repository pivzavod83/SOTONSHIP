# Confirmed demonstration evidence

`penny-drift-evidence.json` records an actual, independently reproduced one-cent
discrepancy in the repository's **AI-authored educational FX example**. It is not
a claimed production-bank defect, an external reviewed training example, or an
LLM-generated finding.

For amount `45.00` and exact decimal rate `1.1830`, actual execution produced:

| Implementation | Observed result |
| --- | --- |
| GnuCOBOL packed-decimal calculation with `ROUNDED` | `53.24` |
| Java `double` product followed by `new BigDecimal(double)` | `53.23` |
| Supplied Java `BigDecimal` patch | `53.24` |

The original fixture declares both input fields with `VALUE 0` and has no input
or output interface. The recorded COBOL harness therefore inserts two explicit
`MOVE` statements before the original calculation and a `DISPLAY` before
`GOBACK`. The declarations and arithmetic statement remain unchanged. This
derivative, **not the unmodified zero-input program**, is what GnuCOBOL compiled
and executed. For Java, each original source is copied byte-for-byte to the
correct class filename and called by a separate `Replay` driver.

The `penny-drift-replay/` directory retains original source snapshots, the
complete harnesses, command/exit/stdout/stderr records and independent Z3 reports.
Executables and Java class files exist only in a temporary directory. The main
record hashes every retained artifact and all three exact original sources.
The UI must check the source hashes before displaying the confirmed flag; an
edited pair is not covered by this evidence.

Z3 independently returns `SAT_COUNTEREXAMPLE_FOUND` for the original pair at
this witness. The patch returns `UNSAT_PROVEN_SAFE` only within the recorded
finite amount range, fixed reference rate and supported scalar grammar.
Neither result certifies arbitrary COBOL or Java programs. GnuCOBOL execution
corroborates this arithmetic example; it is not IBM Enterprise COBOL certification.
The existing example's rate provenance is retained; replay fetches no live FX data.

Reproduce from the repository root:

```sh
ml-engine/.venv/bin/python ml-engine/scripts/replay_penny_drift_demo.py
```

Python's existing Z3 dependency, GnuCOBOL and a JDK are required. Use `--cobc`,
`--java` and `--javac` to specify tool paths. The script only executes the three
hard-coded reviewed fixture hashes and refuses changed sources. It is an offline
fixture tool, not an API for executing uploaded code. Runtime evidence remains
separate from optional AI review: the UI must not present this stored replay as
a fresh LLM response.
