from fastapi.testclient import TestClient

from triage_agent.api import app, get_agent
from triage_agent.config import PROJECT_ROOT
from triage_agent.evaluation import Expectation, load_cases, score_result
from triage_agent.llm import LLMResponse
from triage_agent.models import AgentTrace, NextAction, TriageResult, Urgency

from tests.conftest import make_decision


def test_triage_endpoint(make_agent, dark_mode_ticket):
    agent, _ = make_agent([LLMResponse(parsed=make_decision())])
    app.dependency_overrides[get_agent] = lambda: agent
    try:
        response = TestClient(app).post("/triage", json=dark_mode_ticket.model_dump(mode="json"))
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ticket_id"] == "T-1003"
    assert body["decision"]["urgency"] == "low"


def test_triage_endpoint_rejects_invalid_ticket(make_agent):
    agent, _ = make_agent([])
    app.dependency_overrides[get_agent] = lambda: agent
    try:
        response = TestClient(app).post("/triage", json={"ticket_id": "x"})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422


def _result(**decision_overrides) -> TriageResult:
    return TriageResult(
        ticket_id="T",
        decision=make_decision(**decision_overrides),
        trace=AgentTrace(model="m", prompt_version="p"),
    )


def test_score_flags_under_triage():
    expected = Expectation(urgency=[Urgency.CRITICAL], next_action=[NextAction.ESCALATE_TO_HUMAN])
    score = score_result("case", 1, _result(urgency=Urgency.MEDIUM), expected)

    assert score.under_triaged
    assert not score.passed
    assert score.checks["urgency"] is False


def test_score_accepts_any_listed_value():
    expected = Expectation(
        urgency=[Urgency.LOW, Urgency.MEDIUM],
        next_action=[NextAction.ROUTE_TO_SPECIALIST],
        issue_types=["how_to"],
        language="en",
    )
    score = score_result("case", 1, _result(urgency=Urgency.MEDIUM), expected)

    assert score.passed
    assert not score.under_triaged


def test_golden_set_is_valid_and_tickets_load():
    cases = load_cases(PROJECT_ROOT / "evals" / "golden.json")
    assert len(cases) >= 8
    for case in cases:
        assert case.load_ticket(PROJECT_ROOT).ticket_id
