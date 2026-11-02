"""Deterministic guardrails applied after the LLM decision.

Business-critical rules live in code rather than in the prompt, so they hold even when the model is wrong.
Rules may only make a decision *safer*: the engine refuses any change that lowers urgency, and every
change is recorded as a `PolicyOverride` so reviewers can see why the final decision differs from the model's.
"""

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, ClassVar

from triage_agent.models import (
    IssueType,
    NextAction,
    Plan,
    PolicyOverride,
    Team,
    Ticket,
    ToolCallRecord,
    TriageDecision,
    Urgency,
)

_DISPUTE_PATTERN = re.compile(r"\b(disput\w*|charge ?backs?|lawyers?|legal action|sue)\b", re.IGNORECASE)


@dataclass(frozen=True)
class PolicyContext:
    ticket: Ticket
    tool_calls: list[ToolCallRecord]

    def outputs_of(self, tool_name: str) -> list[dict[str, Any]]:
        return [call.output for call in self.tool_calls if call.name == tool_name and not call.is_error]

    @property
    def full_text(self) -> str:
        return "\n".join(message.text for message in self.ticket.messages)


@dataclass(frozen=True)
class Change:
    field: str
    value: Any
    reason: str


class Rule(ABC):
    name: ClassVar[str]

    @abstractmethod
    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        """Return the changes this rule requires (empty if the rule does not apply)."""


def escalate(urgency: Urgency, team: Team, reason: str) -> list[Change]:
    return [
        Change("urgency", urgency, reason),
        Change("next_action", NextAction.ESCALATE_TO_HUMAN, reason),
        Change("route_to", team, reason),
    ]


class FinancialRiskRule(Rule):
    """Duplicate charges or a dispute/chargeback threat must reach a human in billing."""

    name = "financial_risk"

    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        duplicates = sum(out.get("possible_duplicate_charges", 0) for out in context.outputs_of("get_billing_transactions"))
        dispute_threat = bool(_DISPUTE_PATTERN.search(context.full_text))
        if not duplicates and not dispute_threat:
            return []
        urgency = Urgency.CRITICAL if duplicates and dispute_threat else Urgency.HIGH
        reason = f"possible duplicate charges: {duplicates}, dispute/chargeback threat: {dispute_threat}"
        return escalate(urgency, Team.BILLING, reason)


class OutageRule(Rule):
    """Confirmed incidents, or any Enterprise outage, go straight to SRE."""

    name = "outage"

    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        if IssueType.OUTAGE not in decision.issue_types:
            return []
        incident_confirmed = any(out.get("active_incidents") for out in context.outputs_of("check_service_status"))
        is_enterprise = context.ticket.customer.plan == Plan.ENTERPRISE
        if not (incident_confirmed or is_enterprise):
            return []
        urgency = Urgency.CRITICAL if is_enterprise else Urgency.HIGH
        reason = f"outage reported (enterprise: {is_enterprise}, active incident confirmed: {incident_confirmed})"
        return escalate(urgency, Team.SRE, reason)


class SecurityRule(Rule):
    name = "security"

    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        if IssueType.SECURITY not in decision.issue_types:
            return []
        return escalate(Urgency.HIGH, Team.SECURITY, "possible security issue always needs a human")


class GroundingRule(Rule):
    """Drop KB citations that were never returned by the search tool (hallucinated sources)."""

    name = "grounding"

    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        retrieved = {
            result["id"] for out in context.outputs_of("search_knowledge_base") for result in out.get("results", [])
        }
        grounded = [article_id for article_id in decision.kb_article_ids if article_id in retrieved]
        if grounded == decision.kb_article_ids:
            return []
        return [Change("kb_article_ids", grounded, "cited articles not returned by knowledge-base search")]


class AutoRespondGuardRule(Rule):
    """Only answer automatically when the answer is grounded, low-risk and the model is confident."""

    name = "auto_respond_guard"

    def __init__(self, min_confidence: float) -> None:
        self._min_confidence = min_confidence

    def evaluate(self, decision: TriageDecision, context: PolicyContext) -> list[Change]:
        if decision.next_action != NextAction.AUTO_RESPOND:
            return []
        problems = []
        if decision.confidence < self._min_confidence:
            problems.append(f"confidence {decision.confidence:.2f} < {self._min_confidence}")
        if not decision.kb_article_ids:
            problems.append("no grounded knowledge-base article")
        if decision.urgency.rank >= Urgency.HIGH.rank:
            problems.append(f"urgency is {decision.urgency}")
        if not problems:
            return []
        reason = "; ".join(problems)
        return [
            Change("next_action", NextAction.ROUTE_TO_SPECIALIST, reason),
            Change("route_to", decision.route_to or Team.TIER2_SUPPORT, reason),
        ]


class PolicyEngine:
    def __init__(self, rules: list[Rule]) -> None:
        self._rules = rules

    def apply(self, decision: TriageDecision, context: PolicyContext) -> tuple[TriageDecision, list[PolicyOverride]]:
        overrides: list[PolicyOverride] = []
        for rule in self._rules:  # order matters: later rules see earlier changes
            for change in rule.evaluate(decision, context):
                old_value = getattr(decision, change.field)
                if old_value == change.value or _lowers_urgency(change, old_value):
                    continue
                decision = decision.model_copy(update={change.field: change.value})
                overrides.append(PolicyOverride(
                    rule=rule.name, field=change.field, old_value=old_value, new_value=change.value, reason=change.reason
                ))
        return decision, overrides


def _lowers_urgency(change: Change, old_value: Any) -> bool:
    return change.field == "urgency" and change.value.rank < old_value.rank


def default_policy(auto_respond_min_confidence: float) -> PolicyEngine:
    return PolicyEngine([
        FinancialRiskRule(),
        OutageRule(),
        SecurityRule(),
        GroundingRule(),
        AutoRespondGuardRule(auto_respond_min_confidence),
    ])
