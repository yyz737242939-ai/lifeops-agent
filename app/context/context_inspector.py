from typing import Any


def inspect_assembly_report(report: dict[str, Any]) -> dict[str, Any]:
    """Build a compact explanation layer over the raw context assembly report."""
    selected_ids = set(report.get("selected_unit_ids", []))
    retrieved_ids = {
        item.get("unit_id")
        for item in report.get("retrieved_units", [])
        if isinstance(item, dict)
    }
    unit_reports = [
        unit for unit in report.get("units", []) if isinstance(unit, dict)
    ]
    protected_selected_ids = {
        unit.get("unit_id")
        for unit in unit_reports
        if unit.get("protected") and unit.get("unit_id") in selected_ids
    }
    recent_selected_ids = selected_ids - protected_selected_ids

    raw_tokens = int(report.get("estimated_input_tokens") or 0)
    assembled_tokens = int(report.get("assembled_estimated_input_tokens") or 0)
    token_reduction = max(raw_tokens - assembled_tokens, 0)
    token_reduction_ratio = (
        round(token_reduction / raw_tokens, 4) if raw_tokens > 0 else 0
    )

    composition = {
        "summary_messages": 1 if report.get("summary_inserted") else 0,
        "placeholder_summary_messages": (
            1 if report.get("placeholder_summary_inserted") else 0
        ),
        "protected_units": len(protected_selected_ids),
        "retrieved_units": int(report.get("retrieved_unit_count") or 0),
        "retrieved_refs": int(report.get("retrieved_ref_count") or 0),
        "recent_units": len(recent_selected_ids),
        "evicted_units": int(report.get("evicted_unit_count") or 0),
    }
    return {
        "overview": {
            "mode": report.get("mode"),
            "raw_message_count": report.get("raw_message_count"),
            "assembled_message_count": report.get("assembled_message_count"),
            "raw_estimated_tokens": raw_tokens,
            "assembled_estimated_tokens": assembled_tokens,
            "token_reduction_estimate": token_reduction,
            "token_reduction_ratio": token_reduction_ratio,
        },
        "composition": composition,
        "decisions": _decision_summary(report, composition),
        "diagnostics": _diagnostics(report),
    }


def _decision_summary(
    report: dict[str, Any],
    composition: dict[str, int],
) -> list[dict[str, Any]]:
    decisions = [
        {
            "name": "windowing",
            "status": (
                "evicted_old_units"
                if composition["evicted_units"] > 0
                else "within_recent_window"
            ),
            "selected_unit_count": report.get("selected_unit_count"),
            "evicted_unit_count": report.get("evicted_unit_count"),
            "recent_window_tokens": report.get("recent_window_tokens"),
            "recent_window_budget_tokens": report.get(
                "recent_window_budget_tokens"
            ),
        }
    ]

    if report.get("summary_inserted"):
        decisions.append(
            {
                "name": "summary",
                "status": "inserted",
                "source_unit_count": report.get("summary_source_unit_count"),
            }
        )
    elif report.get("placeholder_summary_inserted"):
        decisions.append({"name": "summary", "status": "placeholder_inserted"})
    else:
        decisions.append({"name": "summary", "status": "not_needed"})

    retrieval_query = report.get("retrieval_query") or {}
    if composition["retrieved_units"] or report.get("retrieved_refs"):
        retrieval_status = "retrieved"
    elif retrieval_query.get("exact_required"):
        retrieval_status = "no_match"
    else:
        retrieval_status = "not_required"
    decisions.append(
        {
            "name": "retrieval",
            "status": retrieval_status,
            "query": retrieval_query,
            "retrieved_unit_count": composition["retrieved_units"],
            "retrieved_ref_count": composition["retrieved_refs"],
        }
    )
    return decisions


def _diagnostics(report: dict[str, Any]) -> list[dict[str, str]]:
    diagnostics: list[dict[str, str]] = []
    if report.get("placeholder_summary_inserted"):
        diagnostics.append(
            {
                "code": "history_compacted_without_summary",
                "message": "Old units were evicted before a rolling summary was available.",
            }
        )

    retrieval_query = report.get("retrieval_query") or {}
    if (
        retrieval_query.get("exact_required")
        and report.get("evicted_unit_count", 0) > 0
        and not report.get("retrieved_units")
        and not report.get("retrieved_refs")
    ):
        diagnostics.append(
            {
                "code": "exact_request_without_retrieval_match",
                "message": "The current request needed exact context, but no old unit or ref matched.",
            }
        )

    for ref_report in report.get("retrieved_refs", []):
        if isinstance(ref_report, dict) and ref_report.get("status") == "rejected":
            diagnostics.append(
                {
                    "code": "context_ref_rejected",
                    "message": str(ref_report.get("ref_id")),
                }
            )
    return diagnostics
