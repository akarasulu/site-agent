from __future__ import annotations

import sys
import types

from site_agent.core import inventory
from site_agent.core.inventory import build_site_tree, domain_terms, inventory_profile, synonym_hits, word_histogram
from site_agent.core.models import DomainTerm
from site_agent.core.profiles import Profile


def test_inventory_histogram_filters_stopwords_and_domain_terms():
    ontology = [
        DomainTerm(
            id="term_port_forwarding",
            canonical_name="port forwarding",
            aliases=["virtual server", "nat rule"],
            confidence=0.9,
        )
    ]
    vocabulary, synonyms = domain_terms(ontology)
    histogram = word_histogram("This page provides the function of port forwarding and virtual server configuration.", vocabulary)

    assert "the" not in histogram
    assert histogram["port"] == 1
    assert histogram["forwarding"] == 1
    assert histogram["virtual"] == 1
    assert histogram["server"] == 1
    assert synonym_hits(histogram, synonyms)["port forwarding"] == 4


def test_inventory_builds_nested_tree_from_paths():
    nodes = [
        {"path": [], "path_key": "", "domain_histogram": {"router": 1}},
        {"path": ["Internet"], "path_key": "internet", "domain_histogram": {"internet": 1}},
        {"path": ["Internet", "Security", "Port Forwarding"], "path_key": "internet/security/port-forwarding", "domain_histogram": {"port": 1}},
    ]

    tree = build_site_tree(nodes)

    internet = tree["children"][0]
    assert internet["label"] == "Internet"
    assert internet["children"][0]["label"] == "Security"
    assert internet["children"][0]["children"][0]["label"] == "Port Forwarding"


def test_inventory_profile_walks_fake_playwright_states(tmp_path, monkeypatch):
    profile = Profile(
        id="profile",
        name="demo",
        base_url="https://example.test",
        host_allowlist=["example.test"],
        created_at="now",
    )
    profile.crawl.max_js_states = 3
    profile.crawl.max_js_depth = 2
    profile.crawl.ignore_https_errors = True
    ontology = [
        DomainTerm(
            id="term_firewall",
            canonical_name="firewall rule",
            aliases=["security rule"],
            confidence=0.9,
        )
    ]

    class FakeBody:
        def inner_text(self, timeout):
            assert timeout == 3000
            return "Firewall rule status and security rule details"

    class FakePage:
        url = "https://example.test/admin"

        def __init__(self):
            self.paths = []

        def locator(self, selector):
            assert selector == "body"
            return FakeBody()

        def content(self):
            return "<body>fallback</body>"

        def title(self):
            return "Admin"

    class FakeContext:
        def __init__(self):
            self.page = FakePage()
            self.closed = False

        def new_page(self):
            return self.page

        def close(self):
            self.closed = True

    class FakeBrowser:
        def __init__(self):
            self.context_kwargs = None
            self.context = FakeContext()
            self.closed = False

        def new_context(self, **kwargs):
            self.context_kwargs = kwargs
            return self.context

        def close(self):
            self.closed = True

    fake_browser = FakeBrowser()

    class FakeChromium:
        def launch(self, headless):
            assert headless is True
            return fake_browser

    class FakePlaywright:
        chromium = FakeChromium()

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setitem(
        sys.modules,
        "playwright.sync_api",
        types.SimpleNamespace(sync_playwright=lambda: FakePlaywright()),
    )
    monkeypatch.setattr(inventory, "safe_click_patterns", lambda profile: [])

    def fake_replay(page, base_url, path, profile):
        page.paths.append(path)
        return path != ("Broken",)

    monkeypatch.setattr(inventory, "replay_navigation_path", fake_replay)
    monkeypatch.setattr(
        inventory,
        "discover_navigation_labels",
        lambda page, profile: ["Firewall", "Broken"] if len(page.paths) == 1 else [],
    )
    monkeypatch.setattr(inventory, "path_revisit_allowed", lambda path, label, profile: True)
    monkeypatch.setattr(
        inventory,
        "extract_browser_facts",
        lambda snapshot, page, page_id, url: snapshot.elements.append(
            types.SimpleNamespace(control_type="heading", label="Firewall")
        ),
    )

    report = inventory_profile(tmp_path, profile, ontology)

    assert fake_browser.context_kwargs == {"ignore_https_errors": True}
    assert fake_browser.context.closed is True
    assert fake_browser.closed is True
    assert report["profile_id"] == "profile"
    assert report["node_count"] == 2
    assert report["failed_paths"] == [{"path": ["Broken"], "reason": "replay_failed"}]
    assert report["domain_vocabulary"] == ["firewall", "rule", "security"]
    assert report["nodes"][0]["headings"] == ["Firewall"]
    assert report["nodes"][0]["synonym_hits"] == {"firewall rule": 4}
    assert report["coverage"]["complete"] is False
