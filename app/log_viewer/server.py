import argparse
import json
import re
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote, urlparse

from app.utils.json_file import read_json_file


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SESSION_DIR = PROJECT_ROOT / "logs" / "sessions"
LEGACY_CONVERSATION_DIR = PROJECT_ROOT / "logs" / "conversations"
# Kept as a patch point for legacy viewer tests and old integrations.
CONVERSATION_DIR = LEGACY_CONVERSATION_DIR
STATIC_DIR = Path(__file__).resolve().parent / "static"
SESSION_ID_PATTERN = re.compile(r"^session_[0-9_]+$")
KINDS = {"events", "llm", "application", "trace", "raw"}
NEW_LOG_FILES = {
    "events": "events.jsonl",
    "llm": "llm.jsonl",
    "application": "application.log",
}


def _read_json(path: Path) -> dict:
    return read_json_file(path, dict)


def _read_jsonl(path: Path) -> list[dict]:
    records = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise ValueError(f"Invalid JSONL at line {line_number}") from error
        if not isinstance(record, dict):
            raise ValueError(f"JSONL line {line_number} must contain an object")
        records.append(record)
    return records


def _read_application_log(path: Path) -> list[dict]:
    records = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split(" | ", 3)
        if len(parts) == 4:
            timestamp, level, logger_name, message = parts
        else:
            timestamp, level, logger_name, message = None, "UNKNOWN", None, line
        records.append(
            {
                "timestamp": timestamp,
                "event": f"application.{level.lower()}",
                "level": level,
                "logger": logger_name,
                "message": message,
                "line": index,
            }
        )
    return records


def _read_first_metadata(paths: tuple[Path, ...]) -> dict:
    """Read the first valid metadata source from a new or legacy session."""
    for path in paths:
        if not path.exists():
            continue
        try:
            return _read_json(path)
        except (OSError, ValueError):
            continue
    return {}


def _list_current_sessions() -> list[dict]:
    if not SESSION_DIR.exists():
        return []
    sessions = []
    for path in SESSION_DIR.iterdir():
        if not path.is_dir() or not SESSION_ID_PATTERN.fullmatch(path.name):
            continue
        metadata = _read_first_metadata((path / "metadata.json",))
        sessions.append(
            {
                "session_id": path.name,
                "started_at": metadata.get("started_at"),
                "has_events": (path / "events.jsonl").exists(),
                "has_llm": (path / "llm.jsonl").exists(),
                "has_application": (path / "application.log").exists(),
                "legacy": False,
            }
        )
    return sessions


def _list_legacy_sessions() -> list[dict]:
    """Expose historical Trace/Raw pairs through the new channel names."""
    if not CONVERSATION_DIR.exists():
        return []
    legacy_ids = {
        path.name.removesuffix("_trace.json")
        for path in CONVERSATION_DIR.glob("session_*_trace.json")
    }
    legacy_ids.update(
        path.name.removesuffix("_raw.json")
        for path in CONVERSATION_DIR.glob("session_*_raw.json")
    )
    sessions = []
    for session_id in legacy_ids:
        if not SESSION_ID_PATTERN.fullmatch(session_id):
            continue
        trace_path = CONVERSATION_DIR / f"{session_id}_trace.json"
        raw_path = CONVERSATION_DIR / f"{session_id}_raw.json"
        metadata = _read_first_metadata((trace_path, raw_path))
        sessions.append(
            {
                "session_id": session_id,
                "started_at": metadata.get("started_at"),
                "has_events": trace_path.exists(),
                "has_llm": raw_path.exists(),
                "has_application": False,
                "has_trace": trace_path.exists(),
                "has_raw": raw_path.exists(),
                "legacy": True,
            }
        )
    return sessions


def list_sessions() -> list[dict]:
    """List current and legacy sessions in newest-first identifier order."""
    sessions = _list_current_sessions() + _list_legacy_sessions()
    return sorted(sessions, key=lambda item: item["session_id"], reverse=True)


def _load_current_log(session_id: str, kind: str) -> dict:
    session_path = SESSION_DIR / session_id
    path = session_path / NEW_LOG_FILES[kind]
    if not path.exists():
        raise FileNotFoundError(path)
    metadata = _read_first_metadata((session_path / "metadata.json",))
    records = (
        _read_application_log(path) if kind == "application" else _read_jsonl(path)
    )
    return {
        "session_id": session_id,
        "started_at": metadata.get("started_at"),
        "kind": kind,
        "events": records,
    }


def _load_legacy_log(session_id: str, kind: str) -> dict:
    legacy_kind = {"events": "trace", "llm": "raw"}.get(kind, kind)
    path = CONVERSATION_DIR / f"{session_id}_{legacy_kind}.json"
    if not path.exists():
        raise FileNotFoundError(path)
    return _read_json(path)


def load_session_log(session_id: str, kind: str) -> dict:
    """Load one channel while safely mapping historical channel names."""
    if not SESSION_ID_PATTERN.fullmatch(session_id):
        raise ValueError("Invalid session id")
    if kind not in KINDS:
        raise ValueError("Invalid log kind")
    if kind in NEW_LOG_FILES:
        try:
            return _load_current_log(session_id, kind)
        except FileNotFoundError:
            if kind in {"events", "llm"}:
                return _load_legacy_log(session_id, kind)
            raise
    return _load_legacy_log(session_id, kind)


class LogViewerHandler(BaseHTTPRequestHandler):
    """Serve read-only log APIs and the bundled static Viewer UI."""

    server_version = "LifeOpsLogViewer/2.0"

    def do_GET(self) -> None:
        path = unquote(urlparse(self.path).path)
        if path == "/api/sessions":
            self._send_json({"sessions": list_sessions()})
            return

        match = re.fullmatch(
            r"/api/sessions/([^/]+)/(events|llm|application|trace|raw)", path
        )
        if match:
            try:
                payload = load_session_log(match.group(1), match.group(2))
            except ValueError as error:
                self._send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
            except FileNotFoundError:
                self._send_json({"error": "Log file not found"}, HTTPStatus.NOT_FOUND)
            except json.JSONDecodeError:
                self._send_json(
                    {"error": "Log file contains invalid JSON"},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )
            else:
                self._send_json(payload)
            return

        static_path = "index.html" if path == "/" else path.removeprefix("/")
        self._send_static(static_path)

    def _send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(content)

    def _send_static(self, relative_path: str) -> None:
        allowed_files = {
            "index.html": "text/html; charset=utf-8",
            "styles.css": "text/css; charset=utf-8",
            "app.js": "text/javascript; charset=utf-8",
        }
        content_type = allowed_files.get(relative_path)
        if content_type is None:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content = (STATIC_DIR / relative_path).read_bytes()
        except FileNotFoundError:
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def log_message(self, format: str, *args: object) -> None:
        return


def serve(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    """Run the local threaded Viewer server until interrupted."""
    server = ThreadingHTTPServer((host, port), LogViewerHandler)
    url = f"http://{host}:{port}"
    print(f"LifeOps log viewer: {url}")
    print("Press Ctrl+C to stop.")
    if open_browser:
        threading.Timer(0.4, webbrowser.open, args=(url,)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nLog viewer stopped.")
    finally:
        server.server_close()


def main() -> None:
    """Parse CLI options and start the local Viewer."""
    parser = argparse.ArgumentParser(description="View LifeOps Agent logs.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    serve(host=args.host, port=args.port, open_browser=not args.no_browser)


if __name__ == "__main__":
    main()
