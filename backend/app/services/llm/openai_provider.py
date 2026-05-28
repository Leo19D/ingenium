"""OpenAI LLM provider implementation (fallback)."""

from __future__ import annotations

from typing import TypeVar

import instructor
from openai import AsyncOpenAI
from pydantic import BaseModel

from app.config import settings
from app.services.llm.provider import LLMMessage, LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)


class OpenAIProvider(LLMProvider):
    def __init__(self) -> None:
        self._client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        self._structured_client = instructor.from_openai(self._client)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        resp = await self._client.chat.completions.create(
            model=model or settings.OPENAI_MODEL_DEFAULT,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": m.role, "content": m.content} for m in messages],
        )
        return LLMResponse(
            text=resp.choices[0].message.content or "",
            model=resp.model,
            input_tokens=resp.usage.prompt_tokens if resp.usage else 0,
            output_tokens=resp.usage.completion_tokens if resp.usage else 0,
            raw=resp,
        )

    async def structured(
        self,
        messages: list[LLMMessage],
        schema: type[T],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> T:
        return await self._structured_client.chat.completions.create(
            model=model or settings.OPENAI_MODEL_DEFAULT,
            max_tokens=max_tokens,
            temperature=temperature,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            response_model=schema,
        )
