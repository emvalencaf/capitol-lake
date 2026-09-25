"""Provider selection (#41): configuration only, no real network calls made here."""

import pytest

from capitol_lake.llm_providers import UnknownProviderError, provider_from_env


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
