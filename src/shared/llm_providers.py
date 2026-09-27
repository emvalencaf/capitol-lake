"""Concrete `complete_text`/`complete_vision` providers for `extract_data.llm_fallback` (#41).

Every provider here matches `extract_data.llm_fallback`'s injected-callable
contract (`complete_text(prompt, source_text, schema)` /
`complete_vision(prompt, page_image, schema)`, each returning a dict already
validated against `schema` by the provider's own structured-output mode) so
the stage itself never depends on any one vendor's SDK or response shape.

Configuration-driven, following `extract_data/handler.py`'s convention
for real network dependencies (stdlib `urllib`, no extra HTTP client
dependency): `provider_from_env()` reads `LLM_FALLBACK_PROVIDER` (default
`"lm_studio"`, a local server, per the spec's free-tools budget) and returns
the matching `Provider`. Swapping providers is a configuration change only —
no code in `extract_data.llm_fallback` or a handler needs to change.

- **LM Studio** (`lm_studio`): a local OpenAI-compatible `/v1/chat/completions`
  server running Gemma (or any local vision-capable model), the free local
  default. No API key.
- **Gemini** (`gemini`): Google's `generateContent` REST API, with
  `responseSchema` for structured output; supports both text and inline
  image parts, so the same model covers both fallback modes. Free tier via
  `GEMINI_API_KEY`.
- **Groq** (`groq`): Groq's OpenAI-compatible `/openai/v1/chat/completions`
  endpoint, text only — Groq's free tier hosts no vision-capable model at
  time of writing, so `complete_vision` raises rather than silently
  returning a low-quality guess from a text-only model fed no image.

This module performs real network I/O and is not unit-tested, per this
codebase's handler convention (see `docs/local-dev.md`): the decision logic
it wraps is `extract_data.llm_fallback`'s, which is tested against canned
responses in `tests/test_llm_fallback.py`.
"""

from __future__ import annotations

import base64
import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from urllib.request import Request, urlopen

USER_AGENT = "capitol-lake LLM fallback (contact: edsonmvf@gmail.com)"

_DEFAULT_LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_LM_STUDIO_MODEL = "gemma-3-27b-it"
_DEFAULT_GEMINI_MODEL = "gemini-2.0-flash"
_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class VisionUnsupportedError(NotImplementedError):
    """A provider's `complete_vision` was called but the provider has no vision-capable model."""


@dataclass(frozen=True)
class Provider:
    """`complete_text`/`complete_vision` pair `extract_data.llm_fallback` expects, plus a name."""

    name: str
    complete_text: Callable[[str, str, dict[str, Any]], dict[str, Any]]
    complete_vision: Callable[[str, bytes, dict[str, Any]], dict[str, Any]]


def _post_json(url: str, payload: dict, *, headers: dict[str, str]) -> dict:
    request = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"User-Agent": USER_AGENT, "Content-Type": "application/json", **headers},
    )
    with urlopen(request) as response:
        return json.loads(response.read())


def _extract_json_content(text: str) -> dict[str, Any]:
    """Parse a chat-completion message's text content as the requested JSON object."""
    return json.loads(text)


# --- LM Studio (OpenAI-compatible chat completions, local) ------------------


def _openai_compatible_chat(
    base_url: str, model: str, messages: list[dict], schema: dict[str, Any], *, api_key: str | None
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    body = _post_json(
        f"{base_url}/chat/completions",
        {
            "model": model,
            "messages": messages,
            "response_format": {
                "type": "json_schema",
                "json_schema": {"name": "silver_fallback_fields", "schema": schema, "strict": True},
            },
        },
        headers=headers,
    )
    return _extract_json_content(body["choices"][0]["message"]["content"])


def _lm_studio_complete_text(
    prompt: str, source_text: str, schema: dict[str, Any]
) -> dict[str, Any]:
    base_url = os.environ.get("LM_STUDIO_BASE_URL", _DEFAULT_LM_STUDIO_BASE_URL)
    model = os.environ.get("LM_STUDIO_MODEL", _DEFAULT_LM_STUDIO_MODEL)
    messages = [{"role": "user", "content": f"{prompt}\n\nFiling text:\n{source_text}"}]
    return _openai_compatible_chat(base_url, model, messages, schema, api_key=None)


def _lm_studio_complete_vision(
    prompt: str, page_image: bytes, schema: dict[str, Any]
) -> dict[str, Any]:
    base_url = os.environ.get("LM_STUDIO_BASE_URL", _DEFAULT_LM_STUDIO_BASE_URL)
    model = os.environ.get("LM_STUDIO_MODEL", _DEFAULT_LM_STUDIO_MODEL)
    image_data_url = "data:image/png;base64," + base64.b64encode(page_image).decode("ascii")
    messages = [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        }
    ]
    return _openai_compatible_chat(base_url, model, messages, schema, api_key=None)


# --- Gemini (generateContent, free tier) -------------------------------------


def _gemini_generate(model: str, contents: list[dict], schema: dict[str, Any]) -> dict[str, Any]:
    api_key = os.environ["GEMINI_API_KEY"]
    body = _post_json(
        f"{_GEMINI_BASE_URL}/{model}:generateContent",
        {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": {k: v for k, v in schema.items() if k != "additionalProperties"},
            },
        },
        headers={"X-Goog-Api-Key": api_key},
    )
    return _extract_json_content(body["candidates"][0]["content"]["parts"][0]["text"])


def _gemini_complete_text(prompt: str, source_text: str, schema: dict[str, Any]) -> dict[str, Any]:
    model = os.environ.get("GEMINI_MODEL", _DEFAULT_GEMINI_MODEL)
    contents = [{"parts": [{"text": f"{prompt}\n\nFiling text:\n{source_text}"}]}]
    return _gemini_generate(model, contents, schema)


def _gemini_complete_vision(
    prompt: str, page_image: bytes, schema: dict[str, Any]
) -> dict[str, Any]:
    model = os.environ.get("GEMINI_MODEL", _DEFAULT_GEMINI_MODEL)
    contents = [
        {
            "parts": [
                {"text": prompt},
                {
                    "inline_data": {
                        "mime_type": "image/png",
                        "data": base64.b64encode(page_image).decode("ascii"),
                    }
                },
            ]
        }
    ]
    return _gemini_generate(model, contents, schema)


# --- Groq (OpenAI-compatible chat completions, text only) -------------------


def _groq_complete_text(prompt: str, source_text: str, schema: dict[str, Any]) -> dict[str, Any]:
    model = os.environ.get("GROQ_MODEL", _DEFAULT_GROQ_MODEL)
    messages = [{"role": "user", "content": f"{prompt}\n\nFiling text:\n{source_text}"}]
    return _openai_compatible_chat(
        _GROQ_BASE_URL, model, messages, schema, api_key=os.environ["GROQ_API_KEY"]
    )


def _groq_complete_vision(prompt: str, page_image: bytes, schema: dict[str, Any]) -> dict[str, Any]:
    raise VisionUnsupportedError(
        "groq: no free-tier vision-capable model; use scanned filings via lm_studio/gemini"
    )


_PROVIDERS: dict[str, Provider] = {
    "lm_studio": Provider("lm_studio", _lm_studio_complete_text, _lm_studio_complete_vision),
    "gemini": Provider("gemini", _gemini_complete_text, _gemini_complete_vision),
    "groq": Provider("groq", _groq_complete_text, _groq_complete_vision),
}


class UnknownProviderError(ValueError):
    """`LLM_FALLBACK_PROVIDER` names a provider not in `_PROVIDERS`."""


def provider_from_env() -> Provider:
    """The `Provider` named by `LLM_FALLBACK_PROVIDER` (default `"lm_studio"`, the local default).

    Swapping providers (#41's acceptance criteria) is entirely a matter of
    setting this one environment variable plus that provider's own
    credentials (`GEMINI_API_KEY`, `GROQ_API_KEY`) — no code changes.
    """
    return provider_by_name(os.environ.get("LLM_FALLBACK_PROVIDER", "lm_studio"))


def provider_by_name(name: str) -> Provider:
    """The `Provider` named `name` (`lm_studio`, `gemini` or `groq`).

    Used by callers that pick a provider by an explicit argument rather than
    `LLM_FALLBACK_PROVIDER` (e.g. `scripts/run_house_eval.py --provider`,
    #89), while still sharing this module's one set of concrete providers.
    """
    try:
        return _PROVIDERS[name]
    except KeyError:
        raise UnknownProviderError(
            f"unknown provider {name!r}; choose one of {sorted(_PROVIDERS)}"
        ) from None
