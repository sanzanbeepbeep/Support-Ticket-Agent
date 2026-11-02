from dataclasses import dataclass, field
from typing import Any

import pytest

from triage_agent.config import PROJECT_ROOT, Settings
from triage_agent.factory import build_agent
from triage_agent.llm import ConversationItem, LLMError, LLMResponse, ToolCall
from triage_agent.models import (
    NextAction,
    Sentiment,
    SentimentTrend,
    Team,
    Ticket,
    TriageDecision,
    Urgency,
)


def make_decision(**overrides: Any) -> TriageDecision:
    values = dict(
        urgency=Urgency.LOW,
        urgency_reason="test",
        product_area="test",
        issue_types=["how_to"],
        sentiment=Sentiment.NEUTRAL,
        sentiment_trend=SentimentTrend.STABLE,
        language="en",
        key_facts=[],
        kb_article_ids=[],
        next_action=NextAction.ROUTE_TO_SPECIALIST,
        route_to=Team.TIER2_SUPPORT,
        action_reason="test",
        customer_reply="Hello",
        internal_note="note",
        confidence=0.9,
    )
    return TriageDecision(**(values | overrides))


def tool_call(name: str, arguments: str, call_id: str = "call_1") -> ToolCall:
    return ToolCall(call_id=call_id, name=name, arguments=arguments)


@dataclass
class FakeLLM:
    """Replays scripted responses and records every request, so tests can assert on the agent loop."""

    script: list[LLMResponse | Exception]
    model: str = "fake-model"
    requests: list[dict[str, Any]] = field(default_factory=list)

    def respond(self, instructions, conversation: list[ConversationItem], tools, output_type, allow_tool_calls=True):
        self.requests.append({"conversation": list(conversation), "allow_tool_calls": allow_tool_calls})
        if not self.script:
            raise LLMError("script exhausted")
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step


@pytest.fixture
def settings() -> Settings:
    return Settings(openai_api_key=None, data_dir=PROJECT_ROOT / "data", max_tool_iterations=4, required_tools=())


@pytest.fixture
def make_agent(settings):
    def _make(script: list[LLMResponse | Exception]):
        llm = FakeLLM(script)
        return build_agent(settings, llm=llm), llm

    return _make


def load_ticket(name: str) -> Ticket:
    return Ticket.model_validate_json((PROJECT_ROOT / "data" / "tickets" / name).read_text(encoding="utf-8"))


@pytest.fixture
def billing_ticket() -> Ticket:
    return load_ticket("ticket_1_billing.json")


@pytest.fixture
def outage_ticket() -> Ticket:
    return load_ticket("ticket_2_outage_th.json")


@pytest.fixture
def dark_mode_ticket() -> Ticket:
    return load_ticket("ticket_3_dark_mode.json")
