"""Domain models: the ticket coming in and the triage result going out."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------- input


class Plan(StrEnum):
    FREE = "free"
    PRO = "pro"
    ENTERPRISE = "enterprise"


class CustomerInfo(BaseModel):
    customer_id: str
    name: str
    plan: Plan
    region: str
    tenure_months: int
    seats: int = 1
    notes: str = ""


class Message(BaseModel):
    minutes_ago: int = Field(ge=0, description="How long ago the message was sent.")
    text: str


class Ticket(BaseModel):
    ticket_id: str
    customer: CustomerInfo
    messages: list[Message] = Field(min_length=1)


# --------------------------------------------------------------------------- output


class Urgency(StrEnum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @property
    def rank(self) -> int:
        """Higher rank = more urgent. Used to compare and to only ever raise urgency."""
        return {"low": 0, "medium": 1, "high": 2, "critical": 3}[self.value]


class IssueType(StrEnum):
    BILLING = "billing"
    OUTAGE = "outage"
    BUG = "bug"
    HOW_TO = "how_to"
    FEATURE_REQUEST = "feature_request"
    ACCOUNT = "account"
    SECURITY = "security"
    SALES = "sales"
    OTHER = "other"


class Sentiment(StrEnum):
    VERY_NEGATIVE = "very_negative"
    NEGATIVE = "negative"
    NEUTRAL = "neutral"
    POSITIVE = "positive"


class SentimentTrend(StrEnum):
    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


class NextAction(StrEnum):
    AUTO_RESPOND = "auto_respond"
    ROUTE_TO_SPECIALIST = "route_to_specialist"
    ESCALATE_TO_HUMAN = "escalate_to_human"


class Team(StrEnum):
    BILLING = "billing"
    SRE = "sre"
    SECURITY = "security"
    PRODUCT = "product"
    TIER2_SUPPORT = "tier2_support"
    SALES = "sales"
    ACCOUNT_MANAGEMENT = "account_management"


class TriageDecision(BaseModel):
    """Structured output produced by the LLM. Every field is required so the schema can be strict."""

    model_config = ConfigDict(extra="forbid")

    urgency: Urgency
    urgency_reason: str = Field(description="One or two sentences citing the evidence for the urgency.")
    product_area: str = Field(description="Product area affected, e.g. 'billing/checkout', 'web app', 'appearance settings'.")
    issue_types: list[IssueType] = Field(description="All issue types present in the thread, most important first.")
    sentiment: Sentiment = Field(description="Customer sentiment in the latest message.")
    sentiment_trend: SentimentTrend = Field(description="How sentiment changed across the thread.")
    language: str = Field(description="ISO 639-1 code of the customer's language, e.g. 'en', 'th'.")
    key_facts: list[str] = Field(description="Concrete facts an agent needs: amounts, errors, deadlines, scope of impact.")
    kb_article_ids: list[str] = Field(description="IDs of knowledge-base articles actually used. Empty if none were relevant.")
    next_action: NextAction
    route_to: Team | None = Field(description="Team that should own the ticket. Null only for auto_respond.")
    action_reason: str
    customer_reply: str = Field(description="Draft reply to the customer, in the customer's language, grounded in tool/KB results.")
    internal_note: str = Field(description="Short hand-off note for the support team.")
    confidence: float = Field(description="0.0-1.0 confidence in this triage decision.")

    @field_validator("confidence")
    @classmethod
    def _clamp_confidence(cls, value: float) -> float:
        # Clamped instead of bounded with ge/le, which would change the strict schema sent to the model.
        return min(max(value, 0.0), 1.0)


class PolicyOverride(BaseModel):
    rule: str
    field: str
    old_value: Any
    new_value: Any
    reason: str


class ToolCallRecord(BaseModel):
    name: str
    arguments: dict[str, Any]
    output: dict[str, Any]
    is_error: bool = False
    duration_ms: float


class AgentTrace(BaseModel):
    model: str
    prompt_version: str
    iterations: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0.0
    tool_calls: list[ToolCallRecord] = Field(default_factory=list)
    missing_required_tools: list[str] = Field(
        default_factory=list, description="Required tools the model still had not called when it had to decide."
    )

    def tool_names(self) -> set[str]:
        return {call.name for call in self.tool_calls}


class TriageResult(BaseModel):
    ticket_id: str
    decision: TriageDecision
    policy_overrides: list[PolicyOverride] = Field(default_factory=list)
    used_fallback: bool = False
    error: str | None = None
    trace: AgentTrace
