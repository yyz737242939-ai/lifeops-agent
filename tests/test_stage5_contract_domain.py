from __future__ import annotations

import inspect
import unittest
from dataclasses import fields

from app.domains.contracts import (
    DomainContextProvider,
    DomainMemoryCandidateProvider,
    DomainPlanningReadModel,
)
from app.domains.research.models import (
    ResearchContextCandidate,
    ResearchMemoryCandidate,
)
from app.domains.research.read_models import ResearchReadService
from app.domains.references import KnowledgeReferenceResolution
from app.domains.travel.models import (
    TravelContextCandidate,
    TravelPreferenceCandidate,
)
from app.domains.travel.read_models import TravelReadService


def _parameter_shape(owner: type, method_name: str) -> tuple[tuple[str, object], ...]:
    signature = inspect.signature(getattr(owner, method_name))
    return tuple(
        (parameter.name, parameter.kind)
        for parameter in signature.parameters.values()
    )


class Stage5DomainContractTest(unittest.TestCase):
    def test_read_implementations_match_shared_protocol_call_shapes(self) -> None:
        cases = (
            (DomainPlanningReadModel, "get_planning_snapshot"),
            (DomainContextProvider, "query_context_candidates"),
            (DomainMemoryCandidateProvider, "query_memory_candidates"),
        )

        for protocol, method_name in cases:
            expected = _parameter_shape(protocol, method_name)
            for implementation in (ResearchReadService, TravelReadService):
                with self.subTest(
                    implementation=implementation.__name__, method=method_name
                ):
                    self.assertEqual(
                        _parameter_shape(implementation, method_name), expected
                    )

    def test_context_and_memory_candidates_keep_only_true_shared_fields(self) -> None:
        research_context = {item.name for item in fields(ResearchContextCandidate)}
        travel_context = {item.name for item in fields(TravelContextCandidate)}
        research_memory = {item.name for item in fields(ResearchMemoryCandidate)}
        travel_memory = {item.name for item in fields(TravelPreferenceCandidate)}

        self.assertEqual(
            research_context & travel_context,
            {
                "candidate_id",
                "item_kind",
                "content",
                "provenance",
                "estimated_chars",
                "created_at",
            },
        )
        self.assertEqual(
            research_memory & travel_memory,
            {"candidate_id", "provenance", "created_at"},
        )

    def test_knowledge_resolution_shape_remains_explicit(self) -> None:
        self.assertEqual(
            tuple(item.name for item in fields(KnowledgeReferenceResolution)),
            (
                "reference",
                "status",
                "title",
                "summary",
                "provenance",
                "error_code",
            ),
        )


if __name__ == "__main__":
    unittest.main()
