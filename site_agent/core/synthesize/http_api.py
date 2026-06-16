from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from site_agent.core.storage import read_json
from site_agent.core.synthesize.runtime import RuntimeErrorForTool, call_tool


def load_api_methods(package_dir: Path) -> dict[str, dict[str, Any]]:
    api_spec_path = package_dir.parent / "api" / "api-spec.json"
    if not api_spec_path.exists():
        raise FileNotFoundError(f"Generated API spec missing: {api_spec_path}")
    spec = read_json(api_spec_path)
    return {str(method.get("name")): method for method in spec.get("methods", [])}


def handle_api_bridge_request(
    package_dir: Path,
    method_name: str,
    payload: dict[str, Any] | None,
) -> tuple[int, dict[str, Any]]:
    """Executes one generated API bridge request."""
    methods = load_api_methods(package_dir)
    method = methods.get(method_name)
    if method is None:
        return HTTPStatus.NOT_FOUND, {"error": f"Unknown generated API method: {method_name}"}
    payload = payload or {}
    if not isinstance(payload, dict):
        return HTTPStatus.BAD_REQUEST, {"error": "Request body must be a JSON object."}
    args = payload.get("args", {})
    if not isinstance(args, dict):
        return HTTPStatus.BAD_REQUEST, {"error": "Request body field 'args' must be an object."}
    mode = str(payload.get("mode") or "dry-run")
    if mode not in {"dry-run", "apply"}:
        return HTTPStatus.BAD_REQUEST, {"error": "Request body field 'mode' must be 'dry-run' or 'apply'."}
    browser = bool(payload.get("browser", False))
    try:
        result = call_tool(
            package_dir,
            str(method.get("backing_tool") or method_name),
            args,
            mode=mode,
            browser=browser,
        )
    except RuntimeErrorForTool as exc:
        return HTTPStatus.BAD_REQUEST, {"error": str(exc)}
    return HTTPStatus.OK, result


def _read_json_body(handler: BaseHTTPRequestHandler) -> dict[str, Any]:
    length = int(handler.headers.get("content-length", "0") or "0")
    if length <= 0:
        return {}
    body = handler.rfile.read(length).decode("utf-8")
    return json.loads(body)


def _write_json(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    body = json.dumps(payload, indent=2, sort_keys=True).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def make_api_bridge_handler(package_dir: Path):
    package_dir = package_dir.resolve()

    class ApiBridgeHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self) -> None:
            parsed = urlparse(self.path)
            if parsed.path == "/health":
                methods = load_api_methods(package_dir)
                _write_json(
                    self,
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "methods": len(methods),
                        "package_dir": str(package_dir),
                    },
                )
                return
            if parsed.path == "/openapi.json":
                openapi_path = package_dir.parent / "docs" / "openapi.json"
                if not openapi_path.exists():
                    _write_json(self, HTTPStatus.NOT_FOUND, {"error": f"OpenAPI spec missing: {openapi_path}"})
                    return
                _write_json(self, HTTPStatus.OK, read_json(openapi_path))
                return
            _write_json(self, HTTPStatus.NOT_FOUND, {"error": f"Unknown path: {parsed.path}"})

        def do_POST(self) -> None:
            parsed = urlparse(self.path)
            prefix = "/methods/"
            if not parsed.path.startswith(prefix):
                _write_json(self, HTTPStatus.NOT_FOUND, {"error": f"Unknown path: {parsed.path}"})
                return
            method_name = unquote(parsed.path[len(prefix) :])
            try:
                payload = _read_json_body(self)
            except json.JSONDecodeError as exc:
                _write_json(self, HTTPStatus.BAD_REQUEST, {"error": f"Invalid JSON body: {exc}"})
                return
            status, result = handle_api_bridge_request(package_dir, method_name, payload)
            _write_json(self, status, result)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ApiBridgeHandler
