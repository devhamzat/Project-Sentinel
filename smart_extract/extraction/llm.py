
"""The LLM seam — the single chokepoint for all model access (CLAUDE.md §9).

Every LLM call in the system goes through this module. It talks to any
OpenAI-compatible endpoint configured purely via .env (``LLM_BASE_URL``,
``LLM_API_KEY``, ``LLM_MODEL``). This is what makes the system model-agnostic:
swap Groq <-> Ollama <-> anything by editing .env only, never code.

Public API:
    complete(prompt, system=None) -> str          # free-form text completion
    extract_json(prompt, system=None) -> dict      # parsed JSON object

Do NOT import the openai SDK or hardcode a model anywhere else.
"""

from __future__ import annotations

import json
import time
from functools import lru_cache
from typing import Any

from openai import (
    APIConnectionError,
    APITimeoutError,
    InternalServerError,
    OpenAI,
    RateLimitError,
)

from smart_extract.config import settings

# Failures worth retrying: transient network drops, timeouts, rate limits, and
# 5xx from the provider. Permanent errors (auth, bad request, model-not-found)
# are NOT here so they fail fast instead of wasting retries.
_RETRYABLE = (APIConnectionError, APITimeoutError, RateLimitError, InternalServerError)


class LLMError(RuntimeError):
    """Raised when the LLM call fails or returns unusable output."""


@lru_cache
def _client() -> OpenAI:
    """Build the OpenAI-compatible client once, from .env settings."""
    if not settings.llm_api_key:
        # Many local endpoints (Ollama) accept any non-empty key; fail loudly
        # rather than send an empty one and get a confusing 401.
        raise LLMError(
            "LLM_API_KEY is empty. Set it in .env "
            "(use any placeholder like 'ollama' for a local endpoint)."
        )
    return OpenAI(base_url=settings.llm_base_url, api_key=settings.llm_api_key)


@lru_cache
def _embed_client() -> OpenAI:
    """Build the embeddings client (may target a different provider than chat).

    Embeddings frequently live behind a different endpoint than chat (e.g. Groq
    serves chat but not embeddings). Defaults fall back to the chat seam's
    URL/key via ``settings.embed_*`` when the dedicated ones are unset.
    """
    if not settings.embed_api_key:
        raise LLMError(
            "No embedding API key. Set LLM_EMBED_API_KEY (or LLM_API_KEY) in .env. "
            "Note: the chat provider may not serve embeddings — point "
            "LLM_EMBED_BASE_URL at one that does."
        )
    return OpenAI(base_url=settings.embed_base_url, api_key=settings.embed_api_key)


def _with_retries(call):
    """Run ``call``, retrying transient failures with exponential backoff.

    Groq's free tier (and any hosted endpoint) will occasionally drop a
    connection or rate-limit under a burst of requests — exactly what happens
    during evaluation, when we fire ~30 extractions back to back. Without this,
    one blip silently dropped a paper from the scored set and skewed the
    numbers. Retries make evaluation reproducible instead of luck-dependent.

    Retryable errors only (see ``_RETRYABLE``); permanent ones raise at once.
    All paths still end in ``LLMError`` so callers handle failure uniformly.
    """
    attempts = max(1, settings.llm_max_retries)
    last: Exception | None = None
    for i in range(attempts):
        try:
            return call()
        except _RETRYABLE as exc:
            last = exc
            if i < attempts - 1:
                time.sleep(settings.llm_retry_backoff * (2 ** i))
        except Exception as exc:  # auth, bad request, model-not-found, etc.
            raise LLMError(f"LLM request failed: {exc}") from exc
    raise LLMError(
        f"LLM request failed after {attempts} attempt(s): {last}"
    ) from last


def _chat(prompt: str, system: str | None, *, json_mode: bool = False) -> str:
    """Send a single-turn chat request and return the raw assistant text."""
    messages: list[dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})

    kwargs: dict[str, Any] = {
        "model": settings.llm_model,
        "messages": messages,
        "temperature": 0,  # deterministic-as-possible for extraction
    }
    if json_mode:
        # Supported by Groq/OpenAI; harmless to request. If an endpoint rejects
        # it, the caller still gets a clear LLMError below.
        kwargs["response_format"] = {"type": "json_object"}

    resp = _with_retries(lambda: _client().chat.completions.create(**kwargs))

    content = resp.choices[0].message.content
    if not content:
        raise LLMError("LLM returned an empty response.")
    return content


def complete(prompt: str, system: str | None = None) -> str:
    """Return a free-form text completion for ``prompt``."""
    return _chat(prompt, system)


def extract_json(prompt: str, system: str | None = None) -> dict[str, Any]:
    """Return a parsed JSON object from the model.

    Asks for JSON mode, then parses. If the model wraps JSON in prose or code
    fences, we make one best-effort attempt to recover the object before
    raising, so a stray ```json fence doesn't crash the pipeline.
    """
    raw = _chat(prompt, system, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is not None:
            return recovered
        raise LLMError(f"LLM did not return valid JSON. Got:\n{raw[:500]}")


def embed(texts: list[str]) -> list[list[float]]:
    """Return one embedding vector per input text via the embeddings seam.

    SPIKE (semantic retrieval — see docs/design-retrieve.md). Batched in one
    request. Raises LLMError on failure or a malformed response, like the rest
    of the seam. Model is ``LLM_EMBED_MODEL``; endpoint is the embed seam.
    """
    if not texts:
        return []
    try:
        resp = _embed_client().embeddings.create(
            model=settings.llm_embed_model, input=texts
        )
    except Exception as exc:  # network, auth, model-not-found, unsupported, ...
        raise LLMError(f"Embedding request failed: {exc}") from exc

    # The API returns items possibly out of order; sort by .index to be safe.
    items = sorted(resp.data, key=lambda d: d.index)
    if len(items) != len(texts):
        raise LLMError(
            f"Embedding count mismatch: asked {len(texts)}, got {len(items)}."
        )
    return [list(item.embedding) for item in items]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort: pull the first {...} JSON object out of noisy text."""
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return obj if isinstance(obj, dict) else None
