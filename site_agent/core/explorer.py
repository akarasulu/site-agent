from __future__ import annotations

import html
import json
import re
from pathlib import Path
from typing import Any

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
    capabilities_path = root / "capabilities" / "capabilities.json"
    capabilities = read_json(capabilities_path) if capabilities_path.exists() else {}
    bindings_by_tool = {binding.get("tool_name"): binding for binding in bindings}
    tools_by_name = {tool.get("name"): tool for tool in tools}
    pages_by_id = page_lookup(snapshot)
    elements_by_id = element_lookup(snapshot)
    forms_by_id = form_lookup(snapshot)
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
        "summary": {
            "methods": len(methods),
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "groups": len({method["group"] for method in methods}),
        },
        "tree": semantic_tree(methods),
        "methods": methods,
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
header { height:58px; display:flex; align-items:center; gap:18px; padding:0 20px; border-bottom:1px solid var(--line); background:#fff; position:sticky; top:0; z-index:5; }
h1 { font-size:18px; margin:0; }
.meta { color:var(--muted); font-size:13px; }
.load-error { margin:18px; padding:14px; border:1px solid #e3aaaa; background:#fff4f4; color:#8d2929; border-radius:8px; }
.shell { --nav-width:330px; --detail-width:420px; display:grid; grid-template-columns: var(--nav-width) 10px minmax(420px, 1fr) 10px var(--detail-width); min-height:calc(100vh - 58px); }
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
pre { white-space:pre-wrap; word-break:break-word; background:#f7f9fc; border:1px solid var(--line); border-radius:6px; padding:10px; font-size:12px; }
@media (max-width: 1100px) { .shell { display:block; } aside, section.detail { border:0; } .splitter, .canvas-splitter { display:none; } .canvas { display:block; } .canvas > .page, .canvas > .anno-list { margin:0 0 16px; } }
</style>
</head>
<body>
<header><h1>Semantic API Explorer</h1><span class="meta" id="profile"></span></header>
<div class="shell" id="shell">
<aside><input class="search" id="q" placeholder="Filter capabilities"><div id="tree"></div></aside>
<button class="splitter" type="button" data-pane="nav" title="Drag to resize, double-click to collapse or restore the capability list" aria-label="Resize capability list"></button>
<main><div class="cards" id="cards"></div><div class="view" id="view"></div></main>
<button class="splitter" type="button" data-pane="detail" title="Drag to resize, double-click to collapse or restore the details pane" aria-label="Resize details pane"></button>
<section class="detail" id="detail"></section>
</div>
<script>
const $ = (id) => document.getElementById(id);
let DATA, selected;
function esc(s){ return String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c])); }
function risk(r){ return `<span class="risk ${esc(r)}">${esc(r)}</span>`; }
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
function renderView(){
  const m = selected;
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
    <h3>Evidence</h3><div class="chips">${(m.evidence_ids || []).slice(0,80).map(e => `<span class="chip">${esc(e)}</span>`).join('')}</div>
    <h3>Reasoning</h3><pre>${esc(m.reasoning_summary || '')}</pre>`;
}
fetch('explorer-data.json').then(r => r.json()).then(data => {
  DATA = data;
  $('profile').textContent = `${data.profile.name} · ${data.profile.base_url}`;
  applyShellLayout();
  setupShellSplitters();
  renderCards();
  selected = data.methods[0];
  renderTree();
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


def write_explorer(workspace: Path, profile: Profile, snapshot: CrawlSnapshot) -> tuple[Path, dict[str, Any]]:
    root = output_root(workspace, profile.name)
    explorer_dir = root / "explorer"
    ensure_dir(explorer_dir)
    data = build_explorer_data(profile, snapshot, root)
    write_json(explorer_dir / "explorer-data.json", data)
    (explorer_dir / "index.html").write_text(EXPLORER_HTML, encoding="utf-8")
    return explorer_dir, data
