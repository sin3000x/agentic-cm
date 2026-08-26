"""Shared runtime for the Orchestrator, Path, and Synthesis Agent adapters.

Each agent used to carry its own copy of the same OpenAI-compatible skeleton:
build a request, emit a trace event, call the model, validate with Pydantic,
and retry once on invalid structure. The copies had drifted — only the
Orchestrator retried transient network failures — so this module owns the
single implementation and every adapter gets the same guarantees.

Agent-specific behavior stays with the agent: its prompt, its Pydantic schema,
its result mapping, and its cross-context validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable, Protocol, TypeVar

from pydantic import BaseModel, ValidationError

from .config import ReasoningEffort
from .llm import CompatibleModelClientError, OpenAICompatibleClient, create_chat_completion


_CHINESE_CHARACTER = re.compile(r"[一-鿿]")

TResult = TypeVar("TResult")
TPayload = TypeVar("TPayload", bound=BaseModel)


def contains_chinese(value: str) -> bool:
    """Whether `value` holds at least one Han character."""
    return bool(_CHINESE_CHARACTER.search(value))


class AgentTraceSink(Protocol):
    def __call__(
        self,
        step: str,
        status: str,
        summary: str,
        details: dict[str, Any] | None = None,
    ) -> None: ...


@dataclass(frozen=True)
class TraceNarration:
    """Human-facing trace copy for one agent's model exchange."""

    request: str
    repair_request: str
    retry_request: str
    response: str
    validation_failed: str
    request_failed: str


@dataclass(frozen=True)
class ModelEndpoint:
    """Connection details an adapter reports into its audit trail.

    The credential itself is never traced, only whether one was present.
    """

    client: OpenAICompatibleClient
    base_url: str
    api_key_header: str
    api_key_present: bool

    def authentication_details(self) -> dict[str, Any]:
        return {
            "header": self.api_key_header,
            "credential_present": self.api_key_present,
            "credential_value_logged": False,
        }


def configure_thinking(
    request: dict[str, Any],
    *,
    enabled: bool,
    reasoning_effort: ReasoningEffort,
) -> None:
    """Add explicit thinking controls to a Chat Completions request."""
    request["extra_body"] = {
        "thinking": {"type": "enabled" if enabled else "disabled"},
    }
    if enabled:
        request["reasoning_effort"] = reasoning_effort


async def request_structured_output(
    endpoint: ModelEndpoint,
    request: dict[str, Any],
    *,
    agent_label: str,
    trace: AgentTraceSink,
    step_prefix: str,
    narration: TraceNarration,
    payload_model: type[TPayload],
    build_result: Callable[[TPayload], TResult],
    repair_instruction: Callable[[Exception], str],
    execution_error: Callable[[str], Exception],
    output_error: Callable[[str], Exception],
    recoverable_output_errors: tuple[type[Exception], ...] = (),
) -> TResult:
    """Call the model until it returns output the caller accepts.

    Retries once for a transient connection failure and once more for output
    that fails validation, then fails closed. `build_result` may raise any of
    `recoverable_output_errors` to reject semantically invalid output and
    trigger the same repair path as a schema violation.

    `request` is mutated in place when a repair instruction is appended, so the
    caller sees exactly what was sent in the trace.
    """
    validation_failures: tuple[type[Exception], ...] = (ValidationError,) + recoverable_output_errors
    last_error: Exception | None = None
    request_attempt = 0

    for schema_attempt in range(2):
        response = None
        for network_attempt in range(2):
            request_attempt += 1
            is_network_retry = network_attempt == 1
            if is_network_retry:
                step, summary = f"{step_prefix}.retry_request", narration.retry_request
            elif schema_attempt == 0:
                step, summary = f"{step_prefix}.request", narration.request
            else:
                step, summary = f"{step_prefix}.repair_request", narration.repair_request
            trace(
                step,
                "STARTED",
                summary,
                {
                    "attempt": request_attempt,
                    "schema_attempt": schema_attempt + 1,
                    "network_attempt": network_attempt + 1,
                    "endpoint": f"{endpoint.base_url}/chat/completions",
                    "request": request,
                    "authentication": endpoint.authentication_details(),
                },
            )
            try:
                response = await create_chat_completion(endpoint.client, request)
                break
            except CompatibleModelClientError as exc:
                will_retry = exc.status == "unavailable" and network_attempt == 0
                trace(
                    f"{step_prefix}.request",
                    "FAILED",
                    narration.request_failed,
                    {
                        "attempt": request_attempt,
                        "http_status": exc.status,
                        "error_type": exc.cause_type,
                        "will_retry": will_retry,
                    },
                )
                if will_retry:
                    continue
                raise execution_error(
                    f"{agent_label} model request failed (status={exc.status})"
                ) from exc

        if response is None:
            raise execution_error(f"{agent_label} model request failed without a response")

        trace(
            f"{step_prefix}.response",
            "COMPLETED",
            narration.response,
            {
                "attempt": request_attempt,
                "http_status": response.http_status,
                "response_id": response.response_id,
                "finish_reason": response.finish_reason,
                "usage": response.usage,
                "content": response.content,
            },
        )
        try:
            return build_result(payload_model.model_validate_json(response.content))
        except validation_failures as exc:
            last_error = exc
            trace(
                f"{step_prefix}.response_validation",
                "FAILED",
                narration.validation_failed,
                {
                    "attempt": request_attempt,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                },
            )
            if schema_attempt == 0:
                request["messages"].append(
                    {"role": "system", "content": repair_instruction(exc)}
                )

    raise output_error(
        f"{agent_label} returned invalid structured output after one repair: {last_error}"
    ) from last_error
