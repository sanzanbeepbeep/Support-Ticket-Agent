"""Thai-language coverage: Thai tickets must flow through rendering, guardrails, tools, API and scoring unchanged."""

import json

import pytest
from fastapi.testclient import TestClient

from triage_agent.api import app, get_agent
from triage_agent.evaluation import Expectation, score_result
from triage_agent.knowledge_base import KnowledgeBase
from triage_agent.llm import LLMResponse
from triage_agent.models import AgentTrace, Message, NextAction, Team, ToolCallRecord, TriageResult, Urgency
from triage_agent.policy import PolicyContext, default_policy

from tests.conftest import load_ticket, make_decision, tool_call

policy = default_policy(auto_respond_min_confidence=0.6)
KB_SEARCH = ToolCallRecord(
    name="search_knowledge_base", arguments={}, output={"results": [{"id": "KB-012"}]}, duration_ms=1.0
)


@pytest.fixture
def deletion_ticket():
    return load_ticket("ticket_6_account_deletion_th.json")


def with_messages(ticket, *texts: str):
    messages = [Message(minutes_ago=10 * (len(texts) - i), text=text) for i, text in enumerate(texts)]
    return ticket.model_copy(update={"messages": messages})


# --------------------------------------------------------------------------- rendering / agent loop


def test_thai_ticket_text_is_rendered_verbatim(make_agent, outage_ticket):
    agent, llm = make_agent([LLMResponse(parsed=make_decision(language="th"))])

    result = agent.triage(outage_ticket)

    rendered = llm.requests[0]["conversation"][0]
    for message in outage_ticket.messages:
        assert message.text in rendered
    # Oldest message first, newest last.
    assert rendered.index("ระบบเข้าไม่ได้ครับ") < rendered.index("เช็ค status.company.com")
    assert result.decision.language == "th"


def test_thai_reply_survives_tool_loop_and_policy(make_agent, deletion_ticket):
    reply = "สวัสดีค่ะ คุณสามารถลบบัญชีได้ที่ Settings > Account > Delete account ข้อมูลจะถูกลบภายใน 30 วันค่ะ"
    agent, _ = make_agent([
        LLMResponse(tool_calls=[tool_call("search_knowledge_base", '{"query": "delete account personal data"}')]),
        LLMResponse(parsed=make_decision(
            language="th", issue_types=["account"], kb_article_ids=["KB-012"],
            next_action=NextAction.ROUTE_TO_SPECIALIST, route_to=Team.ACCOUNT_MANAGEMENT, customer_reply=reply,
        )),
    ])

    result = agent.triage(deletion_ticket)

    assert result.decision.customer_reply == reply
    assert result.decision.kb_article_ids == ["KB-012"]
    assert not result.used_fallback


# --------------------------------------------------------------------------- guardrails


@pytest.mark.parametrize(
    "text",
    [
        "โดนตัดเงินซ้ำสองรอบ ถ้าไม่คืนเงินจะแจ้งธนาคารให้ยกเลิกรายการ",
        "ถ้ายังไม่แก้ไขจะฟ้องร้องบริษัทครับ",
        "ผมปรึกษาทนายแล้ว จะดำเนินคดีตามกฎหมาย",
        "จะแจ้ง chargeback กับบัตรเครดิตค่ะ",
    ],
)
def test_thai_dispute_threat_escalates_to_billing(billing_ticket, text):
    ticket = with_messages(billing_ticket, text)
    decision = make_decision(urgency=Urgency.MEDIUM, issue_types=["billing"], language="th")

    final, overrides = policy.apply(decision, PolicyContext(ticket, []))

    assert (final.urgency, final.next_action, final.route_to) == (
        Urgency.HIGH, NextAction.ESCALATE_TO_HUMAN, Team.BILLING
    )
    assert {o.rule for o in overrides} == {"financial_risk"}


def test_polite_thai_billing_question_is_not_a_dispute(billing_ticket):
    ticket = with_messages(billing_ticket, "สอบถามเรื่องใบแจ้งหนี้เดือนนี้ค่ะ ขอบคุณค่ะ")
    decision = make_decision(issue_types=["billing"], language="th")

    _, overrides = policy.apply(decision, PolicyContext(ticket, []))

    assert all(o.rule != "financial_risk" for o in overrides)


@pytest.mark.parametrize(
    "reply",
    [
        "เราได้อนุมัติการคืนเงินให้คุณแล้วค่ะ",
        "คุณจะได้รับเงินคืนเต็มจำนวนค่ะ",
        "เรารับประกันว่าปัญหานี้จะได้รับการแก้ไข",
        "ทีมงานจะแก้ไขให้ภายใน 2 ชั่วโมงครับ",
        "ที่นั่งใหม่จะพร้อมใช้งานภายในวันพรุ่งนี้ค่ะ",
    ],
)
def test_thai_auto_reply_with_commitment_goes_to_human_review(deletion_ticket, reply):
    decision = make_decision(
        next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-012"],
        language="th", customer_reply=reply,
    )

    final, overrides = policy.apply(decision, PolicyContext(deletion_ticket, [KB_SEARCH]))

    assert final.next_action == NextAction.ROUTE_TO_SPECIALIST
    assert "commitment" in overrides[0].reason


def test_grounded_thai_auto_reply_without_commitment_is_kept(deletion_ticket):
    reply = "สวัสดีค่ะ คุณสามารถลบบัญชีได้เองที่ Settings > Account > Delete account ค่ะ"
    decision = make_decision(
        next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-012"],
        language="th", customer_reply=reply,
    )

    final, overrides = policy.apply(decision, PolicyContext(deletion_ticket, [KB_SEARCH]))

    assert final.next_action == NextAction.AUTO_RESPOND
    assert overrides == []


# --------------------------------------------------------------------------- knowledge base


@pytest.fixture
def kb(settings):
    return KnowledgeBase.from_directory(settings.data_dir / "kb")


@pytest.mark.parametrize(
    ("translated_query", "expected_id"),
    [
        # English queries the model is instructed to write for the Thai sample tickets.
        ("error 500 cannot access all browsers", "KB-006"),
        ("status page operational but asia region not working", "KB-007"),
        ("delete account and personal data how long", "KB-012"),
    ],
)
def test_translated_queries_for_thai_tickets_hit_the_right_article(kb, translated_query, expected_id):
    assert kb.search(translated_query)[0].article.id == expected_id


def test_untranslated_thai_query_returns_no_hits(kb):
    # The tokenizer is ASCII-only, which is why the prompt and tool schema require English queries.
    assert kb.search("ต้องการลบบัญชีและข้อมูลส่วนตัว") == []


# --------------------------------------------------------------------------- API / evaluation


def test_api_round_trips_thai_text(make_agent, deletion_ticket):
    reply = "สวัสดีค่ะ ทีมงานจะติดต่อกลับเพื่อยืนยันตัวตนก่อนลบบัญชีค่ะ"
    agent, llm = make_agent([LLMResponse(parsed=make_decision(language="th", customer_reply=reply))])
    app.dependency_overrides[get_agent] = lambda: agent
    try:
        response = TestClient(app).post(
            "/triage",
            content=json.dumps(deletion_ticket.model_dump(mode="json"), ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["decision"]["customer_reply"] == reply
    assert "ต้องการลบบัญชี" in llm.requests[0]["conversation"][0]


@pytest.mark.parametrize(("language", "passes"), [("th", True), ("en", False)])
def test_eval_checks_reply_language_for_thai_tickets(language, passes):
    expected = Expectation(urgency=[Urgency.LOW], next_action=[NextAction.ROUTE_TO_SPECIALIST], language="th")
    result = TriageResult(
        ticket_id="T-1006", decision=make_decision(language=language), trace=AgentTrace(model="m", prompt_version="p")
    )

    score = score_result("thai", 1, result, expected)

    assert score.passed is passes
