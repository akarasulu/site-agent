from pathlib import Path

from site_agent.core.explorer import build_explorer_data, best_page_match, method_group, page_key, touched_annotations, write_explorer
from site_agent.core.models import CrawlSnapshot, Evidence, Form, Page, UiElement, utc_now
from site_agent.core.profiles import Profile
from site_agent.core.storage import read_json, write_json


def make_profile() -> Profile:
    return Profile(
        id="profile",
        name="demo",
        base_url="https://example.test",
        host_allowlist=["example.test"],
        created_at=utc_now(),
    )


def make_snapshot() -> CrawlSnapshot:
    return CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[
            Page(id="page", url="https://example.test/#state=internet/wan", title="WAN", headings=["WAN Status"], html_snapshot="<h1>WAN</h1>"),
            Page(id="fallback", url="https://example.test/#state=local-network/status", title="LAN", headings=["LAN Client Status"]),
        ],
        forms=[Form(id="form", page_id="page", label="WAN Form", method="post", field_ids=["ui_field"])],
        elements=[
            UiElement(
                id="ui_field",
                page_id="page",
                selector_fingerprint="fp",
                label="Username",
                control_type="text",
                context={"read_value": "admin", "headings": ["WAN Status"]},
                evidence_ids=["ev"],
            ),
            UiElement(
                id="hidden",
                page_id="page",
                selector_fingerprint="hidden",
                label="Hidden",
                control_type="hidden",
                context={"read_value": "secret"},
                evidence_ids=["ev"],
            ),
        ],
        evidence=[Evidence(id="ev", kind="ui", source="fixture", summary="fixture")],
    )


def write_explorer_inputs(root: Path):
    write_json(
        root / "mcp" / "tools.json",
        {
            "tools": [
                {
                    "name": "internet_wan_get",
                    "description": "Read WAN status",
                    "args": {"type": "object", "properties": {"verbose": {"type": "boolean"}}},
                    "risk_level": "low",
                    "source_type": "canonical_concept",
                    "reasoning_summary": "Mapped from WAN page.",
                    "evidence_ids": ["ev"],
                }
            ]
        },
    )
    write_json(
        root / "mcp" / "adapter.bindings.json",
        {
            "bindings": [
                {
                    "tool_name": "internet_wan_get",
                    "selector_action_bindings": {
                        "action": "read_page",
                        "page_id": "missing",
                        "page_url": "https://example.test/#state=internet/wan",
                        "headings": ["WAN Status"],
                        "form_id": "form",
                        "fields": [{"arg": "username", "ui_element_id": "ui_field", "label": "Username"}],
                        "element_ids": ["ui_field", "hidden"],
                        "values": {"wan_status": "connected"},
                    },
                }
            ]
        },
    )
    write_json(
        root / "api" / "api-spec.json",
        {
            "methods": [
                {
                    "name": "internet_wan_get",
                    "description": "Read WAN status",
                    "args": {"type": "object", "properties": {"verbose": {"type": "boolean"}}},
                    "risk_level": "low",
                    "evidence_ids": ["ev"],
                    "backing_tool": "internet_wan_get",
                }
            ]
        },
    )
    write_json(root / "capabilities" / "capabilities.json", {"projection_report": {"capabilities": 1}})


def test_explorer_grouping_page_matching_and_annotations():
    pages = {
        page["id"]: page
        for page in [
            {"id": "exact", "url": "https://example.test/#state=internet/status", "state": "internet/status", "headings": []},
            {"id": "better", "url": "https://example.test/#state=internet/wan", "state": "internet/wan", "headings": ["WAN Status"], "html_snapshot": "<h1>WAN</h1>"},
        ]
    }
    adapter = {"page_url": "https://example.test/#state=internet/wan", "headings": ["WAN Status"]}
    annotations = touched_annotations(
        {"form_id": "form", "method": "post", "fields": [{"arg": "username", "ui_element_id": "ui"}], "element_ids": ["ui", "hidden"]},
        {"ui": {"id": "ui", "label": "Username", "control_type": "text", "read_value": "admin"}, "hidden": {"id": "hidden", "control_type": "hidden"}},
        {"form": {"id": "form", "label": "WAN Form", "method": "post"}},
    )

    assert method_group("security_firewall_get") == "Security / Firewall"
    assert method_group("unknown_tool") == "Other"
    assert page_key("https://example.test/#state=internet/wan", None) == "internet/wan"
    assert best_page_match("exact", adapter, pages)["id"] == "better"
    assert [annotation["kind"] for annotation in annotations] == ["form", "field", "widget"]


def test_build_and_write_explorer_data(tmp_path):
    profile = make_profile()
    root = tmp_path / "output" / profile.name
    write_explorer_inputs(root)

    data = build_explorer_data(profile, make_snapshot(), root)
    explorer_dir, written = write_explorer(tmp_path, profile, make_snapshot())

    assert data["summary"] == {"methods": 1, "pages": 2, "forms": 1, "elements": 2, "groups": 1}
    method = data["methods"][0]
    assert method["group"] == "Internet / WAN"
    assert method["ui"]["page_id"] == "missing"
    assert method["ui"]["form_id"] == "form"
    assert method["ui"]["html_snapshot"] == "<h1>WAN</h1>"
    assert data["capabilities"] == {"capabilities": 1}
    index_html = (explorer_dir / "index.html").read_text(encoding="utf-8")
    assert 'class="splitter"' in index_html
    assert 'class="canvas-splitter"' in index_html
    assert "setupShellSplitters" in index_html
    assert "setupCanvasSplitters" in index_html
    assert "nav-collapsed" in index_html
    assert "visual-collapsed" in index_html
    assert read_json(explorer_dir / "explorer-data.json")["summary"] == written["summary"]
