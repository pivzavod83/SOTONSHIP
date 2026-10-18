"""Offline contract tests: a loopback provider replaces all external inference."""
from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import threading
import time
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from ml_engine import ai_review


REQUEST = {
    "moduleName": "PAIRED-REVIEW",
    "cobolSource": "       IDENTIFICATION DIVISION.\r\n       ADD 1 TO TOTAL.\r\n",
    "javaSource": "class Example {\n  int total = 0;\n}\n",
    "cobolSourceFormat": "FIXED",
    "analysisContext": "TOTAL must retain the reference behavior.",
}
FINDING = {
    "title": "Possible omitted increment", "category": "STATE", "severity": "HIGH",
    "explanation": "The COBOL increments TOTAL; the Java initializes it but does not increment it.",
    "cobolLines": {"start": 2, "end": 2}, "javaLines": {"start": 2, "end": 2},
    "suggestedFix": "Preserve the increment after initialization.",
    "candidateInputs": [{"inputsJson": '{"total":0}',
                         "rationale": "Check whether the increment is preserved."}],
}


def model_output(findings=None):
    return {"summary": "One possible semantic difference requires validation.",
            "findings": [copy.deepcopy(FINDING)] if findings is None else findings,
            "limitations": ["The entry-point contract needs confirmation."]}


def envelope(content=None, **choice_fields):
    message = {"role": "assistant", "content": json.dumps(model_output() if content is None else content)}
    return {"choices": [{"message": message, "finish_reason": "stop", **choice_fields}]}


@contextmanager
def provider(body=None, *, status=200, headers=None, delay=0):
    observed = []
    response_body = json.dumps(envelope()).encode() if body is None else body

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            observed.append({"path": self.path, "headers": dict(self.headers),
                             "body": json.loads(self.rfile.read(int(self.headers["Content-Length"])))})
            if delay:
                time.sleep(delay)
            try:
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                for name, value in (headers or {}).items():
                    self.send_header(name, value)
                self.end_headers()
                self.wfile.write(response_body)
            except (BrokenPipeError, ConnectionResetError):
                pass

        def log_message(self, *_args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {"LLM_BASE_URL": f"http://127.0.0.1:{server.server_port}/v1",
               "LLM_MODEL": "offline-test-model", "LLM_API_KEY": "test-secret-not-a-real-key"}, observed
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def run_mock(monkeypatch, content=None, *, raw=None):
    body = json.dumps(envelope(content)).encode() if raw is None else raw
    monkeypatch.setattr(ai_review, "_post", lambda *_args: body)
    return ai_review.review_sources(REQUEST, {"LLM_MODEL": "offline-test-model", "LLM_API_KEY": "private"})


def test_missing_configuration_does_not_call_provider(monkeypatch):
    def forbidden(*_args):
        pytest.fail("Missing configuration must never contact a provider")
    monkeypatch.setattr(ai_review, "_post", forbidden)
    for environment in ({}, {"LLM_MODEL": "some-model"}):
        result = ai_review.review_sources(REQUEST, environment)
        assert result["status"] == "NOT_CONFIGURED"
        assert result["findings"] == []
        assert result["aiIsProof"] is False
        assert "MODEL" in result["summary"] or "API_KEY" in result["summary"]


def test_real_http_request_and_exact_raw_source_anchoring():
    with provider() as (environment, observed):
        result = ai_review.review_sources(REQUEST, environment)
    assert result["status"] == "ANALYZED"
    assert len(observed) == 1
    sent = observed[0]
    assert sent["path"] == "/v1/chat/completions"
    assert sent["headers"]["Authorization"] == "Bearer test-secret-not-a-real-key"
    assert sent["body"]["response_format"]["json_schema"]["strict"] is True
    assert sent["body"]["response_format"]["json_schema"]["schema"] == ai_review.MODEL_SCHEMA
    assert sent["body"]["max_completion_tokens"] == 4096
    supplied = json.loads(sent["body"]["messages"][1]["content"])
    assert "\n".join(line["text"] for line in supplied["cobolSourceLines"]) == REQUEST["cobolSource"]
    assert "\n".join(line["text"] for line in supplied["javaSourceLines"]) == REQUEST["javaSource"]
    assert supplied["cobolSourceFormat"] == "FIXED"
    assert supplied["analysisContext"] == REQUEST["analysisContext"]
    finding = result["findings"][0]
    assert finding["findingId"] == "F1"
    assert finding["cobolExcerpt"] == "       ADD 1 TO TOTAL.\r"
    assert finding["javaExcerpt"] == "  int total = 0;"
    assert finding["evidenceStatus"] == "AI_HYPOTHESIS"
    assert finding["candidateInputs"][0]["status"] == "NOT_EXECUTED"
    assert result["counterexamplesExecuted"] is False
    assert result["sourceHashes"]["cobol"] == hashlib.sha256(REQUEST["cobolSource"].encode()).hexdigest()
    assert result["sourceHashes"]["java"] == hashlib.sha256(REQUEST["javaSource"].encode()).hexdigest()
    assert "test-secret-not-a-real-key" not in json.dumps(result)


@pytest.mark.parametrize("mode", ["json_schema", "json_object", "text"])
def test_compatibility_modes_are_explicit_without_retry(mode):
    with provider() as (environment, observed):
        environment["LLM_RESPONSE_FORMAT"] = mode
        result = ai_review.review_sources(REQUEST, environment)
    assert result["status"] == "ANALYZED"
    assert len(observed) == 1
    sent = observed[0]["body"]
    if mode == "text":
        assert "response_format" not in sent
    elif mode == "json_object":
        assert sent["response_format"] == {"type": "json_object"}
    else:
        assert sent["response_format"]["type"] == "json_schema"
    if mode != "json_schema":
        assert "Required JSON schema:" in sent["messages"][0]["content"]


def test_loopback_can_use_a_local_model_without_an_api_key():
    with provider() as (environment, observed):
        del environment["LLM_API_KEY"]
        result = ai_review.review_sources(REQUEST, environment)
    assert result["status"] == "ANALYZED"
    assert "Authorization" not in observed[0]["headers"]


@pytest.mark.parametrize("base", [
    "http://example.com/v1", "https://user:secret@example.com/v1",
    "https://example.com/v1?key=secret", "https://example.com/v1#secret",
    "https://example.com\\@localhost/v1", "file:///tmp/provider",
    "https://example.com:0/v1", "https://example.com:99999/v1",
    "https://example.com/\r\nAuthorization: secret", "http://localhost.example.com/v1",
])
def test_unsafe_endpoint_configuration_is_rejected_without_network(monkeypatch, base):
    monkeypatch.setattr(ai_review, "_post", lambda *_args: pytest.fail("Unsafe URL reached transport"))
    result = ai_review.review_sources(REQUEST, {"LLM_BASE_URL": base, "LLM_MODEL": "test", "LLM_API_KEY": "secret"})
    assert result["status"] == "NOT_CONFIGURED"
    assert base not in result["summary"]
    assert "secret" not in result["summary"]


@pytest.mark.parametrize("field,value", [
    ("LLM_TIMEOUT_SECONDS", "0"), ("LLM_TIMEOUT_SECONDS", "91"),
    ("LLM_TIMEOUT_SECONDS", "nan"), ("LLM_MAX_COMPLETION_TOKENS", "9000"),
    ("LLM_MAX_COMPLETION_TOKENS", "0"), ("LLM_RESPONSE_FORMAT", "auto"),
    ("LLM_API_KEY", "secret\r\nInjected: value"), ("LLM_MODEL", "bad\nmodel"),
])
def test_invalid_configuration_is_not_sent(monkeypatch, field, value):
    monkeypatch.setattr(ai_review, "_post", lambda *_args: pytest.fail("Invalid configuration reached transport"))
    environment = {"LLM_MODEL": "test", "LLM_API_KEY": "private", field: value}
    assert ai_review.review_sources(REQUEST, environment)["status"] == "NOT_CONFIGURED"


def test_empty_findings_remain_an_unproven_review(monkeypatch):
    result = run_mock(monkeypatch, model_output([]))
    assert result["status"] == "ANALYZED"
    assert result["findings"] == []
    assert result["aiIsProof"] is False
    assert any("empty finding list does not establish equivalence" in line for line in result["limitations"])


@pytest.mark.parametrize("span", [
    {"start": 0, "end": 1}, {"start": 2, "end": 1}, {"start": 1, "end": 99},
    {"start": True, "end": 2}, {"start": 1.0, "end": 2}, {"start": "1", "end": 2},
    {"start": 1, "end": 1, "extra": "untrusted"},
])
def test_invalid_original_line_spans_reject_the_entire_response(monkeypatch, span):
    faulty = copy.deepcopy(FINDING)
    faulty["javaLines"] = span
    result = run_mock(monkeypatch, model_output([copy.deepcopy(FINDING), faulty]))
    assert result["status"] == "INVALID_MODEL_OUTPUT"
    assert result["findings"] == []


def test_null_spans_are_allowed_only_when_another_span_exists(monkeypatch):
    finding = copy.deepcopy(FINDING)
    finding["cobolLines"] = None
    result = run_mock(monkeypatch, model_output([finding]))
    assert result["status"] == "ANALYZED"
    assert result["findings"][0]["cobolExcerpt"] == ""
    finding["javaLines"] = None
    assert run_mock(monkeypatch, model_output([finding]))["status"] == "INVALID_MODEL_OUTPUT"


@pytest.mark.parametrize("inputs_json", [
    "[]", "null", '"not an object"', '{"x":NaN}', '{"x":Infinity}',
    '{"x":1e1000}', '{"x":1,"x":2}', "{bad JSON}",
    '{"x":' + "[" * 21 + "0" + "]" * 21 + "}",
    '{"x":[' + ",".join("0" for _ in range(1001)) + "]}",
])
def test_candidate_inputs_must_be_bounded_finite_json_objects(monkeypatch, inputs_json):
    finding = copy.deepcopy(FINDING)
    finding["candidateInputs"][0]["inputsJson"] = inputs_json
    result = run_mock(monkeypatch, model_output([finding]))
    assert result["status"] == "INVALID_MODEL_OUTPUT"
    assert result["findings"] == []


@pytest.mark.parametrize("change", [
    lambda output: output.update(proven=True),
    lambda output: output.update(summary=""),
    lambda output: output.update(findings=[copy.deepcopy(FINDING)] * 9),
    lambda output: output["findings"][0].update(evidenceStatus="CONFIRMED"),
    lambda output: output["findings"][0].update(category="PROOF"),
    lambda output: output["findings"][0].update(severity="CRITICAL"),
    lambda output: output["findings"][0].update(title="x" * 161),
    lambda output: output["findings"][0].update(candidateInputs=[{"inputsJson": "{}", "rationale": "x"}] * 4),
])
def test_schema_is_locally_enforced_even_for_non_strict_providers(monkeypatch, change):
    output = model_output()
    change(output)
    assert run_mock(monkeypatch, output)["status"] == "INVALID_MODEL_OUTPUT"


@pytest.mark.parametrize("body", [
    b"not json", b'{"choices":[],"choices":[]}',
    json.dumps({"choices": []}).encode(),
    json.dumps(envelope(finish_reason="length")).encode(),
    json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "```json\n{}\n```"}}]}).encode(),
    json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": '{"summary":"one","summary":"two"}'}}]}).encode(),
    json.dumps({"choices": [{"finish_reason": "stop", "message": {"content": "{}", "tool_calls": [{"id": "x"}]}}]}).encode(),
])
def test_malformed_ambiguous_or_truncated_model_envelopes_are_rejected(monkeypatch, body):
    result = run_mock(monkeypatch, raw=body)
    assert result["status"] == "INVALID_MODEL_OUTPUT"
    assert result["findings"] == []


@pytest.mark.parametrize("refusal", ["message", "content_filter"])
def test_provider_refusal_is_distinct_from_a_clean_review(monkeypatch, refusal):
    body = envelope()
    if refusal == "message":
        body["choices"][0]["message"]["refusal"] = "private provider refusal detail"
    else:
        body["choices"][0]["finish_reason"] = "content_filter"
    result = run_mock(monkeypatch, raw=json.dumps(body).encode())
    assert result["status"] == "REFUSED"
    assert result["findings"] == []
    assert "private provider refusal detail" not in json.dumps(result)


@pytest.mark.parametrize("status", [302, 401, 429, 500])
def test_http_failures_do_not_leak_bodies_or_follow_redirects(status):
    with provider(b"PRIVATE_PROVIDER_BODY key=never-echo-this", status=status,
                  headers={"Location": "https://do-not-follow.invalid/v1"}) as (environment, observed):
        result = ai_review.review_sources(REQUEST, environment)
    assert result["status"] == "PROVIDER_ERROR"
    assert result["findings"] == []
    assert len(observed) == 1
    assert "PRIVATE_PROVIDER_BODY" not in json.dumps(result)
    assert "never-echo-this" not in json.dumps(result)


def test_transport_timeout_returns_no_findings():
    with provider(delay=1.2) as (environment, observed):
        environment["LLM_TIMEOUT_SECONDS"] = "1"
        started = time.monotonic()
        result = ai_review.review_sources(REQUEST, environment)
        elapsed = time.monotonic() - started
    assert result["status"] == "PROVIDER_ERROR"
    assert "timed out" in result["summary"]
    assert result["findings"] == []
    assert elapsed < 2
    assert len(observed) == 1


@pytest.mark.parametrize("declared_length", [False, True])
def test_provider_response_body_is_bounded(declared_length):
    headers = {"Content-Length": str(ai_review.MAX_RESPONSE_BYTES + 1)} if declared_length else {}
    body = b"x" * (ai_review.MAX_RESPONSE_BYTES + 1) if not declared_length else b""
    with provider(body, headers=headers) as (environment, _observed):
        result = ai_review.review_sources(REQUEST, environment)
    assert result["status"] == "INVALID_MODEL_OUTPUT"
    assert result["findings"] == []


@pytest.mark.parametrize("field,value", [
    ("cobolSource", ""), ("javaSource", "x" * 100_001),
    ("javaSource", "\n" * 1500), ("moduleName", "x" * 161),
    ("cobolSourceFormat", "UNKNOWN"), ("analysisContext", "x" * 8001),
    ("apiKey", "must-not-be-a-client-field"),
])
def test_invalid_requests_fail_before_provider(monkeypatch, field, value):
    monkeypatch.setattr(ai_review, "_post", lambda *_args: pytest.fail("Invalid request reached provider"))
    request = {**REQUEST, field: value}
    with pytest.raises(ValueError):
        ai_review.review_sources(request, {})


def test_cli_outputs_one_json_result_without_configuration():
    environment = {key: value for key, value in os.environ.items() if not key.startswith("LLM_")}
    result = subprocess.run([sys.executable, "-m", "ml_engine.ai_review", "--stdin"],
                            input=json.dumps(REQUEST), capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1], env=environment,
                            timeout=10, check=True)
    output = json.loads(result.stdout)
    assert output["status"] == "NOT_CONFIGURED"
    assert output["findings"] == []
    assert result.stderr == ""
    assert REQUEST["cobolSource"] not in result.stdout


def test_cli_rejects_duplicate_request_keys_without_traceback():
    result = subprocess.run([sys.executable, "-m", "ml_engine.ai_review", "--stdin"],
                            input='{"moduleName":"first","moduleName":"second"}',
                            capture_output=True, text=True,
                            cwd=Path(__file__).resolve().parents[1], timeout=10)
    assert result.returncode == 2
    assert json.loads(result.stdout)["status"] == "INVALID_MODEL_OUTPUT"
    assert result.stderr == ""
