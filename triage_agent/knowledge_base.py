"""Small in-memory knowledge base with BM25 ranking.

Kept deliberately simple: the `KnowledgeBase.search` interface is what the tool depends on, so this can be
swapped for a vector / hybrid retriever without touching the agent.
"""

import math
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

_TOKEN = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    "a an and are as at be but by can do does for from how i if in is it my of on or so that the this to "
    "was what when where which why with you your".split()
)


def tokenize(text: str) -> list[str]:
    return [token for token in _TOKEN.findall(text.lower()) if token not in _STOPWORDS]


@dataclass(frozen=True)
class Article:
    id: str
    title: str
    tags: tuple[str, ...]
    body: str

    @property
    def searchable_text(self) -> str:
        # Title and tags are repeated to weight them above body text.
        return " ".join([self.title] * 2 + list(self.tags) * 2 + [self.body])


@dataclass(frozen=True)
class SearchHit:
    article: Article
    score: float


def parse_article(text: str) -> Article:
    """Parse a markdown file with a `---` delimited `key: value` header."""
    _, header, body = text.split("---", 2)
    meta = dict(line.split(":", 1) for line in header.strip().splitlines())
    meta = {key.strip(): value.strip() for key, value in meta.items()}
    tags = tuple(tag.strip() for tag in meta.get("tags", "").split(",") if tag.strip())
    return Article(id=meta["id"], title=meta["title"], tags=tags, body=body.strip())


class KnowledgeBase:
    def __init__(self, articles: list[Article], k1: float = 1.5, b: float = 0.75) -> None:
        self.articles = articles
        self._k1, self._b = k1, b
        self._doc_tokens = [Counter(tokenize(article.searchable_text)) for article in articles]
        self._doc_lengths = [sum(tokens.values()) for tokens in self._doc_tokens]
        self._avg_length = sum(self._doc_lengths) / max(len(articles), 1)
        document_frequency = Counter(term for tokens in self._doc_tokens for term in tokens)
        n = len(articles)
        self._idf = {term: math.log(1 + (n - df + 0.5) / (df + 0.5)) for term, df in document_frequency.items()}

    @classmethod
    def from_directory(cls, directory: Path) -> "KnowledgeBase":
        files = sorted(directory.glob("*.md"))
        return cls([parse_article(path.read_text(encoding="utf-8")) for path in files])

    def search(self, query: str, top_k: int = 3, min_score: float = 1.0) -> list[SearchHit]:
        query_terms = set(tokenize(query))
        hits = [
            SearchHit(article, round(self._score(query_terms, index), 3))
            for index, article in enumerate(self.articles)
        ]
        hits = [hit for hit in hits if hit.score >= min_score]
        return sorted(hits, key=lambda hit: hit.score, reverse=True)[:top_k]

    def _score(self, query_terms: set[str], index: int) -> float:
        tokens, length = self._doc_tokens[index], self._doc_lengths[index]
        score = 0.0
        for term in query_terms:
            tf = tokens.get(term, 0)
            if tf:
                norm = tf * (self._k1 + 1) / (tf + self._k1 * (1 - self._b + self._b * length / self._avg_length))
                score += self._idf[term] * norm
        return score
