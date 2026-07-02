from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from app.skills.skill_loader import SKILLS_DIR


MAX_SOURCE_BYTES = 200_000
SOURCE_TIMEOUT_SECONDS = 8
SOURCE_USER_AGENT = "LifeOps-Agent/0.1 read-only news source fetcher"
ALLOWED_NEWS_URLS = frozenset(
    {
        "https://huggingface.co/papers",
        "https://huggingface.co/blog",
    }
)


@dataclass(frozen=True)
class SkillSource:
    skill_name: str
    source_id: str
    name: str
    url: str
    kind: str
    allowed: bool
    description: str
    relative_path: str


class SkillSourceError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_skill_source(
    skill_name: str,
    source_id: str,
    *,
    skills_dir: Path = SKILLS_DIR,
) -> SkillSource:
    """Load one declared source from a Skill-owned sources directory."""
    if not source_id or not isinstance(source_id, str):
        raise SkillSourceError("invalid_arguments", "source_id must be a non-empty string")

    skill_dir = (skills_dir / skill_name).resolve()
    sources_dir = skill_dir / "sources"
    if not sources_dir.is_dir():
        raise SkillSourceError(
            "skill_source_manifest_not_found",
            f"Source directory not found for skill {skill_name!r}",
        )

    for manifest_path in sorted(sources_dir.glob("*.yaml")):
        declaration = _read_yaml_object(manifest_path)
        if declaration.get("id") == source_id:
            return _source_from_declaration(skill_name, skill_dir, manifest_path, declaration)

    raise SkillSourceError(
        "skill_source_not_found",
        f"Source {source_id!r} is not declared for skill {skill_name!r}",
    )


def fetch_skill_source(
    skill_name: str,
    source_id: str,
    *,
    skills_dir: Path = SKILLS_DIR,
    max_bytes: int = MAX_SOURCE_BYTES,
    timeout_seconds: float = SOURCE_TIMEOUT_SECONDS,
) -> dict[str, Any]:
    """Fetch a declared read-only source with size and URL controls."""
    try:
        source = load_skill_source(skill_name, source_id, skills_dir=skills_dir)
    except SkillSourceError as error:
        return {
            "ok": False,
            "action": "fetch_news_source",
            "error": error.code,
            "message": error.message,
            "source_id": source_id,
        }

    request = Request(source.url, headers={"User-Agent": SOURCE_USER_AGENT})
    fetched_at = datetime.now(UTC).isoformat()
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            content_type = str(response.headers.get("Content-Type", ""))
            raw = response.read(max_bytes + 1)
            truncated = len(raw) > max_bytes
            if truncated:
                raw = raw[:max_bytes]
            charset = response.headers.get_content_charset() or "utf-8"
            content = raw.decode(charset, errors="replace")
            status = getattr(response, "status", 200)
    except HTTPError as error:
        return _fetch_error(source, fetched_at, "source_http_error", str(error), error.code)
    except (URLError, TimeoutError, OSError) as error:
        return _fetch_error(source, fetched_at, "source_fetch_failed", str(error), None)

    return {
        "ok": True,
        "action": "fetch_news_source",
        "skill": source.skill_name,
        "source_id": source.source_id,
        "name": source.name,
        "url": source.url,
        "kind": source.kind,
        "fetched_at": fetched_at,
        "status": status,
        "content_type": content_type,
        "chars": len(content),
        "truncated": truncated,
        "content": content,
        "error": None,
    }


def _fetch_error(
    source: SkillSource,
    fetched_at: str,
    code: str,
    message: str,
    status: int | None,
) -> dict[str, Any]:
    return {
        "ok": False,
        "action": "fetch_news_source",
        "error": code,
        "message": message,
        "skill": source.skill_name,
        "source_id": source.source_id,
        "url": source.url,
        "fetched_at": fetched_at,
        "status": status,
    }


def _read_yaml_object(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise SkillSourceError(
            "skill_source_manifest_invalid",
            f"Could not read source manifest {path.name}: {error}",
        ) from error

    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        key, separator, value = stripped.partition(":")
        if not separator or not key.strip():
            raise SkillSourceError(
                "skill_source_manifest_invalid",
                f"Invalid source manifest line {line_number} in {path.name}",
            )
        data[key.strip()] = _parse_scalar(value.strip())
    return data


def _parse_scalar(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    return value.strip("\"'")


def _source_from_declaration(
    skill_name: str,
    skill_dir: Path,
    manifest_path: Path,
    declaration: dict[str, Any],
) -> SkillSource:
    source_id = _required_string(declaration, "id", manifest_path)
    name = _required_string(declaration, "name", manifest_path)
    url = _required_string(declaration, "url", manifest_path)
    kind = _required_string(declaration, "kind", manifest_path)
    description = str(declaration.get("description") or "")
    allowed = declaration.get("allowed") is True

    _validate_source_url(source_id, url, kind, allowed)
    return SkillSource(
        skill_name=skill_name,
        source_id=source_id,
        name=name,
        url=url,
        kind=kind,
        allowed=allowed,
        description=description,
        relative_path=manifest_path.relative_to(skill_dir).as_posix(),
    )


def _required_string(declaration: dict[str, Any], key: str, path: Path) -> str:
    value = declaration.get(key)
    if not isinstance(value, str) or not value:
        raise SkillSourceError(
            "skill_source_manifest_invalid",
            f"Source manifest {path.name} must declare a non-empty {key}",
        )
    return value


def _validate_source_url(source_id: str, url: str, kind: str, allowed: bool) -> None:
    parsed = urlparse(url)
    if kind != "html":
        raise SkillSourceError(
            "skill_source_forbidden",
            f"Source {source_id!r} must declare kind html",
        )
    if not allowed:
        raise SkillSourceError(
            "skill_source_forbidden",
            f"Source {source_id!r} is not marked allowed",
        )
    if parsed.scheme != "https" or parsed.netloc != "huggingface.co":
        raise SkillSourceError(
            "skill_source_forbidden",
            f"Source {source_id!r} must use the Hugging Face HTTPS host",
        )
    if url not in ALLOWED_NEWS_URLS:
        raise SkillSourceError(
            "skill_source_forbidden",
            f"Source {source_id!r} URL is not in the news allowlist",
        )
