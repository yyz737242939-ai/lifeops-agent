"""Per-case isolated filesystem lifecycle for local evaluations."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.evals.errors import EvalWorkspaceError, EvalWorkspaceErrorCode
from app.evals.models import require_stable_eval_id


_WORKSPACE_OWNERSHIP = object()


@dataclass(frozen=True)
class EvalWorkspacePaths:
    root: Path
    database_path: Path
    log_root: Path
    context_root: Path
    memory_root: Path
    report_root: Path

    def __post_init__(self) -> None:
        if not all(isinstance(getattr(self, name), Path) for name in self.__dataclass_fields__):
            raise ValueError("workspace paths must be Path values.")
        root = self.root.resolve()
        for name in self.__dataclass_fields__:
            if name == "root":
                continue
            try:
                getattr(self, name).resolve().relative_to(root)
            except ValueError as exc:
                raise ValueError("workspace paths must remain inside root.") from exc


class EvalWorkspace:
    """Own exactly one freshly-created case root and its cleanup decision."""

    def __init__(self, paths: EvalWorkspacePaths, *, _ownership: object = None) -> None:
        if not isinstance(paths, EvalWorkspacePaths):
            raise ValueError("paths must be EvalWorkspacePaths.")
        if _ownership is not _WORKSPACE_OWNERSHIP or not paths.root.name.startswith(
            "lifeops-eval-"
        ):
            raise ValueError("EvalWorkspace must be created by EvalWorkspaceFactory.")
        self.paths = paths
        self._closed = False
        self._retained = False

    @property
    def closed(self) -> bool:
        return self._closed

    @property
    def retained(self) -> bool:
        return self._retained

    def close(self, *, keep: bool = False) -> None:
        if not isinstance(keep, bool):
            raise ValueError("keep must be a bool.")
        if self._closed:
            return
        if keep:
            self._retained = True
            self._closed = True
            return
        try:
            shutil.rmtree(self.paths.root)
        except OSError as exc:
            raise EvalWorkspaceError(
                "Eval workspace cleanup failed.",
                code=EvalWorkspaceErrorCode.CLEANUP_FAILED,
            ) from exc
        self._closed = True

    def __enter__(self) -> EvalWorkspace:
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


class EvalWorkspaceFactory:
    def __init__(self, base_root: Path | None = None) -> None:
        if base_root is not None and not isinstance(base_root, Path):
            raise ValueError("base_root must be a Path or None.")
        self._base_root = base_root.resolve() if base_root is not None else None

    def create(self, case_id: str) -> EvalWorkspace:
        require_stable_eval_id(case_id, "case_id")
        try:
            if self._base_root is not None:
                self._base_root.mkdir(parents=True, exist_ok=True)
            root = Path(
                tempfile.mkdtemp(
                    prefix=f"lifeops-eval-{case_id}-",
                    dir=self._base_root,
                )
            ).resolve()
            paths = EvalWorkspacePaths(
                root=root,
                database_path=root / "data" / "lifeops.sqlite3",
                log_root=root / "logs" / "sessions",
                context_root=root / "context",
                memory_root=root / "memory",
                report_root=root / "reports",
            )
            for directory in (
                paths.database_path.parent,
                paths.log_root,
                paths.context_root,
                paths.memory_root,
                paths.report_root,
            ):
                directory.mkdir(parents=True, exist_ok=False)
            return EvalWorkspace(paths, _ownership=_WORKSPACE_OWNERSHIP)
        except (OSError, ValueError) as exc:
            if "root" in locals() and root.is_dir():
                shutil.rmtree(root, ignore_errors=True)
            raise EvalWorkspaceError(
                "Eval workspace preparation failed.",
                code=EvalWorkspaceErrorCode.PREPARE_FAILED,
            ) from exc
