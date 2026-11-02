# Write-up: Support Ticket Triage Agent

## Architecture decisions and why

**Flow:** ticket → LLM tool-calling loop (OpenAI Responses API) → strict structured `TriageDecision` →
deterministic **policy layer** → `TriageResult` with a full trace.

- **Own agent loop instead of a framework.** The loop is about 40 lines. Every step can be seen, tested and capped
  (`MAX_TOOL_ITERATIONS`; on the last turn tool calls are disabled so the model must decide). The LLM sits behind
  a small `LLMClient` protocol: the tests use a scripted fake, and `OPENAI_BASE_URL` points it at any
  OpenAI-compatible server.
- **Structured output, not text parsing.** `TriageDecision` is a Pydantic model sent as a strict JSON schema,
  with enums for urgency, action, team and sentiment. The output is always valid and typed.
- **LLM for judgement, code for hard rules.** The model reads the whole thread (tone changes, deadlines,
  Thai text) and writes the reply. Business-critical rules are enforced in `policy.py` after the model:
  duplicate charges or a dispute threat go to billing, an Enterprise or confirmed outage goes to SRE, security
  goes to the security team, hallucinated KB citations are removed, and auto-respond requires a grounded,
  confident, low-risk answer. Rules can only **raise** urgency or escalate, and each override is recorded
  with its reason.
- **Tools give facts the text cannot.** Billing shows the 3 pending authorizations and the failed provisioning
  webhook. Internal status shows an Asia incident that the public status page does not show yet. Tool schemas
  are generated from Pydantic models, so adding a tool means writing one class.
- **Multilingual.** KB queries are written in English, and the reply uses the customer's language.
- **Traceability.** Every result records the model, the prompt version (a content hash), the tool calls, tokens
  and latency.

## What could go wrong and how I'd handle it

| Risk | Mitigation |
|---|---|
| Under-triage of a serious issue | Policy floor rules; the prompt says over-triage is cheaper; under-triage tracked as its own eval metric |
| Hallucinated answers or policies | Reply grounded in tool/KB output; citations checked against retrieved IDs; no auto-respond without a grounded article |
| Prompt injection in ticket text | Ticket wrapped in `<ticket>` and declared as data; tools are read-only; policy runs after the LLM; injection case in the eval set |
| Promising refunds or ETAs | Explicit prompt rule plus KB guidance; production: an output check for commitments before sending |
| LLM/API outage, rate limits, bad JSON | SDK retries with backoff; tool errors returned to the model as data; on failure → **fail-safe escalation to a human** |
| Tool returns stale or missing data | `found: false` is handled explicitly; confidence drops; the policy blocks auto-respond |
| Cost and latency | Iteration cap; tokens tracked per ticket; production: a small model for clear low-risk tickets and a large one for the rest |
| PII in logs and prompts | Production: redact card and contact data before logging; data retention settings |

## How I'd evaluate it in production

1. **Before launch (offline):** run `triage eval` on a golden set built from real historical tickets labelled by
   senior agents. Metrics: urgency accuracy, **under-triage rate** (the gating metric), action and route accuracy,
   tool recall, schema validity, consistency over repeated runs, cost and latency. It runs in CI on every prompt
   or model change and fails the build on regressions.
2. **Shadow mode:** the agent triages live tickets, but humans still decide. Measure agreement with the human
   decision per urgency and per team, and review every disagreement where the agent's urgency was lower.
3. **Gradual rollout:** enable routing first, then auto-respond for low-risk categories only. Track reopen rate,
   CSAT after auto-replies, time-to-first-response, escalation precision (how many escalations were needed), and
   how often humans override the agent.
4. **Reply quality:** sample replies weekly and score them with an LLM judge (groundedness, covers every
   question, tone, correct language, no promises) checked against human review.
5. **Continuous improvement:** add every misclassification to the golden set, and alert on drift (shifts in the
   category mix, confidence or override rate).

**Next steps beyond this homework:** hybrid retrieval (vector + BM25) over the real help center, async queue
ingestion, a CI eval gate, and deployment on Cloud Run.
