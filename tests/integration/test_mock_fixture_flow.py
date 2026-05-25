from pathlib import Path
import json
import os
import pytest
import socket
import subprocess
import sys
import time
from urllib.request import urlopen
from urllib.parse import urlencode
from urllib.request import Request

from site_agent.cli import main
from site_agent.core.storage import read_json, write_json


def test_mock_fixture_site_discovers_common_admin_flows(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    monkeypatch.chdir(tmp_path)

    assert main(["profile", "init", "--name", "opsboard", "--base-url", "https://opsboard.local"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    (Path("profiles/opsboard/docs") / "opsboard-admin-guide.md").write_text(
        (fixture / "docs" / "opsboard-admin-guide.md").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["mcp", "build", "--profile", "opsboard"]) == 0

    snapshots = list(Path("output/opsboard/crawl").glob("snapshot-*.json"))
    snapshot = read_json(snapshots[0])
    assert len(snapshot["pages"]) == 6
    assert len(snapshot["forms"]) >= 5

    tools = read_json(Path("output/opsboard/mcp/tools.json"))["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert "get_email_address" in tool_names
    assert "get_incident_status" in tool_names
    assert "get_export_format" in tool_names


def free_port() -> int:
    try:
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            return int(sock.getsockname()[1])
    except PermissionError:
        pytest.skip("local socket binding is not available in this sandbox")


def wait_for_url(url: str, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(url, timeout=1) as response:
                if response.status == 200:
                    return
        except Exception:
            time.sleep(0.1)
    raise AssertionError(f"Server did not become ready: {url}")


def api_items(base_url: str) -> list[dict]:
    with urlopen(f"{base_url}/api/items", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))["items"]


def fetch_text(url: str) -> str:
    with urlopen(url, timeout=3) as response:
        return response.read().decode("utf-8")


def post_form(url: str, payload: dict[str, str]) -> None:
    request = Request(url, data=urlencode(payload).encode("utf-8"), method="POST")
    with urlopen(request, timeout=3):
        return


def test_browser_staged_action_executor_round_trips_dynamic_items(tmp_path, monkeypatch):
    pytest.importorskip("playwright.sync_api")
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, str(fixture / "app.py")],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_url(f"{base_url}/items.html")
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("SITE_AGENT_ALLOW_NO_AI", "1")
        assert main(["profile", "init", "--name", "opsboard", "--base-url", f"{base_url}/index.html"]) == 0
        write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
        (Path("profiles/opsboard/docs") / "opsboard-admin-guide.md").write_text(
            (fixture / "docs" / "opsboard-admin-guide.md").read_text(encoding="utf-8"),
            encoding="utf-8",
        )
        assert main(["crawl", "run", "--profile", "opsboard", "--probe-budget-seconds", "30"]) == 0
        snapshot = read_json(sorted(Path("output/opsboard/crawl").glob("snapshot-*.json"))[-1])
        assert any(flow["trigger_label"] == "Add Item" for flow in snapshot["interaction_flows"])
        assert main(["schema", "review", "--profile", "opsboard"]) == 0
        assert main(["mcp", "build", "--profile", "opsboard", "--include-writes"]) == 0
        tools = read_json(Path("output/opsboard/mcp/tools.json"))["tools"]
        tool_names = {tool["name"] for tool in tools}
        assert {"create_item", "activate_item", "deactivate_item", "delete_item"} <= tool_names

        args = tmp_path / "args.json"
        write_json(args, {"item_name": "SA12121", "service_port": "12121", "enabled": False, "dry_run": False, "confirm": True})
        assert main(["mcp", "call", "--profile", "opsboard", "--tool", "create_item", "--args-json", str(args), "--mode", "apply", "--browser"]) == 0
        assert api_items(base_url) == [{"item_name": "SA12121", "service_port": "12121", "enabled": False}]

        write_json(args, {"item_match": {"item_name": "SA12121"}, "dry_run": False, "confirm": True})
        assert main(["mcp", "call", "--profile", "opsboard", "--tool", "activate_item", "--args-json", str(args), "--mode", "apply", "--browser"]) == 0
        assert api_items(base_url)[0]["enabled"] is True
        assert main(["mcp", "call", "--profile", "opsboard", "--tool", "deactivate_item", "--args-json", str(args), "--mode", "apply", "--browser"]) == 0
        assert api_items(base_url)[0]["enabled"] is False
        assert main(["mcp", "call", "--profile", "opsboard", "--tool", "delete_item", "--args-json", str(args), "--mode", "apply", "--browser"]) == 0
        assert api_items(base_url) == []
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def test_controlled_restore_apply_round_trips_mock_settings(tmp_path, monkeypatch):
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    port = free_port()
    base_url = f"http://127.0.0.1:{port}"
    process = subprocess.Popen(
        [sys.executable, str(fixture / "app.py")],
        env={**os.environ, "PORT": str(port)},
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_url(f"{base_url}/settings.html")
        monkeypatch.chdir(tmp_path)
        assert main(["profile", "init", "--name", "opsboard", "--base-url", base_url]) == 0
        profile_path = Path("profiles/opsboard/profile.json")
        profile = read_json(profile_path)
        profile["risk"]["write_mode"] = "apply"
        write_json(profile_path, profile)
        write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))

        html = tmp_path / "settings-v1.html"
        html.write_text(fetch_text(f"{base_url}/settings.html"), encoding="utf-8")
        assert main(["crawl", "run", "--profile", "opsboard", "--fixture-html", str(html), "--url", f"{base_url}/settings.html"]) == 0
        assert main(["schema", "review", "--profile", "opsboard"]) == 0
        assert main(["mcp", "build", "--profile", "opsboard", "--include-writes"]) == 0
        settings_repo = tmp_path / "settings-repo"
        assert main(["config", "save", "--profile", "opsboard", "--repo", str(settings_repo), "--commit", "--tag", "v1"]) == 0
        v1 = read_json(settings_repo / "snapshots/latest.json")
        assert sum(1 for setting in v1["settings"] if setting["restorable"]) >= 3

        post_form(
            f"{base_url}/settings.html",
            {"alert_email": "changed@example.test", "maintenance_window": "Tuesday 04:00 UTC", "retention_days": "60"},
        )
        html.write_text(fetch_text(f"{base_url}/settings.html"), encoding="utf-8")
        assert main(["crawl", "run", "--profile", "opsboard", "--fixture-html", str(html), "--url", f"{base_url}/settings.html"]) == 0
        assert main(["schema", "review", "--profile", "opsboard"]) == 0
        assert main(["mcp", "build", "--profile", "opsboard", "--include-writes"]) == 0
        assert main(["config", "save", "--profile", "opsboard", "--repo", str(settings_repo), "--commit", "--tag", "v2"]) == 0

        assert main(["config", "restore-plan", "--profile", "opsboard", "--repo", str(settings_repo), "--ref", "v1"]) == 0
        plan = read_json(Path("output/opsboard/restore-plans/restore-v1-to-current.json"))
        assert len(plan["steps"]) == 1
        assert {"alert_email", "maintenance_window", "retention_days"} <= set(plan["steps"][0]["args"])

        assert main(["config", "restore", "--profile", "opsboard", "--repo", str(settings_repo), "--ref", "v1", "--mode", "apply", "--confirm"]) == 0
        restored_html = fetch_text(f"{base_url}/settings.html")
        assert "alerts@example.test" in restored_html
        assert "Sunday 02:00 UTC" in restored_html
        assert "Retention days: 30" in restored_html

        html.write_text(restored_html, encoding="utf-8")
        assert main(["crawl", "run", "--profile", "opsboard", "--fixture-html", str(html), "--url", f"{base_url}/settings.html"]) == 0
        assert main(["schema", "review", "--profile", "opsboard"]) == 0
        assert main(["mcp", "build", "--profile", "opsboard", "--include-writes"]) == 0
        assert main(["config", "save", "--profile", "opsboard", "--repo", str(settings_repo)]) == 0
        post_snapshot = settings_repo / "snapshots/latest.json"
        assert main(["config", "restore", "--profile", "opsboard", "--repo", str(settings_repo), "--ref", "v1", "--mode", "dry-run", "--verify-snapshot", str(post_snapshot)]) == 0
        report = read_json(sorted(Path("output/opsboard/reports").glob("restore-*.json"))[-1])
        assert report["post_restore_verification"]["verified"]
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
