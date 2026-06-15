from site_agent.core.ai.backends import FakeAiBackend
from site_agent.core.crawl.playwright import (
    append_state_path_url,
    best_navigation_label,
    is_safe_navigation_label,
    path_revisit_allowed,
    planned_branch_key,
    planned_branch_time_budget_seconds,
    rank_navigation_labels,
    safe_click_patterns,
)
from site_agent.core.models import DomainTerm
from site_agent.core.profiles import CrawlPolicy, Profile
import pytest


def make_profile() -> Profile:
    return Profile(
        id="profile_test",
        name="test",
        base_url="https://example.com",
        host_allowlist=["example.com"],
        created_at="2026-05-24T00:00:00+00:00",
        crawl=CrawlPolicy(js_navigation_texts=["Home"], ai_navigation_planning=True, ai_navigation_budget=1),
    )


def test_safe_navigation_label_rejects_write_and_destructive_actions():
    deny_patterns = safe_click_patterns(make_profile())

    assert is_safe_navigation_label("WAN Status", deny_patterns)
    assert not is_safe_navigation_label("Apply", deny_patterns)
    assert not is_safe_navigation_label("Factory Reset", deny_patterns)
    assert not is_safe_navigation_label("Upload Firmware", deny_patterns)


def test_navigation_ranking_uses_ontology_terms_before_generic_labels():
    profile = make_profile()
    ontology = [
        DomainTerm(
            id="term_wan_status",
            canonical_name="wan status",
            aliases=["internet status"],
            units=[],
            constraints=[],
            sources=["manual"],
            confidence=0.9,
        )
    ]
    ranked, remaining = rank_navigation_labels(["Help", "WAN Status", "Random"], profile, ontology, FakeAiBackend(), 1, include_profile_seeds=True)

    assert ranked[0] == "WAN Status"
    assert "Home" in ranked
    assert remaining == 0


def test_navigation_paths_are_replayable_and_do_not_repeat_seed_sections():
    profile = make_profile()
    profile.crawl.js_navigation_texts = ["Internet", "Local Network"]
    profile.crawl.max_js_depth = 4

    assert append_state_path_url("https://example.com/#old", ("Internet", "WAN")) == "https://example.com/#state=internet/wan"
    assert not path_revisit_allowed(("Internet", "WAN"), "Internet", profile)
    assert path_revisit_allowed(("Internet",), "WAN", profile)
    assert not path_revisit_allowed(("Status", "WAN"), "Status", profile)


def test_planned_branch_budget_groups_deep_paths_by_first_two_segments():
    assert planned_branch_key(("Local Network", "LAN", "IPv4")) == ("local network", "lan")
    assert planned_branch_key(("Topology",)) == ("topology",)

    budget = planned_branch_time_budget_seconds(
        [
            ["Local Network", "LAN", "IPv4"],
            ["Local Network", "LAN", "IPv6"],
            ["Internet", "Status", "WAN"],
            ["Topology"],
        ],
        start_time=100.0,
        deadline=220.0,
    )

    assert budget == 40.0
    assert planned_branch_time_budget_seconds(None, 100.0, 220.0) is None


def test_best_navigation_label_maps_compound_ai_target_to_visible_tab():
    labels = ["Firewall", "Filter Criteria", "DMZ", "Port Forwarding"]

    assert best_navigation_label("Port Forwarding / Virtual Server", labels) == "Port Forwarding"
    assert best_navigation_label("IP Filter / Port Filter", labels) == "Filter Criteria"


def test_form_flow_probe_detects_visible_dynamic_new_item():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    from site_agent.core.crawl.playwright import probe_form_flows
    from site_agent.core.models import CrawlSnapshot, Page, utc_now

    html = """
    <html><body>
      <h1>Rules</h1>
      <section id="rules">
        <button id="addRule" onclick="
          const tpl=document.getElementById('template');
          const row=tpl.cloneNode(true);
          row.id='row:1';
          row.style.display='block';
          row.querySelectorAll('[id]').forEach(el => el.id = el.id + ':1');
          document.getElementById('rules').appendChild(row);
        ">Create New Item</button>
        <div id="template" style="display:none">
          <p>Name Length: 1 ~ 10</p>
          <label>Name <input id="ruleName" name="ruleName" maxlength="10"></label>
          <label>Port <input id="port" name="port"></label>
          <button>Cancel</button>
        </div>
      </section>
    </body></html>
    """
    profile = make_profile()
    profile.crawl.discover_form_flows = True
    profile.crawl.navigation_wait_ms = 50
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run")
    page_model = Page(id="page_1", url=profile.base_url, title="Rules", headings=["Rules"])
    snapshot.pages.append(page_model)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium is unavailable in this sandbox: {exc}")
        page = browser.new_page()
        page.set_content(html)
        probe_form_flows(snapshot, page, profile, page_model.id, profile.base_url)
        browser.close()

    assert len(snapshot.interaction_flows) == 1
    flow = snapshot.interaction_flows[0]
    assert flow.trigger_label == "Create New Item"
    assert flow.requires_open_before_submit
    assert flow.cancel_supported
    selector_ids = {element.context.get("selector_id") for element in snapshot.elements}
    assert {"ruleName:1", "port:1"} <= selector_ids
    assert any("maxLength" in constraints or "maxlength" in constraints for constraints in flow.constraints.values())


def test_browser_form_capture_reconciles_visible_controls_without_parser_fields():
    sync_playwright = pytest.importorskip("playwright.sync_api").sync_playwright

    from site_agent.core.crawl.playwright import capture_browser_forms
    from site_agent.core.models import CrawlSnapshot, Page, utc_now

    html = """
    <html><body>
      <form>
        <table>
          <tr><td>Name</td><td><input id="alias" name="Alias" value="ssh"></td></tr>
          <tr><td>Protocol</td><td><select id="proto" name="Protocol"><option>TCP</option></select></td></tr>
          <tr><td>WAN Port</td><td><input id="wan" name="ExternalPort" value="12121"></td></tr>
          <tr><td>LAN Host</td><td><input id="lan" name="InternalClient" value="192.168.1.123"></td></tr>
          <tr><td></td><td><input type="button" value="Apply"></td></tr>
        </table>
      </form>
    </body></html>
    """
    profile = make_profile()
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run")
    page_model = Page(id="page_1", url=profile.base_url, title="Port Forwarding", headings=["Port Forwarding"])
    snapshot.pages.append(page_model)
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as exc:
            pytest.skip(f"Chromium is unavailable in this sandbox: {exc}")
        page = browser.new_page()
        page.set_content(html)
        capture_browser_forms(snapshot, page, page_model.id, profile.base_url)
        browser.close()

    assert len(snapshot.forms) == 1
    fields = [element for element in snapshot.elements if element.id in snapshot.forms[0].field_ids]
    assert {"Name", "Protocol", "WAN Port", "LAN Host"} <= {field.label for field in fields}
    assert all(field.context.get("browser_reconciled_form") for field in fields)
