from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "lifeops-mock-package-tracking", "version": "0.1.0"}
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DATA_PATH = REPO_ROOT / "data" / "mock_packages" / "shipments.json"

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "track_package",
        "title": "Track Package",
        "description": "Return the current status for a mock package tracking number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Mock package tracking number, for example PKG-001.",
                }
            },
            "required": ["tracking_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "list_package_updates",
        "title": "List Package Updates",
        "description": "Return the tracking history for a mock package tracking number.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Mock package tracking number, for example PKG-001.",
                }
            },
            "required": ["tracking_number"],
            "additionalProperties": False,
        },
    },
    {
        "name": "estimate_delivery_window",
        "title": "Estimate Delivery Window",
        "description": "Return the estimated delivery date and time window for a mock package.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "tracking_number": {
                    "type": "string",
                    "description": "Mock package tracking number, for example PKG-001.",
                }
            },
            "required": ["tracking_number"],
            "additionalProperties": False,
        },
    },
]


class ToolInputError(ValueError):
    pass


def load_shipments(data_path: Path = DEFAULT_DATA_PATH) -> list[dict[str, Any]]:
    payload = json.loads(data_path.read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"{data_path} must contain a JSON list")
    return [item for item in payload if isinstance(item, dict)]


def require_tracking_number(arguments: Any) -> str:
    if not isinstance(arguments, dict):
        raise ToolInputError("arguments must be an object")
    tracking_number = arguments.get("tracking_number")
    if not isinstance(tracking_number, str) or not tracking_number.strip():
        raise ToolInputError("tracking_number must be a non-empty string")
    return tracking_number.strip()


def find_shipment(
    tracking_number: str,
    data_path: Path = DEFAULT_DATA_PATH,
) -> dict[str, Any] | None:
    normalized = tracking_number.upper()
    for shipment in load_shipments(data_path):
        if str(shipment.get("tracking_number", "")).upper() == normalized:
            return shipment
    return None


def track_package(arguments: dict[str, Any], data_path: Path = DEFAULT_DATA_PATH) -> dict[str, Any]:
    tracking_number = require_tracking_number(arguments)
    shipment = find_shipment(tracking_number, data_path)
    if shipment is None:
        return package_not_found(tracking_number)

    updates = shipment.get("updates")
    latest_update = updates[-1] if isinstance(updates, list) and updates else None
    return {
        "ok": True,
        "tracking_number": shipment.get("tracking_number"),
        "carrier": shipment.get("carrier"),
        "status": shipment.get("status"),
        "current_location": shipment.get("current_location"),
        "estimated_delivery_date": shipment.get("estimated_delivery_date"),
        "estimated_delivery_window": shipment.get("estimated_delivery_window"),
        "latest_update": latest_update,
    }


def list_package_updates(
    arguments: dict[str, Any],
    data_path: Path = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    tracking_number = require_tracking_number(arguments)
    shipment = find_shipment(tracking_number, data_path)
    if shipment is None:
        return package_not_found(tracking_number)

    return {
        "ok": True,
        "tracking_number": shipment.get("tracking_number"),
        "carrier": shipment.get("carrier"),
        "updates": shipment.get("updates", []),
    }


def estimate_delivery_window(
    arguments: dict[str, Any],
    data_path: Path = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    tracking_number = require_tracking_number(arguments)
    shipment = find_shipment(tracking_number, data_path)
    if shipment is None:
        return package_not_found(tracking_number)

    return {
        "ok": True,
        "tracking_number": shipment.get("tracking_number"),
        "carrier": shipment.get("carrier"),
        "status": shipment.get("status"),
        "current_location": shipment.get("current_location"),
        "estimated_delivery_date": shipment.get("estimated_delivery_date"),
        "estimated_delivery_window": shipment.get("estimated_delivery_window"),
    }


def package_not_found(tracking_number: str) -> dict[str, Any]:
    return {
        "ok": False,
        "error": {
            "code": "package_not_found",
            "message": f"Package not found: {tracking_number}",
        },
        "tracking_number": tracking_number,
    }


TOOL_HANDLERS = {
    "track_package": track_package,
    "list_package_updates": list_package_updates,
    "estimate_delivery_window": estimate_delivery_window,
}


def handle_request(
    request: dict[str, Any],
    data_path: Path = DEFAULT_DATA_PATH,
) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")

    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return result_response(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "tools/list":
        return result_response(request_id, {"tools": TOOL_SCHEMAS})
    if method == "tools/call":
        return handle_tool_call(request_id, request.get("params"), data_path)

    return error_response(request_id, -32601, f"Method not found: {method}")


def handle_tool_call(
    request_id: Any,
    params: Any,
    data_path: Path = DEFAULT_DATA_PATH,
) -> dict[str, Any]:
    if not isinstance(params, dict):
        return error_response(request_id, -32602, "tools/call params must be an object")

    tool_name = params.get("name")
    arguments = params.get("arguments", {})
    handler = TOOL_HANDLERS.get(str(tool_name))
    if handler is None:
        return error_response(request_id, -32602, f"Unknown tool: {tool_name}")

    try:
        payload = handler(arguments, data_path)
    except ToolInputError as error:
        return error_response(request_id, -32602, str(error))
    except Exception as error:
        return error_response(request_id, -32603, f"Tool failed: {error}")

    return result_response(request_id, mcp_tool_result(payload))


def mcp_tool_result(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "structuredContent": payload,
        "isError": payload.get("ok") is False,
    }


def result_response(request_id: Any, result: dict[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def error_response(request_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


def serve_stdio() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            if not isinstance(request, dict):
                response = error_response(None, -32600, "Request must be a JSON object")
            else:
                response = handle_request(request)
        except json.JSONDecodeError as error:
            response = error_response(None, -32700, f"Parse error: {error}")

        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve_stdio()
