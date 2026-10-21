from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, Omit, OpenAIError
from openai.types.chat import ChatCompletion


class CompatibleModelClientError(RuntimeError):
    def __init__(self, message: str, *, status: int | str, cause_type: str) -> None:
        super().__init__(message)
        self.status = status
        self.cause_type = cause_type


@dataclass(frozen=True)
class ChatCompletionResult:
    response_id: str | None
    http_status: int
    finish_reason: str | None
    usage: dict[str, Any] | None
    content: str


@dataclass(frozen=True)
class OpenAICompatibleClient:
    sdk: AsyncOpenAI
    omit_authorization: bool


def build_openai_compatible_client(
    api_key: str | None,
    *,
    base_url: str,
    api_key_header: str = "Authorization",
    api_key_prefix: str = "Bearer",
    timeout_seconds: float | None = 45.0,
    http_client: httpx.AsyncClient | None = None,
) -> OpenAICompatibleClient:
    parsed = urlsplit(base_url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("The OpenAI-compatible base URL must be an absolute HTTP(S) URL")

    credential = f"{api_key_prefix} {api_key}".strip() if api_key else None
    default_headers: dict[str, str | Omit] = {}
    sdk_api_key = api_key or "credential-not-configured"
    uses_sdk_bearer = api_key_header.lower() == "authorization" and api_key_prefix == "Bearer"
    if not uses_sdk_bearer:
        default_headers["Authorization"] = Omit()
        if credential:
            default_headers[api_key_header] = credential
    elif not api_key:
        default_headers["Authorization"] = Omit()

    return OpenAICompatibleClient(
        sdk=AsyncOpenAI(
            api_key=sdk_api_key,
            base_url=f"{base_url.rstrip('/')}/",
            timeout=timeout_seconds,
            max_retries=0,
            default_headers=default_headers,  # type: ignore[arg-type]
            http_client=http_client,
        ),
        omit_authorization=not uses_sdk_bearer or not api_key,
    )


def provider_reasoning(delta: dict[str, Any]) -> str:
    """Read only explicit provider reasoning fields, preferring one representation."""
    for key in ("reasoning_content", "reasoning", "thinking"):
        value = delta.get(key)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, list):
            text = "".join(
                block.get("text", block.get("thinking", ""))
                for block in value if isinstance(block, dict)
                and isinstance(block.get("text", block.get("thinking", "")), str)
            )
            if text:
                return text
    return "".join(
        block["text"] for block in delta.get("reasoning_details", []) or []
        if isinstance(block, dict) and block.get("type") in ("reasoning.text", "thinking", "reasoning")
        and isinstance(block.get("text"), str)
    )


class ProviderTextStream:
    """Separate explicit <think> blocks even when a tag spans network chunks.

    Only a leading think block is recognized, so quoted tags inside final JSON
    remain business content. No ordinary answer text is relabelled as reasoning.
    """

    def __init__(self) -> None:
        self._pending = ""
        self._mode = "prefix"

    def feed(self, content: str) -> tuple[str, str]:
        self._pending += content
        if self._mode == "content":
            text, self._pending = self._pending, ""
            return text, ""
        if self._mode == "prefix":
            candidate = self._pending.lstrip()
            if "<think>".startswith(candidate):
                return "", ""
            if candidate.startswith("<think>"):
                self._pending = candidate[len("<think>"):]
                self._mode = "thinking"
            else:
                self._mode = "content"
                return self.feed("")
        marker = "</think>"
        if marker in self._pending:
            thought, text = self._pending.split(marker, 1)
            self._pending = ""
            self._mode = "content"
            return text, thought
        # Retain a possible partial closing tag until the next chunk arrives.
        keep = next((size for size in range(len(marker) - 1, 0, -1)
                     if self._pending.endswith(marker[:size])), 0)
        text = self._pending[:-keep] if keep else self._pending
        self._pending = self._pending[-keep:] if keep else ""
        return "", text

    def finish(self) -> tuple[str, str]:
        text, self._pending = self._pending, ""
        return ("", text) if self._mode == "thinking" else (text, "")


async def create_chat_completion(
    client: OpenAICompatibleClient,
    request: dict[str, Any],
    on_reasoning: Callable[[str], None] | None = None,
) -> ChatCompletionResult:
    try:
        extra_headers = {"Authorization": Omit()} if client.omit_authorization else None
        raw_response = await client.sdk.chat.completions.with_raw_response.create(
            **request,
            extra_headers=extra_headers,
        )
        completion = raw_response.parse()
        parser = ProviderTextStream()
        if request.get("stream") and "text/event-stream" in raw_response.headers.get("content-type", ""):
            content_parts: list[str] = []
            response_id = None
            finish_reason = None
            usage = None
            async with completion:
                async for chunk in completion:
                    response_id = chunk.id or response_id
                    if chunk.usage:
                        usage = chunk.usage.model_dump(mode="json")
                    if not chunk.choices:
                        continue
                    choice = chunk.choices[0]
                    finish_reason = choice.finish_reason or finish_reason
                    delta = choice.delta.model_dump()
                    text, thought = parser.feed(delta.get("content") or "")
                    content_parts.append(text)
                    reasoning = provider_reasoning(delta) or thought
                    if reasoning and on_reasoning:
                        on_reasoning(reasoning)
            text, thought = parser.finish()
            content_parts.append(text)
            if thought and on_reasoning:
                on_reasoning(thought)
            if not finish_reason:
                raise CompatibleModelClientError(
                    "OpenAI-compatible stream ended without a finish reason",
                    status="incomplete", cause_type="IncompleteModelResponse",
                )
            return ChatCompletionResult(
                response_id, raw_response.status_code, finish_reason, usage, "".join(content_parts),
            )
        if request.get("stream"):
            # Some compatible gateways ignore stream=true and return ordinary JSON.
            completion = ChatCompletion.model_validate(json.loads(raw_response.content))
    except APIStatusError as exc:
        raise CompatibleModelClientError(
            "OpenAI-compatible service returned an error",
            status=exc.status_code,
            cause_type=type(exc).__name__,
        ) from exc
    except (APIConnectionError, APITimeoutError, OpenAIError, httpx.TransportError) as exc:
        raise CompatibleModelClientError(
            "OpenAI-compatible service request failed",
            status="unavailable",
            cause_type=type(exc).__name__,
        ) from exc

    if not completion.choices or completion.choices[0].message.content is None:
        raise CompatibleModelClientError(
            "OpenAI-compatible service returned no message content",
            status=raw_response.status_code,
            cause_type="EmptyModelResponse",
        )
    choice = completion.choices[0]
    parser = ProviderTextStream()
    text, thought = parser.feed(choice.message.content)
    tail, remaining_thought = parser.finish()
    reasoning = provider_reasoning(choice.message.model_dump()) or (thought + remaining_thought)
    if reasoning and on_reasoning:
        on_reasoning(reasoning)
    return ChatCompletionResult(
        response_id=completion.id,
        http_status=raw_response.status_code,
        finish_reason=choice.finish_reason,
        usage=completion.usage.model_dump(mode="json") if completion.usage else None,
        content=text + tail,
    )


async def available_model_ids() -> list[str]:
    """Fetch the configured provider's /models using the runtime credentials."""
    from .config import load_runtime_environment, llm_timeout_seconds_from_environment

    load_runtime_environment()
    client = build_openai_compatible_client(
        os.getenv("AGENTIC_CM_LLM_API_KEY"),
        base_url=os.getenv("AGENTIC_CM_LLM_BASE_URL", ""),
        api_key_header=os.getenv("AGENTIC_CM_LLM_API_KEY_HEADER", "Authorization"),
        api_key_prefix=os.getenv("AGENTIC_CM_LLM_API_KEY_PREFIX", "Bearer"),
        timeout_seconds=llm_timeout_seconds_from_environment(),
    )
    try:
        extra_headers = {"Authorization": Omit()} if client.omit_authorization else None
        page = await client.sdk.models.list(extra_headers=extra_headers)
        if not isinstance(page.data, list) or any(
            not isinstance(item.id, str) or not item.id.strip() for item in page.data
        ):
            raise ValueError("Invalid model list")
        return sorted({item.id for item in page.data})
    finally:
        await client.sdk.close()
