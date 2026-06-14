import pytest

from site_agent.core.ai.backends import NoopAiBackend
from site_agent.core.crawl import playwright as crawl_playwright
from site_agent.core.crawl.playwright import (
    CrawlError,
    add_fact,
    add_ui_cue,
    append_state_path_url,
    append_state_url,
    best_navigation_label,
    browser_form_fingerprint,
    capture_browser_forms,
    control_identity,
    crawl_fixture_site,
    crawl_html_fixture,
    discover_form_flow_triggers,
    discover_navigation_items,
    discover_navigation_label_groups,
    discover_primary_navigation_labels,
    fact_fingerprint,
    infer_inline_constraints,
    is_safe_navigation_label,
    path_revisit_allowed,
    probe_form_flows,
    rank_navigation_labels,
    replay_navigation_path,
    safe_click_patterns,
    score_candidate_label,
    selector_fingerprint_for_control,
    state_slug,
    state_text_hash,
    term_tokens,
    validate_url_allowed,
    visible_control_snapshot,
)
from site_agent.core.models import CrawlSnapshot, DomainTerm, Form, utc_now
from site_agent.core.profiles import Profile


def make_profile() -> Profile:
    return Profile(
        id="profile",
        name="demo",
        base_url="https://example.test",
        host_allowlist=["example.test"],
        created_at=utc_now(),
    )


def test_url_state_and_hash_helpers_are_stable():
    assert state_slug("Local Network / Wi-Fi") == "local-network-wi-fi"
    assert append_state_url("https://example.test/#old", "Wi-Fi Settings") == "https://example.test/#state=wi-fi-settings"
    assert append_state_path_url("https://example.test/#old", ("Internet", "WAN")) == "https://example.test/#state=internet/wan"
    assert state_text_hash("  A\n\nB  ") == state_text_hash("A\nB")
    assert fact_fingerprint("WAN Status", "https://example.test") == fact_fingerprint("WAN Status", "https://example.test")


def test_validate_url_allowed_uses_profile_host_allowlist():
    profile = make_profile()

    validate_url_allowed(profile, "https://example.test/settings")

    with pytest.raises(CrawlError, match="not in profile allowlist"):
        validate_url_allowed(profile, "https://evil.test/settings")


def test_navigation_label_safety_and_ranking():
    profile = make_profile()
    ontology = [
        DomainTerm(id="term_wifi", canonical_name="wifi settings", aliases=["WLAN"], confidence=0.9),
        DomainTerm(id="term_firewall", canonical_name="firewall", confidence=0.9),
    ]

    deny_patterns = safe_click_patterns(profile)
    assert is_safe_navigation_label("Wi-Fi Settings", deny_patterns)
    assert not is_safe_navigation_label("Factory Reset", deny_patterns)
    assert not is_safe_navigation_label("What is this very long question?", deny_patterns)
    assert term_tokens(ontology) >= {"wifi", "settings", "wlan", "firewall"}
    assert score_candidate_label("Wi-Fi Settings", term_tokens(ontology), {}) > score_candidate_label("Unknown", term_tokens(ontology), {})

    ranked, remaining = rank_navigation_labels(
        ["Factory Reset", "Firewall", "Wi-Fi Settings"],
        profile,
        ontology,
        NoopAiBackend(),
        ai_calls_remaining=2,
        include_profile_seeds=False,
    )

    assert set(ranked[:2]) == {"Wi-Fi Settings", "Firewall"}
    assert ranked[-1] == "Factory Reset"
    assert remaining == 1


def test_add_fact_and_ui_cue_deduplicate_snapshot_elements():
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run")
    context = {"page_title": "Status", "headings": ["Status"]}

    add_fact(snapshot, "page", "https://example.test", "WAN Status", "Connected", context)
    add_fact(snapshot, "page", "https://example.test", "WAN Status", "Connected", context)
    add_ui_cue(snapshot, "page", "https://example.test", "Internet", "heading", context)
    add_ui_cue(snapshot, "page", "https://example.test", "Internet", "heading", context)

    assert [element.label for element in snapshot.elements] == ["WAN Status", "Internet"]
    assert snapshot.elements[0].context["read_value"] == "Connected"
    assert len(snapshot.evidence) == 2


class FakeLocator:
    def __init__(self, *, values=None, text="", fail=False):
        self.values = values if values is not None else []
        self.text = text
        self.fail = fail

    def evaluate_all(self, script):
        if self.fail:
            raise RuntimeError("locator failed")
        return self.values

    def inner_text(self, timeout):
        if self.fail:
            raise RuntimeError("body failed")
        return self.text


class FakePage:
    url = "https://example.test/admin"

    def __init__(self, *, nav_items=None, controls=None, triggers=None, forms=None, body=""):
        self.nav_items = nav_items or []
        self.controls = controls or []
        self.triggers = triggers or []
        self.forms = forms or []
        self.body = body
        self.gotos = []
        self.waits = []

    def locator(self, selector):
        if selector == "input, select, textarea, button":
            return FakeLocator(values=self.controls)
        if selector == "form":
            return FakeLocator(values=self.forms)
        if selector == "body":
            return FakeLocator(text=self.body)
        if ".collapBarWithDataTrans" in selector:
            return FakeLocator(values=self.triggers)
        return FakeLocator(values=self.nav_items)

    def title(self):
        return "Admin"

    def content(self):
        return "<html><body>Admin</body></html>"

    def goto(self, url, wait_until):
        self.gotos.append((url, wait_until))

    def wait_for_timeout(self, value):
        self.waits.append(value)


def test_browser_navigation_discovery_grouping_and_replay(monkeypatch):
    profile = make_profile()
    nav_items = [
        {"label": "Status\nStatus", "rect": {"x": 0, "y": 0, "width": 80, "height": 20}},
        {"label": "Wi-Fi", "rect": {"x": 100, "y": 0, "width": 80, "height": 20}},
        {"label": "Firewall", "rect": {"x": 200, "y": 0, "width": 80, "height": 20}},
        {"label": "Factory Reset", "rect": {"x": 0, "y": 40, "width": 80, "height": 20}},
        {"label": "OK", "rect": {"x": 0, "y": 80, "width": 80, "height": 20}},
    ]
    page = FakePage(nav_items=nav_items)

    items = discover_navigation_items(page, profile)

    assert [item["label"] for item in items] == ["Status", "Wi-Fi", "Firewall"]
    assert discover_primary_navigation_labels(page, profile) == ["Status", "Wi-Fi", "Firewall"]
    groups = discover_navigation_label_groups(
        [
            {"label": "Internet", "rect": {"x": 0, "y": 0, "width": 80, "height": 20}},
            {"label": "LAN", "rect": {"x": 0, "y": 40, "width": 80, "height": 20}},
            {"label": "Wi-Fi", "rect": {"x": 0, "y": 90, "width": 80, "height": 20}},
            {"label": "Status", "rect": {"x": 120, "y": 0, "width": 80, "height": 20}},
            {"label": "Security", "rect": {"x": 240, "y": 0, "width": 80, "height": 20}},
        ]
    )
    assert "x:0" in groups["internet"]
    assert "y:0" in groups["security"]
    assert best_navigation_label("port forwarding", ["Virtual Server Port Forwarding", "Status"]) == "Virtual Server Port Forwarding"
    assert path_revisit_allowed(("Internet",), "Security", profile)
    assert not path_revisit_allowed(("Internet",), "Internet", profile)

    clicked = []
    monkeypatch.setattr(crawl_playwright, "discover_navigation_labels", lambda page, profile: ["Home", "Status"])
    monkeypatch.setattr(crawl_playwright, "click_navigation_label", lambda page, label: clicked.append(label) or True)
    monkeypatch.setattr(crawl_playwright, "dismiss_blocking_overlays", lambda page: False)

    assert replay_navigation_path(page, "https://example.test/admin", ("Status",), profile)
    assert clicked == ["Home", "Status"]
    assert page.gotos[-1] == ("https://example.test/admin", "networkidle")
    assert not replay_navigation_path(page, "https://example.test/admin", ("Factory Reset",), profile)


def test_browser_form_capture_and_flow_helpers(monkeypatch):
    profile = make_profile()
    profile.crawl.navigation_wait_ms = 5
    control = {
        "index": 0,
        "id": "service_port",
        "name": "service_port",
        "type": "number",
        "label": "Service Port",
        "value": "443",
        "visible": True,
        "attrs": {"maxlength": "5"},
    }
    page = FakePage(
        controls=[control],
        triggers=[
            {"index": 1, "label": " Add Rule ", "visible": True},
            {"index": 2, "label": "Create New", "visible": True},
            {"index": 3, "label": "Cancel", "visible": True},
            {"index": 4, "label": "Add Rule", "visible": True},
        ],
        body="Service Port Length : 1~5\nService Port Range : 1-65535",
        forms=[
            {
                "index": 0,
                "action": "/save",
                "method": "post",
                "label": "Forwarding",
                "controls": [
                    {**control, "label": "Service Port"},
                    {"index": 1, "id": "enabled", "name": "enabled", "type": "checkbox", "label": "Enabled", "value": "on"},
                ],
            }
        ],
    )

    assert visible_control_snapshot(page) == [control]
    constraints = infer_inline_constraints(page, [control])
    assert constraints[str(control_identity(control))]["minLength"] == 1
    assert constraints[str(control_identity(control))]["maximum"] == 65535
    assert [trigger["label"] for trigger in discover_form_flow_triggers(page)] == ["Add Rule", "Create New"]
    assert selector_fingerprint_for_control(control, page.url) == selector_fingerprint_for_control(control, page.url)
    assert browser_form_fingerprint({"index": 0}, control, page.url) == browser_form_fingerprint({"index": 0}, control, page.url)

    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run")
    capture_browser_forms(snapshot, page, "page", page.url)

    assert len(snapshot.forms) == 1
    assert len(snapshot.forms[0].field_ids) == 2
    assert {element.label for element in snapshot.elements} == {"Service Port", "Enabled"}
    assert all(element.context["browser_reconciled_form"] for element in snapshot.elements)

    existing = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        forms=[Form(id="form", page_id="page", label="existing", field_ids=["ui"])],
    )
    capture_browser_forms(existing, page, "page", page.url)
    assert len(existing.forms) == 1

    dynamic = {**control, "id": "rule_name", "name": "rule_name", "type": "text", "label": "Rule Name"}
    snapshots = iter([[], [dynamic]])
    monkeypatch.setattr(crawl_playwright, "discover_form_flow_triggers", lambda page: [{"label": "Add Rule"}])
    monkeypatch.setattr(crawl_playwright, "visible_control_snapshot", lambda page: next(snapshots))
    monkeypatch.setattr(crawl_playwright, "click_form_flow_trigger", lambda page, label: True)
    monkeypatch.setattr(crawl_playwright, "cancel_form_flow", lambda page: True)
    monkeypatch.setattr(crawl_playwright, "infer_inline_constraints", lambda page, controls: {str(control_identity(dynamic)): {"required": "true"}})

    flow_snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run")
    probe_form_flows(flow_snapshot, page, profile, "page", page.url)

    assert len(flow_snapshot.interaction_flows) == 1
    flow = flow_snapshot.interaction_flows[0]
    assert flow.trigger_label == "Add Rule"
    assert flow.cancel_supported is True
    assert flow.constraints[str(control_identity(dynamic))] == {"required": "true"}


def test_fixture_crawlers_validate_and_follow_local_pages(tmp_path):
    profile = make_profile()
    profile.crawl.max_pages = 5

    snapshot = crawl_html_fixture(
        profile,
        "<h1>Status</h1><form><label>WAN</label><input name='wan'></form>",
        "https://example.test/status",
    )
    assert snapshot.pages
    assert snapshot.forms

    with pytest.raises(CrawlError, match="allowlist"):
        crawl_html_fixture(profile, "<h1>Bad</h1>", "https://evil.test/status")

    site_dir = tmp_path / "site"
    site_dir.mkdir()
    (site_dir / "index.html").write_text(
        "<title>Home</title><h1>Home</h1><a href='settings.html'>Settings</a><a href='https://evil.test/x'>External</a>",
        encoding="utf-8",
    )
    (site_dir / "settings.html").write_text("<title>Settings</title><h1>Settings</h1><a href='index.html'>Home</a>", encoding="utf-8")
    events = []

    site_snapshot = crawl_fixture_site(profile, site_dir, progress=events.append, progress_total=2)

    assert {page.title for page in site_snapshot.pages} == {"Home", "Settings"}
    assert [event["phase"] for event in events] == ["fixture-page", "fixture-page"]
