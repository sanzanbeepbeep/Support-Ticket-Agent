"""Tool abstraction and registry.

Adding a tool = subclass `Tool`, declare a Pydantic args model, implement `run`, and register it.
The JSON schema sent to the LLM is generated from the args model, so schema and validation never drift.
"""

import json
import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from pydantic import BaseModel, ValidationError

from triage_agent.models import ToolCallRecord

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    """Provider-neutral description of a tool, translated to the vendor format by the LLM client."""

    name: str
    description: str
    parameters: dict[str, Any]


class Tool(ABC):
    name: ClassVar[str]
    description: ClassVar[str]
    args_model: ClassVar[type[BaseModel]]

    @abstractmethod
    def run(self, args: BaseModel) -> dict[str, Any]:
        """Execute the tool. Must return a JSON-serialisable dict."""

    def spec(self) -> ToolSpec:
        return ToolSpec(self.name, self.description, self.args_model.model_json_schema())


class ToolRegistry:
    def __init__(self, tools: list[Tool]) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Tool names must be unique")

    @property
    def names(self) -> list[str]:
        return list(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [tool.spec() for tool in self._tools.values()]

    def execute(self, name: str, raw_arguments: str) -> ToolCallRecord:
        """Run a tool call from the LLM. Never raises: errors are returned to the model as data."""
        started = time.perf_counter()
        arguments: dict[str, Any] = {}
        try:
            arguments = json.loads(raw_arguments or "{}")
            tool = self._tools.get(name)
            if tool is None:
                raise LookupError(f"Unknown tool '{name}'. Available: {', '.join(self.names)}")
            output = tool.run(tool.args_model.model_validate(arguments))
            is_error = False
        except (json.JSONDecodeError, ValidationError, LookupError) as exc:
            output, is_error = {"error": str(exc)}, True
        except Exception as exc:  # a broken backend must not crash the whole triage
            logger.exception("Tool %s failed", name)
            output, is_error = {"error": f"Tool failed: {exc.__class__.__name__}"}, True

        return ToolCallRecord(
            name=name,
            arguments=arguments if isinstance(arguments, dict) else {"raw": raw_arguments},
            output=output,
            is_error=is_error,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
