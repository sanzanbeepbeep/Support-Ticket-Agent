import json

import pytest

from triage_agent.config import PROJECT_ROOT
from triage_agent.schemas import build_schemas, render

SCHEMA_DIR = PROJECT_ROOT / "schemas"


@pytest.fixture
def schemas(settings):
    return build_schemas(settings)


def test_committed_schemas_match_models(schemas):
    for filename, schema in schemas.items():
        committed = (SCHEMA_DIR / filename).read_text(encoding="utf-8")
        assert committed == render(schema), f"{filename} is stale, run `triage schema`"


def test_tool_definitions_are_strict_openai_functions(schemas):
    tools = schemas["tools.json"]
    assert {tool["name"] for tool in tools} == {
        "get_customer_history", "get_billing_transactions", "check_service_status", "search_knowledge_base"
    }
    for tool in tools:
        assert tool["type"] == "function" and tool["strict"] is True
        assert tool["description"]
        assert tool["parameters"]["additionalProperties"] is False


def test_decision_schema_requires_every_field(schemas):
    decision = schemas["triage_decision.schema.json"]
    assert set(decision["required"]) == set(decision["properties"])
    assert decision["$defs"]["Urgency"]["enum"] == ["critical", "high", "medium", "low"]


def test_tickets_have_the_fields_the_schema_requires(schemas):
    required = set(schemas["ticket.schema.json"]["required"])
    for path in (PROJECT_ROOT / "data" / "tickets").glob("*.json"):
        assert required <= set(json.loads(path.read_text(encoding="utf-8"))), path.name
