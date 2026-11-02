# Support Ticket Triage Agent

An AI agent that triages customer support tickets with OpenAI GPT models. For each ticket it:

- classifies **urgency** (critical / high / medium / low)
- extracts **product area, issue types, sentiment and its trend, language and key facts**
- looks up the **customer, billing, service status and knowledge base** through tools
- decides the **next action** (`auto_respond`, `route_to_specialist` or `escalate_to_human`) and the owning team
- drafts a **customer reply** in the customer's language plus an **internal note**

Design decisions, risks and evaluation are covered in [WRITEUP.md](WRITEUP.md).

## Setup

Requires Python 3.12+.

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate    macOS/Linux: source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env        # then set OPENAI_API_KEY
```

All settings are environment variables (see [.env.example](.env.example)). `OPENAI_MODEL` defaults to `gpt-4.1`.

## Run

Triage the three sample tickets:

```bash
triage run data/tickets/            # human-readable output
triage run data/tickets/ --verbose  # + tool calls, tokens, latency, prompt version
triage run data/tickets/ --json     # full structured result
```

`python -m triage_agent run ...` works too.

HTTP API:

```bash
uvicorn triage_agent.api:app --reload
curl -X POST localhost:8000/triage -H "Content-Type: application/json" -d @data/tickets/ticket_2_outage_th.json
```

Interactive docs are served at http://localhost:8000/docs.

## Test and evaluate

```bash
pytest                    # offline unit tests, no API key needed (scripted fake LLM)
triage eval               # golden set: 3 samples + 5 edge cases, real model
triage eval --repeats 3   # also measures consistency across runs
```

`triage eval` prints per-case checks, pass rates, under-triage count, latency and tokens, and saves a JSON report
to `evals/reports/` tagged with the model and the prompt version. It exits non-zero if any ticket is under-triaged,
so it can be used as a CI gate.

## Project layout

```
triage_agent/
  agent.py           tool-calling loop -> structured decision -> policy guardrails
  llm.py             LLMClient protocol + OpenAI Responses API implementation
  policy.py          deterministic guardrail rules applied after the LLM
  prompts/system_prompt.md   the system prompt
  prompting.py       prompt loading (content-hash versioning) and ticket rendering
  tools/             Tool base class + registry, and the 4 tools (mock backends)
  knowledge_base.py  BM25 search over data/kb/*.md
  models.py          ticket input and triage output schemas (Pydantic)
  evaluation.py      golden-set scoring and reports
  factory.py         wiring of concrete implementations
  cli.py, api.py     interfaces
data/
  tickets/           the 3 sample tickets
  kb/                knowledge-base articles
  mock_db/           customers, billing, incidents (mock backends)
evals/
  golden.json        expected labels per case
  cases/             edge-case tickets
tests/               pytest suite
```

## Tools

| Tool | Purpose | Backend |
|---|---|---|
| `get_customer_history` | plan, account events, past tickets | `data/mock_db/customers.json` |
| `get_billing_transactions` | charges, upgrade status, duplicate detection | `data/mock_db/billing.json` |
| `check_service_status` | internal incidents by region (incl. ones not yet on the status page) | `data/mock_db/incidents.json` |
| `search_knowledge_base` | BM25 search over FAQ/procedure articles | `data/kb/*.md` |

Tool schemas are generated from each tool's Pydantic argument model and sent as strict function definitions.
To add a tool, subclass `Tool` in `triage_agent/tools/`, then register it in `factory.build_tools`.
