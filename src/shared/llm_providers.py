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

## Free-tier pacing (`docs/metrics.md`'s "House LLM extractor benchmark")

Groq and Gemini's free tiers both cap calls well below what
`scripts/run_house_eval.py --extractor llm`'s per-filing loop fires them at,
so every `groq`/`gemini` call is paced by `_rate_limiter_for` to its
model's free-tier limit before this module ever sends it. This is pacing,
not retrying: exactly one attempt is still made per filing, just spaced out
enough to not be an avoidable rate-limit failure — it doesn't conflict with
ADR 0019's "no automatic retries on a provider failure" (a rate limit hit
despite pacing is still surfaced uncaught, same as before).

`_FREE_TIER_MIN_INTERVAL_SECONDS` below is sourced 2026-09-27:

- **Groq**: from Groq's own console (`https://console.groq.com/docs/rate-limits`,
  which still publishes a concrete free-tier table: 30 RPM / 8K TPM for most
  models). `qwen/qwen3.8-27b`'s interval is wider than that table would
  suggest: a live 429 from this model named a separate, undocumented
  ~1000-output-tokens/minute sub-limit (reasoning models emit chain-of-thought
  tokens before their JSON answer, so a single call's real output-token cost
  is far higher than the JSON payload alone), and one call against this
  benchmark's schema already requests ~900+ of that — so it's paced by the
  empirically-observed limit, not the published one.
- **Gemini**: a per-minute `min_interval` cannot actually fix Gemini's real
  constraint. A live 429 body named the binding quota as
  `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, value **20** — 20
  requests per *day*, per model, per project, confirmed directly against the
  API on this date, not a third-party estimate. `gemini-2.0-flash` (this
  module's old default) has since been retired outright (a live call now
  404s telling callers to move to `gemini-3.8-flash`), and both
  `gemini-2.5-flash` (the current default) and `gemini-3.8-flash` sit behind
  this same 20/day cap. Older third-party-reported RPM/TPM figures for these
  models describe a more generous free tier Google has since tightened —
  don't trust them over this. A full 30-digital-filing House benchmark
  cannot complete against Gemini's free tier in a single day; treat a
  Gemini run here as a small spot-check, not a benchmark round.
"""

from __future__ import annotations

import base64
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any
from urllib.request import Request, urlopen

USER_AGENT = "capitol-lake LLM fallback (contact: edsonmvf@gmail.com)"

_DEFAULT_LM_STUDIO_BASE_URL = "http://localhost:1234/v1"
_DEFAULT_LM_STUDIO_MODEL = "gemma-3-27b-it"
# `gemini-2.0-flash` was retired by Google (a live call now 404s: "This model
# ... is no longer available"). `gemini-3.8-flash`, its suggested successor,
# has a free tier too thin to benchmark against (~20 requests/*day*, per
# Google's own developer forum) — `gemini-2.5-flash` is the newest model
# still on a workable free tier, confirmed live 2026-09-27.
_DEFAULT_GEMINI_MODEL = "gemini-2.5-flash"
_DEFAULT_GROQ_MODEL = "llama-3.3-70b-versatile"

# provider name -> model -> minimum seconds between calls to that model.
_FREE_TIER_MIN_INTERVAL_SECONDS: dict[str, dict[str, float]] = {
    "groq": {
        # 30 RPM / 8K TPM (console.groq.com/docs/rate-limits, 2026-09-27).
        "llama-3.3-70b-versatile": 2.0,
        "openai/gpt-oss-20b": 2.0,
        "openai/gpt-oss-120b": 2.0,
        # Empirically ~1 call/minute (see module docstring); 30 RPM alone
        # under-paces this reasoning model badly.
        "qwen/qwen3.8-27b": 75.0,
    },
    "gemini": {
        # Confirmed directly from a live 429 body 2026-09-27 (not a
        # third-party estimate): both models are capped at
        # `GenerateRequestsPerDayPerProjectPerModel-FreeTier`, quotaValue
        # 20 -- 20 requests/*day*, per model, per project. That's a daily
        # quota, not a per-minute one, so no `min_interval` here actually
        # makes a multi-filing benchmark practical; these values only
        # smooth out a burst of calls within whatever's left of the day's
        # 20. Earlier third-party RPM/TPM figures for these models (and for
        # the now-retired `gemini-2.0-flash`) reflect a more generous free
        # tier Google has since tightened; do not trust them over this.
        "gemini-2.5-flash": 6.0,
        "gemini-3.8-flash": 4.0,
    },
}
_DEFAULT_MIN_INTERVAL_SECONDS = 2.0

_GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"
_GROQ_BASE_URL = "https://api.groq.com/openai/v1"


class VisionUnsupportedError(NotImplementedError):
    """A provider's `complete_vision` was called but the provider has no vision-capable model."""


@dataclass
class RateLimiter:
    """Sleeps as needed to keep calls to `wait()` at least `min_interval` apart.

    Paces a provider call to its own published (or empirically-observed)
    free-tier limit before the call is made — see the module docstring's
    "Free-tier pacing" section for why this isn't the retry ADR 0019 rejects.
    """

    min_interval: float = 0.0
    clock: Callable[[], float] = time.monotonic
    sleep: Callable[[float], None] = time.sleep
    _last_call: float | None = field(default=None, init=False, repr=False)

    def wait(self) -> None:
        now = self.clock()
        if self._last_call is not None:
            remaining = self.min_interval - (now - self._last_call)
            if remaining > 0:
                self.sleep(remaining)
                now = self.clock()
        self._last_call = now


_rate_limiters: dict[tuple[str, str], RateLimiter] = {}


def _rate_limiter_for(provider_name: str, model: str) -> RateLimiter:
    """The shared `RateLimiter` for this provider+model, created on first use."""
    key = (provider_name, model)
    if key not in _rate_limiters:
        interval = _FREE_TIER_MIN_INTERVAL_SECONDS.get(provider_name, {}).get(
            model, _DEFAULT_MIN_INTERVAL_SECONDS
        )
        _rate_limiters[key] = RateLimiter(min_interval=interval)
    return _rate_limiters[key]


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


def _to_gemini_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Convert a `{"type": ["string", "null"]}`-style schema to Gemini's OpenAPI-subset form.

    Gemini's `responseSchema` rejects that JSON Schema nullable-union shape
    outright (a real 400: "Proto field is not repeating, cannot start
    list") and has no `additionalProperties` field either. Recurses through
    `properties`/`items` since a nested `Transaction` field
    (`extract_data.llm_extract.transaction_schema`) uses the same nullable
    pattern as the top-level page schema.
    """
    out = {k: v for k, v in schema.items() if k != "additionalProperties"}
    type_ = out.get("type")
    if isinstance(type_, list):
        non_null = [t for t in type_ if t != "null"]
        out["type"] = non_null[0] if len(non_null) == 1 else non_null
        out["nullable"] = True
    if "properties" in out:
        out["properties"] = {k: _to_gemini_schema(v) for k, v in out["properties"].items()}
    if "items" in out:
        out["items"] = _to_gemini_schema(out["items"])
    return out


def _gemini_generate(model: str, contents: list[dict], schema: dict[str, Any]) -> dict[str, Any]:
    _rate_limiter_for("gemini", model).wait()
    api_key = os.environ["GEMINI_API_KEY"]
    body = _post_json(
        f"{_GEMINI_BASE_URL}/{model}:generateContent",
        {
            "contents": contents,
            "generationConfig": {
                "responseMimeType": "application/json",
                "responseSchema": _to_gemini_schema(schema),
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
    _rate_limiter_for("groq", model).wait()
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
