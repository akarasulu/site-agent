from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, BinaryIO, TextIO
from urllib.parse import urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

from site_agent.core.storage import read_json


class RuntimeErrorForTool(RuntimeError):
    pass


def load_package(package_dir: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tools = read_json(package_dir / "tools.json").get("tools", [])
    bindings = read_json(package_dir / "adapter.bindings.json").get("bindings", [])
    return tools, bindings


def load_server(package_dir: Path) -> dict[str, Any]:
    server_path = package_dir / "server.json"
    return read_json(server_path) if server_path.exists() else {}


def list_tools(package_dir: Path) -> list[dict[str, Any]]:
    tools, _ = load_package(package_dir)
    return [
        {
            "name": tool["name"],
            "description": tool["description"],
            "inputSchema": tool["args"],
        }
        for tool in tools
    ]


def call_generated_python_api(package_dir: Path, server: dict[str, Any], tool_name: str, args: dict[str, Any], mode: str, browser: bool) -> dict[str, Any] | None:
    api = server.get("python_api") or {}
    package_name = api.get("package_name")
    client_class_name = api.get("client_class")
    api_path = api.get("path")
    if not package_name or not client_class_name or not api_path:
        return None
    root = (package_dir / api_path).resolve() if not Path(api_path).is_absolute() else Path(api_path)
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))
    module = __import__(package_name, fromlist=[client_class_name])
    client_class = getattr(module, client_class_name)
    client = client_class.from_package_dir(package_dir)
    return client.call_tool(tool_name, args, mode=mode, browser=browser)


def browser_page_url(server: dict[str, Any], adapter: dict[str, Any]) -> str:
    base_url = (server.get("base_url") or "").rstrip("/")
    page_url = adapter.get("page_url") or base_url
    if not page_url:
        raise RuntimeErrorForTool("Browser staged actions require server.base_url in the generated MCP package.")
    if "[redacted" in page_url and base_url:
        match = re.search(r"https?://\[[^\]]+\](?::\d+)?(?P<path>/[^#]*)", page_url)
        path = match.group("path") if match else "/"
        base = urlparse(base_url)
        return f"{base.scheme}://{base.netloc}{path}"
    if page_url.startswith("http://") or page_url.startswith("https://"):
        return page_url.split("#", 1)[0]
    return urljoin(base_url + "/", page_url)


def visible_button_regex(words: str):
    return re.compile(words, re.IGNORECASE)


def click_text_control(page, label: str) -> None:
    escaped = re.escape(label)
    candidates = [
        page.get_by_role("button", name=re.compile(escaped, re.IGNORECASE)),
        page.locator("button, input[type=button], input[type=submit], a, [role=button]").filter(has_text=re.compile(escaped, re.IGNORECASE)),
    ]
    for candidate in candidates:
        try:
            candidate.first.click(timeout=2000)
            return
        except Exception:
            pass
    raise RuntimeErrorForTool(f"Could not click staged action trigger labelled '{label}'.")


def field_locator(page, field: dict[str, Any]):
    selector_id = field.get("selector_id")
    selector_name = field.get("selector_name")
    label = field.get("label") or field.get("arg")
    candidates = []
    if selector_id:
        candidates.append(page.locator(f"#{selector_id}"))
    if selector_name:
        candidates.append(page.locator(f"[name='{selector_name}']"))
    if label:
        candidates.append(page.get_by_label(re.compile(re.escape(label), re.IGNORECASE)))
        candidates.append(page.locator("input, select, textarea").filter(has_text=re.compile(re.escape(label), re.IGNORECASE)))
    return candidates


def fill_staged_field(page, field: dict[str, Any], value: Any) -> None:
    for candidate in field_locator(page, field):
        try:
            control = candidate.first
            control.wait_for(state="visible", timeout=1500)
            tag_type = (control.get_attribute("type") or "").lower()
            if tag_type in {"checkbox", "radio"}:
                checked = str(value).lower() in {"1", "true", "yes", "on", "enabled", "active"}
                control.set_checked(checked, timeout=1500)
            else:
                control.fill(str(value), timeout=1500)
            return
        except Exception:
            pass
    raise RuntimeErrorForTool(f"Could not fill staged field '{field.get('label') or field.get('arg')}'.")


def click_commit_control(page) -> None:
    commit = page.locator("button, input[type=button], input[type=submit], [role=button]").filter(
        has_text=visible_button_regex(r"\b(save|apply|submit|create|add|ok|confirm)\b")
    )
    try:
        commit.last.click(timeout=2000)
        return
    except Exception:
        try:
            page.keyboard.press("Enter")
            return
        except Exception as exc:
            raise RuntimeErrorForTool("Could not find a visible save/apply/submit control for staged action.") from exc


def row_for_match(page, item_match: dict[str, Any]):
    values = [str(value) for value in item_match.values() if str(value)]
    if not values:
        raise RuntimeErrorForTool("Staged item actions require non-empty item_match values.")
    row = page.locator("tr, li, [role=row], .row, .item").filter(has_text=values[0])
    for value in values[1:]:
        row = row.filter(has_text=value)
    return row.first


def browser_apply_staged_action(server: dict[str, Any], tool: dict[str, Any], adapter: dict[str, Any], args: dict[str, Any]) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        raise RuntimeErrorForTool("Browser staged actions require Playwright to be installed.") from exc

    action = adapter.get("action")
    planned_steps = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        try:
            target_url = browser_page_url(server, adapter)
            page.goto(target_url, wait_until="networkidle")
            planned_steps.append({"step": "navigate", "url": target_url})
            if action == "open_fill_dynamic_form":
                click_text_control(page, adapter.get("trigger_label", ""))
                planned_steps.append({"step": "open_flow", "trigger_label": adapter.get("trigger_label")})
                for field in adapter.get("fields", []):
                    fill_staged_field(page, field, args.get(field["arg"], ""))
                planned_steps.append({"step": "fill_fields", "fields": [field.get("arg") for field in adapter.get("fields", [])]})
                click_commit_control(page)
                page.wait_for_timeout(500)
                planned_steps.append({"step": "submit_or_apply"})
                body = page.locator("body").inner_text(timeout=3000)
                provided_values = [str(args.get(field["arg"], "")) for field in adapter.get("fields", []) if str(args.get(field["arg"], ""))]
                verified = [value for value in provided_values if value in body]
                return {
                    "status": "applied",
                    "planned_steps": planned_steps,
                    "verified_values": verified,
                    "evidence_ids": tool.get("evidence_ids", []),
                    "risk_level": tool.get("risk_level", "medium"),
                }
            row = row_for_match(page, args.get("item_match", {}))
            planned_steps.append({"step": "find_item", "item_match": args.get("item_match", {})})
            if action == "set_dynamic_item_state":
                desired = adapter.get("desired_state")
                try:
                    row.locator("button, input[type=button], [role=button]").filter(has_text=visible_button_regex(r"\b(on|off|enable|disable|activate|deactivate)\b")).first.click(timeout=2000)
                except Exception:
                    checkbox = row.locator("input[type=checkbox]").first
                    checkbox.set_checked(desired == "on", timeout=2000)
                page.wait_for_timeout(500)
                planned_steps.append({"step": "set_state", "desired_state": desired})
            elif action == "delete_dynamic_item":
                try:
                    page.on("dialog", lambda dialog: dialog.accept())
                except Exception:
                    pass
                row.locator("button, input[type=button], [role=button]").filter(has_text=visible_button_regex(r"\b(delete|remove)\b")).first.click(timeout=2000)
                page.wait_for_timeout(500)
                planned_steps.append({"step": "delete_item"})
            body = page.locator("body").inner_text(timeout=3000)
            return {
                "status": "applied",
                "planned_steps": planned_steps,
                "page_text": body[:2000],
                "evidence_ids": tool.get("evidence_ids", []),
                "risk_level": tool.get("risk_level", "medium"),
            }
        finally:
            browser.close()


def call_tool(
    package_dir: Path,
    tool_name: str,
    args: dict[str, Any] | None = None,
    mode: str = "dry-run",
    browser: bool = False,
    use_python_api: bool = True,
) -> dict[str, Any]:
    args = args or {}
    tools, bindings = load_package(package_dir)
    server = load_server(package_dir)
    if use_python_api:
        delegated = call_generated_python_api(package_dir, server, tool_name, args, mode, browser)
        if delegated is not None:
            delegated.setdefault("execution_surface", "python_api")
            return delegated
    tool_by_name = {tool["name"]: tool for tool in tools}
    binding_by_name = {binding["tool_name"]: binding for binding in bindings}
    if tool_name not in tool_by_name:
        target_name = alias_lookup(tools).get(tool_name)
        if not target_name:
            raise RuntimeErrorForTool(f"Unknown tool: {tool_name}")
        tool_name = target_name
    tool = tool_by_name[tool_name]
    binding = binding_by_name.get(tool_name, {})
    adapter = binding.get("selector_action_bindings", {})
    if adapter.get("action") == "read_page":
        return {
            "values": adapter.get("values", {}),
            "headings": adapter.get("headings", []),
            "page_url": adapter.get("page_url"),
            "evidence_ids": tool.get("evidence_ids", []),
            "confidence": tool.get("confidence"),
            "risk_level": tool.get("risk_level", "low"),
            "exposure_level": tool.get("exposure_level", "ready_public"),
        }
    if adapter.get("action") in {"open_fill_dynamic_form", "set_dynamic_item_state", "delete_dynamic_item"}:
        dry_run = mode != "apply" or bool(args.get("dry_run", True))
        planned_steps = [
            {"step": "navigate", "page_id": adapter.get("page_id")},
            {"step": "open_flow", "trigger_label": adapter.get("trigger_label")},
        ]
        if adapter.get("action") == "open_fill_dynamic_form":
            planned_steps.append(
                {
                    "step": "fill_fields",
                    "fields": {field["arg"]: args.get(field["arg"], "") for field in adapter.get("fields", [])},
                    "constraints": adapter.get("constraints", {}),
                }
            )
            planned_steps.append({"step": "submit_or_apply", "requires_confirmation": tool.get("requires_confirmation", False)})
        elif adapter.get("action") == "set_dynamic_item_state":
            planned_steps.append({"step": "find_item", "item_match": args.get("item_match", {})})
            planned_steps.append({"step": "set_state", "desired_state": adapter.get("desired_state")})
            planned_steps.append({"step": "submit_or_apply", "requires_confirmation": tool.get("requires_confirmation", False)})
        else:
            planned_steps.append({"step": "find_item", "item_match": args.get("item_match", {})})
            planned_steps.append({"step": "delete_item", "requires_confirmation": True})
        if dry_run:
            return {
                "status": "dry_run",
                "planned_steps": planned_steps,
                "evidence_ids": tool.get("evidence_ids", []),
                "risk_level": tool.get("risk_level", "medium"),
                "requires_confirmation": tool.get("requires_confirmation", False),
                "exposure_level": tool.get("exposure_level", "review_required"),
                "adapter_action": adapter.get("action"),
            }
        if tool.get("requires_confirmation") and not args.get("confirm"):
            raise RuntimeErrorForTool("Apply mode for this staged action requires confirm=true.")
        if browser:
            return browser_apply_staged_action(server, tool, adapter, args)
        raise RuntimeErrorForTool("Apply mode for staged browser actions requires --browser; dry-run is available.")
    if adapter.get("action") == "submit_form":
        dry_run = mode != "apply" or bool(args.get("dry_run", True))
        field_args = {field["arg"]: args.get(field["arg"], "") for field in adapter.get("fields", [])}
        plan = {
            "method": adapter.get("method", "get").lower(),
            "url": urljoin((server.get("base_url") or "").rstrip("/") + "/", adapter.get("action_url") or ""),
            "fields": field_args,
        }
        if dry_run:
            return {
                "status": "dry_run",
                "planned_request": plan,
                "evidence_ids": tool.get("evidence_ids", []),
                "risk_level": tool.get("risk_level", "medium"),
                "requires_confirmation": tool.get("requires_confirmation", False),
                "exposure_level": tool.get("exposure_level", "review_required"),
            }
        if tool.get("requires_confirmation") and not args.get("confirm"):
            raise RuntimeErrorForTool("Apply mode for this tool requires confirm=true.")
        if tool.get("risk_level") == "high":
            raise RuntimeErrorForTool("High-risk apply calls are not allowed by this runtime.")
        data = urlencode(field_args).encode("utf-8")
        method = plan["method"].upper()
        url = plan["url"]
        if method == "GET":
            url = f"{url}?{urlencode(field_args)}"
            data = None
        request = Request(url, data=data, method=method)
        with urlopen(request, timeout=10) as response:
            status_code = response.status
        return {"status": "applied", "http_status": status_code, "evidence_ids": tool.get("evidence_ids", []), "risk_level": tool.get("risk_level", "medium")}
    value = adapter.get("read_value")
    if value is None:
        value = ""
    result = {
        "value": value,
        "evidence_ids": tool.get("evidence_ids", []),
        "confidence": tool.get("confidence"),
        "risk_level": tool.get("risk_level", "low"),
    }
    return result


def mcp_tool_schema(tool: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": tool["name"],
        "description": tool["description"],
        "inputSchema": tool["args"],
    }


def alias_lookup(tools: list[dict[str, Any]]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    public_names = {tool.get("name") for tool in tools}
    for tool in tools:
        target = tool.get("name")
        if not target:
            continue
        for alias in tool.get("compatibility_aliases", []) or []:
            if alias and alias not in public_names:
                lookup[str(alias)] = str(target)
    return lookup


def handle_request(package_dir: Path, request: dict[str, Any]) -> dict[str, Any] | None:
    request_id = request.get("id")
    method = request.get("method")
    is_notification = "id" not in request
    try:
        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "site-agent-generated", "version": "0.1.0"},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            tools, _ = load_package(package_dir)
            result = {"tools": [mcp_tool_schema(tool) for tool in tools]}
        elif method == "tools/call":
            params = request.get("params", {})
            tool_name = params.get("name")
            if not tool_name:
                raise RuntimeErrorForTool("tools/call requires params.name")
            structured = call_tool(package_dir, tool_name, params.get("arguments", {}), params.get("mode", "dry-run"), bool(params.get("browser", False)))
            result = {
                "content": [{"type": "text", "text": json.dumps(structured, sort_keys=True)}],
                "structuredContent": structured,
                "isError": False,
            }
        elif is_notification:
            return None
        else:
            return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        return {"jsonrpc": "2.0", "id": request_id, "result": result}
    except Exception as exc:
        if is_notification:
            return None
        return {"jsonrpc": "2.0", "id": request_id, "error": {"code": -32000, "message": str(exc)}}


def _write_framed_response(writer: BinaryIO, response: dict[str, Any]) -> None:
    body = json.dumps(response, sort_keys=True).encode("utf-8")
    writer.write(f"Content-Length: {len(body)}\r\n\r\n".encode("ascii") + body)
    writer.flush()


def _serve_framed(package_dir: Path, reader: BinaryIO, writer: BinaryIO, first_header: bytes | None = None) -> None:
    line = first_header
    while True:
        headers: dict[str, str] = {}
        if line is None:
            line = reader.readline()
        if not line:
            break
        while line in (b"\r\n", b"\n"):
            line = reader.readline()
            if not line:
                return
        while line not in (b"\r\n", b"\n", b""):
            decoded = line.decode("ascii", errors="replace").strip()
            if ":" in decoded:
                name, value = decoded.split(":", 1)
                headers[name.lower()] = value.strip()
            line = reader.readline()
        length = int(headers.get("content-length", "0"))
        if length <= 0:
            line = None
            continue
        body = reader.read(length)
        if not body:
            break
        response = handle_request(package_dir, json.loads(body.decode("utf-8")))
        if response is not None:
            _write_framed_response(writer, response)
        line = None


def _serve_binary_json_lines(package_dir: Path, reader: BinaryIO, writer: BinaryIO, first_line: bytes) -> None:
    line = first_line
    while line:
        stripped = line.strip()
        if stripped:
            response = handle_request(package_dir, json.loads(stripped.decode("utf-8")))
            if response is not None:
                writer.write((json.dumps(response, sort_keys=True) + "\n").encode("utf-8"))
                writer.flush()
        line = reader.readline()


def serve_json_lines(package_dir: Path, stdin: TextIO = sys.stdin, stdout: TextIO = sys.stdout) -> None:
    reader = getattr(stdin, "buffer", None)
    writer = getattr(stdout, "buffer", None)
    if reader is not None and writer is not None:
        first_line = reader.readline()
        if not first_line:
            return
        if first_line.lower().startswith(b"content-length:"):
            _serve_framed(package_dir, reader, writer, first_line)
        else:
            _serve_binary_json_lines(package_dir, reader, writer, first_line)
        return

    for line in stdin:
        stripped = line.strip()
        if not stripped:
            continue
        response = handle_request(package_dir, json.loads(stripped))
        if response is not None:
            stdout.write(json.dumps(response, sort_keys=True) + "\n")
            stdout.flush()
