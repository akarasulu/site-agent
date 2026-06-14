from __future__ import annotations

from io import BytesIO
import json
import sys
import types

import pytest

from site_agent.core.storage import write_json
from site_agent.core.synthesize import runtime
from site_agent.core.synthesize.runtime import (
    RuntimeErrorForTool,
    browser_apply_staged_action,
    browser_page_url,
    call_tool,
    handle_request,
    list_tools,
    row_for_match,
    serve_json_lines,
)


def write_runtime_package(tmp_path, *, tools, bindings, server=None):
    package_dir = tmp_path / "mcp"
    write_json(package_dir / "tools.json", {"tools": tools})
    write_json(package_dir / "adapter.bindings.json", {"bindings": bindings})
    write_json(package_dir / "server.json", server or {"base_url": "https://example.test/app"})
    return package_dir


def tool(name, *, action=None, risk_level="medium", requires_confirmation=False):
    payload = {
        "name": name,
        "description": f"{name} description",
        "args": {"type": "object", "properties": {}},
        "risk_level": risk_level,
        "evidence_ids": [f"ev_{name}"],
        "confidence": 0.9,
        "requires_confirmation": requires_confirmation,
        "exposure_level": "review_required" if requires_confirmation else "ready_public",
    }
    if action:
        payload["source_type"] = "ui_flow"
    return payload


def binding(name, action, **adapter):
    return {
        "tool_name": name,
        "profile_id": "profile",
        "version": "0.1.0",
        "selector_action_bindings": {"action": action, "page_id": "page", **adapter},
    }


def test_runtime_lists_tools_and_delegates_to_generated_python_api(tmp_path):
    api_root = tmp_path / "api_root"
    package = api_root / "fake_api"
    package.mkdir(parents=True)
    (package / "__init__.py").write_text(
        "class FakeClient:\n"
        "    @classmethod\n"
        "    def from_package_dir(cls, package_dir):\n"
        "        client = cls()\n"
        "        client.package_dir = str(package_dir)\n"
        "        return client\n"
        "    def call_tool(self, tool_name, args, mode='dry-run', browser=False):\n"
        "        return {'tool_name': tool_name, 'args': args, 'mode': mode, 'browser': browser}\n",
        encoding="utf-8",
    )
    package_dir = write_runtime_package(
        tmp_path,
        tools=[tool("get_status", risk_level="low")],
        bindings=[],
        server={
            "python_api": {
                "package_name": "fake_api",
                "client_class": "FakeClient",
                "path": str(api_root),
            }
        },
    )

    assert list_tools(package_dir) == [
        {
            "name": "get_status",
            "description": "get_status description",
            "inputSchema": {"type": "object", "properties": {}},
        }
    ]
    delegated = call_tool(package_dir, "anything", {"x": 1}, mode="apply", browser=True)

    assert delegated["execution_surface"] == "python_api"
    assert delegated["tool_name"] == "anything"
    assert delegated["args"] == {"x": 1}
    assert delegated["mode"] == "apply"
    assert delegated["browser"] is True


def test_runtime_plans_staged_item_actions_and_browser_apply(tmp_path, monkeypatch):
    package_dir = write_runtime_package(
        tmp_path,
        tools=[
            tool("enable_item", action="set_dynamic_item_state"),
            tool("delete_item", action="delete_dynamic_item", risk_level="high", requires_confirmation=True),
        ],
        bindings=[
            binding("enable_item", "set_dynamic_item_state", desired_state="on"),
            binding("delete_item", "delete_dynamic_item"),
        ],
    )

    enable_plan = call_tool(package_dir, "enable_item", {"item_match": {"name": "vpn"}})
    delete_plan = call_tool(package_dir, "delete_item", {"item_match": {"name": "vpn"}})

    assert enable_plan["status"] == "dry_run"
    assert {"step": "set_state", "desired_state": "on"} in enable_plan["planned_steps"]
    assert delete_plan["planned_steps"][-1] == {"step": "delete_item", "requires_confirmation": True}

    with pytest.raises(RuntimeErrorForTool, match="requires confirm=true"):
        call_tool(
            package_dir,
            "delete_item",
            {"item_match": {"name": "vpn"}, "dry_run": False},
            mode="apply",
        )

    monkeypatch.setattr(
        runtime,
        "browser_apply_staged_action",
        lambda server, tool_payload, adapter, args: {
            "status": "applied",
            "tool": tool_payload["name"],
            "action": adapter["action"],
            "args": args,
        },
    )
    applied = call_tool(
        package_dir,
        "delete_item",
        {"item_match": {"name": "vpn"}, "dry_run": False, "confirm": True},
        mode="apply",
        browser=True,
    )

    assert applied["status"] == "applied"
    assert applied["tool"] == "delete_item"
    assert applied["action"] == "delete_dynamic_item"


def test_runtime_submit_form_dry_run_confirmation_and_http_apply(tmp_path, monkeypatch):
    package_dir = write_runtime_package(
        tmp_path,
        tools=[
            tool("submit_settings", action="submit_form", requires_confirmation=True),
            tool("submit_search", action="submit_form", risk_level="low"),
        ],
        bindings=[
            binding(
                "submit_settings",
                "submit_form",
                method="post",
                action_url="/settings",
                fields=[{"arg": "timezone"}, {"arg": "hostname"}],
            ),
            binding(
                "submit_search",
                "submit_form",
                method="get",
                action_url="/search",
                fields=[{"arg": "query"}],
            ),
        ],
    )

    plan = call_tool(package_dir, "submit_settings", {"timezone": "UTC"})

    assert plan["status"] == "dry_run"
    assert plan["planned_request"]["method"] == "post"
    assert plan["planned_request"]["fields"] == {"timezone": "UTC", "hostname": ""}

    with pytest.raises(RuntimeErrorForTool, match="requires confirm=true"):
        call_tool(package_dir, "submit_settings", {"timezone": "UTC", "dry_run": False}, mode="apply")

    seen = {}

    class FakeResponse:
        status = 204

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    def fake_urlopen(request, timeout):
        seen["url"] = request.full_url
        seen["data"] = request.data
        seen["method"] = request.get_method()
        seen["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(runtime, "urlopen", fake_urlopen)

    result = call_tool(
        package_dir,
        "submit_search",
        {"query": "port forwarding", "dry_run": False},
        mode="apply",
    )

    assert result["status"] == "applied"
    assert result["http_status"] == 204
    assert seen["method"] == "GET"
    assert seen["data"] is None
    assert seen["timeout"] == 10
    assert seen["url"].endswith("/search?query=port+forwarding")


def test_runtime_high_risk_submit_form_apply_is_blocked(tmp_path):
    package_dir = write_runtime_package(
        tmp_path,
        tools=[tool("factory_reset", action="submit_form", risk_level="high", requires_confirmation=True)],
        bindings=[binding("factory_reset", "submit_form", method="post", action_url="/reset", fields=[])],
    )

    with pytest.raises(RuntimeErrorForTool, match="High-risk apply calls"):
        call_tool(package_dir, "factory_reset", {"dry_run": False, "confirm": True}, mode="apply")


def test_runtime_request_errors_notifications_and_binary_json_lines(tmp_path):
    package_dir = write_runtime_package(tmp_path, tools=[tool("get_status", risk_level="low")], bindings=[])

    assert handle_request(package_dir, {"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    unknown = handle_request(package_dir, {"jsonrpc": "2.0", "id": 1, "method": "unknown"})
    missing_name = handle_request(package_dir, {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {}})

    assert unknown["error"]["code"] == -32601
    assert missing_name["error"]["code"] == -32000
    assert "params.name" in missing_name["error"]["message"]

    request = json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/list"}).encode("utf-8") + b"\n"
    stdin = type("BinaryText", (), {"buffer": BytesIO(request)})()
    output = BytesIO()
    stdout = type("BinaryText", (), {"buffer": output})()

    serve_json_lines(package_dir, stdin, stdout)

    response = json.loads(output.getvalue().decode("utf-8"))
    assert response["id"] == 3
    assert response["result"]["tools"][0]["name"] == "get_status"


def test_runtime_browser_url_and_row_helpers():
    assert browser_page_url({"base_url": "https://real.example"}, {"page_url": "/settings"}) == "https://real.example/settings"
    assert (
        browser_page_url(
            {"base_url": "https://real.example:8443"},
            {"page_url": "https://[redacted-host]/admin#section"},
        )
        == "https://real.example:8443/admin"
    )
    assert browser_page_url({}, {"page_url": "https://example.test/path#state"}) == "https://example.test/path"

    with pytest.raises(RuntimeErrorForTool, match="server.base_url"):
        browser_page_url({}, {})
    with pytest.raises(RuntimeErrorForTool, match="non-empty item_match"):
        row_for_match(object(), {})


class FakeBodyLocator:
    def __init__(self, text):
        self.text = text

    def inner_text(self, timeout):
        return self.text


class FakeBrowserPage:
    def __init__(self, body_text="alpha 443 vpn"):
        self.body_text = body_text
        self.gotos = []
        self.waits = []
        self.dialog_handlers = []

    def goto(self, url, wait_until):
        self.gotos.append((url, wait_until))

    def wait_for_timeout(self, timeout):
        self.waits.append(timeout)

    def locator(self, selector):
        assert selector == "body"
        return FakeBodyLocator(self.body_text)

    def on(self, event, handler):
        self.dialog_handlers.append((event, handler))


class FakeBrowser:
    def __init__(self, page):
        self.page = page
        self.closed = False

    def new_page(self):
        return self.page

    def close(self):
        self.closed = True


class FakeChromium:
    def __init__(self, browser):
        self.browser = browser
        self.headless = None

    def launch(self, headless):
        self.headless = headless
        return self.browser


class FakePlaywright:
    def __init__(self, browser):
        self.chromium = FakeChromium(browser)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


def install_fake_playwright(monkeypatch, page):
    browser = FakeBrowser(page)
    fake_playwright = FakePlaywright(browser)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", types.SimpleNamespace(sync_playwright=lambda: fake_playwright))
    return browser, fake_playwright


def test_browser_apply_staged_open_fill_form_uses_safe_helpers(monkeypatch):
    page = FakeBrowserPage()
    browser, fake_playwright = install_fake_playwright(monkeypatch, page)
    calls = []
    monkeypatch.setattr(runtime, "click_text_control", lambda page, label: calls.append(("click", label)))
    monkeypatch.setattr(runtime, "fill_staged_field", lambda page, field, value: calls.append(("fill", field["arg"], value)))
    monkeypatch.setattr(runtime, "click_commit_control", lambda page: calls.append(("commit",)))

    result = browser_apply_staged_action(
        {"base_url": "https://example.test"},
        {"name": "create_item", "evidence_ids": ["ev_create"], "risk_level": "medium"},
        {
            "action": "open_fill_dynamic_form",
            "page_url": "/rules",
            "trigger_label": "Add Rule",
            "fields": [{"arg": "name"}, {"arg": "port"}],
        },
        {"name": "alpha", "port": 443},
    )

    assert fake_playwright.chromium.headless is True
    assert browser.closed is True
    assert page.gotos == [("https://example.test/rules", "networkidle")]
    assert calls == [("click", "Add Rule"), ("fill", "name", "alpha"), ("fill", "port", 443), ("commit",)]
    assert result["status"] == "applied"
    assert result["verified_values"] == ["alpha", "443"]
    assert result["planned_steps"][-1] == {"step": "submit_or_apply"}


class FakeFilteredLocator:
    def __init__(self, click_log, *, fail_click=False):
        self.click_log = click_log
        self.fail_click = fail_click
        self.first = self

    def filter(self, **kwargs):
        return self

    def click(self, timeout):
        if self.fail_click:
            raise RuntimeError("button unavailable")
        self.click_log.append(("click", timeout))


class FakeCheckboxLocator:
    first = None

    def __init__(self, check_log):
        self.check_log = check_log
        self.first = self

    def set_checked(self, checked, timeout):
        self.check_log.append((checked, timeout))


class FakeActionRow:
    def __init__(self, *, fail_button=False):
        self.click_log = []
        self.check_log = []
        self.fail_button = fail_button

    def locator(self, selector):
        if selector == "input[type=checkbox]":
            return FakeCheckboxLocator(self.check_log)
        return FakeFilteredLocator(self.click_log, fail_click=self.fail_button)


def test_browser_apply_staged_item_state_and_delete_paths(monkeypatch):
    page = FakeBrowserPage("vpn row still visible")
    install_fake_playwright(monkeypatch, page)
    state_row = FakeActionRow(fail_button=True)
    monkeypatch.setattr(runtime, "row_for_match", lambda page, item_match: state_row)

    state_result = browser_apply_staged_action(
        {"base_url": "https://example.test"},
        {"name": "enable_item", "evidence_ids": ["ev_enable"], "risk_level": "medium"},
        {"action": "set_dynamic_item_state", "page_url": "/items", "desired_state": "on"},
        {"item_match": {"name": "vpn"}},
    )

    assert state_row.check_log == [(True, 2000)]
    assert {"step": "set_state", "desired_state": "on"} in state_result["planned_steps"]
    assert state_result["page_text"] == "vpn row still visible"

    delete_page = FakeBrowserPage("vpn deleted")
    install_fake_playwright(monkeypatch, delete_page)
    delete_row = FakeActionRow()
    monkeypatch.setattr(runtime, "row_for_match", lambda page, item_match: delete_row)

    delete_result = browser_apply_staged_action(
        {"base_url": "https://example.test"},
        {"name": "delete_item", "evidence_ids": ["ev_delete"], "risk_level": "high"},
        {"action": "delete_dynamic_item", "page_url": "/items"},
        {"item_match": {"name": "vpn"}},
    )

    assert delete_page.dialog_handlers[0][0] == "dialog"
    assert delete_row.click_log == [("click", 2000)]
    assert {"step": "delete_item"} in delete_result["planned_steps"]
    assert delete_result["risk_level"] == "high"
