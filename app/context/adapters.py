"""Empty production defaults and recording fakes for future Context slots."""

from __future__ import annotations

from app.context.models import ContextContribution, ContextQuery


class EmptyProfileProvider:
    def load_profile(self) -> ContextContribution | None:
        return None


class EmptyMemoryRetriever:
    def search(
        self,
        query: ContextQuery,
        max_items: int,
        max_tokens: int,
    ) -> tuple[ContextContribution, ...]:
        return ()


class FakeProfileProvider:
    def __init__(self, contribution: ContextContribution | None) -> None:
        if contribution is not None and not isinstance(
            contribution, ContextContribution
        ):
            raise ValueError("contribution must be ContextContribution when provided.")
        self._contribution = contribution
        self.load_count = 0

    def load_profile(self) -> ContextContribution | None:
        self.load_count += 1
        return self._contribution


class FakeMemoryRetriever:
    def __init__(self, contributions: tuple[ContextContribution, ...]) -> None:
        if not isinstance(contributions, tuple) or any(
            not isinstance(item, ContextContribution) for item in contributions
        ):
            raise ValueError("contributions must contain ContextContribution values.")
        self._contributions = contributions
        self.calls: list[tuple[ContextQuery, int, int]] = []

    def search(
        self,
        query: ContextQuery,
        max_items: int,
        max_tokens: int,
    ) -> tuple[ContextContribution, ...]:
        self.calls.append((query, max_items, max_tokens))
        return self._contributions
