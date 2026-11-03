"""Command line interface.

    triage run data/tickets/              # triage every ticket in a folder (or pass files)
    triage run data/tickets/ --verbose    # also show tool calls and token usage
    triage run data/tickets/ --json       # machine-readable output
    triage eval --repeats 3               # score the agent against the golden set
    triage schema                         # regenerate the JSON Schemas in schemas/
"""

import argparse
import json
import logging
import sys
import textwrap
from pathlib import Path

from pydantic import ValidationError

from triage_agent.config import PROJECT_ROOT, get_settings
from triage_agent.evaluation import format_report, load_cases, run_evaluation, save_report
from triage_agent.factory import build_agent
from triage_agent.llm import LLMError
from triage_agent.models import Ticket, TriageResult
from triage_agent.schemas import export_schemas


def collect_ticket_files(paths: list[Path]) -> list[Path]:
    files: list[Path] = []
    for path in paths:
        files.extend(sorted(path.glob("*.json")) if path.is_dir() else [path])
    return files


def format_result(result: TriageResult, verbose: bool = False) -> str:
    d = result.decision
    route = f" -> {d.route_to}" if d.route_to else ""
    lines = [
        f"=== {result.ticket_id} " + "=" * 50,
        f"Urgency : {d.urgency.upper():<9} Action: {d.next_action}{route}   Confidence: {d.confidence:.2f}",
        f"Issues  : {', '.join(d.issue_types)} | area: {d.product_area} | sentiment: {d.sentiment} ({d.sentiment_trend})"
        f" | lang: {d.language}",
        f"Why     : {d.urgency_reason}",
        f"Action  : {d.action_reason}",
        "Key facts:",
        *(f"  - {fact}" for fact in d.key_facts),
        f"KB used : {', '.join(d.kb_article_ids) or '-'}",
    ]
    if result.policy_overrides:
        lines.append("Policy overrides:")
        lines += [
            f"  - [{o.rule}] {o.field}: {o.old_value} -> {o.new_value} ({o.reason})" for o in result.policy_overrides
        ]
    if result.used_fallback:
        lines.append(f"FALLBACK used: {result.error}")
    lines += ["Draft reply:", textwrap.indent(d.customer_reply or "-", "  "), f"Internal note: {d.internal_note}"]
    if verbose:
        trace = result.trace
        lines.append(f"Trace: {trace.iterations} iterations, {trace.input_tokens}+{trace.output_tokens} tokens, "
                     f"{trace.latency_ms / 1000:.1f}s, {trace.model}, {trace.prompt_version}")
        if trace.missing_required_tools:
            lines.append(f"  WARNING required tools never called: {', '.join(trace.missing_required_tools)}")
        lines += [
            f"  tool {call.name}({json.dumps(call.arguments, ensure_ascii=False)})"
            f"{' ERROR' if call.is_error else ''} {call.duration_ms}ms"
            for call in trace.tool_calls
        ]
    return "\n".join(lines) + "\n"


def load_tickets(files: list[Path]) -> tuple[list[Ticket], list[str]]:
    """Load every ticket up front, so one bad file is reported before any tokens are spent."""
    tickets, errors = [], []
    for path in files:
        try:
            tickets.append(Ticket.model_validate_json(path.read_text(encoding="utf-8")))
        except OSError as exc:
            errors.append(f"{path}: cannot read file ({exc.strerror or exc})")
        except ValidationError as exc:
            errors.append(f"{path}: not a valid ticket ({exc.error_count()} errors, first: {exc.errors()[0]['msg']})")
    return tickets, errors


def cmd_run(args: argparse.Namespace) -> int:
    tickets, errors = load_tickets(collect_ticket_files(args.paths))
    if errors or not tickets:
        for error in errors or ["no ticket files found"]:
            print(f"Error: {error}", file=sys.stderr)
        return 2

    agent = build_agent()
    results = []
    for ticket in tickets:
        result = agent.triage(ticket)
        results.append(result)
        if not args.json:
            print(format_result(result, args.verbose))
    if args.json:
        print(json.dumps([r.model_dump(mode="json") for r in results], indent=2, ensure_ascii=False))
    return 0


def cmd_eval(args: argparse.Namespace) -> int:
    report = run_evaluation(build_agent(), load_cases(args.golden), PROJECT_ROOT, repeats=args.repeats)
    print(format_report(report))
    print(f"\nReport saved to {save_report(report, args.report_dir)}")
    return 0 if report.under_triage_count == 0 else 1


def cmd_schema(args: argparse.Namespace) -> int:
    for path in export_schemas(get_settings(), args.out):
        print(f"wrote {path}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="triage", description="Support ticket triage agent")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="Triage ticket JSON files")
    run.add_argument("paths", nargs="+", type=Path, help="Ticket files or folders")
    run.add_argument("--json", action="store_true", help="Print results as JSON")
    run.add_argument("--verbose", "-v", action="store_true", help="Show tool calls and usage")
    run.set_defaults(handler=cmd_run)

    evaluate = sub.add_parser("eval", help="Evaluate against the golden set")
    evaluate.add_argument("--golden", type=Path, default=PROJECT_ROOT / "evals" / "golden.json")
    evaluate.add_argument("--repeats", type=int, default=1, help="Runs per case, to measure consistency")
    evaluate.add_argument("--report-dir", type=Path, default=PROJECT_ROOT / "evals" / "reports")
    evaluate.set_defaults(handler=cmd_eval)

    schema = sub.add_parser("schema", help="Export JSON Schemas for tickets, results and tools")
    schema.add_argument("--out", type=Path, default=PROJECT_ROOT / "schemas")
    schema.set_defaults(handler=cmd_schema)
    return parser


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
    # Thai text must print correctly on Windows consoles too.
    sys.stdout.reconfigure(encoding="utf-8")
    args = build_parser().parse_args(argv)
    try:
        return args.handler(args)
    except LLMError as exc:  # configuration problems such as a missing API key
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
