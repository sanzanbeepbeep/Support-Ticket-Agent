import pytest

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
    incidents = {"active_incidents": [{"id": "INC-1", "severity": "major"}]}
    context = PolicyContext(outage_ticket, [record("check_service_status", incidents)])

    final, _ = policy.apply(decision, context)

    assert (final.urgency, final.next_action, final.route_to) == (
        Urgency.CRITICAL, NextAction.ESCALATE_TO_HUMAN, Team.SRE
    )


def test_minor_incident_does_not_force_escalation_for_non_enterprise(dark_mode_ticket):
    decision = make_decision(urgency=Urgency.MEDIUM, issue_types=["outage"])
    minor = {"active_incidents": [{"id": "INC-2", "severity": "minor"}]}

    final, overrides = policy.apply(decision, PolicyContext(dark_mode_ticket, [record("check_service_status", minor)]))

    assert final.urgency == Urgency.MEDIUM
    assert all(o.rule != "outage" for o in overrides)


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


@pytest.mark.parametrize(
    "reply",
    [
        "Good news: your refund has been approved and you will receive a full refund.",
        "We guarantee this will be fixed.",
        "Your new seats will be ready by Monday.",
        "Our team will resolve this within 2 hours.",
    ],
)
def test_auto_reply_with_commitment_goes_to_human_review(dark_mode_ticket, reply):
    decision = make_decision(
        next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-004"], customer_reply=reply
    )
    context = PolicyContext(dark_mode_ticket, [record("search_knowledge_base", {"results": [{"id": "KB-004"}]})])

    final, overrides = policy.apply(decision, context)

    assert final.next_action == NextAction.ROUTE_TO_SPECIALIST
    assert "commitment" in overrides[0].reason


def test_grounded_confident_auto_respond_is_kept(dark_mode_ticket):
    decision = make_decision(next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-004"])
    context = PolicyContext(dark_mode_ticket, [record("search_knowledge_base", {"results": [{"id": "KB-004"}]})])

    final, overrides = policy.apply(decision, context)

    assert final.next_action == NextAction.AUTO_RESPOND
    assert overrides == []


@pytest.mark.parametrize(
    ("issue_types", "team"),
    [(["account"], Team.ACCOUNT_MANAGEMENT), (["feature_request"], Team.PRODUCT), (["how_to"], Team.TIER2_SUPPORT)],
)
def test_blocked_auto_reply_goes_to_the_team_that_owns_the_issue(dark_mode_ticket, issue_types, team):
    decision = make_decision(
        next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=[], issue_types=issue_types
    )

    final, _ = policy.apply(decision, PolicyContext(dark_mode_ticket, []))

    assert (final.next_action, final.route_to) == (NextAction.ROUTE_TO_SPECIALIST, team)


def test_escalation_without_a_team_gets_one(dark_mode_ticket):
    decision = make_decision(next_action=NextAction.ESCALATE_TO_HUMAN, route_to=None, issue_types=["bug", "billing"])

    final, overrides = policy.apply(decision, PolicyContext(dark_mode_ticket, []))

    assert final.route_to == Team.PRODUCT  # issue_types are ordered most important first
    assert [o.rule for o in overrides] == ["routing_consistency"]


def test_auto_respond_keeps_null_route(dark_mode_ticket):
    decision = make_decision(next_action=NextAction.AUTO_RESPOND, route_to=None, kb_article_ids=["KB-004"])
    context = PolicyContext(dark_mode_ticket, [record("search_knowledge_base", {"results": [{"id": "KB-004"}]})])

    final, _ = policy.apply(decision, context)

    assert final.route_to is None
