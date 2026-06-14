import pytest

from site_agent.core.ai.backends import NoopAiBackend
from site_agent.core.crawl.playwright import (
    CrawlError,
    add_fact,
    add_ui_cue,
    append_state_path_url,
    append_state_url,
    fact_fingerprint,
    is_safe_navigation_label,
    rank_navigation_labels,
    safe_click_patterns,
    score_candidate_label,
    state_slug,
    state_text_hash,
    term_tokens,
    validate_url_allowed,
)
from site_agent.core.models import CrawlSnapshot, DomainTerm, utc_now
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
