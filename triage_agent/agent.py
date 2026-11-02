"""The triage agent: tool-calling loop -> structured decision -> policy guardrails."""

import json
import logging
import time

from triage_agent.llm import ConversationItem, LLMClient, LLMError, ToolOutput
from triage_agent.models import (
    AgentTrace,
    NextAction,
    Sentiment,
    SentimentTrend,
    Team,
    Ticket,
    TriageDecision,
    TriageResult,
    Urgency,
)
from triage_agent.policy import PolicyContext, PolicyEngine
from triage_agent.prompting import Prompt, render_ticket
from triage_agent.tools import ToolRegistry

logger = logging.getLogger(__name__)


class TriageAgent:
    def __init__(
        self,
        llm: LLMClient,
        tools: ToolRegistry,
        policy: PolicyEngine,
        system_prompt: Prompt,
        max_iterations: int = 6,
        required_tools: tuple[str, ...] = (),
    ) -> None:
        if max_iterations < 1:
            raise ValueError("max_iterations must be at least 1")
        unknown = set(required_tools) - set(tools.names)
        if unknown:
            raise ValueError(f"Required tools are not registered: {unknown}")
        self._llm = llm
        self._tools = tools
        self._policy = policy
        self._prompt = system_prompt
        self._max_iterations = max_iterations
        self._required_tools = required_tools

    def triage(self, ticket: Ticket) -> TriageResult:
        started = time.perf_counter()
        trace = AgentTrace(model=self._llm.model, prompt_version=self._prompt.version)
        error = None
        try:
            decision = self._investigate(ticket, trace)
        except LLMError as exc:
            # Fail safe: if the model is unavailable, a human looks at the ticket.
            logger.error("Triage failed for %s: %s", ticket.ticket_id, exc)
            decision, error = fallback_decision(ticket, str(exc)), str(exc)

        decision, overrides = self._policy.apply(decision, PolicyContext(ticket, trace.tool_calls))
        trace.latency_ms = round((time.perf_counter() - started) * 1000, 1)
        return TriageResult(
            ticket_id=ticket.ticket_id,
            decision=decision,
            policy_overrides=overrides,
            used_fallback=error is not None,
            error=error,
            trace=trace,
        )

    def _investigate(self, ticket: Ticket, trace: AgentTrace) -> TriageDecision:
        conversation: list[ConversationItem] = [render_ticket(ticket)]
        tool_specs = self._tools.specs()

        for iteration in range(1, self._max_iterations + 1):
            trace.iterations = iteration
            is_last = iteration == self._max_iterations
            response = self._llm.respond(
                instructions=self._prompt.text,
                conversation=conversation,
                tools=tool_specs,
                output_type=TriageDecision,
                allow_tool_calls=not is_last,  # on the last turn the model must commit to a decision
            )
            trace.input_tokens += response.input_tokens
            trace.output_tokens += response.output_tokens

            if not response.tool_calls:
                if response.parsed is None:
                    raise LLMError("Model returned no tool calls and no decision.")
                missing = [name for name in self._required_tools if name not in trace.tool_names()]
                if missing and not is_last:
                    # The model skipped mandatory investigation: send it back once more instead of trusting it.
                    conversation.append(f"Your investigation is incomplete. Call {', '.join(missing)} before deciding.")
                    continue
                return response.parsed

            for call in response.tool_calls:
                record = self._tools.execute(call.name, call.arguments)
                trace.tool_calls.append(record)
                conversation += [call, ToolOutput(call.call_id, json.dumps(record.output, ensure_ascii=False))]

        raise LLMError(f"No decision after {self._max_iterations} iterations.")


def fallback_decision(ticket: Ticket, error: str) -> TriageDecision:
    return TriageDecision(
        urgency=Urgency.HIGH,
        urgency_reason="Automatic triage failed; urgency unknown, so treated as high until a human reviews it.",
        product_area="unknown",
        issue_types=[],
        sentiment=Sentiment.NEUTRAL,
        sentiment_trend=SentimentTrend.STABLE,
        language="unknown",
        key_facts=[],
        kb_article_ids=[],
        next_action=NextAction.ESCALATE_TO_HUMAN,
        route_to=Team.TIER2_SUPPORT,
        action_reason="Automatic triage failed.",
        customer_reply="",
        internal_note=f"Triage agent error for ticket {ticket.ticket_id}: {error}",
        confidence=0.0,
    )
