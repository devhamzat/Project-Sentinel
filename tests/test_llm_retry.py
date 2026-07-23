"""Offline tests for the LLM seam's retry/backoff (_with_retries).

Transient failures (dropped connections, rate limits, 5xx) must be retried so
evaluation isn't luck-dependent; permanent failures (auth, bad request) must
fail fast. No network: we drive the retry helper with fake callables and stub
out time.sleep so the tests are instant.
"""

from __future__ import annotations

import httpx
import pytest
from openai import APIConnectionError, AuthenticationError, RateLimitError

from smart_extract.extraction import llm
from smart_extract.extraction.llm import LLMError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(llm.time, "sleep", lambda *_: None)


def _conn_error() -> APIConnectionError:
    # The SDK's APIConnectionError needs a request object.
    return APIConnectionError(request=httpx.Request("POST", "http://x"))


def test_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 4)
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise _conn_error()
        return "ok"

    assert llm._with_retries(flaky) == "ok"
    assert calls["n"] == 3  # failed twice, succeeded on the third


def test_exhausts_retries_and_raises_llmerror(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 3)
    calls = {"n": 0}

    def always_fails():
        calls["n"] += 1
        raise _conn_error()

    with pytest.raises(LLMError) as exc_info:
        llm._with_retries(always_fails)
    assert calls["n"] == 3
    assert "3 attempt" in str(exc_info.value)


def test_permanent_error_fails_fast(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 4)
    calls = {"n": 0}

    def auth_fail():
        calls["n"] += 1
        raise AuthenticationError(
            "bad key",
            response=httpx.Response(401, request=httpx.Request("POST", "http://x")),
            body=None,
        )

    with pytest.raises(LLMError):
        llm._with_retries(auth_fail)
    assert calls["n"] == 1  # not retried


def test_rate_limit_is_retryable(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_max_retries", 2)
    calls = {"n": 0}

    def rate_limited():
        calls["n"] += 1
        if calls["n"] == 1:
            raise RateLimitError(
                "slow down",
                response=httpx.Response(429, request=httpx.Request("POST", "http://x")),
                body=None,
            )
        return "recovered"

    assert llm._with_retries(rate_limited) == "recovered"
    assert calls["n"] == 2