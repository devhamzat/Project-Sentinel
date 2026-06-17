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
from functools import lru_cache
from typing import Any

from openai import OpenAI

from smart_extract.config import settings


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

    try:
        resp = _client().chat.completions.create(**kwargs)
    except Exception as exc:  # network, auth, bad model name, etc.
        raise LLMError(f"LLM request failed: {exc}") from exc

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
    raising, so a stray ```json fence doesn't crash the pipeline (§12).
    """
    raw = _chat(prompt, system, json_mode=True)
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        recovered = _extract_json_object(raw)
        if recovered is not None:
            return recovered
        raise LLMError(f"LLM did not return valid JSON. Got:\n{raw[:500]}")


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
