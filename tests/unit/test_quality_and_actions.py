from pathlib import Path

from site_agent.core.actions import build_action_report, classify_action_risk
from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, Form, MappedSchema, Page, ToolSpec, UiElement, utc_now
from site_agent.core.profiles import Profile
from site_agent.core.quality import compare_coverage, quality_gate_report, update_crawl_memory
from site_agent.core.storage import read_json


def make_profile() -> Profile:
    return Profile(id="profile", name="demo", base_url="https://example.com", host_allowlist=["example.com"], created_at=utc_now())


def test_action_risk_inventory_classifies_high_and_medium_forms():
    assert classify_action_risk("Factory Reset", [])[0] == "high"
    assert classify_action_risk("Save Settings", ["SSID"])[0] == "medium"
    assert classify_action_risk("Export", [])[0] == "low"

    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        forms=[Form(id="form", page_id="page", label="Factory Reset", field_ids=["button"])],
        elements=[UiElement(id="button", page_id="page", selector_fingerprint="x", label="Factory Reset", control_type="submit")],
    )

    report = build_action_report(snapshot)

    assert report["summary"]["risk_counts"]["high"] == 1
    assert report["actions"][0]["requires_confirmation"]


def test_coverage_compare_and_memory(tmp_path):
    profile = make_profile()
    previous = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run1", pages=[Page(id="p1", url="https://example.com/#state=home")])
    current = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run2",
        pages=[Page(id="p1", url="https://example.com/#state=home"), Page(id="p2", url="https://example.com/#state=settings")],
        forms=[Form(id="form", page_id="p2", label="Settings")],
        elements=[UiElement(id="ui", page_id="p2", selector_fingerprint="fp", label="SSID", control_type="text")],
    )
    schema = MappedSchema(
        profile_id="profile",
        run_id="run2",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term_ssid", canonical_name="ssid")],
        mappings=[
            ConceptMapping("ui", "term_ssid", "ssid", ["SSID"], 0.9, ["ev"], "ready", "matched"),
        ],
        evidence=[Evidence(id="ev", kind="ui", source="ui", summary="label")],
    )

    comparison = compare_coverage(profile, previous, current, None, schema)
    memory_path = update_crawl_memory(
        tmp_path,
        profile,
        comparison,
        {"attribution": {"promotable_labels": ["Settings"]}},
    )

    assert comparison["summary"]["new_states"] == 1
    assert comparison["summary"]["new_forms"] == 1
    assert read_json(memory_path)["last_outcome"] == "useful_gain"
    assert "Settings" in read_json(memory_path)["promoted_labels"]


def test_quality_gate_flags_missing_tool_evidence():
    profile = make_profile()
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run", pages=[Page(id="page", url="https://example.com")])
    schema = MappedSchema(profile_id="profile", run_id="run", generated_at=utc_now(), ontology=[], mappings=[], evidence=[])
    report = quality_gate_report(profile, snapshot, schema, [{"name": "get_status", "evidence_ids": [], "risk_level": "low"}])

    assert not report["passed"]
    assert report["failures"]


def test_quality_gate_fails_coverage_regression():
    profile = make_profile()
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run2", pages=[Page(id="page", url="https://example.com")])
    schema = MappedSchema(profile_id="profile", run_id="run2", generated_at=utc_now(), ontology=[], mappings=[], evidence=[])
    comparison = {
        "summary": {
            "removed_states": 5,
            "new_states": 0,
            "new_forms": 0,
            "new_mapped_terms": 0,
            "widget_state_growth": 0,
            "high_value_state_growth": -2,
        }
    }

    report = quality_gate_report(profile, snapshot, schema, [], comparison)

    assert not report["passed"]
    assert any("Coverage regression" in failure for failure in report["failures"])


def test_memory_promotes_probe_labels_when_mappings_improve(tmp_path):
    profile = make_profile()
    comparison = {
        "previous_run_id": "run1",
        "current_run_id": "run2",
        "generated_at": utc_now(),
        "summary": {
            "high_value_state_growth": 0,
            "new_mapped_terms": 1,
            "new_ui_elements": 0,
            "new_forms": 0,
            "new_states": 0,
            "widget_state_growth": 0,
        },
    }

    memory_path = update_crawl_memory(tmp_path, profile, comparison, {"attribution": {"probe_labels": ["DDNS"]}})

    assert "DDNS" in read_json(memory_path)["promoted_labels"]
