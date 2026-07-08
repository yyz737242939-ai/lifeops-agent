import json
import re
from dataclasses import dataclass, field
from typing import Any

from app.context.context_ref_store import read_context_ref
from app.context.context_types import ContextUnit
from app.utils.json_file import parse_json_object
from app.utils.serialization import json_safe


REF_ID_PATTERN = re.compile(r"\bctx_[A-Za-z0-9_-]+\b")
DATE_PATTERN = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
NUMBER_PATTERN = re.compile(r"\b\d+\b")

DOMAIN_KEYWORDS = {
    "todo": {
        "todo",
        "todos",
        "task",
        "tasks",
    },
    "expense": {
        "expense",
        "expenses",
        "spending",
        "transaction",
        "transactions",
    },
    "wellbeing": {
        "sleep",
        "mood",
        "energy",
        "wellbeing",
    },
    "activity": {
        "activity",
        "activities",
        "recommendation",
    },
}

ACTION_KEYWORDS = {
    "complete",
    "finish",
    "done",
    "update",
    "change",
    "delete",
    "remove",
    "edit",
}

EXACT_FIELD_KEYWORDS = {
    "id",
    "ref",
    "date",
    "amount",
    "exact",
    "before",
    "sixth",
    "seventh",
    "eighth",
    "ninth",
    "tenth",
}


@dataclass(frozen=True)
class ContextIndexEntry:
    unit_id: str
    kind: str
    tool_names: frozenset[str] = frozenset()
    entity_ids: frozenset[str] = frozenset()
    keywords: frozenset[str] = frozenset()
    action_status: str | None = None
    ref_ids: frozenset[str] = frozenset()
    protected: bool = False


@dataclass(frozen=True)
class ContextQuery:
    text: str
    exact_required: bool
    ref_ids: frozenset[str] = frozenset()
    entity_ids: frozenset[str] = frozenset()
    domains: frozenset[str] = frozenset()


@dataclass(frozen=True)
class RetrievedUnit:
    unit: ContextUnit
    reason: str
    matched_fields: tuple[str, ...]


@dataclass(frozen=True)
class ContextRetrievalResult:
    query: ContextQuery
    units: list[RetrievedUnit] = field(default_factory=list)
    ref_messages: list[dict[str, str]] = field(default_factory=list)
    ref_reports: list[dict[str, Any]] = field(default_factory=list)


class ContextIndex:
    """Deterministic metadata index for small, exact context retrieval."""

    def retrieve(
        self,
        *,
        query_text: str,
        candidate_units: list[ContextUnit],
        excluded_unit_ids: set[str] | None = None,
        max_units: int = 3,
        max_refs: int = 2,
    ) -> ContextRetrievalResult:
        query = build_query(query_text)
        if not query.exact_required:
            return ContextRetrievalResult(query=query)

        excluded = excluded_unit_ids or set()
        scored: list[tuple[int, RetrievedUnit, ContextIndexEntry]] = []
        for unit in candidate_units:
            if unit.unit_id in excluded:
                continue
            entry = build_entry(unit)
            score, reason, matched_fields = _score_entry(query, entry)
            if score <= 0:
                continue
            scored.append(
                (
                    score,
                    RetrievedUnit(
                        unit=unit,
                        reason=reason,
                        matched_fields=tuple(matched_fields),
                    ),
                    entry,
                )
            )

        scored.sort(key=lambda item: item[0], reverse=True)
        retrieved_units = [item[1] for item in scored[:max_units]]

        ref_reports: list[dict[str, Any]] = []
        ref_messages: list[dict[str, str]] = []
        loaded_ref_ids: set[str] = set()
        candidate_ref_ids = _ordered_ref_ids(query, [item[2] for item in scored])
        for ref_id in candidate_ref_ids:
            if len(loaded_ref_ids) >= max_refs:
                break
            loaded_ref_ids.add(ref_id)
            payload = read_context_ref(ref_id)
            if payload is None:
                ref_reports.append(
                    {
                        "ref_id": ref_id,
                        "reason": "current_request_requires_exact_fields",
                        "status": "rejected",
                    }
                )
                continue
            ref_reports.append(
                {
                    "ref_id": ref_id,
                    "reason": "current_request_requires_exact_fields",
                    "status": "loaded",
                    "tool_name": payload.get("tool_name"),
                }
            )
            ref_messages.append(_ref_payload_message(ref_id, payload))

        return ContextRetrievalResult(
            query=query,
            units=retrieved_units,
            ref_messages=ref_messages,
            ref_reports=ref_reports,
        )


def build_query(text: str) -> ContextQuery:
    normalized = text.lower()
    ref_ids = frozenset(REF_ID_PATTERN.findall(text))
    domains = frozenset(
        domain
        for domain, keywords in DOMAIN_KEYWORDS.items()
        if any(keyword in normalized for keyword in keywords)
    )
    entity_ids = frozenset(NUMBER_PATTERN.findall(text))
    exact_required = bool(
        ref_ids
        or DATE_PATTERN.search(text)
        or any(keyword in normalized for keyword in ACTION_KEYWORDS)
        or any(keyword in normalized for keyword in EXACT_FIELD_KEYWORDS)
    )
    return ContextQuery(
        text=text,
        exact_required=exact_required,
        ref_ids=ref_ids,
        entity_ids=entity_ids,
        domains=domains,
    )


def build_entry(unit: ContextUnit) -> ContextIndexEntry:
    serialized_text = json.dumps(json_safe(unit.messages), ensure_ascii=False)
    normalized = serialized_text.lower()
    tool_names = _tool_names(unit)
    result = _tool_result(unit)
    ref_ids = set(REF_ID_PATTERN.findall(serialized_text))
    entity_ids: set[str] = set()
    action_status = None
    if result is not None:
        entity_ids.update(_entity_ids(result))
        if result.get("ok") is True:
            action_status = "success"
        elif result.get("ok") is False:
            action_status = "failed"

    keywords = set(tool_names)
    for domain, domain_keywords in DOMAIN_KEYWORDS.items():
        if any(keyword in normalized for keyword in domain_keywords):
            keywords.add(domain)
    return ContextIndexEntry(
        unit_id=unit.unit_id,
        kind=unit.kind,
        tool_names=frozenset(tool_names),
        entity_ids=frozenset(entity_ids),
        keywords=frozenset(keywords),
        action_status=action_status,
        ref_ids=frozenset(ref_ids),
        protected=unit.protected,
    )


def _score_entry(
    query: ContextQuery, entry: ContextIndexEntry
) -> tuple[int, str, list[str]]:
    score = 0
    matched_fields: list[str] = []
    if query.ref_ids and query.ref_ids.intersection(entry.ref_ids):
        score += 100
        matched_fields.append("ref_id")
    if query.entity_ids and query.entity_ids.intersection(entry.entity_ids):
        score += 80
        matched_fields.append("entity_id")
    if (
        entry.kind == "tool"
        and query.domains
        and query.domains.intersection(entry.keywords)
    ):
        score += 30
        matched_fields.append("domain")
    if entry.ref_ids and not matched_fields:
        score += 10
        matched_fields.append("available_ref")
    if score == 0:
        return 0, "", []
    reason = (
        "matched_ref_id"
        if "ref_id" in matched_fields
        else (
            "matched_entity_id"
            if "entity_id" in matched_fields
            else (
                "matched_domain"
                if "domain" in matched_fields
                else "available_ref_for_exact_request"
            )
        )
    )
    return score, reason, matched_fields


def _ordered_ref_ids(
    query: ContextQuery, entries: list[ContextIndexEntry]
) -> list[str]:
    ordered: list[str] = []
    for ref_id in query.ref_ids:
        if ref_id not in ordered:
            ordered.append(ref_id)
    for entry in entries:
        for ref_id in entry.ref_ids:
            if ref_id not in ordered:
                ordered.append(ref_id)
    return ordered


def _ref_payload_message(ref_id: str, payload: dict[str, Any]) -> dict[str, str]:
    body = {
        "ref_id": ref_id,
        "tool_name": payload.get("tool_name"),
        "summary": payload.get("summary"),
        "full_result": payload.get("full_result"),
    }
    return {
        "role": "system",
        "content": (
            "[Retrieved context ref]\n"
            + json.dumps(json_safe(body), ensure_ascii=False, sort_keys=True)
        ),
    }


def _tool_names(unit: ContextUnit) -> set[str]:
    names: set[str] = set()
    tool_name = unit.metadata.get("tool_name")
    if isinstance(tool_name, str) and tool_name:
        names.add(tool_name)
    for message in unit.messages:
        name = _message_field(message, "name")
        if isinstance(name, str) and name:
            names.add(name)
    return names


def _tool_result(unit: ContextUnit) -> dict[str, Any] | None:
    for message in unit.messages:
        if _message_field(message, "type") != "function_call_output":
            continue
        output = _message_field(message, "output")
        if isinstance(output, dict):
            return output
        if isinstance(output, str):
            return parse_json_object(output)
    return None


def _entity_ids(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"id", "todo_id", "expense_id"} and isinstance(
                item, (int, str)
            ):
                found.add(str(item))
            found.update(_entity_ids(item))
    elif isinstance(value, list):
        for item in value:
            found.update(_entity_ids(item))
    return found


def _message_field(message: Any, field: str) -> Any:
    if isinstance(message, dict):
        return message.get(field)
    return getattr(message, field, None)
