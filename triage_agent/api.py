"""HTTP API.  Run with:  uvicorn triage_agent.api:app --reload"""

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException

from triage_agent.agent import TriageAgent
from triage_agent.factory import build_agent
from triage_agent.llm import LLMError
from triage_agent.models import Ticket, TriageResult

app = FastAPI(title="Support Ticket Triage Agent", version="0.1.0")


@lru_cache
def _cached_agent() -> TriageAgent:
    return build_agent()


def get_agent() -> TriageAgent:
    try:
        return _cached_agent()
    except LLMError as exc:  # e.g. missing API key: a configuration problem, not a server crash
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/triage", response_model=TriageResult)
def triage(ticket: Ticket, agent: Annotated[TriageAgent, Depends(get_agent)]) -> TriageResult:
    # Sync endpoint on purpose: FastAPI runs it in a worker thread, so the blocking OpenAI call
    # does not block the event loop.
    return agent.triage(ticket)
