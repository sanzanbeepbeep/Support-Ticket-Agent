import json

import pytest

from triage_agent.factory import build_tools
from triage_agent.knowledge_base import KnowledgeBase
from triage_agent.tools.billing import count_possible_duplicates


@pytest.fixture
def registry(settings):
    return build_tools(settings)


@pytest.fixture
def kb(settings):
    return KnowledgeBase.from_directory(settings.data_dir / "kb")


def test_tool_schemas_are_strict_compatible(registry):
    for spec in registry.specs():
        params = spec.parameters
        assert params["type"] == "object"
        assert params["additionalProperties"] is False
        assert set(params["required"]) == set(params["properties"]), f"{spec.name}: all fields must be required"


def test_customer_history_found_and_missing(registry):
    found = registry.execute("get_customer_history", json.dumps({"customer_id": "C-2002"}))
    assert found.output["found"] is True
    assert found.output["plan"] == "enterprise"

    missing = registry.execute("get_customer_history", json.dumps({"customer_id": "nope"}))
    assert missing.output == {"found": False, "customer_id": "nope"}


def test_billing_detects_duplicate_charges(registry):
    record = registry.execute("get_billing_transactions", json.dumps({"customer_id": "C-1001"}))
    assert record.output["possible_duplicate_charges"] == 2
    assert len(record.output["transactions"]) == 3


def test_count_possible_duplicates_ignores_refunded():
    transactions = [
        {"amount": 10, "description": "x", "status": "captured"},
        {"amount": 10, "description": "x", "status": "refunded"},
    ]
    assert count_possible_duplicates(transactions) == 0


def test_service_status_reports_regional_incident(registry):
    asia = registry.execute("check_service_status", json.dumps({"region": "asia"}))
    europe = registry.execute("check_service_status", json.dumps({"region": "europe"}))
    north_america = registry.execute("check_service_status", json.dumps({"region": "north_america"}))
    assert asia.output["overall_status"] == "degraded"
    assert asia.output["active_incidents"][0]["id"] == "INC-4821"
    # Europe has one incident still being monitored and one resolved; only the open one counts.
    assert [i["id"] for i in europe.output["active_incidents"]] == ["INC-4815"]
    assert north_america.output["overall_status"] == "operational"


@pytest.mark.parametrize(
    ("query", "expected_id"),
    [
        ("payment failed upgrade pro charged still free plan", "KB-001"),
        ("chargeback dispute duplicate charges refund", "KB-002"),
        ("dark mode system default macos not working", "KB-004"),
        ("error 500 cannot access multiple browsers", "KB-006"),
        ("status page says operational but asia region down", "KB-007"),
        ("how to log out", "KB-009"),
        ("cancel annual plan refund", "KB-011"),
        ("delete account personal data", "KB-012"),
        ("csv import error IMP-413 file too large", "KB-013"),
        ("add seats enterprise contract invoice currency", "KB-014"),
    ],
)
def test_knowledge_base_top_hit(kb, query, expected_id):
    assert kb.search(query)[0].article.id == expected_id


def test_knowledge_base_returns_nothing_for_unrelated_query(kb):
    assert kb.search("quantum entanglement recipe") == []


def test_registry_returns_errors_instead_of_raising(registry):
    unknown = registry.execute("delete_everything", "{}")
    bad_json = registry.execute("get_customer_history", "{not json")
    bad_args = registry.execute("check_service_status", json.dumps({"region": "mars"}))
    for record in (unknown, bad_json, bad_args):
        assert record.is_error
        assert "error" in record.output
