from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from triage_agent.tools.base import Tool
from triage_agent.tools.mock_db import MockDatabase

Region = Literal["global", "asia", "europe", "north_america"]


class ServiceStatusArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    region: Region = Field(description="Region to check. Use the customer's region; 'global' returns all regions.")


class ServiceStatusTool(Tool):
    name = "check_service_status"
    description = (
        "Check internal monitoring for active incidents, including ones not yet published on the public status page. "
        "Use for errors, outages, slowness or 'cannot access' reports."
    )
    args_model = ServiceStatusArgs

    def __init__(self, db: MockDatabase) -> None:
        self._db = db

    def run(self, args: ServiceStatusArgs) -> dict[str, Any]:
        active = [
            incident
            for incident in self._db.incidents
            if incident["status"] != "resolved" and (args.region == "global" or incident["region"] == args.region)
        ]
        return {
            "region": args.region,
            "overall_status": "degraded" if active else "operational",
            "active_incidents": active,
        }
