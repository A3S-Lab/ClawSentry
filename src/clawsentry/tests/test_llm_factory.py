"""Tests for llm_factory — build_analyzer_from_env()."""

from __future__ import annotations

import os
from unittest import mock

import pytest

from clawsentry.gateway.llm_factory import build_analyzer_from_env
from clawsentry.gateway.llm_provider import OpenAIProvider, AnthropicProvider
from clawsentry.gateway.semantic_analyzer import (
    CompositeAnalyzer,
    LLMAnalyzer,
    RuleBasedAnalyzer,
)


def _clean_env():
    """Return a mock env dict with all AHP_LLM_* and API keys cleared."""
    keys_to_clear = [
        "CS_LLM_PROVIDER",
        "CS_LLM_MODEL",
        "CS_LLM_BASE_URL",
        "CS_L3_ENABLED",
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
    ]
    return {k: "" for k in keys_to_clear}


class TestBuildAnalyzerFromEnv:
    def test_default_returns_none(self):
        """No env vars → None (gateway uses default RuleBasedAnalyzer)."""
        with mock.patch.dict(os.environ, _clean_env(), clear=False):
            result = build_analyzer_from_env()
        assert result is None

    def test_empty_provider_returns_none(self):
        """CS_LLM_PROVIDER='' → None."""
        env = {**_clean_env(), "CS_LLM_PROVIDER": ""}
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert result is None

    def test_unknown_provider_returns_none(self):
        """CS_LLM_PROVIDER=unknown → None with warning."""
        env = {**_clean_env(), "CS_LLM_PROVIDER": "unknown"}
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert result is None

    def test_openai_provider_missing_key_returns_none(self):
        """CS_LLM_PROVIDER=openai but no OPENAI_API_KEY → None."""
        env = {**_clean_env(), "CS_LLM_PROVIDER": "openai"}
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert result is None

    def test_anthropic_provider_missing_key_returns_none(self):
        """CS_LLM_PROVIDER=anthropic but no ANTHROPIC_API_KEY → None."""
        env = {**_clean_env(), "CS_LLM_PROVIDER": "anthropic"}
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert result is None

    def test_openai_provider_from_env(self):
        """CS_LLM_PROVIDER=openai + OPENAI_API_KEY → CompositeAnalyzer with OpenAIProvider."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-123",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
        # Should contain RuleBasedAnalyzer + LLMAnalyzer
        assert len(result._analyzers) == 2
        assert isinstance(result._analyzers[0], RuleBasedAnalyzer)
        assert isinstance(result._analyzers[1], LLMAnalyzer)
        assert isinstance(result._analyzers[1]._provider, OpenAIProvider)

    def test_anthropic_provider_from_env(self):
        """CS_LLM_PROVIDER=anthropic + ANTHROPIC_API_KEY → CompositeAnalyzer with AnthropicProvider."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "anthropic",
            "ANTHROPIC_API_KEY": "sk-ant-test-key-123",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
        assert len(result._analyzers) == 2
        assert isinstance(result._analyzers[0], RuleBasedAnalyzer)
        assert isinstance(result._analyzers[1], LLMAnalyzer)
        assert isinstance(result._analyzers[1]._provider, AnthropicProvider)

    def test_custom_base_url(self):
        """CS_LLM_BASE_URL sets OpenAIProvider.base_url for compatible endpoints."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-123",
            "CS_LLM_BASE_URL": "http://35.220.164.252:3888/v1/",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
        provider = result._analyzers[1]._provider
        assert isinstance(provider, OpenAIProvider)
        assert provider._config.base_url == "http://35.220.164.252:3888/v1/"

    def test_custom_model(self):
        """CS_LLM_MODEL overrides default model name."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-123",
            "CS_LLM_MODEL": "kimi-k2.5",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
        provider = result._analyzers[1]._provider
        assert isinstance(provider, OpenAIProvider)
        assert provider._model == "kimi-k2.5"

    def test_l3_enabled(self):
        """CS_L3_ENABLED=true adds AgentAnalyzer to composite."""
        from pathlib import Path
        from clawsentry.gateway.server import TrajectoryStore

        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-123",
            "CS_L3_ENABLED": "true",
        }
        store = TrajectoryStore(db_path=":memory:")
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env(
                trajectory_store=store,
                workspace_root=Path("/tmp"),
            )
        assert isinstance(result, CompositeAnalyzer)
        # Should contain RuleBasedAnalyzer + LLMAnalyzer + AgentAnalyzer
        assert len(result._analyzers) == 3
        from clawsentry.gateway.agent_analyzer import AgentAnalyzer
        assert isinstance(result._analyzers[2], AgentAnalyzer)

    def test_l3_disabled_by_default(self):
        """Without CS_L3_ENABLED, no AgentAnalyzer."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "openai",
            "OPENAI_API_KEY": "sk-test-key-123",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
        assert len(result._analyzers) == 2

    def test_provider_case_insensitive(self):
        """CS_LLM_PROVIDER is case-insensitive."""
        env = {
            **_clean_env(),
            "CS_LLM_PROVIDER": "OpenAI",
            "OPENAI_API_KEY": "sk-test-key-123",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            result = build_analyzer_from_env()
        assert isinstance(result, CompositeAnalyzer)
