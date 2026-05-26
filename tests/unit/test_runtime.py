from pathlib import Path
from io import BytesIO, StringIO
import json

from site_agent.core.align.lexical import align_snapshot
from site_agent.cli import main
from site_agent.core.models import CrawlSnapshot, DomainTerm, Evidence, UiElement, utc_now
from site_agent.core.storage import read_json
from site_agent.core.synthesize.mcp import synthesize_tools, write_mcp_package
from site_agent.core.synthesize.runtime import call_tool, handle_request, serve_json_lines


def test_runtime_returns_value_from_private_adapter_binding(tmp_path):
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_1",
        run_id="run_1",
        elements=[
            UiElement(
                id="ui_1",
                page_id="page_1",
                selector_fingerprint="abc",
                label="WAN Status",
                control_type="readonly_status",
                context={"read_value": "Connected"},
                evidence_ids=["ev_ui"],
            )
        ],
        evidence=[Evidence(id="ev_ui", kind="ui", source="fixture", summary="WAN Status: Connected")],
    )
    ontology = [DomainTerm(id="term_wan_status", canonical_name="wan status", aliases=["WAN Status"], sources=["ev_doc"], confidence=0.9)]
    schema = align_snapshot("profile_1", snapshot, ontology, [Evidence(id="ev_doc", kind="doc", source="manual", summary="WAN status docs")])
    tools, bindings = synthesize_tools(
        "profile_1",
        schema,
        {"ui_1": "abc"},
        {"ui_1": "Connected"},
    )

    write_mcp_package(tmp_path, "demo", tools, bindings)
    package_dir = tmp_path / "output" / "demo" / "mcp"

    public_tools = read_json(package_dir / "tools.json")["tools"]
    assert "selector_fingerprint" not in public_tools[0]
    assert call_tool(package_dir, "get_wan_status")["value"] == "Connected"

    response = handle_request(package_dir, {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": "get_wan_status"}})
    assert response["result"]["structuredContent"]["value"] == "Connected"

    stdin = StringIO(json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}) + "\n")
    stdout = StringIO()
    serve_json_lines(package_dir, stdin, stdout)
    listed = json.loads(stdout.getvalue())
    assert listed["result"]["tools"][0]["name"] == "get_wan_status"

    framed_requests = [
        {"jsonrpc": "2.0", "id": 3, "method": "initialize", "params": {"protocolVersion": "2024-11-05"}},
        {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/list"},
    ]
    body = b"".join(
        f"Content-Length: {len(payload)}\r\n\r\n".encode("ascii") + payload
        for payload in (json.dumps(request).encode("utf-8") for request in framed_requests)
    )
    framed_stdin = type("BinaryText", (), {"buffer": BytesIO(body)})()
    framed_output = BytesIO()
    framed_stdout = type("BinaryText", (), {"buffer": framed_output})()

    serve_json_lines(package_dir, framed_stdin, framed_stdout)

    raw = framed_output.getvalue()
    responses = []
    while raw:
        header, raw = raw.split(b"\r\n\r\n", 1)
        length = int(header.decode("ascii").split(":", 1)[1].strip())
        payload, raw = raw[:length], raw[length:]
        responses.append(json.loads(payload))
    assert [response["id"] for response in responses] == [3, 4]
    assert responses[1]["result"]["tools"][0]["name"] == "get_wan_status"


def test_runtime_resolves_compatibility_aliases(tmp_path):
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_1",
        run_id="run_1",
        elements=[
            UiElement(
                id="ui_1",
                page_id="page_1",
                selector_fingerprint="abc",
                label="WAN Connection",
                control_type="readonly_status",
                context={"read_value": "Connected"},
                evidence_ids=["ev_ui"],
            )
        ],
        evidence=[Evidence(id="ev_ui", kind="ui", source="fixture", summary="WAN Connection: Connected")],
    )
    ontology = [DomainTerm(id="term_wan_connection", canonical_name="wan connection", aliases=["WAN Connection"], sources=["ev_doc"], confidence=0.9)]
    schema = align_snapshot("profile_1", snapshot, ontology, [Evidence(id="ev_doc", kind="doc", source="manual", summary="WAN connection docs")])
    tools, bindings = synthesize_tools("profile_1", schema, {"ui_1": "abc"}, {"ui_1": "Connected"})
    tools[0].compatibility_aliases.append("get_wan_status")
    write_mcp_package(tmp_path, "demo", tools, bindings)
    package_dir = tmp_path / "output" / "demo" / "mcp"

    assert call_tool(package_dir, "get_wan_connection")["value"] == "Connected"
    assert call_tool(package_dir, "get_wan_status")["value"] == "Connected"


def test_mcp_import_emits_json_and_installs_codex_block(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["profile", "init", "--name", "demo-site", "--base-url", "https://demo.test"]) == 0
    capsys.readouterr()
    write_mcp_package(tmp_path, "demo-site", [], [])

    assert main(["mcp", "import", "--profile", "demo-site", "--target", "json", "--server-name", "demo_router"]) == 0
    emitted = json.loads(capsys.readouterr().out)
    server = emitted["mcpServers"]["demo_router"]
    assert server["args"] == ["-m", "site_agent", "mcp", "serve", "--profile", "demo-site"]
    assert server["cwd"] == str(tmp_path)

    config_path = tmp_path / "codex.toml"
    assert (
        main(
            [
                "mcp",
                "import",
                "--profile",
                "demo-site",
                "--target",
                "codex",
                "--server-name",
                "demo_router",
                "--config",
                str(config_path),
                "--apply",
            ]
        )
        == 0
    )
    config = config_path.read_text(encoding="utf-8")
    assert "[mcp_servers.demo_router]" in config
    assert "site_agent" in config

    assert (
        main(
            [
                "mcp",
                "import",
                "--profile",
                "demo-site",
                "--target",
                "codex",
                "--server-name",
                "demo_router",
                "--config",
                str(config_path),
                "--apply",
            ]
        )
        == 0
    )
    assert config_path.read_text(encoding="utf-8").count("[mcp_servers.demo_router]") == 1
