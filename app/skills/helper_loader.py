import importlib
import json
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.skills.skill_loader import SKILLS_DIR
from app.utils.serialization import json_safe


_HELPER_EXECUTOR = ThreadPoolExecutor(max_workers=2, thread_name_prefix="lifeops-helper")


@dataclass(frozen=True)
class SkillHelper:
    skill_name: str
    helper_id: str
    module: str
    function: str
    read_only: bool
    timeout_seconds: float
    parameters: dict[str, Any]


class SkillHelperError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def load_skill_helper(
    skill_name: str,
    helper_id: str,
    *,
    skills_dir: Path = SKILLS_DIR,
) -> SkillHelper:
    """Load one declared helper from a Skill-owned helper manifest."""
    if not helper_id or not isinstance(helper_id, str):
        raise SkillHelperError("invalid_arguments", "helper_id must be a non-empty string")

    manifest = _read_manifest(skill_name, skills_dir)
    helpers = manifest.get("helpers")
    if not isinstance(helpers, dict):
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            f"{skill_name} helper manifest must contain a helpers object",
        )
    declaration = helpers.get(helper_id)
    if not isinstance(declaration, dict):
        raise SkillHelperError(
            "skill_helper_not_found",
            f"Helper {helper_id!r} is not declared for skill {skill_name!r}",
        )
    return _helper_from_declaration(skill_name, helper_id, declaration)


def run_skill_helper(
    skill_name: str,
    helper_id: str,
    arguments: dict[str, Any],
    *,
    skills_dir: Path = SKILLS_DIR,
) -> dict[str, Any]:
    """Run one declared read-only helper with schema and timeout checks."""
    try:
        helper = load_skill_helper(skill_name, helper_id, skills_dir=skills_dir)
        _validate_arguments(helper.parameters, arguments)
        function = _load_helper_function(helper)
        future = _HELPER_EXECUTOR.submit(function, **arguments)
        result = future.result(timeout=helper.timeout_seconds)
    except FutureTimeoutError:
        future.cancel()
        return {
            "ok": False,
            "action": "run_news_helper",
            "error": "skill_helper_timeout",
            "message": f"Helper {helper_id!r} exceeded its timeout",
            "helper_id": helper_id,
        }
    except SkillHelperError as error:
        return {
            "ok": False,
            "action": "run_news_helper",
            "error": error.code,
            "message": error.message,
            "helper_id": helper_id,
        }
    except Exception as error:
        return {
            "ok": False,
            "action": "run_news_helper",
            "error": "skill_helper_failed",
            "message": str(error),
            "helper_id": helper_id,
        }

    return {
        "ok": True,
        "action": "run_news_helper",
        "skill": skill_name,
        "helper_id": helper_id,
        "result": json_safe(result),
    }


def _read_manifest(skill_name: str, skills_dir: Path) -> dict[str, Any]:
    manifest_path = skills_dir / skill_name / "helpers" / "manifest.json"
    if not manifest_path.is_file():
        raise SkillHelperError(
            "skill_helper_manifest_not_found",
            f"Helper manifest not found for skill {skill_name!r}",
        )
    try:
        raw = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            f"Invalid helper manifest JSON: {error}",
        ) from error
    if not isinstance(raw, dict):
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            "Helper manifest root must be a JSON object",
        )
    return raw


def _helper_from_declaration(
    skill_name: str,
    helper_id: str,
    declaration: dict[str, Any],
) -> SkillHelper:
    module = _required_string(declaration, "module", helper_id)
    function = _required_string(declaration, "function", helper_id)
    read_only = declaration.get("read_only") is True
    timeout_seconds = declaration.get("timeout_seconds", 3)
    parameters = declaration.get("parameters")

    if not read_only:
        raise SkillHelperError(
            "skill_helper_forbidden",
            f"Helper {helper_id!r} must be declared read_only",
        )
    if not isinstance(timeout_seconds, (int, float)) or timeout_seconds <= 0:
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            f"Helper {helper_id!r} must declare a positive timeout_seconds",
        )
    if not isinstance(parameters, dict):
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            f"Helper {helper_id!r} must declare a parameters schema",
        )

    expected_prefix = f"app.skills.{skill_name}.helpers."
    if not module.startswith(expected_prefix):
        raise SkillHelperError(
            "skill_helper_forbidden",
            f"Helper {helper_id!r} must live under {expected_prefix}",
        )
    if function.startswith("_") or "." in function:
        raise SkillHelperError(
            "skill_helper_forbidden",
            f"Helper {helper_id!r} function name is not allowed",
        )

    return SkillHelper(
        skill_name=skill_name,
        helper_id=helper_id,
        module=module,
        function=function,
        read_only=read_only,
        timeout_seconds=float(timeout_seconds),
        parameters=parameters,
    )


def _required_string(declaration: dict[str, Any], key: str, helper_id: str) -> str:
    value = declaration.get(key)
    if not isinstance(value, str) or not value:
        raise SkillHelperError(
            "skill_helper_manifest_invalid",
            f"Helper {helper_id!r} must declare a non-empty {key}",
        )
    return value


def _validate_arguments(schema: dict[str, Any], arguments: dict[str, Any]) -> None:
    if not isinstance(arguments, dict):
        raise SkillHelperError("invalid_arguments", "arguments must be an object")

    properties = schema.get("properties")
    required = schema.get("required", [])
    if not isinstance(properties, dict) or not isinstance(required, list):
        raise SkillHelperError("skill_helper_manifest_invalid", "invalid parameters schema")

    unknown = set(arguments) - set(properties)
    if unknown:
        raise SkillHelperError(
            "invalid_arguments",
            f"Unexpected helper arguments: {sorted(unknown)}",
        )
    missing = [name for name in required if name not in arguments]
    if missing:
        raise SkillHelperError(
            "invalid_arguments",
            f"Missing helper arguments: {missing}",
        )

    for name, value in arguments.items():
        declaration = properties[name]
        if not isinstance(declaration, dict):
            raise SkillHelperError("skill_helper_manifest_invalid", "invalid property schema")
        _validate_value_type(name, value, declaration.get("type"))


def _validate_value_type(name: str, value: Any, expected_type: Any) -> None:
    if expected_type == "string" and not isinstance(value, str):
        raise SkillHelperError("invalid_arguments", f"{name} must be a string")
    if expected_type == "integer" and not isinstance(value, int):
        raise SkillHelperError("invalid_arguments", f"{name} must be an integer")
    if expected_type == "array" and not isinstance(value, list):
        raise SkillHelperError("invalid_arguments", f"{name} must be an array")
    if expected_type == "object" and not isinstance(value, dict):
        raise SkillHelperError("invalid_arguments", f"{name} must be an object")


def _load_helper_function(helper: SkillHelper) -> Any:
    module = importlib.import_module(helper.module)
    function = getattr(module, helper.function, None)
    if not callable(function):
        raise SkillHelperError(
            "skill_helper_not_found",
            f"Helper function {helper.function!r} was not found",
        )
    return function
