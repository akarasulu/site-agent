from __future__ import annotations

import html
import re
import shutil
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from site_agent.core.models import CrawlSnapshot
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import ensure_dir, read_json, write_json


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


GROUPS = [
    ("Home", ("home_",)),
    ("Topology", ("topology_", "devices_")),
    ("Internet / WAN", ("internet_status_", "internet_wan_", "wan_connection_", "internet_mobile_")),
    ("Internet Services", ("internet_ddns_", "internet_sntp_", "internet_port_binding_", "internet_parental_", "internet_dslite_", "internet_6rd_")),
    ("Security / Firewall", ("security_firewall_", "security_filtering_", "security_mac_", "security_url_", "security_dmz_")),
    ("NAT / Port Forwarding / UPnP", ("security_port_forwarding_", "security_upnp_")),
    ("Local Network / LAN", ("local_network_lan_", "local_network_status_", "local_network_clients_", "lan_dhcp_", "lan_port_", "local_network_dhcpv6_", "local_network_dns_")),
    ("Wi-Fi / WLAN", ("local_network_wifi_", "wifi_")),
    ("Local Services", ("local_network_ftp_", "local_network_dms_", "local_network_upnp_")),
    ("VoIP", ("voip_",)),
    ("Management / Diagnostics", ("management_",)),
]


SURFACE_ARTIFACTS = [
    ("openapi_json", ("docs", "openapi.json"), "artifacts/openapi.json", "OpenAPI JSON", "api"),
    ("openapi_yaml", ("docs", "openapi.yaml"), "artifacts/openapi.yaml", "OpenAPI YAML", "api"),
    ("api_reference", ("docs", "api-reference.md"), "artifacts/api-reference.md", "API Reference", "docs"),
    ("quickstart", ("docs", "quickstart.md"), "artifacts/quickstart.md", "Quickstart", "docs"),
    ("python_api", ("docs", "python-api.md"), "artifacts/python-api.md", "Python API", "docs"),
    ("mcp_tools", ("docs", "mcp-tools.md"), "artifacts/mcp-tools.md", "MCP Tools", "docs"),
    ("ansible_collection", ("docs", "ansible-collection.md"), "artifacts/ansible-collection.md", "Ansible Collection", "docs"),
    ("postman_collection", ("postman", "collection.json"), "artifacts/postman-collection.json", "Postman Collection", "postman"),
    ("postman_environment", ("postman", "environment.json"), "artifacts/postman-environment.json", "Postman Environment", "postman"),
]

DEFAULT_API_BRIDGE_URL = "http://127.0.0.1:8766"


def surface_artifact_entries(root: Path) -> dict[str, dict[str, Any]]:
    entries = {}
    for key, source_parts, relative_path, title, kind in SURFACE_ARTIFACTS:
        source = root.joinpath(*source_parts)
        if source.exists():
            href = human_artifact_href(key, relative_path)
            entries[key] = {
                "href": href,
                "raw_href": relative_path,
                "title": title,
                "kind": kind,
                "bytes": source.stat().st_size,
            }
    return entries


def human_artifact_href(key: str, relative_path: str) -> str:
    if relative_path.endswith(".md"):
        return str(Path(relative_path).with_suffix(".html"))
    if key in {"postman_collection", "postman_environment"}:
        return str(Path(relative_path).with_suffix(".html"))
    return relative_path


def browser_artifact_redirect(path: str, accept_header: str) -> str | None:
    parsed = urlsplit(path)
    if parse_qs(parsed.query).get("raw"):
        return None
    if "text/html" not in accept_header.lower():
        return None
    if parsed.path.startswith("/artifacts/") and parsed.path.endswith(".md"):
        return str(Path(parsed.path).with_suffix(".html"))
    postman_redirects = {
        "/artifacts/openapi.json": "/swagger.html",
        "/artifacts/postman-collection.json": "/artifacts/postman-collection.html",
        "/artifacts/postman-environment.json": "/artifacts/postman-environment.html",
    }
    return postman_redirects.get(parsed.path)


def copy_surface_artifacts(root: Path, explorer_dir: Path) -> None:
    ensure_dir(explorer_dir / "artifacts")
    for key, source_parts, relative_path, title, _kind in SURFACE_ARTIFACTS:
        source = root.joinpath(*source_parts)
        if source.exists():
            destination = explorer_dir / relative_path
            ensure_dir(destination.parent)
            shutil.copy2(source, destination)
            if relative_path.endswith(".md"):
                Path(explorer_dir / human_artifact_href(key, relative_path)).write_text(
                    build_markdown_viewer(title, relative_path, source.read_text(encoding="utf-8")),
                    encoding="utf-8",
                )
            elif key in {"postman_collection", "postman_environment"}:
                Path(explorer_dir / human_artifact_href(key, relative_path)).write_text(
                    build_postman_viewer(title, key, relative_path),
                    encoding="utf-8",
                )


def inline_markdown(value: str) -> str:
    escaped = html.escape(value)
    escaped = re.sub(r"`([^`]+)`", r"<code>\1</code>", escaped)
    escaped = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", escaped)
    return escaped


def markdown_table(lines: list[str]) -> str:
    raw_rows = []
    for line in lines:
        raw_cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in raw_cells):
            continue
        raw_rows.append(raw_cells)
    if not raw_rows:
        return ""
    headers = raw_rows[0]
    head = "".join(f"<th>{inline_markdown(cell)}</th>" for cell in headers)
    body_rows = []
    for row in raw_rows[1:]:
        cells = []
        for index, cell in enumerate(row):
            header = headers[index].strip().lower() if index < len(headers) else ""
            value = evidence_table_cell(cell) if header in {"evidence", "evidence ids"} else inline_markdown(cell)
            cells.append(f"<td>{value}</td>")
        body_rows.append("<tr>" + "".join(cells) + "</tr>")
    body = "".join(body_rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def evidence_table_cell(value: str) -> str:
    normalized = value.strip()
    if not normalized or normalized.lower() == "none":
        return "none"
    evidence_ids = [item.strip().strip("`") for item in normalized.split(",") if item.strip()]
    if not evidence_ids:
        return inline_markdown(normalized)
    label = f"{len(evidence_ids)} evidence item" + ("" if len(evidence_ids) == 1 else "s")
    chips = "".join(f"<code>{html.escape(evidence_id)}</code>" for evidence_id in evidence_ids)
    return f"<details class=\"evidence\"><summary>{label}</summary><div class=\"evidence-list\">{chips}</div></details>"


def markdown_to_html(markdown: str) -> str:
    html_lines: list[str] = []
    lines = markdown.splitlines()
    in_code = False
    code_lines: list[str] = []
    index = 0
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            if in_code:
                html_lines.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
                code_lines = []
                in_code = False
            else:
                in_code = True
            index += 1
            continue
        if in_code:
            code_lines.append(line)
            index += 1
            continue
        if line.startswith("|"):
            table_lines = []
            while index < len(lines) and lines[index].startswith("|"):
                table_lines.append(lines[index])
                index += 1
            html_lines.append(markdown_table(table_lines))
            continue
        stripped = line.strip()
        if not stripped:
            index += 1
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            level = len(heading.group(1))
            html_lines.append(f"<h{level}>{inline_markdown(heading.group(2))}</h{level}>")
        elif stripped.startswith("* "):
            items = []
            while index < len(lines) and lines[index].strip().startswith("* "):
                items.append(f"<li>{inline_markdown(lines[index].strip()[2:])}</li>")
                index += 1
            html_lines.append("<ul>" + "".join(items) + "</ul>")
            continue
        else:
            html_lines.append(f"<p>{inline_markdown(stripped)}</p>")
        index += 1
    if in_code:
        html_lines.append("<pre><code>" + html.escape("\n".join(code_lines)) + "</code></pre>")
    return "\n".join(html_lines)


def build_artifact_page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(title)}</title>
<style>
body {{ margin:0; font-family:Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color:#17202a; background:#f6f8fb; }}
main {{ max-width:1080px; margin:0 auto; padding:24px; }}
article {{ background:#fff; border:1px solid #d9dee6; border-radius:8px; padding:24px; }}
a {{ color:#1267b1; }}
table {{ border-collapse:collapse; width:100%; margin:14px 0; font-size:14px; }}
th, td {{ border-bottom:1px solid #d9dee6; padding:8px; text-align:left; vertical-align:top; }}
th {{ color:#425166; font-size:12px; }}
pre {{ background:#17202a; color:#f8fbff; overflow:auto; padding:14px; border-radius:6px; }}
code {{ font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }}
details.evidence summary {{ color:#1267b1; cursor:pointer; font-weight:650; }}
.evidence-list {{ display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; max-height:220px; overflow:auto; }}
.evidence-list code {{ background:#f1f5f9; border:1px solid #d9dee6; border-radius:999px; padding:2px 6px; }}
.actions {{ display:flex; flex-wrap:wrap; gap:8px; margin:12px 0 18px; }}
.button {{ background:#1267b1; border:1px solid #1267b1; border-radius:6px; color:#fff; display:inline-flex; min-height:34px; padding:7px 11px; text-decoration:none; }}
.button.secondary {{ background:#fff; color:#1267b1; }}
</style>
</head>
<body>
<main><article>{body}</article></main>
</body>
</html>
"""


def build_markdown_viewer(title: str, raw_href: str, markdown: str) -> str:
    body = (
        f"<div class=\"actions\"><a class=\"button secondary\" href=\"{html.escape(Path(raw_href).name)}?raw=1\" download>Download Markdown</a>"
        "<a class=\"button secondary\" href=\"../index.html\">Back To Explorer</a></div>"
        + markdown_to_html(markdown)
    )
    return build_artifact_page(title, body)


def build_postman_viewer(title: str, key: str, raw_href: str) -> str:
    noun = "collection" if key == "postman_collection" else "environment"
    raw_name = Path(raw_href).name
    body = f"""
<h1>{html.escape(title)}</h1>
<p>Use this generated Postman {noun} with the local site-agent API bridge.</p>
<div class="actions">
  <a class="button" href="{html.escape(raw_name)}?raw=1" download>Download {html.escape(title)}</a>
  <a class="button secondary" href="https://web.postman.co/" target="_blank" rel="noreferrer">Open Postman Web</a>
  <a class="button secondary" href="https://learning.postman.com/docs/getting-started/importing-and-exporting/importing-data/" target="_blank" rel="noreferrer">Postman Import Docs</a>
  <a class="button secondary" href="../index.html">Back To Explorer</a>
</div>
<h2>Import Steps</h2>
<ol>
  <li>Start the bridge with <code>site-agent api serve --profile &lt;profile&gt;</code>.</li>
  <li>In Postman, choose <strong>Import</strong> and select the downloaded {html.escape(noun)} JSON file.</li>
  <li>Import both the collection and environment so requests can use <code>{{{{baseUrl}}}}</code>.</li>
</ol>
<h2>Preview</h2>
<pre id="json-preview">Loading JSON preview...</pre>
<script>
fetch('{html.escape(raw_name)}?raw=1')
  .then(response => response.json())
  .then(data => {{
    document.getElementById('json-preview').textContent = JSON.stringify(data, null, 2);
  }})
  .catch(error => {{
    document.getElementById('json-preview').textContent = String(error);
  }});
</script>
"""
    return build_artifact_page(title, body)


def openapi_bridge_metadata(root: Path) -> tuple[str, dict[str, dict[str, str]]]:
    openapi_path = root / "docs" / "openapi.json"
    if not openapi_path.exists():
        return DEFAULT_API_BRIDGE_URL, {}
    spec = read_json(openapi_path)
    servers = spec.get("servers") or []
    bridge_url = DEFAULT_API_BRIDGE_URL
    if servers and isinstance(servers[0], dict) and servers[0].get("url"):
        bridge_url = str(servers[0]["url"]).rstrip("/")
    operations: dict[str, dict[str, str]] = {}
    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        post = path_item.get("post")
        if not isinstance(post, dict):
            continue
        site_agent = post.get("x-site-agent") if isinstance(post.get("x-site-agent"), dict) else {}
        method_name = str(site_agent.get("method_name") or post.get("operationId") or Path(path).name)
        tags = post.get("tags") if isinstance(post.get("tags"), list) else []
        operations[method_name] = {
            "path": str(path),
            "operation_id": str(post.get("operationId") or method_name),
            "tag": str(tags[0]) if tags else "Generated API",
        }
    return bridge_url, operations


def method_group(name: str) -> str:
    for group, prefixes in GROUPS:
        if name.startswith(prefixes):
            return group
    return "Other"


def page_key(url: str | None, page_id: str | None) -> str:
    if url:
        return url.split("#state=", 1)[-1] if "#state=" in url else url
    return page_id or "unknown"


def element_lookup(snapshot: CrawlSnapshot) -> dict[str, dict[str, Any]]:
    return {
        element.id: {
            "id": element.id,
            "page_id": element.page_id,
            "label": element.label,
            "control_type": element.control_type,
            "selector_fingerprint": element.selector_fingerprint,
            "read_value": element.context.get("read_value") if isinstance(element.context, dict) else None,
            "headings": element.context.get("headings", []) if isinstance(element.context, dict) else [],
            "evidence_ids": element.evidence_ids,
        }
        for element in snapshot.elements
    }


def form_lookup(snapshot: CrawlSnapshot) -> dict[str, dict[str, Any]]:
    return {
        form.id: {
            "id": form.id,
            "page_id": form.page_id,
            "label": form.label,
            "method": form.method,
            "action": form.action,
            "field_ids": form.field_ids,
        }
        for form in snapshot.forms
    }


def page_lookup(snapshot: CrawlSnapshot) -> dict[str, dict[str, Any]]:
    return {
        page.id: {
            "id": page.id,
            "url": page.url,
            "title": page.title,
            "headings": page.headings,
            "state": page_key(page.url, page.id),
            "html_snapshot": page.html_snapshot,
        }
        for page in snapshot.pages
    }


def best_page_match(page_id: str | None, adapter: dict[str, Any], pages_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    exact = pages_by_id.get(page_id or "", {})
    if exact.get("html_snapshot"):
        return exact
    desired_state = page_key(adapter.get("page_url"), page_id)
    desired_tokens = {part for part in slug(desired_state).split("_") if len(part) > 2}
    desired_headings = {slug(item) for item in adapter.get("headings", []) or [] if str(item).strip()}
    best: tuple[float, dict[str, Any]] = (0.0, exact)
    for page in pages_by_id.values():
        page_tokens = {part for part in slug(page.get("state") or page.get("url") or "").split("_") if len(part) > 2}
        page_headings = {slug(item) for item in page.get("headings", []) or [] if str(item).strip()}
        score = 0.0
        if desired_tokens:
            score += len(desired_tokens & page_tokens) / len(desired_tokens)
        if desired_headings and desired_headings & page_headings:
            score += 1.0
        if page.get("html_snapshot"):
            score += 1.0
        if score > best[0]:
            best = (score, page)
    return best[1] if best[0] >= 0.75 else exact


def semantic_tree(methods: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = {group: [] for group, _ in GROUPS}
    groups["Other"] = []
    for method in methods:
        groups.setdefault(method_group(method["name"]), []).append(method)
    return [
        {
            "name": group,
            "count": len(items),
            "methods": sorted((item["name"] for item in items)),
        }
        for group, items in groups.items()
        if items
    ]


def touched_annotations(adapter: dict[str, Any], elements_by_id: dict[str, dict[str, Any]], forms_by_id: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    annotations: list[dict[str, Any]] = []
    form_id = adapter.get("form_id")
    if form_id:
        form = forms_by_id.get(form_id, {"id": form_id})
        annotations.append(
            {
                "kind": "form",
                "id": form_id,
                "label": adapter.get("page_label") or form.get("label") or "form",
                "detail": f"{adapter.get('method', form.get('method') or 'get').upper()} form submit",
            }
        )
    for field in adapter.get("fields", []) or []:
        element = elements_by_id.get(str(field.get("ui_element_id", "")), {})
        annotations.append(
            {
                "kind": "field",
                "id": field.get("ui_element_id") or field.get("arg"),
                "arg": field.get("arg"),
                "label": field.get("label") or field.get("arg"),
                "control_type": field.get("control_type") or element.get("control_type") or "field",
                "detail": f"API argument `{field.get('arg')}`",
            }
        )
    for element_id in adapter.get("element_ids", []) or []:
        element = elements_by_id.get(str(element_id))
        if not element or element.get("control_type") == "hidden":
            continue
        annotations.append(
            {
                "kind": "widget",
                "id": element_id,
                "label": element.get("label") or element_id,
                "control_type": element.get("control_type"),
                "value": element.get("read_value"),
                "detail": "Read from page evidence",
            }
        )
        if len(annotations) >= 80:
            break
    return annotations


def build_explorer_data(profile: Profile, snapshot: CrawlSnapshot, root: Path) -> dict[str, Any]:
    tools = read_json(root / "mcp" / "tools.json").get("tools", [])
    bindings = read_json(root / "mcp" / "adapter.bindings.json").get("bindings", [])
    api_path = root / "api" / "api-spec.json"
    api_methods = read_json(api_path).get("methods", []) if api_path.exists() else []
    ansible_path = root / "ansible" / "ansible-spec.json"
    ansible_spec = read_json(ansible_path) if ansible_path.exists() else {}
    capabilities_path = root / "capabilities" / "capabilities.json"
    capabilities = read_json(capabilities_path) if capabilities_path.exists() else {}
    bindings_by_tool = {binding.get("tool_name"): binding for binding in bindings}
    tools_by_name = {tool.get("name"): tool for tool in tools}
    pages_by_id = page_lookup(snapshot)
    elements_by_id = element_lookup(snapshot)
    forms_by_id = form_lookup(snapshot)
    artifacts = surface_artifact_entries(root)
    api_bridge_url, openapi_operations = openapi_bridge_metadata(root)
    methods: list[dict[str, Any]] = []
    for method in sorted(api_methods, key=lambda item: item.get("name", "")):
        name = method.get("name", "")
        tool = tools_by_name.get(method.get("backing_tool") or name, {})
        binding = bindings_by_tool.get(method.get("backing_tool") or name, {})
        adapter = binding.get("selector_action_bindings", {})
        form_id = adapter.get("form_id")
        form = forms_by_id.get(form_id or "", {})
        page_id = adapter.get("page_id") or form.get("page_id")
        exact_page = pages_by_id.get(page_id or "", {})
        adapter_for_match = dict(adapter)
        if not adapter_for_match.get("page_url"):
            adapter_for_match["page_url"] = exact_page.get("url")
        if not adapter_for_match.get("headings"):
            adapter_for_match["headings"] = exact_page.get("headings", [])
        page = best_page_match(page_id, adapter_for_match, pages_by_id)
        annotations = touched_annotations(adapter, elements_by_id, forms_by_id)
        methods.append(
            {
                "name": name,
                "group": method_group(name),
                "description": method.get("description") or tool.get("description", ""),
                "risk_level": method.get("risk_level") or tool.get("risk_level"),
                "args": sorted((method.get("args", {}).get("properties") or {}).keys()),
                "arg_schema": method.get("args", {}),
                "return_schema": method.get("return_schema", {}),
                "openapi": openapi_operations.get(
                    name,
                    {
                        "path": f"/methods/{name}",
                        "operation_id": name,
                        "tag": "Generated API",
                    },
                ),
                "backing_tool": method.get("backing_tool") or name,
                "source_type": tool.get("source_type"),
                "reasoning_summary": tool.get("reasoning_summary"),
                "evidence_ids": method.get("evidence_ids") or tool.get("evidence_ids", []),
                "adapter_action": adapter.get("action"),
                "ui": {
                    "page_id": page_id,
                    "page_url": adapter.get("page_url") or page.get("url"),
                    "source_url": (adapter.get("page_url") or page.get("url") or "").split("#", 1)[0],
                    "state": page_key(adapter.get("page_url") or page.get("url"), page_id),
                    "headings": adapter.get("headings") or page.get("headings", []),
                    "html_snapshot": page.get("html_snapshot"),
                    "form_id": form_id,
                    "page_label": adapter.get("page_label"),
                    "purpose_label": adapter.get("purpose_label"),
                    "values": adapter.get("values", {}),
                    "annotations": annotations,
                },
            }
        )
    return {
        "profile": {"id": profile.id, "name": profile.name, "base_url": profile.base_url},
        "api_bridge_url": api_bridge_url,
        "summary": {
            "methods": len(methods),
            "public_tools": len([tool for tool in tools if tool.get("exposure_level") != "internal_disabled"]),
            "ansible_modules": len(ansible_spec.get("modules", [])),
            "docs": len([entry for entry in artifacts.values() if entry["kind"] in {"api", "docs"}]),
            "postman": len([entry for entry in artifacts.values() if entry["kind"] == "postman"]),
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "groups": len({method["group"] for method in methods}),
        },
        "tree": semantic_tree(methods),
        "methods": methods,
        "artifacts": artifacts,
        "mcp": {
            "tools": [
                {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "risk_level": tool.get("risk_level", "low"),
                    "source_type": tool.get("source_type", "canonical_concept"),
                    "evidence_ids": tool.get("evidence_ids", []),
                }
                for tool in sorted(tools, key=lambda item: item.get("name", ""))
                if tool.get("exposure_level") != "internal_disabled"
            ]
        },
        "ansible": {
            "namespace": ansible_spec.get("namespace", "site_agent"),
            "name": ansible_spec.get("name"),
            "modules": ansible_spec.get("modules", []),
        },
        "capabilities": capabilities.get("projection_report", {}),
    }


EXPLORER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Semantic API Explorer</title>
<style>
:root { color-scheme: light; --ink:#17202a; --muted:#5d6978; --line:#d9dee6; --blue:#1267b1; --green:#19775c; --red:#a33a3a; --bg:#f6f8fb; --panel:#fff; }
* { box-sizing: border-box; }
body { margin:0; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; background:var(--bg); color:var(--ink); }
header { min-height:58px; display:flex; align-items:center; gap:18px; padding:8px 20px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:5; }
h1 { font-size:18px; margin:0; }
.meta { color:var(--muted); font-size:13px; }
.modes, .tabs { display:flex; flex-wrap:wrap; gap:6px; }
.modes { margin-left:auto; }
.mode, .tab, .small-button { background:#fff; border:1px solid var(--line); border-radius:6px; color:var(--ink); cursor:pointer; font-size:13px; padding:7px 10px; }
.small-button { padding:5px 8px; }
.mode:hover, .mode.active, .tab:hover, .tab.active, .small-button:hover { background:#eaf3fb; border-color:#9bc5e7; color:#0d5d9f; }
.mode.active { background:#1267b1; border-color:#1267b1; color:#fff; }
.load-error { margin:18px; padding:14px; border:1px solid #e3aaaa; background:#fff4f4; color:#8d2929; border-radius:8px; }
.shell { --nav-width:330px; --detail-width:420px; display:grid; grid-template-columns: var(--nav-width) 10px minmax(420px, 1fr) 10px var(--detail-width); min-height:calc(100vh - 58px); }
.shell.portal-mode { display:block; }
.shell.portal-mode aside, .shell.portal-mode .splitter, .shell.portal-mode section.detail { display:none; }
.shell.portal-mode main { max-width:1180px; margin:0 auto; }
.shell.nav-collapsed { --nav-width:0px; }
.shell.detail-collapsed { --detail-width:0px; }
aside, main, section { min-width:0; }
aside { border-right:1px solid var(--line); background:#fff; overflow:auto; padding:14px; }
main { overflow:auto; padding:18px; }
section.detail { border-left:1px solid var(--line); background:#fff; overflow:auto; padding:18px; }
.shell.nav-collapsed aside, .shell.detail-collapsed section.detail { border:0; overflow:hidden; padding:0; visibility:hidden; }
.splitter { appearance:none; background:#edf2f7; border:0; border-left:1px solid var(--line); border-right:1px solid var(--line); cursor:col-resize; min-width:10px; padding:0; position:relative; }
.splitter:hover, .splitter:focus-visible, .splitter.dragging { background:#dce8f4; outline:none; }
.splitter::before { background:#9aabba; border-radius:999px; content:""; height:44px; left:50%; position:absolute; top:calc(50vh - 58px); transform:translateX(-50%); width:2px; }
.splitter::after { color:#667789; content:""; font-size:12px; left:50%; line-height:1; position:absolute; top:calc(50vh - 32px); transform:translateX(-50%); }
.splitter[data-pane="nav"]::after { content:"<"; }
.splitter[data-pane="detail"]::after { content:">"; }
.shell.nav-collapsed .splitter[data-pane="nav"]::after { content:">"; }
.shell.detail-collapsed .splitter[data-pane="detail"]::after { content:"<"; }
.search { width:100%; padding:10px 11px; border:1px solid var(--line); border-radius:6px; font-size:14px; margin-bottom:12px; }
details { border-bottom:1px solid #edf0f4; padding:6px 0; }
summary { cursor:pointer; font-weight:650; font-size:14px; }
.method { display:block; width:100%; text-align:left; border:0; background:transparent; padding:7px 8px; border-radius:6px; color:var(--ink); cursor:pointer; font-size:13px; }
.method:hover, .method.active { background:#eaf3fb; color:#0d5d9f; }
.cards { display:grid; grid-template-columns: repeat(4, minmax(0, 1fr)); gap:10px; margin-bottom:16px; }
.card { background:#fff; border:1px solid var(--line); border-radius:8px; padding:12px; }
.card b { display:block; font-size:22px; }
.portal { background:#fff; border:1px solid var(--line); border-radius:8px; padding:18px; }
.portal h2 { font-size:20px; margin:0 0 8px; }
.portal h3 { font-size:15px; margin:20px 0 8px; }
.portal p { color:var(--muted); margin:0 0 14px; max-width:860px; }
.doc-grid { display:grid; grid-template-columns:repeat(3, minmax(0, 1fr)); gap:10px; margin:14px 0; }
.doc-card { border:1px solid var(--line); border-radius:8px; padding:12px; background:#fbfcfe; }
.doc-card b { display:block; margin-bottom:6px; }
.callout { border:1px solid #b8d6ec; border-radius:8px; background:#f2f8fd; padding:12px; margin:14px 0; }
.example-grid { display:grid; grid-template-columns:repeat(2, minmax(0, 1fr)); gap:10px; margin-top:12px; }
.example-card { border:1px solid var(--line); border-radius:8px; background:#fff; padding:12px; min-width:0; }
.example-card b { display:block; margin-bottom:8px; }
.try-panel { border:1px solid #b8d6ec; border-radius:8px; background:#fff; margin-top:12px; padding:12px; }
.try-grid { display:grid; grid-template-columns:minmax(0, 1fr) minmax(0, 1fr); gap:12px; }
.try-panel label { color:var(--muted); display:block; font-size:13px; margin-bottom:6px; }
.try-panel input[type="text"], .try-panel textarea { border:1px solid var(--line); border-radius:6px; font:13px ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; padding:9px; width:100%; }
.try-panel textarea { min-height:240px; resize:vertical; }
.try-status { color:var(--muted); font-size:13px; margin-top:8px; min-height:20px; }
.try-status.error { color:var(--red); }
.try-status.ok { color:var(--green); }
.check-row { align-items:center; display:flex; gap:8px; margin:8px 0; }
.actions { display:flex; flex-wrap:wrap; gap:8px; margin:12px 0; }
.button-link { align-items:center; background:#1267b1; border:1px solid #1267b1; border-radius:6px; color:#fff; display:inline-flex; font-size:13px; min-height:34px; padding:7px 11px; text-decoration:none; }
.button-link.secondary { background:#fff; color:#1267b1; }
.cmd { background:#17202a; border-radius:6px; color:#f8fbff; font-family:ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; font-size:12px; padding:12px; white-space:pre-wrap; }
.table { width:100%; border-collapse:collapse; font-size:13px; margin-top:8px; }
.table th, .table td { border-bottom:1px solid var(--line); padding:8px; text-align:left; vertical-align:top; }
.table th { color:#425166; font-size:12px; }
.view { background:#fff; border:1px solid var(--line); border-radius:8px; overflow:hidden; }
.view-head { padding:14px 16px; border-bottom:1px solid var(--line); display:flex; align-items:flex-start; justify-content:space-between; gap:12px; }
.view-title { font-size:18px; font-weight:700; }
.risk { padding:3px 7px; border-radius:999px; font-size:12px; border:1px solid var(--line); }
.risk.low { color:var(--green); background:#edf8f4; }
.risk.medium { color:#986400; background:#fff6da; }
.canvas { --visual-width:320px; --annotations-width:280px; padding:16px; display:grid; grid-template-columns: var(--visual-width) 10px minmax(380px, 1fr) 10px var(--annotations-width); gap:0; }
.canvas.visual-collapsed { --visual-width:0px; }
.canvas.annotations-collapsed { --annotations-width:0px; }
.canvas > .page, .canvas > .anno-list { margin:0 8px; }
.canvas.visual-collapsed > .ui-visual, .canvas.annotations-collapsed > .anno-list { border:0; margin:0; overflow:hidden; padding:0; visibility:hidden; }
.canvas-splitter { appearance:none; align-self:stretch; background:#edf2f7; border:1px solid var(--line); border-bottom:0; border-top:0; cursor:col-resize; min-width:10px; padding:0; position:relative; }
.canvas-splitter:hover, .canvas-splitter:focus-visible, .canvas-splitter.dragging { background:#dce8f4; outline:none; }
.canvas-splitter::before { background:#9aabba; border-radius:999px; content:""; height:40px; left:50%; position:absolute; top:220px; transform:translateX(-50%); width:2px; }
.canvas-splitter[data-pane="visual"]::after { color:#667789; content:"<"; font-size:12px; left:50%; position:absolute; top:246px; transform:translateX(-50%); }
.canvas-splitter[data-pane="annotations"]::after { color:#667789; content:">"; font-size:12px; left:50%; position:absolute; top:246px; transform:translateX(-50%); }
.canvas.visual-collapsed .canvas-splitter[data-pane="visual"]::after { content:">"; }
.canvas.annotations-collapsed .canvas-splitter[data-pane="annotations"]::after { content:"<"; }
.page { border:1px solid #cfd7e2; background:#fbfcfe; min-height:420px; min-width:0; border-radius:6px; padding:14px; position:relative; }
.actual-page { padding:0; overflow:hidden; }
.actual-page iframe { width:100%; height:620px; border:0; background:#fff; }
.empty-visual { padding:14px; color:var(--muted); }
.browser { height:28px; border-bottom:1px solid var(--line); margin:-14px -14px 14px; padding:6px 10px; color:var(--muted); font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.heading { padding:9px 10px; background:#fff; border:1px solid var(--line); border-radius:6px; margin-bottom:8px; font-weight:650; }
.widget { display:flex; align-items:center; justify-content:space-between; gap:8px; border:1px solid var(--line); background:#fff; border-radius:6px; padding:8px 10px; margin:7px 0; font-size:13px; }
.widget .badge { color:#0d5d9f; background:#eaf3fb; padding:2px 6px; border-radius:999px; font-size:11px; }
.widget.field { border-color:#88b8e1; }
.widget.form { border-color:#d1a650; background:#fffaf0; }
.anno-list { border-left:3px solid #e5eaf0; padding-left:12px; }
.anno { border:1px solid var(--line); border-radius:6px; padding:8px; margin-bottom:8px; font-size:13px; background:#fff; }
.anno b { display:block; margin-bottom:3px; }
.kv { display:grid; grid-template-columns:120px 1fr; gap:6px 10px; font-size:13px; }
.chips { display:flex; flex-wrap:wrap; gap:6px; }
.chip { border:1px solid var(--line); border-radius:999px; padding:3px 7px; font-size:12px; background:#fbfcfe; }
details.evidence { background:#fbfcfe; border:1px solid var(--line); border-radius:6px; padding:8px; }
details.evidence summary { color:#1267b1; cursor:pointer; font-weight:650; }
.evidence-list { display:flex; flex-wrap:wrap; gap:6px; margin-top:8px; max-height:220px; overflow:auto; }
.evidence-list code { background:#fff; border:1px solid var(--line); border-radius:999px; font-size:12px; padding:2px 6px; }
pre { white-space:pre-wrap; word-break:break-word; background:#f7f9fc; border:1px solid var(--line); border-radius:6px; padding:10px; font-size:12px; }
@media (max-width: 1100px) { header { align-items:flex-start; flex-direction:column; gap:8px; } .modes { margin-left:0; } .shell { display:block; } aside, section.detail { border:0; } .splitter, .canvas-splitter { display:none; } .canvas { display:block; } .canvas > .page, .canvas > .anno-list { margin:0 0 16px; } .doc-grid, .example-grid, .try-grid { grid-template-columns:1fr; } }
</style>
</head>
<body>
<header>
  <h1>Generated API Explorer</h1><span class="meta" id="profile"></span>
  <nav class="modes" aria-label="Explorer modes">
    <button class="mode" type="button" data-mode="use" onclick="setMode('use')">Use</button>
    <button class="mode" type="button" data-mode="automate" onclick="setMode('automate')">Automate</button>
    <button class="mode" type="button" data-mode="audit" onclick="setMode('audit')">Audit</button>
    <button class="mode" type="button" data-mode="debug" onclick="setMode('debug')">Debug</button>
  </nav>
  <nav class="tabs" aria-label="Explorer sections">
    <button class="tab" type="button" data-tab="overview" onclick="setTab('overview')">Overview</button>
    <button class="tab" type="button" data-tab="api" onclick="setTab('api')">API</button>
    <button class="tab" type="button" data-tab="python" onclick="setTab('python')">Python</button>
    <button class="tab" type="button" data-tab="mcp" onclick="setTab('mcp')">MCP</button>
    <button class="tab" type="button" data-tab="ansible" onclick="setTab('ansible')">Ansible</button>
    <button class="tab" type="button" data-tab="postman" onclick="setTab('postman')">Postman</button>
    <button class="tab" type="button" data-tab="audit" onclick="setTab('audit')">Audit</button>
    <button class="tab" type="button" data-tab="debug" onclick="setTab('debug')">Debug</button>
  </nav>
</header>
<div class="shell" id="shell">
<aside><input class="search" id="q" placeholder="Filter capabilities"><div id="tree"></div></aside>
<button class="splitter" type="button" data-pane="nav" title="Drag to resize, double-click to collapse or restore the capability list" aria-label="Resize capability list"></button>
<main><div class="cards" id="cards"></div><div class="view" id="view"></div></main>
<button class="splitter" type="button" data-pane="detail" title="Drag to resize, double-click to collapse or restore the details pane" aria-label="Resize details pane"></button>
<section class="detail" id="detail"></section>
</div>
<script>
const $ = (id) => document.getElementById(id);
let DATA, selected, currentTab = localStorage.getItem('siteAgentExplorer.tab') || 'overview';
let currentMode = localStorage.getItem('siteAgentExplorer.mode') || 'use';
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function risk(r){ return `<span class="risk ${esc(r)}">${esc(r)}</span>`; }
function jsString(value){ return JSON.stringify(String(value ?? '')).replace(/"/g, '&quot;'); }
function evidenceDetails(ids, emptyLabel='none'){
  const values = (ids || []).filter(Boolean);
  if (!values.length) return `<span class="meta">${esc(emptyLabel)}</span>`;
  const label = `${values.length} evidence item${values.length === 1 ? '' : 's'}`;
  const chips = values.map(id => `<code>${esc(id)}</code>`).join('');
  return `<details class="evidence"><summary>${esc(label)}</summary><div class="evidence-list">${chips}</div></details>`;
}
function shellQuote(s){
  const value = String(s ?? '');
  return /^[A-Za-z0-9_./:-]+$/.test(value) ? value : `'${value.replace(/'/g, `'\"'\"'`)}'`;
}
function profileSlug(){
  return DATA.profile.name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '') || 'generated';
}
function sampleValue(name, schema={}){
  if (Array.isArray(schema.enum) && schema.enum.length) return schema.enum[0];
  const type = Array.isArray(schema.type) ? schema.type[0] : schema.type;
  if (type === 'boolean') return false;
  if (type === 'integer' || type === 'number') return 0;
  if (type === 'array') return [];
  if (type === 'object') return {};
  return `example_${name}`;
}
function sampleArgs(method){
  const properties = method.arg_schema?.properties || {};
  return (method.args || []).reduce((args, name) => {
    args[name] = sampleValue(name, properties[name] || {});
    return args;
  }, {});
}
function methodRequest(method){
  return {args: sampleArgs(method), browser: false, mode: 'dry-run'};
}
function bridgeDefaultUrl(){
  return (localStorage.getItem('siteAgentExplorer.bridgeUrl') || DATA.api_bridge_url || 'http://127.0.0.1:8766').replace(/\/+$/, '');
}
function bridgeUrl(){
  const input = $('bridge-url');
  const value = (input?.value || bridgeDefaultUrl()).trim().replace(/\/+$/, '');
  localStorage.setItem('siteAgentExplorer.bridgeUrl', value);
  return value;
}
function swaggerHref(method){
  const operation = method.openapi || {};
  return `swagger.html#/${encodeURIComponent(operation.tag || 'Generated API')}/${encodeURIComponent(operation.operation_id || method.name)}`;
}
function methodCallArgs(method){
  const args = sampleArgs(method);
  return Object.entries(args).map(([name, value]) => `${name}=${JSON.stringify(value)}`).join(', ');
}
function ansibleModuleFor(method){
  return (DATA.ansible?.modules || []).find(module => String(module.name || '').endsWith(method.name));
}
function selectedMethod(){
  selected = selected || DATA.methods[0];
  return selected;
}
function setTryStatus(message, kind=''){
  const status = $('try-status');
  if (!status) return;
  status.className = `try-status ${kind}`;
  status.textContent = message;
}
function setTryResponse(value){
  const response = $('try-response');
  if (!response) return;
  response.textContent = typeof value === 'string' ? value : JSON.stringify(value, null, 2);
}
function resetTryBody(){
  const body = $('try-body');
  const method = selectedMethod();
  if (!body || !method) return;
  body.value = JSON.stringify(methodRequest(method), null, 2);
  setTryStatus('Request reset to dry-run defaults.', 'ok');
  setTryResponse('');
}
async function checkBridge(){
  setTryStatus('Checking bridge...', '');
  try {
    const response = await fetch(`${bridgeUrl()}/health`, {method: 'GET'});
    const payload = await response.json();
    if (!response.ok) {
      setTryStatus(`Bridge returned HTTP ${response.status}.`, 'error');
    } else {
      setTryStatus(`Bridge ready: ${payload.methods ?? '?'} method(s).`, 'ok');
    }
    setTryResponse(payload);
  } catch (error) {
    setTryStatus(`Bridge not reachable. Start: site-agent api serve --profile ${DATA.profile.name}`, 'error');
    setTryResponse(String(error));
  }
}
function parseTryBody(){
  try {
    const payload = JSON.parse($('try-body')?.value || '{}');
    if (!payload || typeof payload !== 'object' || Array.isArray(payload)) {
      throw new Error('Request body must be a JSON object.');
    }
    if (payload.args != null && (typeof payload.args !== 'object' || Array.isArray(payload.args))) {
      throw new Error('Request body field "args" must be an object.');
    }
    payload.args = payload.args || {};
    payload.browser = Boolean(payload.browser);
    return payload;
  } catch (error) {
    setTryStatus(`Invalid request JSON: ${error.message || error}`, 'error');
    setTryResponse('');
    return null;
  }
}
async function tryOperation(methodName, applyMode=false){
  const method = DATA.methods.find(item => item.name === methodName) || selectedMethod();
  const payload = parseTryBody();
  if (!payload || !method) return;
  if (applyMode) {
    if (!$('try-apply-confirm')?.checked) {
      setTryStatus('Enable apply mode before sending a mutating request.', 'error');
      return;
    }
    if ((method.risk_level || 'low') !== 'low' && !window.confirm(`Apply ${method.name}? This is ${method.risk_level} risk.`)) {
      setTryStatus('Apply request cancelled.', '');
      return;
    }
    payload.mode = 'apply';
  } else {
    payload.mode = 'dry-run';
  }
  setTryStatus(`${applyMode ? 'Applying' : 'Running dry-run'} ${method.name}...`, '');
  setTryResponse('');
  try {
    const response = await fetch(`${bridgeUrl()}/methods/${encodeURIComponent(method.name)}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    const text = await response.text();
    let payloadOut;
    try {
      payloadOut = text ? JSON.parse(text) : {};
    } catch (_error) {
      payloadOut = text;
    }
    setTryStatus(response.ok ? `HTTP ${response.status} ${response.statusText || 'OK'}` : `HTTP ${response.status} ${response.statusText || 'error'}`, response.ok ? 'ok' : 'error');
    setTryResponse(payloadOut);
  } catch (error) {
    setTryStatus(`Request failed. Is the API bridge running on ${bridgeUrl()}?`, 'error');
    setTryResponse(String(error));
  }
}
const layoutState = {
  navWidth: Number(localStorage.getItem('siteAgentExplorer.navWidth')) || 330,
  detailWidth: Number(localStorage.getItem('siteAgentExplorer.detailWidth')) || 420,
  visualWidth: Number(localStorage.getItem('siteAgentExplorer.visualWidth')) || 320,
  annotationsWidth: Number(localStorage.getItem('siteAgentExplorer.annotationsWidth')) || 280,
  navCollapsed: localStorage.getItem('siteAgentExplorer.navCollapsed') === 'true',
  detailCollapsed: localStorage.getItem('siteAgentExplorer.detailCollapsed') === 'true',
  visualCollapsed: localStorage.getItem('siteAgentExplorer.visualCollapsed') === 'true',
  annotationsCollapsed: localStorage.getItem('siteAgentExplorer.annotationsCollapsed') === 'true',
};
function clamp(value, min, max){
  return Math.min(Math.max(value, min), max);
}
function applyShellLayout(){
  const shell = $('shell');
  shell.style.setProperty('--nav-width', `${layoutState.navCollapsed ? 0 : layoutState.navWidth}px`);
  shell.style.setProperty('--detail-width', `${layoutState.detailCollapsed ? 0 : layoutState.detailWidth}px`);
  shell.classList.toggle('nav-collapsed', layoutState.navCollapsed);
  shell.classList.toggle('detail-collapsed', layoutState.detailCollapsed);
}
function applyCanvasLayout(canvas){
  if (!canvas) return;
  canvas.style.setProperty('--visual-width', `${layoutState.visualCollapsed ? 0 : layoutState.visualWidth}px`);
  canvas.style.setProperty('--annotations-width', `${layoutState.annotationsCollapsed ? 0 : layoutState.annotationsWidth}px`);
  canvas.classList.toggle('visual-collapsed', layoutState.visualCollapsed);
  canvas.classList.toggle('annotations-collapsed', layoutState.annotationsCollapsed);
}
function saveLayoutValue(key, value){
  localStorage.setItem(`siteAgentExplorer.${key}`, String(value));
}
function togglePane(pane){
  const key = `${pane}Collapsed`;
  layoutState[key] = !layoutState[key];
  saveLayoutValue(key, layoutState[key]);
  if (pane === 'nav' || pane === 'detail') {
    applyShellLayout();
  } else {
    applyCanvasLayout(document.querySelector('.canvas'));
  }
}
function setupShellSplitters(){
  document.querySelectorAll('.splitter').forEach(splitter => {
    let startX = 0;
    let startWidth = 0;
    let dragged = false;
    const pane = splitter.dataset.pane;
    splitter.addEventListener('dblclick', () => togglePane(pane));
    splitter.addEventListener('pointerdown', event => {
      startX = event.clientX;
      startWidth = pane === 'nav' ? layoutState.navWidth : layoutState.detailWidth;
      dragged = false;
      splitter.classList.add('dragging');
      splitter.setPointerCapture(event.pointerId);
    });
    splitter.addEventListener('pointermove', event => {
      if (!splitter.classList.contains('dragging')) return;
      const delta = event.clientX - startX;
      dragged = dragged || Math.abs(delta) > 3;
      if (pane === 'nav') {
        layoutState.navCollapsed = false;
        layoutState.navWidth = clamp(startWidth + delta, 220, 560);
        saveLayoutValue('navWidth', layoutState.navWidth);
        saveLayoutValue('navCollapsed', false);
      } else {
        layoutState.detailCollapsed = false;
        layoutState.detailWidth = clamp(startWidth - delta, 260, 640);
        saveLayoutValue('detailWidth', layoutState.detailWidth);
        saveLayoutValue('detailCollapsed', false);
      }
      applyShellLayout();
    });
    splitter.addEventListener('pointerup', event => {
      splitter.classList.remove('dragging');
      splitter.releasePointerCapture(event.pointerId);
      if (!dragged) togglePane(pane);
    });
  });
}
function setupCanvasSplitters(canvas){
  canvas.querySelectorAll('.canvas-splitter').forEach(splitter => {
    let startX = 0;
    let startWidth = 0;
    let dragged = false;
    const pane = splitter.dataset.pane;
    splitter.addEventListener('dblclick', () => togglePane(pane));
    splitter.addEventListener('pointerdown', event => {
      startX = event.clientX;
      startWidth = pane === 'visual' ? layoutState.visualWidth : layoutState.annotationsWidth;
      dragged = false;
      splitter.classList.add('dragging');
      splitter.setPointerCapture(event.pointerId);
    });
    splitter.addEventListener('pointermove', event => {
      if (!splitter.classList.contains('dragging')) return;
      const delta = event.clientX - startX;
      dragged = dragged || Math.abs(delta) > 3;
      if (pane === 'visual') {
        layoutState.visualCollapsed = false;
        layoutState.visualWidth = clamp(startWidth + delta, 180, 560);
        saveLayoutValue('visualWidth', layoutState.visualWidth);
        saveLayoutValue('visualCollapsed', false);
      } else {
        layoutState.annotationsCollapsed = false;
        layoutState.annotationsWidth = clamp(startWidth - delta, 180, 520);
        saveLayoutValue('annotationsWidth', layoutState.annotationsWidth);
        saveLayoutValue('annotationsCollapsed', false);
      }
      applyCanvasLayout(canvas);
    });
    splitter.addEventListener('pointerup', event => {
      splitter.classList.remove('dragging');
      splitter.releasePointerCapture(event.pointerId);
      if (!dragged) togglePane(pane);
    });
  });
}
function renderTree(filter=''){
  const q = filter.toLowerCase();
  $('tree').innerHTML = DATA.tree.map(g => {
    const methods = g.methods.filter(n => !q || n.toLowerCase().includes(q) || g.name.toLowerCase().includes(q));
    if (!methods.length) return '';
    return `<details open><summary>${esc(g.name)} <span class="meta">${methods.length}</span></summary>` +
      methods.map(n => `<button class="method ${selected?.name===n?'active':''}" onclick="selectMethod('${esc(n)}')">${esc(n)}</button>`).join('') +
      `</details>`;
  }).join('');
}
function selectMethod(name){
  selected = DATA.methods.find(m => m.name === name) || DATA.methods[0];
  renderTree($('q').value);
  renderView();
}
function renderCards(){
  $('cards').innerHTML = [
    ['Methods', DATA.summary.methods],
    ['Pages', DATA.summary.pages],
    ['Forms', DATA.summary.forms],
    ['UI Elements', DATA.summary.elements],
  ].map(([k,v]) => `<div class="card"><span class="meta">${k}</span><b>${v}</b></div>`).join('');
}
function artifact(key){
  return DATA.artifacts?.[key];
}
function artifactButton(key, label, secondary=false){
  const item = artifact(key);
  if (!item) return `<span class="meta">${esc(label)} not generated yet</span>`;
  return `<a class="button-link ${secondary ? 'secondary' : ''}" href="${esc(item.href)}" target="_blank" rel="noreferrer">${esc(label)}</a>`;
}
function rawArtifactButton(key, label, secondary=true){
  const item = artifact(key);
  if (!item) return `<span class="meta">${esc(label)} not generated yet</span>`;
  const href = item.raw_href || item.href;
  return `<a class="button-link ${secondary ? 'secondary' : ''}" href="${esc(href)}?raw=1" target="_blank" rel="noreferrer" download>${esc(label)}</a>`;
}
function docCard(title, body, links){
  return `<div class="doc-card"><b>${esc(title)}</b><p>${esc(body)}</p><div class="actions">${links.join('')}</div></div>`;
}
function portalCards(){
  $('cards').innerHTML = [
    ['API Methods', DATA.summary.methods],
    ['MCP Tools', DATA.summary.public_tools],
    ['Ansible Modules', DATA.summary.ansible_modules],
    ['Docs', DATA.summary.docs + DATA.summary.postman],
  ].map(([k,v]) => `<div class="card"><span class="meta">${k}</span><b>${v}</b></div>`).join('');
}
function commandBlock(lines){
  return `<div class="cmd">${esc(lines.join('\n'))}</div>`;
}
function codeBlock(value){
  return `<pre>${esc(value)}</pre>`;
}
function selectPortalMethod(name){
  selected = DATA.methods.find(method => method.name === name) || DATA.methods[0];
  renderView();
}
function operationRows(limit=14, includeActions=false){
  const rows = DATA.methods.slice(0, limit).map(m => `
    <tr><td><code>${esc(m.name)}</code></td><td>${risk(m.risk_level || 'low')}</td><td><code>${esc(m.backing_tool)}</code></td><td>${esc((m.args || []).join(', ') || 'none')}</td>${includeActions ? `<td><button class="small-button" type="button" onclick="selectPortalMethod(${jsString(m.name)})">Examples</button></td>` : ''}</tr>`).join('');
  const actionHead = includeActions ? '<th>Use</th>' : '';
  return `<table class="table"><thead><tr><th>Method</th><th>Risk</th><th>Backing Tool</th><th>Arguments</th>${actionHead}</tr></thead><tbody>${rows}</tbody></table>`;
}
function mcpRows(limit=16){
  const rows = (DATA.mcp?.tools || []).slice(0, limit).map(t => `
    <tr><td><code>${esc(t.name)}</code></td><td>${risk(t.risk_level || 'low')}</td><td>${esc(t.source_type || '')}</td><td>${evidenceDetails(t.evidence_ids || [])}</td></tr>`).join('');
  return `<table class="table"><thead><tr><th>Tool</th><th>Risk</th><th>Source</th><th>Evidence</th></tr></thead><tbody>${rows}</tbody></table>`;
}
function ansibleRows(limit=16){
  const rows = (DATA.ansible?.modules || []).slice(0, limit).map(m => `
    <tr><td><code>${esc(m.name)}</code></td><td>${esc(String(m.supports_check_mode ?? false))}</td><td>${esc(m.idempotence_level || 'none')}</td><td>${risk(m.risk_level || 'low')}</td></tr>`).join('');
  return `<table class="table"><thead><tr><th>Module</th><th>Check Mode</th><th>Idempotence</th><th>Risk</th></tr></thead><tbody>${rows || '<tr><td colspan="4" class="meta">No generated Ansible modules yet.</td></tr>'}</tbody></table>`;
}
function methodExamples(method=selectedMethod()){
  if (!method) return '';
  const requestBody = JSON.stringify(methodRequest(method));
  const prettyRequest = JSON.stringify(methodRequest(method), null, 2);
  const pythonArgs = methodCallArgs(method);
  const packageName = `${profileSlug()}_client`;
  const module = ansibleModuleFor(method);
  const bridge = bridgeDefaultUrl();
  const ansibleExample = module ? [
    '- name: Run generated method',
    `  site_agent.${DATA.ansible?.name || profileSlug()}.${module.name}:`,
    '    browser: false',
    '    mode: dry-run',
  ].join('\n') : 'No generated Ansible module is available for this method.';
  const httpExample = [
    `curl -s -X POST ${bridge}/methods/${method.name} \\`,
    `  -H 'Content-Type: application/json' \\`,
    `  --data '${requestBody}'`,
  ].join('\n');
  const pythonExample = [
    `from ${packageName} import ${profileSlug().replace(/(^|_)([a-z])/g, (_, p, c) => c.toUpperCase())}Client`,
    '',
    `client = ${profileSlug().replace(/(^|_)([a-z])/g, (_, p, c) => c.toUpperCase())}Client.from_profile("profiles/${DATA.profile.name}")`,
    `result = client.${method.name}(${pythonArgs})`,
    'print(result)',
  ].join('\n');
  const mcpExample = [
    `site-agent mcp call --profile ${shellQuote(DATA.profile.name)} \\`,
    `  --tool ${shellQuote(method.backing_tool || method.name)} \\`,
    `  --args-json request-args.json`,
  ].join('\n');
  return `<div class="callout">
    <h3>Selected Operation</h3>
    <p><code>${esc(method.name)}</code> ${risk(method.risk_level || 'low')} ${esc(method.description || '')}</p>
    <div class="actions"><a class="button-link" href="${esc(swaggerHref(method))}" target="_blank" rel="noreferrer">Try in Swagger</a><button class="small-button" type="button" onclick="setTab('audit')">Review Evidence</button>${artifactButton('api_reference', 'Reference', true)}${artifactButton('postman_collection', 'Postman', true)}</div>
    <div class="example-grid">
      <div class="example-card"><b>HTTP Body</b>${codeBlock(prettyRequest)}</div>
      <div class="example-card"><b>curl</b>${codeBlock(httpExample)}</div>
      <div class="example-card"><b>Python</b>${codeBlock(pythonExample)}</div>
      <div class="example-card"><b>MCP</b>${codeBlock(mcpExample)}</div>
      <div class="example-card"><b>Ansible</b>${codeBlock(ansibleExample)}</div>
      <div class="example-card"><b>Postman</b>${codeBlock(`Import the generated collection and environment, then run ${method.name}.`)}</div>
    </div>
    ${tryPanel(method, prettyRequest)}
  </div>`;
}
function tryPanel(method, prettyRequest){
  const applyHint = (method.risk_level || 'low') === 'low'
    ? 'Apply mode can still change the target; dry-run is recommended first.'
    : `${method.risk_level} risk operation. Apply mode requires explicit confirmation.`;
  return `<div class="try-panel">
    <h3>Try Operation</h3>
    <p>Runs through the local API bridge. Keep requests in <code>dry-run</code> until you are ready to apply changes.</p>
    <div class="try-grid">
      <div>
        <label for="bridge-url">API bridge URL</label>
        <input id="bridge-url" type="text" value="${esc(bridgeDefaultUrl())}" oninput="localStorage.setItem('siteAgentExplorer.bridgeUrl', this.value.trim())">
        <div class="actions">
          <button class="small-button" type="button" onclick="checkBridge()">Check Bridge</button>
          <button class="small-button" type="button" onclick="resetTryBody()">Reset Dry-Run Body</button>
        </div>
        <label for="try-body">Request JSON</label>
        <textarea id="try-body" spellcheck="false">${esc(prettyRequest)}</textarea>
        <div class="check-row">
          <input id="try-apply-confirm" type="checkbox">
          <label for="try-apply-confirm">${esc(applyHint)}</label>
        </div>
        <div class="actions">
          <button class="button-link" type="button" onclick="tryOperation(${jsString(method.name)}, false)">Run Dry-Run</button>
          <button class="button-link secondary" type="button" onclick="tryOperation(${jsString(method.name)}, true)">Run Apply</button>
        </div>
        <div id="try-status" class="try-status">Start the bridge with <code>site-agent api serve --profile ${esc(DATA.profile.name)}</code>.</div>
      </div>
      <div>
        <label for="try-response">Response</label>
        <pre id="try-response"></pre>
      </div>
    </div>
  </div>`;
}
function modeCards(){
  return `<div class="doc-grid">
    ${docCard('Use', 'HTTP, Swagger, Postman, and copy-ready request examples.', [`<button class="small-button" type="button" onclick="setMode('use')">Open Use Mode</button>`])}
    ${docCard('Automate', 'Python, MCP, and Ansible surfaces generated from the same schema.', [`<button class="small-button" type="button" onclick="setMode('automate')">Open Automate Mode</button>`])}
    ${docCard('Audit', 'UI snapshots, annotations, mappings, and evidence for reviewers.', [`<button class="small-button" type="button" onclick="setMode('audit')">Open Audit Mode</button>`])}
    ${docCard('Debug', 'Raw summary, artifact inventory, and capability projection data.', [`<button class="small-button" type="button" onclick="setMode('debug')">Open Debug Mode</button>`])}
  </div>`;
}
function renderOverview(){
  return `<div class="portal">
    <h2>${esc(DATA.profile.name)} generated automation surfaces</h2>
    <p>Start with the local API bridge, then choose the surface that matches the job: HTTP, Swagger, Postman, Python, MCP, Ansible, audit, or debug.</p>
    <div class="actions">
      <a class="button-link" href="swagger.html" target="_blank" rel="noreferrer">Swagger UI</a>
      ${artifactButton('openapi_json', 'OpenAPI JSON', true)}
      ${artifactButton('postman_collection', 'Postman Collection', true)}
    </div>
    ${commandBlock([
      `site-agent api serve --profile ${shellQuote(DATA.profile.name)}`,
      `site-agent explorer serve --profile ${shellQuote(DATA.profile.name)}`,
    ])}
    ${modeCards()}
    ${methodExamples()}
    <div class="doc-grid">
      ${docCard('HTTP API', 'OpenAPI contract for the generated local bridge.', [artifactButton('api_reference', 'Reference'), rawArtifactButton('openapi_yaml', 'YAML')])}
      ${docCard('Python API', 'Typed selector-free package backed by generated runtime metadata.', [artifactButton('python_api', 'Python Docs')])}
      ${docCard('MCP Tools', 'Agent-facing tools with risk and evidence metadata.', [artifactButton('mcp_tools', 'MCP Docs')])}
      ${docCard('Ansible', 'Generated collection for evidenced read/update operations.', [artifactButton('ansible_collection', 'Ansible Docs')])}
      ${docCard('Postman', 'Importable collection and environment for generated HTTP calls.', [artifactButton('postman_collection', 'Import Guide'), rawArtifactButton('postman_collection', 'Collection JSON'), rawArtifactButton('postman_environment', 'Environment JSON')])}
      ${docCard('Audit View', 'Evidence, UI snapshots, and adapter context for reviewers.', [`<button class="tab" type="button" onclick="setTab('audit')">Open Audit</button>`])}
    </div>
  </div>`;
}
function renderApi(){
  return `<div class="portal">
    <h2>Generated HTTP API</h2>
    <p>The local bridge exposes POST endpoints under <code>/methods/&lt;method&gt;</code> and defaults examples to dry-run mode.</p>
    <div class="actions"><a class="button-link" href="swagger.html" target="_blank" rel="noreferrer">Open Swagger UI</a>${rawArtifactButton('openapi_json', 'OpenAPI JSON')}${artifactButton('api_reference', 'API Reference', true)}</div>
    ${commandBlock([`site-agent api serve --profile ${shellQuote(DATA.profile.name)}`])}
    ${methodExamples()}
    ${operationRows(24, true)}
  </div>`;
}
function renderPython(){
  const packageName = DATA.artifacts?.python_api ? `${profileSlug()}_client` : 'generated_client';
  return `<div class="portal">
    <h2>Python API</h2>
    <p>Use the generated package as the shared execution layer for scripts, MCP, and higher-level automation.</p>
    <div class="actions">${artifactButton('python_api', 'Python API Docs')}${artifactButton('api_reference', 'HTTP Reference', true)}</div>
    ${commandBlock([
      `site-agent api build --profile ${shellQuote(DATA.profile.name)}`,
      `python -m pip install -e ${shellQuote(`output/${DATA.profile.name}/api`)}`,
      `python -c "from ${packageName} import *; print('client ready')"`,
    ])}
    ${methodExamples()}
    ${operationRows(24, true)}
  </div>`;
}
function renderMcp(){
  return `<div class="portal">
    <h2>MCP Tools</h2>
    <p>Serve the generated MCP package or emit reusable client configuration for agent clients.</p>
    <div class="actions">${artifactButton('mcp_tools', 'MCP Docs')}${artifactButton('api_reference', 'Backing API Reference', true)}</div>
    ${commandBlock([
      `site-agent mcp serve --profile ${shellQuote(DATA.profile.name)}`,
      `site-agent mcp import --profile ${shellQuote(DATA.profile.name)} --target json`,
      `site-agent mcp import --profile ${shellQuote(DATA.profile.name)} --target codex --apply`,
    ])}
    ${methodExamples()}
    ${mcpRows()}
  </div>`;
}
function renderAnsible(){
  return `<div class="portal">
    <h2>Ansible Collection</h2>
    <p>Generated modules wrap the Python API where the approved model has enough evidence for facts or idempotent updates.</p>
    <div class="actions">${artifactButton('ansible_collection', 'Ansible Docs')}</div>
    ${commandBlock([
      `site-agent ansible build --profile ${shellQuote(DATA.profile.name)}`,
      `ANSIBLE_COLLECTIONS_PATH=${shellQuote(`output/${DATA.profile.name}/ansible`)} ansible-doc -l site_agent.${DATA.ansible?.name || DATA.profile.name}`,
    ])}
    ${methodExamples()}
    ${ansibleRows()}
  </div>`;
}
function renderPostman(){
  return `<div class="portal">
    <h2>Postman</h2>
    <p>Import both generated files, start the local bridge, then run requests against <code>{{baseUrl}}</code>.</p>
    <div class="actions"><a class="button-link" href="https://web.postman.co/" target="_blank" rel="noreferrer">Open Postman Web</a><a class="button-link secondary" href="https://learning.postman.com/docs/getting-started/importing-and-exporting/importing-data/" target="_blank" rel="noreferrer">Import Docs</a>${artifactButton('postman_collection', 'Collection Guide', true)}${artifactButton('postman_environment', 'Environment Guide', true)}${rawArtifactButton('postman_collection', 'Download Collection')}${rawArtifactButton('postman_environment', 'Download Environment')}${rawArtifactButton('openapi_json', 'OpenAPI JSON')}</div>
    ${commandBlock([`site-agent api serve --profile ${shellQuote(DATA.profile.name)}`])}
    ${methodExamples()}
    ${operationRows(24, true)}
  </div>`;
}
function renderDebug(){
  const artifactRows = Object.entries(DATA.artifacts || {}).map(([key, item]) => `
    <tr><td><code>${esc(key)}</code></td><td>${esc(item.kind || '')}</td><td><a href="${esc(item.href)}" target="_blank" rel="noreferrer">${esc(item.href)}</a></td><td>${item.raw_href ? `<a href="${esc(item.raw_href)}?raw=1" target="_blank" rel="noreferrer">raw</a>` : '<span class="meta">same</span>'}</td></tr>`).join('');
  return `<div class="portal">
    <h2>Debug</h2>
    <p>Use this view when validating generated files, capability projection, or artifact routing.</p>
    <h3>Summary</h3>${codeBlock(JSON.stringify(DATA.summary, null, 2))}
    <h3>Artifacts</h3><table class="table"><thead><tr><th>Key</th><th>Kind</th><th>Human View</th><th>Raw</th></tr></thead><tbody>${artifactRows}</tbody></table>
    <h3>Capability Projection</h3>${codeBlock(JSON.stringify(DATA.capabilities || {}, null, 2))}
  </div>`;
}
function renderPortal(){
  portalCards();
  $('tree').innerHTML = '';
  $('detail').innerHTML = '';
  const renderers = {overview: renderOverview, api: renderApi, python: renderPython, mcp: renderMcp, ansible: renderAnsible, postman: renderPostman, debug: renderDebug};
  $('view').innerHTML = (renderers[currentTab] || renderOverview)();
}
function renderTabs(){
  renderModes();
  const tabsByMode = {
    use: ['overview', 'api', 'postman'],
    automate: ['python', 'mcp', 'ansible'],
    audit: ['audit'],
    debug: ['debug'],
  };
  const visibleTabs = new Set(tabsByMode[currentMode] || tabsByMode.use);
  document.querySelectorAll('.tab[data-tab]').forEach(tab => {
    tab.hidden = !visibleTabs.has(tab.dataset.tab);
    tab.classList.toggle('active', tab.dataset.tab === currentTab);
  });
}
function renderModes(){
  document.querySelectorAll('.mode[data-mode]').forEach(mode => mode.classList.toggle('active', mode.dataset.mode === currentMode));
}
function modeForTab(tab){
  if (['python', 'mcp', 'ansible'].includes(tab)) return 'automate';
  if (tab === 'audit') return 'audit';
  if (tab === 'debug') return 'debug';
  return 'use';
}
function setMode(mode){
  currentMode = mode;
  currentTab = {use: 'overview', automate: 'python', audit: 'audit', debug: 'debug'}[mode] || 'overview';
  localStorage.setItem('siteAgentExplorer.mode', currentMode);
  localStorage.setItem('siteAgentExplorer.tab', currentTab);
  renderView();
}
function setTab(tab){
  currentTab = tab;
  currentMode = modeForTab(tab);
  localStorage.setItem('siteAgentExplorer.mode', currentMode);
  localStorage.setItem('siteAgentExplorer.tab', currentTab);
  renderView();
}
function renderView(){
  renderTabs();
  const shell = $('shell');
  shell.classList.toggle('portal-mode', !['audit'].includes(currentTab));
  if (!['audit'].includes(currentTab)) {
    renderPortal();
    return;
  }
  renderCards();
  renderTree($('q').value);
  if (!selected) selected = DATA.methods[0];
  renderAuditView();
}
function renderAuditView(){
  const m = selected;
  if (!m) {
    $('view').innerHTML = '<div class="portal"><h2>No generated methods</h2><p>Build the API and MCP surfaces, then rebuild the explorer.</p></div>';
    $('detail').innerHTML = '';
    return;
  }
  const ui = m.ui || {};
  const annotations = ui.annotations || [];
  const headings = ui.headings?.length ? ui.headings : [ui.page_label, ui.purpose_label].filter(Boolean);
  const values = Object.entries(ui.values || {}).slice(0, 40);
  const frameHtml = ui.html_snapshot ? `<iframe sandbox="" srcdoc="${esc(ui.html_snapshot)}"></iframe>` : `<div class="empty-visual">No captured HTML visual is available for this page yet. Re-crawl with the current site-agent so rendered HTML snapshots are captured.</div>`;
  const sourceLink = ui.source_url ? `<a class="source-link" href="${esc(ui.source_url)}" target="_blank" rel="noreferrer">Open source page</a>` : '';
  $('view').innerHTML = `
    <div class="view-head"><div><div class="view-title">${esc(m.name)}</div><div class="meta">${esc(m.description)}</div></div>${risk(m.risk_level)}</div>
    <div class="canvas">
      <div class="page ui-visual">
        <div class="browser">${esc(ui.page_url || ui.state || ui.page_id || 'page unknown')}</div>
        ${headings.map(h => `<div class="heading">${esc(h)}</div>`).join('') || '<div class="heading">Discovered UI Surface</div>'}
        ${annotations.slice(0, 28).map(a => `<div class="widget ${esc(a.kind)}"><span>${esc(a.label || a.arg || a.id)}</span><span class="badge">${esc(a.kind)}</span></div>`).join('')}
        ${values.slice(0, 12).map(([k,v]) => `<div class="widget"><span>${esc(k)}</span><span class="meta">${esc(v)}</span></div>`).join('')}
      </div>
      <button class="canvas-splitter" type="button" data-pane="visual" title="Drag to resize, double-click to collapse or restore the UI summary" aria-label="Resize UI summary"></button>
      <div class="page actual-page">
        <div class="browser">${ui.html_snapshot ? 'Captured rendered HTML snapshot' : 'Captured HTML snapshot missing'}</div>
        ${frameHtml}
      </div>
      <button class="canvas-splitter" type="button" data-pane="annotations" title="Drag to resize, double-click to collapse or restore annotations" aria-label="Resize annotations"></button>
      <div class="anno-list">
        ${annotations.length ? annotations.map(a => `<div class="anno"><b>${esc(a.kind)}: ${esc(a.label || a.arg || a.id)}</b><div class="meta">${esc(a.detail || a.control_type || '')}</div></div>`).join('') : '<div class="anno"><b>No field-level annotation</b><div class="meta">This capability is backed by read-only page evidence or a scalar read adapter.</div></div>'}
      </div>
    </div>`;
  applyCanvasLayout(document.querySelector('.canvas'));
  setupCanvasSplitters(document.querySelector('.canvas'));
  $('detail').innerHTML = `
    <h2>${esc(m.name)}</h2>
    <div class="kv">
      <b>Group</b><span>${esc(m.group)}</span>
      <b>Action</b><span>${esc(m.adapter_action || 'unknown')}</span>
      <b>Backing tool</b><span>${esc(m.backing_tool)}</span>
      <b>Source</b><span>${esc(m.source_type)}</span>
      <b>UI state</b><span>${esc(ui.state)}</span>
      <b>Source page</b><span>${sourceLink || '<span class="meta">none</span>'}</span>
      <b>Form</b><span>${esc(ui.form_id || 'none')}</span>
    </div>
    <h3>Arguments</h3><div class="chips">${(m.args || []).map(a => `<span class="chip">${esc(a)}</span>`).join('') || '<span class="meta">none</span>'}</div>
    <h3>Evidence</h3>${evidenceDetails((m.evidence_ids || []).slice(0,80))}
    <h3>Reasoning</h3><pre>${esc(m.reasoning_summary || '')}</pre>`;
}
fetch('explorer-data.json').then(r => r.json()).then(data => {
  DATA = data;
  $('profile').textContent = `${data.profile.name} · ${data.profile.base_url}`;
  currentMode = modeForTab(currentTab);
  applyShellLayout();
  setupShellSplitters();
  selected = data.methods[0];
  renderView();
  $('q').addEventListener('input', e => renderTree(e.target.value));
}).catch(err => {
  document.body.innerHTML = `<header><h1>Semantic API Explorer</h1></header>
  <div class="load-error"><b>Explorer data did not load.</b><br>
  This page needs to be served over HTTP so it can fetch <code>explorer-data.json</code>.
  Run <code>site-agent explorer serve --profile &lt;profile&gt;</code> and open the printed URL.<br><br>
  ${esc(err.message || err)}</div>`;
});
</script>
</body>
</html>
"""


SWAGGER_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Generated API Swagger UI</title>
<link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui.css">
<style>
body { margin:0; background:#fff; }
.topbar { display:none; }
</style>
</head>
<body>
<div id="swagger-ui"></div>
<script src="https://cdn.jsdelivr.net/npm/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
<script>
window.addEventListener('load', () => {
  SwaggerUIBundle({
    url: 'artifacts/openapi.json',
    dom_id: '#swagger-ui',
    deepLinking: true,
    displayRequestDuration: true,
    tryItOutEnabled: true,
  });
});
</script>
</body>
</html>
"""


def write_explorer(workspace: Path, profile: Profile, snapshot: CrawlSnapshot) -> tuple[Path, dict[str, Any]]:
    root = output_root(workspace, profile.name)
    explorer_dir = root / "explorer"
    ensure_dir(explorer_dir)
    data = build_explorer_data(profile, snapshot, root)
    copy_surface_artifacts(root, explorer_dir)
    write_json(explorer_dir / "explorer-data.json", data)
    (explorer_dir / "index.html").write_text(EXPLORER_HTML, encoding="utf-8")
    (explorer_dir / "swagger.html").write_text(SWAGGER_HTML, encoding="utf-8")
    return explorer_dir, data
