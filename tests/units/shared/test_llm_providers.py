"""Provider selection (#41): configuration only, no real network calls made here."""

import pytest

from shared.llm_providers import (
    RateLimiter,
    UnknownProviderError,
    _rate_limiter_for,
    _to_gemini_schema,
    provider_by_name,
    provider_from_env,
)


def test_defaults_to_lm_studio_when_unset(monkeypatch):
    monkeypatch.delenv("LLM_FALLBACK_PROVIDER", raising=False)

    provider = provider_from_env()

    assert provider.name == "lm_studio"


@pytest.mark.parametrize("name", ["lm_studio", "gemini", "groq"])
def test_selects_provider_named_by_env_var(monkeypatch, name):
    monkeypatch.setenv("LLM_FALLBACK_PROVIDER", name)

    provider = provider_from_env()

    assert provider.name == name


def test_unknown_provider_name_raises():
    import os

    os.environ["LLM_FALLBACK_PROVIDER"] = "not-a-real-provider"
    try:
        with pytest.raises(UnknownProviderError):
            provider_from_env()
    finally:
        del os.environ["LLM_FALLBACK_PROVIDER"]


@pytest.mark.parametrize("name", ["lm_studio", "gemini", "groq"])
def test_provider_by_name_selects_named_provider(name):
    assert provider_by_name(name).name == name


def test_provider_by_name_unknown_name_raises():
    with pytest.raises(UnknownProviderError):
        provider_by_name("not-a-real-provider")


# ---------------------------------------------------------------------------
# RateLimiter (same contract as house_collect.collect.RateLimiter)
# ---------------------------------------------------------------------------


def test_rate_limiter_does_not_sleep_on_first_call():
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: 100.0, sleep=sleeps.append)

    limiter.wait()

    assert sleeps == []


def test_rate_limiter_sleeps_remaining_interval_on_fast_second_call():
    clock_values = iter([100.0, 100.2, 100.2])
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: next(clock_values), sleep=sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == [pytest.approx(0.8)]


def test_rate_limiter_does_not_sleep_when_interval_already_elapsed():
    clock_values = iter([100.0, 101.5])
    sleeps = []
    limiter = RateLimiter(min_interval=1.0, clock=lambda: next(clock_values), sleep=sleeps.append)

    limiter.wait()
    limiter.wait()

    assert sleeps == []


def test_rate_limiter_for_known_model_uses_its_free_tier_interval():
    limiter = _rate_limiter_for("groq", "qwen/qwen3.8-27b")

    assert limiter.min_interval == 75.0


def test_rate_limiter_for_unknown_model_falls_back_to_default_interval():
    limiter = _rate_limiter_for("groq", "some-future-model-not-in-the-table")

    assert limiter.min_interval == 2.0


def test_rate_limiter_for_same_provider_and_model_returns_the_same_instance():
    first = _rate_limiter_for("gemini", "gemini-2.5-flash")
    second = _rate_limiter_for("gemini", "gemini-2.5-flash")

    assert first is second


# ---------------------------------------------------------------------------
# _to_gemini_schema (Gemini's responseSchema rejects JSON Schema nullable unions)
# ---------------------------------------------------------------------------


def test_to_gemini_schema_converts_nullable_union_to_nullable_flag():
    schema = {"type": ["string", "null"]}

    assert _to_gemini_schema(schema) == {"type": "string", "nullable": True}


def test_to_gemini_schema_drops_additional_properties():
    schema = {"type": "object", "properties": {}, "additionalProperties": False}

    assert "additionalProperties" not in _to_gemini_schema(schema)


def test_to_gemini_schema_recurses_into_properties_and_items():
    schema = {
        "type": "object",
        "properties": {
            "transactions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"owner": {"type": ["string", "null"]}},
                    "additionalProperties": False,
                },
            }
        },
        "additionalProperties": False,
    }

    converted = _to_gemini_schema(schema)

    owner = converted["properties"]["transactions"]["items"]["properties"]["owner"]
    assert owner == {"type": "string", "nullable": True}
    assert "additionalProperties" not in converted
    assert "additionalProperties" not in converted["properties"]["transactions"]["items"]
