"""
LLM Provider abstraction — multi-provider support for L2 semantic analysis.

Design basis: 09-l2-pluggable-semantic-analysis.md section 4.4
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional, Protocol, runtime_checkable


@dataclass
class LLMProviderConfig:
    """Configuration for an LLM provider."""
    api_key: str
    model: str = ""
    max_tokens: int = 256
    temperature: float = 0.0
    base_url: Optional[str] = None


@runtime_checkable
class LLMProvider(Protocol):
    """Protocol for LLM provider implementations."""

    @property
    def provider_id(self) -> str: ...

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        timeout_ms: float,
        max_tokens: int = 256,
    ) -> str: ...


class AnthropicProvider:
    """Anthropic Claude API provider."""

    DEFAULT_MODEL = "claude-haiku-4-5-20251001"

    def __init__(self, config: LLMProviderConfig) -> None:
        self._config = config
        self._model = config.model or self.DEFAULT_MODEL
        self._client: Optional[object] = None

    def _get_client(self) -> object:
        """Lazy-init the Anthropic async client (deferred to avoid proxy issues at import)."""
        if self._client is None:
            import anthropic
            self._client = anthropic.AsyncAnthropic(api_key=self._config.api_key)
        return self._client

    @property
    def provider_id(self) -> str:
        return "anthropic"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        timeout_ms: float,
        max_tokens: int = 256,
    ) -> str:
        effective_max_tokens = max_tokens or self._config.max_tokens
        client = self._get_client()
        response = await asyncio.wait_for(
            client.messages.create(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=effective_max_tokens,
                temperature=self._config.temperature,
                system=system_prompt,
                messages=[{"role": "user", "content": user_message}],
            ),
            timeout=timeout_ms / 1000,
        )
        return response.content[0].text  # type: ignore[union-attr]


class OpenAIProvider:
    """OpenAI-compatible API provider (supports custom base_url for Ollama etc.)."""

    DEFAULT_MODEL = "gpt-4o-mini"

    def __init__(self, config: LLMProviderConfig) -> None:
        self._config = config
        self._model = config.model or self.DEFAULT_MODEL
        self._client: Optional[object] = None

    def _get_client(self) -> object:
        """Lazy-init the OpenAI async client (deferred to avoid proxy issues at import)."""
        if self._client is None:
            import openai
            kwargs: dict = {"api_key": self._config.api_key}
            if self._config.base_url:
                kwargs["base_url"] = self._config.base_url
            self._client = openai.AsyncOpenAI(**kwargs)
        return self._client

    @property
    def provider_id(self) -> str:
        return "openai"

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        timeout_ms: float,
        max_tokens: int = 256,
    ) -> str:
        effective_max_tokens = max_tokens or self._config.max_tokens
        client = self._get_client()
        response = await asyncio.wait_for(
            client.chat.completions.create(  # type: ignore[union-attr]
                model=self._model,
                max_tokens=effective_max_tokens,
                temperature=self._config.temperature,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_message},
                ],
            ),
            timeout=timeout_ms / 1000,
        )
        return response.choices[0].message.content  # type: ignore[union-attr]
