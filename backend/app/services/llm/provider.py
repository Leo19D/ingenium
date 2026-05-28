"""
LLM provider abstraction.

All LLM calls go through this interface so we can swap Claude / OpenAI /
local models without touching call sites.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMMessage(BaseModel):
    role: str  # 'system' | 'user' | 'assistant'
    content: str


class LLMResponse(BaseModel):
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    raw: Any = None


class LLMProvider(ABC):
    """Async LLM provider interface."""

    @abstractmethod
    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        """Plain text completion."""

    @abstractmethod
    async def structured(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> T:
        """Structured output validated against a Pydantic schema."""


def get_llm_provider(name: str | None = None) -> LLMProvider:
    """Factory for the configured provider."""
    from app.config import settings
    from app.services.llm.claude import ClaudeProvider
    from app.services.llm.openai_provider import OpenAIProvider

    provider = (name or settings.LLM_PROVIDER).lower()
    if provider == "anthropic":
        return ClaudeProvider()
    if provider == "openai":
        return OpenAIProvider()
    raise ValueError(f"Unknown LLM provider: {provider}")
