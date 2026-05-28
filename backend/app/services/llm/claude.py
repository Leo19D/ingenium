"""Claude (Anthropic) LLM provider implementation."""

from __future__ import annotations

from typing import TypeVar

import instructor
from anthropic import AsyncAnthropic
from pydantic import BaseModel

from app.config import settings
from app.services.llm.provider import LLMMessage, LLMProvider, LLMResponse

T = TypeVar("T", bound=BaseModel)


class ClaudeProvider(LLMProvider):
    def __init__(self) -> None:
        self._client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        self._structured_client = instructor.from_anthropic(self._client)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str | None = None,
        max_tokens: int = 4096,
        temperature: float = 0.0,
    ) -> LLMResponse:
        system = "\n".join(m.content for m in messages if m.role == "system")
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        resp = await self._client.messages.create(
            model=model or settings.ANTHROPIC_MODEL_DEFAULT,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=chat,
        )
        text = "".join(b.text for b in resp.content if hasattr(b, "text"))
        return LLMResponse(
            text=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
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
        system = "\n".join(m.content for m in messages if m.role == "system")
        chat = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        return await self._structured_client.messages.create(
            model=model or settings.ANTHROPIC_MODEL_DEFAULT,
            max_tokens=max_tokens,
            temperature=temperature,
            system=system or None,
            messages=chat,
            response_model=schema,
        )
