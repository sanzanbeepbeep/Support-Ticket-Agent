"""LLM client abstraction.

The agent talks to `LLMClient`, a tiny protocol. `OpenAIClient` implements it with the Responses API
(function calling + structured output). Tests use a scripted fake, and any OpenAI-compatible server
can be targeted through `OPENAI_BASE_URL`.
"""

from dataclasses import dataclass, field
from typing import Protocol

import openai
from pydantic import BaseModel, ValidationError

from triage_agent.config import Settings
from triage_agent.tools import ToolSpec


class LLMError(RuntimeError):
    """Raised when the model cannot produce a usable response."""


@dataclass(frozen=True)
class ToolCall:
    call_id: str
    name: str
    arguments: str  # raw JSON string, validated by the tool registry


@dataclass(frozen=True)
class ToolOutput:
    call_id: str
    output: str  # JSON string


# A conversation is the user's ticket followed by alternating tool calls / tool outputs.
ConversationItem = str | ToolCall | ToolOutput


@dataclass
class LLMResponse[T: BaseModel]:
    tool_calls: list[ToolCall] = field(default_factory=list)
    parsed: T | None = None
    input_tokens: int = 0
    output_tokens: int = 0


class LLMClient(Protocol):
    model: str

    def respond[T: BaseModel](
        self,
        instructions: str,
        conversation: list[ConversationItem],
        tools: list[ToolSpec],
        output_type: type[T],
        allow_tool_calls: bool = True,
    ) -> LLMResponse[T]:
        """Either request tool calls or return the final structured output.

        `allow_tool_calls=False` forces the model to answer with `output_type` now.
        """
        ...


class OpenAIClient:
    def __init__(self, settings: Settings) -> None:
        if not settings.openai_api_key:
            raise LLMError("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
        self.model = settings.openai_model
        self._temperature = settings.openai_temperature
        self._client = openai.OpenAI(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            max_retries=settings.openai_max_retries,
            timeout=settings.openai_timeout_seconds,
        )

    def respond[T: BaseModel](
        self,
        instructions: str,
        conversation: list[ConversationItem],
        tools: list[ToolSpec],
        output_type: type[T],
        allow_tool_calls: bool = True,
    ) -> LLMResponse[T]:
        optional = {"temperature": self._temperature} if self._temperature is not None else {}
        try:
            response = self._client.responses.parse(
                model=self.model,
                instructions=instructions,
                input=[_to_input_item(item) for item in conversation],
                tools=[_to_function_tool(spec) for spec in tools],
                tool_choice="auto" if allow_tool_calls else "none",
                text_format=output_type,
                **optional,
            )
        except (openai.OpenAIError, ValidationError) as exc:
            raise LLMError(f"OpenAI request failed: {exc}") from exc

        tool_calls = [
            ToolCall(call_id=item.call_id, name=item.name, arguments=item.arguments)
            for item in response.output
            if item.type == "function_call"
        ]
        parsed = None if tool_calls else response.output_parsed
        if not tool_calls and parsed is None:
            raise LLMError("Model returned neither tool calls nor a parsable decision (possible refusal).")

        usage = response.usage
        return LLMResponse(
            tool_calls=tool_calls,
            parsed=parsed,
            input_tokens=usage.input_tokens if usage else 0,
            output_tokens=usage.output_tokens if usage else 0,
        )


def _to_function_tool(spec: ToolSpec) -> dict:
    return {
        "type": "function",
        "name": spec.name,
        "description": spec.description,
        "parameters": spec.parameters,
        "strict": True,
    }


def _to_input_item(item: ConversationItem) -> dict:
    match item:
        case str():
            return {"role": "user", "content": item}
        case ToolCall():
            return {"type": "function_call", "call_id": item.call_id, "name": item.name, "arguments": item.arguments}
        case ToolOutput():
            return {"type": "function_call_output", "call_id": item.call_id, "output": item.output}
    raise TypeError(f"Unsupported conversation item: {item!r}")
