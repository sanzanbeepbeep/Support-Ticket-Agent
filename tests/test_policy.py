from triage_agent.models import NextAction, Team, ToolCallRecord, Urgency
from triage_agent.policy import PolicyContext, default_policy

from tests.conftest import make_decision

policy = default_policy(auto_respond_min_confidence=0.6)


def record(name: str, output: dict) -> ToolCallRecord:
    return ToolCallRecord(name=name, arguments={}, output=output, duration_ms=1.0)


def test_duplicate_charges_and_dispute_threat_force_critical_billing_escalation(billing_ticket):
    decision = make_decision(urgency=Urgency.HIGH, issue_types=["billing"], next_action=NextAction.ROUTE_TO_SPECIALIST)
    context = PolicyContext(billing_ticket, [record("get_billing_transactions", {"possible_duplicate_charges": 2})])

    final, overrides = policy.apply(decision, context)

    assert final.urgency == Urgency.CRITICAL
    assert final.next_action == NextAction.ESCALATE_TO_HUMAN
    assert final.route_to == Team.BILLING
    assert {o.rule for o in overrides} == {"financial_risk"}


def test_enterprise_outage_goes_to_sre(outage_ticket):
    decision = make_decision(urgency=Urgency.HIGH, issue_types=["outage"], route_to=Team.TIER2_SUPPORT)
    context = PolicyContext(outage_ticket, [record("check_service_status", {"active_incidents": [{"id": "INC-1"}]})])

    final, _ = policy.apply(decision, context)

    assert (final.urgency, final.next_action, final.route_to) == (
        Urgency.CRITICAL, NextAction.ESCALATE_TO_HUMAN, Team.SRE
    )


def test_rules_never_lower_urgency(billing_ticket):
    decision = make_decision(urgency=Urgency.CRITICAL, issue_types=["billing"])
    context = PolicyContext(billing_ticket, [])  # dispute threat only -> rule asks for HIGH

    final, overrides = policy.apply(decision, context)

    assert final.urgency == Urgency.CRITICAL
    assert all(o.field != "urgency" for o in overrides)


def test_hallucinated_kb_citations_are_removed(dark_mode_ticket):
    decision = make_decision(kb_article_ids=["KB-004", "KB-999"])
    context = PolicyContext(dark_mode_ticket, [record("search_knowledge_base", {"results": [{"id": "KB-004"}]})])

    final, _ = policy.apply(decision, context)

    assert final.kb_article_ids == ["KB-004"]


def test_auto_respond_blocked_without_grounding_or_confidence(dark_mode_ticket):
    decision = make_decision(next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=[], confidence=0.4)

    final, overrides = policy.apply(decision, PolicyContext(dark_mode_ticket, []))

    assert final.next_action == NextAction.ROUTE_TO_SPECIALIST
    assert final.route_to == Team.TIER2_SUPPORT
    assert "confidence" in overrides[0].reason and "knowledge-base" in overrides[0].reason


def test_grounded_confident_auto_respond_is_kept(dark_mode_ticket):
    decision = make_decision(next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-004"])
    context = PolicyContext(dark_mode_ticket, [record("search_knowledge_base", {"results": [{"id": "KB-004"}]})])

    final, overrides = policy.apply(decision, context)

    assert final.next_action == NextAction.AUTO_RESPOND
    assert overrides == []
