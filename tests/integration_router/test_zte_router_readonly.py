from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

import pytest

from site_agent.core.align.lexical import align_snapshot
from site_agent.core.crawl.playwright import crawl_profile
from site_agent.core.ingest.docs import build_ontology_artifact
from site_agent.core.profiles import load_profile, profile_root
from site_agent.core.synthesize.mcp import synthesize_tools, write_mcp_package
from site_agent.core.synthesize.runtime import call_tool


pytestmark = pytest.mark.skipif(
    os.environ.get("SITE_AGENT_RUN_ROUTER_TESTS") != "1" or not os.environ.get("SITE_AGENT_ROUTER_PASSWORD"),
    reason="Router integration tests are opt-in and require SITE_AGENT_ROUTER_PASSWORD.",
)


def test_zte_router_readonly_js_menu_crawl(tmp_path):
    repo = Path(__file__).resolve().parents[2]
    example = repo / "profiles" / "examples" / "zte-router"
    target = tmp_path / "profiles" / "zte-router"
    shutil.copytree(example, target)

    profile = load_profile(tmp_path, "zte-router")
    auth_dir = profile_root(tmp_path, profile.name) / "auth"
    auth_dir.mkdir(parents=True, exist_ok=True)
    storage_state = auth_dir / "storage-state.json"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright is not installed.")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(ignore_https_errors=True)
        page = context.new_page()
        page.goto(profile.base_url, wait_until="domcontentloaded", timeout=15000)
        page.fill("#Frm_Username", os.environ.get("SITE_AGENT_ROUTER_USER", "admin"))
        page.fill("#Frm_Password", os.environ["SITE_AGENT_ROUTER_PASSWORD"])
        page.click("#LoginId")
        page.wait_for_timeout(3000)
        context.storage_state(path=str(storage_state))
        browser.close()

    ontology, doc_evidence = build_ontology_artifact(tmp_path, profile)
    snapshot = crawl_profile(tmp_path, profile, ontology=ontology)
    assert len(snapshot.pages) >= 6
    assert len(snapshot.elements) >= 20

    schema = align_snapshot(profile.id, snapshot, ontology, doc_evidence)
    stable = [mapping for mapping in schema.mappings if mapping.status == "ready"]
    stable_names = {mapping.canonical_name for mapping in stable}
    assert {"wan status", "software version"} <= stable_names

    selector_lookup = {element.id: element.selector_fingerprint for element in snapshot.elements}
    value_lookup = {element.id: str(element.context["read_value"]) for element in snapshot.elements if "read_value" in element.context}
    tools, bindings = synthesize_tools(profile.id, schema, selector_lookup, value_lookup)
    write_mcp_package(tmp_path, profile.name, tools, bindings)
    tool_names = {tool.name for tool in tools}
    assert {"get_wan_status", "get_software_version"} <= tool_names
    assert call_tool(tmp_path / "output" / profile.name / "mcp", "get_wan_status")["value"]
