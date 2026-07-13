"""File-backed observability logs."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from app.common.serialization import to_json
from app.common.time import utc_now_iso
from app.observability.events import LogLlmInteraction, LogRuntimeEvent
from app.runtime.models import RuntimeRequest


@dataclass(frozen=True)
class SessionLogMetadata:
    session_id: str
    started_at: str = field(default_factory=utc_now_iso)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("session_id must be non-empty.")
        if not self.started_at.strip():
            raise ValueError("started_at must be non-empty.")
        if not isinstance(self.metadata, dict):
            raise ValueError("metadata must be a dict.")


class JsonlLogWriter:
    """Append one JSON object per line."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)

    def append(self, entry: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(to_json(entry))
            handle.write("\n")

    def read_all(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        import json

        rows: list[dict[str, Any]] = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rows.append(json.loads(line))
        return rows


class EventLogWriter:
    """File-backed structured runtime event writer."""

    def __init__(self, path: str | Path) -> None:
        self._writer = JsonlLogWriter(path)

    @property
    def path(self) -> Path:
        return self._writer.path

    def append(self, event: LogRuntimeEvent) -> LogRuntimeEvent:
        self._writer.append(
            {
                "id": event.id,
                "timestamp": event.created_at,
                "session_id": event.session_id,
                "run_id": event.run_id,
                "turn_id": event.turn_id,
                "seq": event.seq,
                "event_type": event.event_type,
                "level": event.level,
                "payload": event.payload,
            }
        )
        return event

    def read_all(self) -> list[dict[str, Any]]:
        return self._writer.read_all()


class LlmLogWriter:
    """File-backed raw LLM request-response writer."""

    def __init__(self, path: str | Path) -> None:
        self._writer = JsonlLogWriter(path)

    @property
    def path(self) -> Path:
        return self._writer.path

    def append(self, interaction: LogLlmInteraction) -> LogLlmInteraction:
        self._writer.append(
            {
                "id": interaction.id,
                "timestamp": interaction.created_at,
                "session_id": interaction.session_id,
                "run_id": interaction.run_id,
                "turn_id": interaction.turn_id,
                "seq": interaction.seq,
                "provider": interaction.provider,
                "model": interaction.model,
                "request": interaction.request,
                "response": interaction.response,
                "status": interaction.status,
                "error_code": interaction.error_code,
            }
        )
        return interaction

    def read_all(self) -> list[dict[str, Any]]:
        return self._writer.read_all()


class RequestLlmLog:
    """Assign ordered interaction sequence numbers for one RuntimeRequest."""

    def __init__(self, writer: LlmLogWriter, request: RuntimeRequest) -> None:
        self._writer = writer
        self._request = request
        self._seq = 0

    def record(
        self,
        *,
        provider: str,
        model: str,
        request: dict[str, Any],
        response: dict[str, Any] | None,
        status: str = "ok",
        error_code: str | None = None,
    ) -> None:
        self._seq += 1
        self._writer.append(
            LogLlmInteraction(
                run_id=self._request.run_id,
                session_id=self._request.session_id,
                turn_id=self._request.turn_id,
                seq=self._seq,
                provider=provider,
                model=model,
                request=request,
                response=response,
                status=status,
                error_code=error_code,
            )
        )


class SessionLogWriter:
    """Owns the three observability log files for one runtime session."""

    def __init__(
        self,
        session_dir: str | Path,
        *,
        metadata: SessionLogMetadata | None = None,
    ) -> None:
        self.session_dir = Path(session_dir)
        self.session_dir.mkdir(parents=True, exist_ok=True)
        self.event_log = EventLogWriter(self.session_dir / "events.jsonl")
        self.llm_log = LlmLogWriter(self.session_dir / "llm.jsonl")
        self.application_log_path.touch(exist_ok=True)
        if metadata is not None:
            self.write_metadata(metadata)

    @classmethod
    def create(
        cls,
        root: str | Path,
        *,
        session_id: str,
        metadata: dict[str, Any] | None = None,
    ) -> "SessionLogWriter":
        safe_started_at = utc_now_iso().replace(":", "").replace("+", "Z")
        session_dir = Path(root) / f"session_{safe_started_at}_{session_id}"
        return cls(
            session_dir,
            metadata=SessionLogMetadata(
                session_id=session_id,
                metadata=metadata or {},
            ),
        )

    @property
    def application_log_path(self) -> Path:
        return self.session_dir / "application.log"

    def write_metadata(self, metadata: SessionLogMetadata) -> None:
        (self.session_dir / "metadata.json").write_text(
            to_json(asdict(metadata)),
            encoding="utf-8",
        )

    def append_event(self, event: LogRuntimeEvent) -> LogRuntimeEvent:
        return self.event_log.append(event)

    def append_llm(self, interaction: LogLlmInteraction) -> LogLlmInteraction:
        return self.llm_log.append(interaction)
