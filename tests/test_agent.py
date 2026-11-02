import json

import pytest

from triage_agent.factory import build_agent
from triage_agent.llm import LLMError, LLMResponse, ToolCall, ToolOutput
from triage_agent.models import NextAction, Team, Urgency

from tests.conftest import FakeLLM, make_decision, tool_call


def test_agent_runs_tools_then_returns_decision(make_agent, billing_ticket):
    agent, llm = make_agent([
        LLMResponse(tool_calls=[
            tool_call("get_customer_history", '{"customer_id": "C-1001"}', "c1"),
            tool_call("get_billing_transactions", '{"customer_id": "C-1001"}', "c2"),
        ], input_tokens=100, output_tokens=20),
        LLMResponse(parsed=make_decision(urgency=Urgency.CRITICAL, issue_types=["billing"],
                                         next_action=NextAction.ESCALATE_TO_HUMAN, route_to=Team.BILLING),
                    input_tokens=300, output_tokens=200),
    ])

    result = agent.triage(billing_ticket)

    assert result.decision.urgency == Urgency.CRITICAL
    assert [call.name for call in result.trace.tool_calls] == ["get_customer_history", "get_billing_transactions"]
    assert (result.trace.input_tokens, result.trace.output_tokens, result.trace.iterations) == (400, 220, 2)
    assert not result.used_fallback

    # The second request carries the tool calls and their outputs back to the model.
    second_conversation = llm.requests[1]["conversation"]
    outputs = [item for item in second_conversation if isinstance(item, ToolOutput)]
    assert [o.call_id for o in outputs] == ["c1", "c2"]
    assert json.loads(outputs[1].output)["possible_duplicate_charges"] == 2


def test_ticket_is_rendered_as_delimited_data(make_agent, outage_ticket):
    agent, llm = make_agent([LLMResponse(parsed=make_decision())])
    agent.triage(outage_ticket)

    rendered = llm.requests[0]["conversation"][0]
    assert rendered.startswith('<ticket id="T-1002">') and rendered.endswith("</ticket>")
    assert "error 500" in rendered and "2 hours ago" in rendered


def test_last_iteration_forbids_tool_calls(make_agent, dark_mode_ticket):
    looping_call = LLMResponse(tool_calls=[tool_call("get_customer_history", '{"customer_id": "C-3003"}')])
    agent, llm = make_agent([looping_call] * 3 + [LLMResponse(parsed=make_decision())])  # max_iterations=4

    result = agent.triage(dark_mode_ticket)

    assert [r["allow_tool_calls"] for r in llm.requests] == [True, True, True, False]
    assert result.trace.iterations == 4
    assert not result.used_fallback


def test_llm_failure_falls_back_to_human_escalation(make_agent, billing_ticket):
    agent, _ = make_agent([LLMError("rate limited")])

    result = agent.triage(billing_ticket)

    assert result.used_fallback
    assert result.error == "rate limited"
    assert result.decision.next_action == NextAction.ESCALATE_TO_HUMAN
    assert result.decision.confidence == 0.0
    # Policy still runs on the fallback: the dispute threat in the text routes it to billing.
    assert result.decision.route_to == Team.BILLING


def test_agent_is_sent_back_when_required_tools_were_skipped(settings, dark_mode_ticket):
    llm = FakeLLM([
        LLMResponse(parsed=make_decision()),  # decides without investigating
        LLMResponse(tool_calls=[
            tool_call("get_customer_history", '{"customer_id": "C-3003"}', "c1"),
            tool_call("search_knowledge_base", '{"query": "dark mode"}', "c2"),
        ]),
        LLMResponse(parsed=make_decision(kb_article_ids=["KB-004"])),
    ])
    strict_settings = settings.model_copy(update={"required_tools": ("get_customer_history", "search_knowledge_base")})

    result = build_agent(strict_settings, llm=llm).triage(dark_mode_ticket)

    reminder = llm.requests[1]["conversation"][-1]
    assert isinstance(reminder, str) and "get_customer_history, search_knowledge_base" in reminder
    assert result.trace.tool_names() == {"get_customer_history", "search_knowledge_base"}
    assert result.decision.kb_article_ids == ["KB-004"]
    assert not result.used_fallback


def test_unknown_required_tool_is_rejected_at_startup(settings):
    with pytest.raises(ValueError, match="not registered"):
        build_agent(settings.model_copy(update={"required_tools": ("send_email",)}), llm=FakeLLM([]))


def test_bad_tool_arguments_are_reported_to_model_not_raised(make_agent, dark_mode_ticket):
    agent, llm = make_agent([
        LLMResponse(tool_calls=[ToolCall("c1", "check_service_status", '{"region": "moon"}')]),
        LLMResponse(parsed=make_decision()),
    ])

    result = agent.triage(dark_mode_ticket)

    assert result.trace.tool_calls[0].is_error
    error_output = llm.requests[1]["conversation"][-1]
    assert "error" in json.loads(error_output.output)
