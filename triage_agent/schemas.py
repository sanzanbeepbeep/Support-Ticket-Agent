"""Export the JSON Schemas of the agent's contracts.

The Pydantic models are the single source of truth. The files in `schemas/` are generated from them
(`triage schema`), and a test fails if the committed files drift from the code.
"""

import json
from pathlib import Path
from typing import Any

from triage_agent.config import Settings
from triage_agent.factory import build_tools
from triage_agent.llm import to_function_tool
from triage_agent.models import Ticket, TriageDecision, TriageResult


def build_schemas(settings: Settings) -> dict[str, Any]:
    return {
        "ticket.schema.json": Ticket.model_json_schema(),
        "triage_decision.schema.json": TriageDecision.model_json_schema(),
        "triage_result.schema.json": TriageResult.model_json_schema(),
        "tools.json": [to_function_tool(spec) for spec in build_tools(settings).specs()],
    }


def render(schema: Any) -> str:
    return json.dumps(schema, indent=2, ensure_ascii=False) + "\n"


def export_schemas(settings: Settings, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    written = []
    for filename, schema in build_schemas(settings).items():
        path = directory / filename
        path.write_text(render(schema), encoding="utf-8")
        written.append(path)
    return written
