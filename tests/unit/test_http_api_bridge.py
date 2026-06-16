import json
import threading
from http.server import ThreadingHTTPServer
from urllib.request import Request, urlopen

from site_agent.core.synthesize.http_api import handle_api_bridge_request, make_api_bridge_handler
from site_agent.core.storage import write_json


def write_bridge_fixture(tmp_path):
    package_dir = tmp_path / "output" / "demo" / "mcp"
    write_json(
        package_dir / "tools.json",
        {
            "tools": [
                {
                    "name": "get_status",
                    "description": "Read status",
                    "args": {"type": "object", "properties": {}, "additionalProperties": False},
                    "return_schema": {"type": "object"},
                    "risk_level": "low",
                    "evidence_ids": ["ev_status"],
                }
            ]
        },
    )
    write_json(
        package_dir / "adapter.bindings.json",
        {
            "bindings": [
                {
                    "tool_name": "get_status",
                    "selector_action_bindings": {
                        "action": "read",
                        "read_value": "ok",
                    },
                }
            ]
        },
    )
    write_json(
        tmp_path / "output" / "demo" / "api" / "api-spec.json",
        {
            "package_name": "demo_client",
            "version": "0.1.0",
            "methods": [
                {
                    "name": "get_status",
                    "description": "Read status",
                    "args": {"type": "object", "properties": {}, "additionalProperties": False},
                    "return_schema": {"type": "object"},
                    "risk_level": "low",
                    "dry_run_supported": True,
                    "evidence_ids": ["ev_status"],
                    "backing_tool": "get_status",
                }
            ],
            "evidence_ids": ["ev_status"],
        },
    )
    write_json(
        tmp_path / "output" / "demo" / "docs" / "openapi.json",
        {"openapi": "3.1.0", "paths": {"/methods/get_status": {}}},
    )
    return package_dir


def test_api_bridge_dispatches_generated_methods(tmp_path):
    package_dir = write_bridge_fixture(tmp_path)

    status, result = handle_api_bridge_request(package_dir, "get_status", {"args": {}})

    assert status == 200
    assert result["value"] == "ok"
    assert result["evidence_ids"] == ["ev_status"]
    missing_status, missing = handle_api_bridge_request(package_dir, "missing", {"args": {}})
    assert missing_status == 404
    assert "Unknown generated API method" in missing["error"]


def test_api_bridge_serves_health_openapi_and_method_calls(tmp_path):
    package_dir = write_bridge_fixture(tmp_path)
    server = ThreadingHTTPServer(("127.0.0.1", 0), make_api_bridge_handler(package_dir))
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_address[1]}"
    try:
        with urlopen(f"{base_url}/health", timeout=3) as response:
            health = json.loads(response.read().decode("utf-8"))
            assert response.headers["Access-Control-Allow-Origin"] == "*"
        assert health["status"] == "ok"
        assert health["methods"] == 1

        options = Request(f"{base_url}/methods/get_status", method="OPTIONS")
        with urlopen(options, timeout=3) as response:
            assert response.status == 204
            assert response.headers["Access-Control-Allow-Origin"] == "*"
            assert "POST" in response.headers["Access-Control-Allow-Methods"]

        with urlopen(f"{base_url}/openapi.json", timeout=3) as response:
            openapi = json.loads(response.read().decode("utf-8"))
        assert openapi["openapi"] == "3.1.0"

        request = Request(
            f"{base_url}/methods/get_status",
            data=json.dumps({"args": {}}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urlopen(request, timeout=3) as response:
            result = json.loads(response.read().decode("utf-8"))
        assert result["value"] == "ok"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
