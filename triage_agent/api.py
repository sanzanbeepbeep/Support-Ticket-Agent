"""HTTP API.  Run with:  uvicorn triage_agent.api:app --reload"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI

from triage_agent.agent import TriageAgent
from triage_agent.factory import build_agent
from triage_agent.models import Ticket, TriageResult

app = FastAPI(title="Support Ticket Triage Agent", version="0.1.0")


@lru_cache
def get_agent() -> TriageAgent:
    return build_agent()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageResult)
def triage(ticket: Ticket, agent: Annotated[TriageAgent, Depends(get_agent)]) -> TriageResult:
    # Sync endpoint on purpose: FastAPI runs it in a worker thread, so the blocking OpenAI call
    # does not block the event loop.
    return agent.triage(ticket)
