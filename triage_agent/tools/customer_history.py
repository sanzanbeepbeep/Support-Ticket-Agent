from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from triage_agent.tools.base import Tool
from triage_agent.tools.mock_db import MockDatabase


class CustomerHistoryArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    customer_id: str = Field(description="Customer ID from the ticket, e.g. 'C-1001'.")


class CustomerHistoryTool(Tool):
    name = "get_customer_history"
    description = (
        "Look up a customer's account: plan, account status, recent account events, usage and past support tickets. "
        "Call this first for every ticket."
    )
    args_model = CustomerHistoryArgs

    def __init__(self, db: MockDatabase) -> None:
        self._db = db

    def run(self, args: CustomerHistoryArgs) -> dict[str, Any]:
        customer = self._db.customers.get(args.customer_id)
        if customer is None:
            return {"found": False, "customer_id": args.customer_id}
        return {"found": True, "customer_id": args.customer_id, **customer}
