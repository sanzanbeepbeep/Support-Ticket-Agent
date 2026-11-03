from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from triage_agent.tools.base import Tool
from triage_agent.tools.mock_db import MockDatabase


class BillingArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(description="Customer ID from the ticket.")


class BillingTransactionsTool(Tool):
    name = "get_billing_transactions"
    description = (
        "Fetch recent payment transactions, subscription state and failed upgrade attempts for a customer. "
        "Use for any payment, charge, refund, invoice or plan-upgrade issue."
    )
    args_model = BillingArgs

    def __init__(self, db: MockDatabase) -> None:
        self._db = db

    def run(self, args: BillingArgs) -> dict[str, Any]:
        account = self._db.billing.get(args.customer_id)
        if account is None:
            return {"found": False, "customer_id": args.customer_id}

        transactions = account.get("transactions", [])
        return {
            "found": True,
            "customer_id": args.customer_id,
            **account,
            # Pre-computed so the model doesn't have to count, and so policy rules can rely on it.
            "possible_duplicate_charges": count_possible_duplicates(transactions),
        }


def count_possible_duplicates(transactions: list[dict[str, Any]], window_minutes: int = 24 * 60) -> int:
    """Number of extra non-refunded charges with the same amount and description inside a short time window.

    The window keeps regular renewals (the same "Pro monthly" charge every month) from counting as duplicates.
    """
    groups: dict[tuple[Any, Any], list[int]] = defaultdict(list)
    for tx in transactions:
        if tx["status"] in {"pending", "captured"}:
            groups[(tx["amount"], tx["description"])].append(tx.get("minutes_ago", 0))

    duplicates = 0
    for times in groups.values():
        times.sort()
        duplicates += sum(1 for previous, current in zip(times, times[1:]) if current - previous <= window_minutes)
    return duplicates
