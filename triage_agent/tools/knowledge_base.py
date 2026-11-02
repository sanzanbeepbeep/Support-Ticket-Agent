from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from triage_agent.knowledge_base import KnowledgeBase
from triage_agent.tools.base import Tool


class KnowledgeBaseArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(
        description="Search query in English using product keywords (translate non-English tickets first), "
        "e.g. 'dark mode system default not working mac'."
    )


class KnowledgeBaseTool(Tool):
    name = "search_knowledge_base"
    description = (
        "Search help-center FAQs and internal support procedures. Returns the most relevant articles. "
        "Call once per distinct sub-issue in the ticket."
    )
    args_model = KnowledgeBaseArgs

    def __init__(self, knowledge_base: KnowledgeBase, top_k: int = 3) -> None:
        self._kb = knowledge_base
        self._top_k = top_k

    def run(self, args: KnowledgeBaseArgs) -> dict[str, Any]:
        hits = self._kb.search(args.query, top_k=self._top_k)
        return {
            "query": args.query,
            "results": [
                {"id": hit.article.id, "title": hit.article.title, "score": hit.score, "content": hit.article.body}
                for hit in hits
            ],
            "note": None if hits else "No relevant article found. Do not invent an answer.",
        }
