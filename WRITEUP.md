# Write-up: Support Ticket Triage Agent

## Architecture decisions and why

**Flow:** ticket → LLM tool-calling loop (OpenAI Responses API) → strict `TriageDecision` → policy layer → `TriageResult` + trace.

- **Own agent loop, no framework.** Small, testable, capped by `MAX_TOOL_ITERATIONS`. The LLM sits behind a protocol, so tests use a fake model and `OPENAI_BASE_URL` can point at any OpenAI-compatible server.
- **Strict structured output.** The decision is a Pydantic schema with enums, so the result is always valid and typed.
- **LLM for judgement, code for hard rules.** The model reads the thread and drafts the reply. `policy.py` then enforces billing, outage and security escalation, removes made-up KB citations, and blocks unsafe auto-replies. Rules can only raise urgency, and every change is logged with its reason.
- **Tools supply facts the text can't.** Duplicate charges, an Asia incident not yet on the status page. A tool is one class whose schema is generated from Pydantic.
- **Multilingual and traceable.** KB queries go in English and replies in the customer's language. Each result records the model, prompt version, tool calls and tokens.

## What could go wrong and how I'd handle it

| Risk | Mitigation |
|---|---|
| Under-triage | Policy floor rules; under-triage tracked as its own metric |
| Hallucination | Replies grounded in tools/KB; citations checked against search results |
| Prompt injection | Ticket wrapped as data; read-only tools; policy runs after the LLM |
| Promises (refunds, dates) | Auto-replies with commitments go to a human |
| Context collision | Link an incident only when symptoms match; force escalation only for major incidents |
| Skipped investigation | Required tools; the model is sent back if it decides early |
| LLM/API failure | Retries, then fail-safe escalation to a human |
| Cost and PII | Iteration cap, token tracking; redact PII in production |

**Results (gpt-4.1):** 15/15 golden cases pass, 0 under-triaged, stable across 3 runs (45/45). A red-team run that told the model to under-triage and promise refunds was corrected by the policy layer.

## How I'd evaluate it in production

1. **Offline:** golden set from real tickets labelled by senior agents. Gate CI on under-triage rate, plus urgency, action and route accuracy.
2. **Shadow mode:** agent decides, humans act. Measure agreement and review every case where the agent's urgency was lower.
3. **Gradual rollout:** routing first, then auto-respond for low-risk categories. Track reopen rate, CSAT, override rate and time to first response.
4. **Continuous:** LLM-judge reply quality checked against human review; add every miss to the golden set; alert on drift.

**Next steps:** hybrid vector + BM25 retrieval, async queue, CI eval gate, Cloud Run deployment.
