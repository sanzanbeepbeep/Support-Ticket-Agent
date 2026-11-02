from collections import Counter
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


def count_possible_duplicates(transactions: list[dict[str, Any]]) -> int:
    """Number of extra non-refunded charges sharing the same amount and description."""
    keys = Counter(
        (tx["amount"], tx["description"])
        for tx in transactions
        if tx["status"] in {"pending", "captured"}
    )
    return sum(count - 1 for count in keys.values() if count > 1)
