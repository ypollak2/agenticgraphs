"""The live runner's transport: determinism, accounting, and backoff.

`LLMRunner._post` is where v1.8 put the three properties every recorded number
depends on — pinned sampling, real token counts, and a retry that keeps a rate
limit from being written down as a contract failure. None of it was exercised by
a test, which is how the previous version shipped a hardcoded $0.002/node price
beside an endpoint that returns the true one on every response.

Every test here stubs the transport. Nothing reaches a network.
"""
from __future__ import annotations

import json
import urllib.error
from io import BytesIO

import pytest

from agenticgraphs import harness
from agenticgraphs.harness import LLMRunner, _spend


@pytest.fixture
def env(monkeypatch):
    monkeypatch.setenv("AGR_LLM_BASE_URL", "https://api.example.test/v1")
    monkeypatch.setenv("AGR_LLM_MODEL", "gpt-4o")
    monkeypatch.setenv("AGR_LLM_API_KEY", "k")


def _response(content: str = '{"ok": true}', prompt=100, completion=20):
    return BytesIO(json.dumps({
        "choices": [{"message": {"content": content}}],
        "usage": {"prompt_tokens": prompt, "completion_tokens": completion},
    }).encode())


class _Recorder:
    """Stands in for urlopen, recording each request and replaying a script."""

    def __init__(self, script):
        self.script, self.payloads, self.calls = list(script), [], 0

    def __call__(self, req, timeout=None):
        self.calls += 1
        self.payloads.append(json.loads(req.data))
        item = self.script.pop(0) if self.script else _response()
        if isinstance(item, Exception):
            raise item
        return _ctx(item)


class _ctx:
    def __init__(self, body):
        self.body = body

    def __enter__(self):
        return self.body

    def __exit__(self, *a):
        return False


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(harness.time, "sleep", lambda _: None)


def test_base_url_must_be_http(monkeypatch):
    """The `# noqa: S310` on the request says the scheme was checked. Check it."""
    monkeypatch.setenv("AGR_LLM_BASE_URL", "file:///etc/passwd")
    monkeypatch.setenv("AGR_LLM_MODEL", "m")
    with pytest.raises(ValueError, match="http"):
        LLMRunner()


def test_sampling_is_pinned_on_every_request(env, monkeypatch):
    rec = _Recorder([])
    monkeypatch.setattr(harness.urllib.request, "urlopen", rec)
    r = LLMRunner()
    r.bind({"termination": {"contract": "c"}, "verification": []})
    r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})
    sent = rec.payloads[0]
    assert sent["temperature"] == 0 and sent["seed"] == LLMRunner.SAMPLING["seed"]
    assert sent["max_tokens"] == LLMRunner.SAMPLING["max_tokens"]
    assert sent["response_format"] == {"type": "json_object"}


def test_usage_is_recorded_not_discarded(env, monkeypatch):
    monkeypatch.setattr(harness.urllib.request, "urlopen",
                        _Recorder([_response(prompt=1000, completion=500)]))
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})
    assert r.usage == {"prompt_tokens": 1000, "completion_tokens": 500, "calls": 1}


def test_cost_is_priced_from_tokens_when_the_model_is_known(env, monkeypatch):
    monkeypatch.setattr(harness.urllib.request, "urlopen",
                        _Recorder([_response(prompt=1_000_000, completion=1_000_000)]))
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})
    spent, measured = _spend(r, steps=1)
    assert measured
    assert spent == pytest.approx(12.50)  # gpt-4o: $2.50 in + $10.00 out per 1M


def test_unknown_model_falls_back_and_says_so(env, monkeypatch):
    monkeypatch.setenv("AGR_LLM_MODEL", "some-local-thing:7b")
    monkeypatch.setattr(harness.urllib.request, "urlopen", _Recorder([_response()]))
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})
    spent, measured = _spend(r, steps=3)
    assert not measured, "a guessed price must never report itself as measured"
    assert spent == pytest.approx(3 * harness._EST_USD_PER_NODE)


def test_a_rate_limit_is_retried_not_recorded_as_failure(env, monkeypatch):
    rec = _Recorder([
        urllib.error.HTTPError("u", 429, "Too Many Requests", {}, None),
        urllib.error.HTTPError("u", 503, "Unavailable", {}, None),
        _response(),
    ])
    monkeypatch.setattr(harness.urllib.request, "urlopen", rec)
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    assert r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {}) == {"ok": True}
    assert rec.calls == 3


def test_a_client_error_is_not_retried(env, monkeypatch):
    rec = _Recorder([urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)])
    monkeypatch.setattr(harness.urllib.request, "urlopen", rec)
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    with pytest.raises(urllib.error.HTTPError):
        r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})
    assert rec.calls == 1


def test_json_mode_is_dropped_for_an_endpoint_that_rejects_it(env, monkeypatch):
    """Not every OpenAI-compatible server implements `response_format`.

    Dropping it is a capability fallback, not a retry — the run must continue
    with the `extract_json` repair layer rather than fail.
    """
    rec = _Recorder([urllib.error.HTTPError("u", 400, "Bad Request", {}, None), _response()])
    monkeypatch.setattr(harness.urllib.request, "urlopen", rec)
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    assert r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {}) == {"ok": True}
    assert "response_format" in rec.payloads[0]
    assert "response_format" not in rec.payloads[1]


def test_exhausted_retries_raise_with_the_last_cause(env, monkeypatch):
    err = urllib.error.HTTPError("u", 503, "Unavailable", {}, None)
    monkeypatch.setattr(harness.urllib.request, "urlopen", _Recorder([err] * 8))
    r = LLMRunner()
    r.bind({"termination": {}, "verification": []})
    with pytest.raises(RuntimeError, match="attempts"):
        r.run({"id": "n", "speciality": "producer", "outputs": ["ok"]}, {})


def test_the_prompt_never_carries_the_assert_text(env, monkeypatch):
    """v1.8's central change: a node is told what to produce, not how it is marked.

    Telling a node `["output.matches_ownership_map"]` and then scoring it on
    `output.matches_ownership_map` measures echo, not work.
    """
    rec = _Recorder([])
    monkeypatch.setattr(harness.urllib.request, "urlopen", rec)
    r = LLMRunner()
    r.bind({
        "termination": {"contract": "routing matches the ownership map"},
        "verification": [{"assert": "output.matches_ownership_map"}],
    })
    r.run({"id": "verify", "speciality": "critic",
           "outputs": ["matches_ownership_map", "output"]}, {})
    prompt = rec.payloads[0]["messages"][0]["content"]
    assert "output.matches_ownership_map" not in prompt
    assert "Downstream assertions" not in prompt
    # The key and the contract are legitimate: a node must know what it owes.
    assert "matches_ownership_map" in prompt
    assert "routing matches the ownership map" in prompt
