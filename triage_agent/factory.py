"""Composition root: the one place that wires concrete implementations together."""

from triage_agent.agent import TriageAgent
from triage_agent.config import Settings, get_settings
from triage_agent.knowledge_base import KnowledgeBase
from triage_agent.llm import LLMClient, OpenAIClient
from triage_agent.policy import default_policy
from triage_agent.prompting import load_prompt
from triage_agent.tools import (
    BillingTransactionsTool,
    CustomerHistoryTool,
    KnowledgeBaseTool,
    MockDatabase,
    ServiceStatusTool,
    ToolRegistry,
)


def build_tools(settings: Settings) -> ToolRegistry:
    db = MockDatabase(settings.data_dir)
    knowledge_base = KnowledgeBase.from_directory(settings.data_dir / "kb")
    return ToolRegistry([
        CustomerHistoryTool(db),
        BillingTransactionsTool(db),
        ServiceStatusTool(db),
        KnowledgeBaseTool(knowledge_base),
    ])


def build_agent(settings: Settings | None = None, llm: LLMClient | None = None) -> TriageAgent:
    settings = settings or get_settings()
    return TriageAgent(
        llm=llm or OpenAIClient(settings),
        tools=build_tools(settings),
        policy=default_policy(settings.auto_respond_min_confidence),
        system_prompt=load_prompt("system_prompt"),
        max_iterations=settings.max_tool_iterations,
        required_tools=settings.required_tools,
    )
