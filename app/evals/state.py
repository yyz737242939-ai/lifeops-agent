"""Eval-owned whitelist state probes and safe before/after deltas."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from app.common.validation import require_unique_non_empty_strings
from app.evals.errors import EvalStateProbeError, EvalStateProbeErrorCode
from app.evals.models import (
    FrozenJson,
    freeze_eval_object,
    freeze_eval_value,
    require_stable_eval_id,
)
from app.evals.workspace import EvalWorkspacePaths


@dataclass(frozen=True)
class EvalStateSnapshot:
    probe_id: str
    safe_values: Mapping[str, FrozenJson]

    def __post_init__(self) -> None:
        require_stable_eval_id(self.probe_id, "probe_id")
        object.__setattr__(
            self,
            "safe_values",
            freeze_eval_object(self.safe_values, "safe_values"),
        )


@dataclass(frozen=True)
class EvalStateChange:
    probe_id: str
    key: str
    before_present: bool
    after_present: bool
    before: FrozenJson = None
    after: FrozenJson = None

    def __post_init__(self) -> None:
        require_stable_eval_id(self.probe_id, "probe_id")
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("key must be a non-empty string.")
        if not isinstance(self.before_present, bool) or not isinstance(
            self.after_present, bool
        ):
            raise ValueError("change presence flags must be bool values.")
        if not self.before_present and self.before is not None:
            raise ValueError("before must be None when before_present is false.")
        if not self.after_present and self.after is not None:
            raise ValueError("after must be None when after_present is false.")
        object.__setattr__(self, "before", freeze_eval_value(self.before, "before"))
        object.__setattr__(self, "after", freeze_eval_value(self.after, "after"))


@dataclass(frozen=True)
class EvalStateDelta:
    before: tuple[EvalStateSnapshot, ...]
    after: tuple[EvalStateSnapshot, ...]
    changes: tuple[EvalStateChange, ...]

    def __post_init__(self) -> None:
        for field_name in ("before", "after", "changes"):
            if not isinstance(getattr(self, field_name), tuple):
                raise ValueError(f"{field_name} must be a tuple.")
        _snapshot_index(self.before)
        _snapshot_index(self.after)
        if not all(isinstance(change, EvalStateChange) for change in self.changes):
            raise ValueError("changes must contain only EvalStateChange values.")


class EvalStateProbe(Protocol):
    @property
    def probe_id(self) -> str: ...

    def read(self, workspace: EvalWorkspacePaths) -> Mapping[str, object]: ...


class EvalStateProbeRegistry:
    def __init__(self, probes: tuple[EvalStateProbe, ...]) -> None:
        if not isinstance(probes, tuple):
            raise ValueError("probes must be a tuple.")
        ids = tuple(probe.probe_id for probe in probes)
        require_unique_non_empty_strings(ids, "probe_ids")
        for probe_id in ids:
            require_stable_eval_id(probe_id, "probe_id")
        self._probes = dict(zip(ids, probes))

    @property
    def probe_ids(self) -> tuple[str, ...]:
        return tuple(self._probes)

    def capture(
        self,
        probe_ids: tuple[str, ...],
        workspace: EvalWorkspacePaths,
    ) -> tuple[EvalStateSnapshot, ...]:
        require_unique_non_empty_strings(probe_ids, "probe_ids")
        if not isinstance(workspace, EvalWorkspacePaths):
            raise ValueError("workspace must be EvalWorkspacePaths.")
        snapshots: list[EvalStateSnapshot] = []
        for probe_id in probe_ids:
            require_stable_eval_id(probe_id, "probe_id")
            probe = self._probes.get(probe_id)
            if probe is None:
                raise EvalStateProbeError(
                    "Eval state probe is not registered.",
                    code=EvalStateProbeErrorCode.UNKNOWN_PROBE,
                )
            try:
                values = probe.read(workspace)
                snapshots.append(EvalStateSnapshot(probe_id, values))
            except EvalStateProbeError:
                raise
            except Exception as exc:
                raise EvalStateProbeError(
                    "Eval state probe failed.",
                    code=EvalStateProbeErrorCode.PROBE_FAILED,
                ) from exc
        return tuple(snapshots)


def build_state_delta(
    before: tuple[EvalStateSnapshot, ...],
    after: tuple[EvalStateSnapshot, ...],
) -> EvalStateDelta:
    before_by_id = _snapshot_index(before)
    after_by_id = _snapshot_index(after)
    if tuple(before_by_id) != tuple(after_by_id):
        raise EvalStateProbeError(
            "Before and after snapshots do not contain the same probes.",
            code=EvalStateProbeErrorCode.SNAPSHOT_MISMATCH,
        )
    changes: list[EvalStateChange] = []
    for probe_id, before_snapshot in before_by_id.items():
        after_snapshot = after_by_id[probe_id]
        keys = sorted(set(before_snapshot.safe_values) | set(after_snapshot.safe_values))
        for key in keys:
            before_present = key in before_snapshot.safe_values
            after_present = key in after_snapshot.safe_values
            before_value = before_snapshot.safe_values.get(key)
            after_value = after_snapshot.safe_values.get(key)
            if before_present == after_present and before_value == after_value:
                continue
            changes.append(
                EvalStateChange(
                    probe_id=probe_id,
                    key=key,
                    before_present=before_present,
                    after_present=after_present,
                    before=before_value,
                    after=after_value,
                )
            )
    return EvalStateDelta(before=before, after=after, changes=tuple(changes))


def _snapshot_index(
    snapshots: tuple[EvalStateSnapshot, ...],
) -> dict[str, EvalStateSnapshot]:
    if not isinstance(snapshots, tuple) or not all(
        isinstance(snapshot, EvalStateSnapshot) for snapshot in snapshots
    ):
        raise ValueError("snapshots must contain only EvalStateSnapshot values.")
    ids = tuple(snapshot.probe_id for snapshot in snapshots)
    if len(set(ids)) != len(ids):
        raise ValueError("snapshots must not contain duplicate probe IDs.")
    return {snapshot.probe_id: snapshot for snapshot in snapshots}
