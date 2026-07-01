"""Simple Semantic Memory retrieval."""

from dataclasses import dataclass
import re

from app.memory.memory_store import SemanticMemoryStore
from app.memory.memory_types import MemoryItem


TYPE_QUERY_TERMS = {
    "fact": ("fact", "事实"),
    "preference": ("preference", "偏好", "喜欢", "默认"),
    "goal": ("goal", "目标", "计划"),
    "constraint": ("constraint", "约束", "限制", "不要", "不能"),
}
STOP_TERMS = {
    "今天",
    "怎么",
    "如何",
    "安排",
    "相关",
    "这个",
    "那个",
    "我的",
    "什么",
}


@dataclass(frozen=True)
class RetrievedMemory:
    """Semantic Memory selected for the current user input."""

    item: MemoryItem
    score: int
    reason: str


class MemoryRetriever:
    """Retrieve a few active Semantic Memory items with deterministic rules."""

    def __init__(
        self,
        store: SemanticMemoryStore | None = None,
        *,
        max_results: int = 5,
    ) -> None:
        self.store = store or SemanticMemoryStore()
        self.max_results = max_results

    def retrieve(self, query: str) -> list[RetrievedMemory]:
        query_text = query.strip().lower()
        if not query_text:
            return []

        query_terms = _query_terms(query_text)
        matches: list[RetrievedMemory] = []
        for item in self.store.list_memories():
            score, reason = _score_item(item, query_text, query_terms)
            if score <= 0:
                continue
            matches.append(RetrievedMemory(item=item, score=score, reason=reason))

        matches.sort(key=lambda match: (-match.score, match.item.created_at))
        return matches[: self.max_results]


def _score_item(
    item: MemoryItem,
    query_text: str,
    query_terms: set[str],
) -> tuple[int, str]:
    score = 0
    reasons: list[str] = []

    type_terms = TYPE_QUERY_TERMS[item.type]
    if any(term in query_text for term in type_terms):
        score += 5
        reasons.append(f"type:{item.type}")

    for tag in item.tags:
        if tag and tag in query_text:
            score += 4
            reasons.append(f"tag:{tag}")

    memory_text = " ".join([item.content, *item.tags]).lower()
    keyword_hits = sorted(term for term in query_terms if term in memory_text)
    if keyword_hits:
        score += min(len(keyword_hits), 5)
        reasons.append("keyword:" + ",".join(keyword_hits[:3]))

    return score, ";".join(reasons)


def _query_terms(text: str) -> set[str]:
    terms = set(re.findall(r"[a-z0-9_]{2,}", text))
    for chunk in re.findall(r"[\u4e00-\u9fff]{2,}", text):
        if len(chunk) <= 6:
            terms.add(chunk)
        for index in range(len(chunk) - 1):
            terms.add(chunk[index : index + 2])
    return {term for term in terms if term not in STOP_TERMS}
