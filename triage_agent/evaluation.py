"""Golden-set evaluation: run the agent on labelled tickets and score each decision.

Expectations hold *acceptable* values (lists) because some cases legitimately allow more than one answer
(for example a cosmetic bug may be low or medium). Under-triage, meaning a predicted urgency below every
acceptable value, is tracked separately because it is the most costly mistake in support triage.
"""

import json
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path

from pydantic import BaseModel, Field

from triage_agent.agent import TriageAgent
from triage_agent.models import IssueType, NextAction, Team, Ticket, TriageResult, Urgency


class Expectation(BaseModel):
    urgency: list[Urgency]
    next_action: list[NextAction]
    route_to: list[Team | None] = Field(default_factory=list, description="Empty = not checked.")
    issue_types: list[IssueType] = Field(default_factory=list, description="Must all be present.")
    language: str | None = None
    required_tools: list[str] = Field(default_factory=list)


class EvalCase(BaseModel):
    name: str
    ticket_path: Path
    expected: Expectation

    def load_ticket(self, root: Path) -> Ticket:
        return Ticket.model_validate_json((root / self.ticket_path).read_text(encoding="utf-8"))


class CaseScore(BaseModel):
    case: str
    run: int
    checks: dict[str, bool]
    under_triaged: bool
    urgency: Urgency
    next_action: NextAction
    latency_ms: float
    tokens: int

    @property
    def passed(self) -> bool:
        return all(self.checks.values())


class EvalReport(BaseModel):
    model: str
    prompt_version: str
    created_at: str
    scores: list[CaseScore]

    def check_pass_rates(self) -> dict[str, float]:
        names = sorted({name for score in self.scores for name in score.checks})
        rates = {}
        for name in names:
            results = [score.checks[name] for score in self.scores if name in score.checks]
            rates[name] = sum(results) / len(results)
        return rates

    @property
    def under_triage_count(self) -> int:
        return sum(score.under_triaged for score in self.scores)

    @property
    def fully_passed(self) -> int:
        return sum(score.passed for score in self.scores)


def score_result(case: str, run: int, result: TriageResult, expected: Expectation) -> CaseScore:
    decision = result.decision
    checks = {
        "urgency": decision.urgency in expected.urgency,
        "next_action": decision.next_action in expected.next_action,
        "no_fallback": not result.used_fallback,
    }
    if expected.route_to:
        checks["route_to"] = decision.route_to in expected.route_to
    if expected.issue_types:
        checks["issue_types"] = set(expected.issue_types) <= set(decision.issue_types)
    if expected.language:
        checks["language"] = decision.language.lower() == expected.language
    if expected.required_tools:
        checks["required_tools"] = set(expected.required_tools) <= result.trace.tool_names()

    return CaseScore(
        case=case,
        run=run,
        checks=checks,
        under_triaged=decision.urgency.rank < min(u.rank for u in expected.urgency),
        urgency=decision.urgency,
        next_action=decision.next_action,
        latency_ms=result.trace.latency_ms,
        tokens=result.trace.input_tokens + result.trace.output_tokens,
    )


def load_cases(golden_file: Path) -> list[EvalCase]:
    return [EvalCase.model_validate(item) for item in json.loads(golden_file.read_text(encoding="utf-8"))]


def run_evaluation(agent: TriageAgent, cases: Iterable[EvalCase], root: Path, repeats: int = 1) -> EvalReport:
    scores, trace = [], None
    for case in cases:
        ticket = case.load_ticket(root)
        for run in range(1, repeats + 1):
            result = agent.triage(ticket)
            trace = result.trace
            scores.append(score_result(case.name, run, result, case.expected))
    return EvalReport(
        model=trace.model if trace else "n/a",
        prompt_version=trace.prompt_version if trace else "n/a",
        created_at=datetime.now().isoformat(timespec="seconds"),
        scores=scores,
    )


def format_report(report: EvalReport) -> str:
    lines = [f"Model: {report.model}   Prompt: {report.prompt_version}", ""]
    lines.append(f"{'case':<28}{'run':>4}  {'urgency':<9}{'action':<21}{'pass':<6}failed checks")
    for score in report.scores:
        failed = ", ".join(name for name, ok in score.checks.items() if not ok) or "-"
        if score.under_triaged:
            failed += "  (UNDER-TRIAGED)"
        lines.append(
            f"{score.case:<28}{score.run:>4}  {score.urgency:<9}{score.next_action:<21}"
            f"{'yes' if score.passed else 'NO':<6}{failed}"
        )

    total = len(report.scores)
    lines += ["", f"Fully passed: {report.fully_passed}/{total}   Under-triaged: {report.under_triage_count}"]
    lines += [f"  {name:<16}{rate:6.0%}" for name, rate in report.check_pass_rates().items()]
    if total:
        avg_latency = sum(s.latency_ms for s in report.scores) / total / 1000
        avg_tokens = sum(s.tokens for s in report.scores) / total
        lines.append(f"Avg latency: {avg_latency:.1f}s   Avg tokens/ticket: {avg_tokens:,.0f}")
    return "\n".join(lines)


def save_report(report: EvalReport, directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = report.created_at.replace(":", "").replace("-", "")
    path = directory / f"{stamp}_{report.model}_{report.prompt_version.replace('@', '-')}.json"
    path.write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return path
