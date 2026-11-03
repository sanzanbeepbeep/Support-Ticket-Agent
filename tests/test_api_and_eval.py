from fastapi.testclient import TestClient

from triage_agent import api, cli
from triage_agent.api import app, get_agent
from triage_agent.config import PROJECT_ROOT
from triage_agent.evaluation import Expectation, load_cases, score_result
from triage_agent.llm import LLMError, LLMResponse
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


def test_triage_endpoint_returns_503_when_agent_cannot_start(monkeypatch, dark_mode_ticket):
    def broken():
        raise LLMError("OPENAI_API_KEY is not set.")

    monkeypatch.setattr(api, "build_agent", broken)
    api._cached_agent.cache_clear()
    try:
        response = TestClient(app).post("/triage", json=dark_mode_ticket.model_dump(mode="json"))
    finally:
        api._cached_agent.cache_clear()

    assert response.status_code == 503
    assert "OPENAI_API_KEY" in response.json()["detail"]


def test_cli_reports_bad_ticket_files_before_calling_the_model(monkeypatch, tmp_path, capsys):
    def must_not_build():
        raise AssertionError("agent built despite invalid input")

    monkeypatch.setattr(cli, "build_agent", must_not_build)
    bad = tmp_path / "bad.json"
    bad.write_text('{"ticket_id": "x"}', encoding="utf-8")

    exit_code = cli.main(["run", str(bad), str(tmp_path / "missing.json")])

    err = capsys.readouterr().err
    assert exit_code == 2
    assert "bad.json: not a valid ticket" in err and "missing.json: cannot read file" in err
