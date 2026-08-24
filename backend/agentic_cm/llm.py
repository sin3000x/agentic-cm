from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit

import httpx
from openai import APIConnectionError, APIStatusError, APITimeoutError, AsyncOpenAI, Omit, OpenAIError


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
    timeout_seconds: float = 45.0,
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


async def create_chat_completion(
    client: OpenAICompatibleClient,
    request: dict[str, Any],
) -> ChatCompletionResult:
    try:
        extra_headers = {"Authorization": Omit()} if client.omit_authorization else None
        raw_response = await client.sdk.chat.completions.with_raw_response.create(
            **request,
            extra_headers=extra_headers,
        )
        completion = raw_response.parse()
    except APIStatusError as exc:
        raise CompatibleModelClientError(
            "OpenAI-compatible service returned an error",
            status=exc.status_code,
            cause_type=type(exc).__name__,
        ) from exc
    except (APIConnectionError, APITimeoutError, OpenAIError) as exc:
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
    return ChatCompletionResult(
        response_id=completion.id,
        http_status=raw_response.status_code,
        finish_reason=choice.finish_reason,
        usage=completion.usage.model_dump(mode="json") if completion.usage else None,
        content=choice.message.content,
    )
