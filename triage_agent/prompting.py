"""Prompt loading (with content-hash versioning) and ticket rendering."""

import hashlib
import html
from dataclasses import dataclass
from pathlib import Path

from triage_agent.models import Ticket

PROMPTS_DIR = Path(__file__).parent / "prompts"


@dataclass(frozen=True)
class Prompt:
    name: str
    text: str

    @property
    def version(self) -> str:
        """Short content hash, recorded in every result so outputs can be traced to the exact prompt."""
        return f"{self.name}@{hashlib.sha256(self.text.encode()).hexdigest()[:8]}"


def load_prompt(name: str) -> Prompt:
    return Prompt(name=name, text=(PROMPTS_DIR / f"{name}.md").read_text(encoding="utf-8"))


def humanize_minutes(minutes: int) -> str:
    if minutes < 1:
        return "just now"
    if minutes < 60:
        return f"{minutes} min ago"
    if minutes < 24 * 60:
        hours = minutes / 60
        return f"{hours:g} hours ago" if hours != 1 else "1 hour ago"
    days = minutes // (24 * 60)
    return f"{days} days ago" if days != 1 else "1 day ago"


def _as_data(text: str) -> str:
    """Escape angle brackets so customer text cannot close the `<ticket>` block and pose as instructions."""
    return html.escape(text, quote=False)


def render_ticket(ticket: Ticket) -> str:
    customer = ticket.customer
    messages = sorted(ticket.messages, key=lambda message: message.minutes_ago, reverse=True)
    thread = "\n".join(
        f"[Message {index} - {humanize_minutes(message.minutes_ago)}]\n{_as_data(message.text)}"
        for index, message in enumerate(messages, start=1)
    )
    return (
        f'<ticket id="{html.escape(ticket.ticket_id)}">\n'
        "Customer profile (CRM):\n"
        f"- customer_id: {_as_data(customer.customer_id)}\n"
        f"- name: {_as_data(customer.name)}\n"
        f"- plan: {customer.plan}\n"
        f"- region: {_as_data(customer.region)}\n"
        f"- tenure: {customer.tenure_months} months\n"
        f"- seats: {customer.seats}\n"
        f"- notes: {_as_data(customer.notes) or '-'}\n\n"
        f"Message thread (oldest first):\n{thread}\n"
        "</ticket>"
    )
