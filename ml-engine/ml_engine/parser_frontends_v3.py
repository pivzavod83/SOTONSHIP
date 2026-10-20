"""Offline compiler frontend bridge; parsing never grants equivalence or runs code."""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import selectors
import shutil
import subprocess
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_JAR = ROOT / "parser-frontends/target/parser-frontends-3.0.0.jar"
MAX_SOURCE_BYTES = 200_000
MAX_RESPONSE_BYTES = 2_000_000
STAGES = ("syntaxParsed", "namesTypesResolved", "semanticsModeled")


class FrontendWorker:
    """One bounded JVM reused between requests; a hung/crashed request becomes UNKNOWN."""
    def __init__(self, jar: Path = DEFAULT_JAR, java: str = "java", timeout: float = 15):
        self.jar, self.java, self.timeout = jar.resolve(), java, timeout
        self.process = None
        self.stderr = None
        self.pending = b""

    def close(self):
        if self.process:
            if self.process.poll() is None:
                self.process.kill()
            self.process.wait(timeout=5)
            self.process.stdin.close()
            self.process.stdout.close()
            self.process = None
        if self.stderr:
            self.stderr.close()
            self.stderr = None
        self.pending = b""

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def _start(self):
        if self.process is not None and self.process.poll() is None:
            return
        self.close()
        if not self.jar.is_file():
            raise FileNotFoundError("Build parser-frontends first; the versioned frontend JAR is missing")
        self.stderr = tempfile.TemporaryFile()
        self.process = subprocess.Popen(
            [self.java, "-Xmx768m", "-Xss4m", "-Dfile.encoding=UTF-8", "-jar", str(self.jar)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=self.stderr,
            cwd=ROOT / "parser-frontends", bufsize=0,
        )

    def inspect(self, source: str, language: str, profile: str, filename: str) -> dict:
        import time
        if language not in {"Java", "COBOL"} or profile not in {"JAVA", "FREE", "FIXED"}:
            raise ValueError("Invalid language/source-format contract")
        if len(source.encode("utf-8")) > MAX_SOURCE_BYTES:
            return unknown_result("SOURCE_BYTE_BUDGET")
        self._start()
        request = json.dumps({"source": source, "language": language,
                              "sourceFormat": profile, "filename": Path(filename).name}, ensure_ascii=True).encode() + b"\n"
        try:
            self.process.stdin.write(request)
            deadline = time.monotonic() + self.timeout
            with selectors.DefaultSelector() as selector:
                selector.register(self.process.stdout, selectors.EVENT_READ)
                while b"\n" not in self.pending:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0 or not selector.select(remaining):
                        raise TimeoutError("FRONTEND_TIMEOUT")
                    block = os.read(self.process.stdout.fileno(), 65536)
                    if not block:
                        raise ValueError("FRONTEND_PROCESS_EXITED")
                    self.pending += block
                    if len(self.pending) > MAX_RESPONSE_BYTES:
                        raise ValueError("FRONTEND_RESPONSE_BUDGET")
            line, self.pending = self.pending.split(b"\n", 1)
            result = json.loads(line)
            if not isinstance(result, dict) or "error" in result:
                raise ValueError("FRONTEND_REPORTED_FAILURE")
            if result.get("language") != language:
                raise ValueError("FRONTEND_LANGUAGE_MISMATCH")
            if not isinstance(result.get("syntax"), dict) or not isinstance(result.get("resolution"), dict):
                raise ValueError("INVALID_FRONTEND_PHASE")
            if result.get("syntax", {}).get("status") not in {"PARSED", "ERROR", "UNKNOWN"}:
                raise ValueError("INVALID_FRONTEND_STATUS")
            if result["resolution"].get("status") not in {"RESOLVED", "ERROR", "UNKNOWN", "NOT_ATTEMPTED"}:
                raise ValueError("INVALID_RESOLUTION_STATUS")
            return result
        except (ValueError, OSError, TimeoutError) as error:
            self.close()
            return unknown_result(str(error)[:250])


def unknown_result(code: str) -> dict:
    return {"syntax": {"status": "UNKNOWN", "diagnostics": [{"code": code, "message": code}]},
            "resolution": {"status": "NOT_ATTEMPTED", "diagnostics": []}, "structure": {}}


def compiler_check(source: str, profile: str, cobc: str | None, timeout: float = 8) -> dict:
    """GnuCOBOL static checking only, with no code generation or execution."""
    if cobc is None:
        return {"status": "UNKNOWN", "reason": "GNUCOBOL_NOT_CONFIGURED"}
    # External includes require a separate explicit dependency contract. Conservative
    # blocking also covers COPY/REPLACE produced through source preprocessing.
    if re.search(r"\b(?:COPY|REPLACE)\b", source, re.I):
        return {"status": "UNKNOWN", "reason": "EXTERNAL_PREPROCESSING_CONTRACT_REQUIRED"}
    if profile not in {"FREE", "FIXED"}:
        raise ValueError("Explicit COBOL source format required")
    with tempfile.TemporaryDirectory(prefix="omul-cobol-static-") as directory:
        path = Path(directory) / "Input.cob"
        path.write_text(source, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if not k.startswith("COB")}
        try:
            checked = subprocess.run([cobc, "-fsyntax-only", "-std=default", "-free" if profile == "FREE" else "-fixed", path.name],
                                     cwd=directory, env=env, stdin=subprocess.DEVNULL,
                                     capture_output=True, timeout=timeout)
            stderr = checked.stderr.decode("utf-8", errors="replace")[:12_000]
            return {"status": "ACCEPTED" if checked.returncode == 0 else "REJECTED",
                    "returnCode": checked.returncode, "diagnostics": stderr,
                    "scope": "Configured GnuCOBOL default dialect static check; actual version is recorded in the experiment protocol. No source execution or behavior validation"}
        except subprocess.TimeoutExpired:
            return {"status": "UNKNOWN", "reason": "GNUCOBOL_TIMEOUT"}


def phase_outcomes(result: dict, semantic_ir_status: str, language: str, static_check: dict | None = None) -> dict:
    """Whole-source stage outcomes. Incomplete earlier stages never count downstream."""
    syntax = result["syntax"]["status"]
    outcomes = {"syntaxParsed": "PASS" if syntax == "PARSED" else "FAIL" if syntax == "ERROR" else "UNKNOWN"}
    resolution = result["resolution"]
    resolved = syntax == "PARSED" and resolution.get("status") == "RESOLVED" and resolution.get("bindingComplete") is True
    if language == "COBOL":
        resolved = (syntax == "PARSED" and resolution.get("asgAnalysisCompleted") is True
                    and resolution.get("status") != "ERROR" and resolution.get("countsComplete") is True
                    and resolution.get("unresolvedReferences") == 0
                    and (static_check or {}).get("status") == "ACCEPTED")
    resolution_failed = syntax == "ERROR" or resolution.get("status") == "ERROR" or (static_check or {}).get("status") == "REJECTED"
    outcomes["namesTypesResolved"] = "PASS" if resolved else "FAIL" if resolution_failed else "UNKNOWN"
    outcomes["semanticsModeled"] = ("PASS" if resolved and semantic_ir_status == "COMPLETE" else
                                    "FAIL" if semantic_ir_status in {"PARTIAL", "UNSUPPORTED"} else "UNKNOWN")
    return outcomes


def aggregate(records: list[dict]) -> dict:
    metrics = {}
    for stage in STAGES:
        counts = Counter(record["outcomes"][stage] for record in records)
        metrics[stage] = {"count": counts["PASS"], "denominator": len(records), "status": "MEASURED",
                          "unknown": counts["UNKNOWN"], "failed": counts["FAIL"]}
    return metrics


def compact_frontend(result: dict) -> dict:
    """Versioned report keeps status/counters and bounded diagnostics, not full ASTs."""
    phases = {}
    for stage in ("syntax", "resolution"):
        value = result.get(stage, {})
        phases[stage] = {key: val for key, val in value.items() if key != "diagnostics"}
        phases[stage]["diagnostics"] = [{**item, "message": str(item.get("message", ""))[:1200]} for item in value.get("diagnostics", [])[:4]]
    structure = result.get("structure", {})
    return {**phases, "frontend": result.get("frontend"),
            "structure": {key: value for key, value in structure.items() if key not in {"nodes", "symbols", "references"}}}


def discover_cobc() -> str | None:
    return shutil.which("cobc")
