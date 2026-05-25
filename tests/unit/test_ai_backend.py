import os
from pathlib import Path

import pytest

from site_agent.cli import main
from site_agent.core.ai.backends import get_ai_backend
from site_agent.core.storage import read_json, write_json


def test_fake_ai_backend_aligns_evidence_backed_alias_and_describes_tool(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "fake")
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Status</h1><div>WAN State: Connected</div>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    write_json(
        Path("profiles/demo/ontology.seed.json"),
        {"terms": [{"canonical_name": "wan status", "sources": ["manual"], "confidence": 0.9}]},
    )
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0

    snapshot_path = sorted(Path("output/demo/crawl").glob("snapshot-*.json"))[-1]
    snapshot = read_json(snapshot_path)
    page_id = snapshot["pages"][0]["id"]
    snapshot["elements"].append(
        {
            "id": "ui_wan_state",
            "page_id": page_id,
            "selector_fingerprint": "fact_wan_state",
            "label": "WAN State",
            "control_type": "readonly_status",
            "context": {"read_value": "Connected"},
            "evidence_ids": ["ev_wan_state"],
        }
    )
    snapshot["evidence"].append(
        {
            "id": "ev_wan_state",
            "kind": "ui",
            "source": "https://example.com",
            "summary": "read-only status labelled 'WAN State'",
            "locator": "fact_wan_state",
            "created_at": snapshot["timestamp"],
        }
    )
    write_json(snapshot_path, snapshot)

    assert main(["schema", "review", "--profile", "demo"]) == 0
    schema = read_json(sorted(Path("output/demo/schema").glob("mapped-schema-*.json"))[-1])
    mapping = next(item for item in schema["mappings"] if item["ui_element_id"] == "ui_wan_state")
    assert mapping["status"] == "ready"
    assert mapping["canonical_name"] == "wan status"
    assert "AI backend matched" in mapping["reasoning_summary"]

    assert main(["mcp", "build", "--profile", "demo"]) == 0
    tool = read_json(Path("output/demo/mcp/tools.json"))["tools"][0]
    assert tool["description"] == "Read wan status from the approved evidence-backed schema."

    assert main(["ai", "analyze", "--profile", "demo", "--max-elements", "5"]) == 0
    report = read_json(Path("output/demo/reports/ai-analysis-" + schema["run_id"] + ".json"))
    assert report["field_classifications"] == []
    assert report["crawl_priorities"] == []


def test_fake_ai_backend_field_action_conflict_and_priority():
    from site_agent.core.ai.analyze import build_ai_analysis_report
    from site_agent.core.ai.backends import FakeAiBackend
    from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, MappedSchema, UiElement, utc_now

    evidence = [
        Evidence(id="ev_email", kind="ui", source="fixture", summary="email field"),
        Evidence(id="ev_save", kind="ui", source="fixture", summary="save button"),
        Evidence(id="ev_doc", kind="doc", source="manual", summary="docs"),
    ]
    elements = [
        UiElement(id="ui_email", page_id="page", selector_fingerprint="a", label="Alert email", control_type="email", evidence_ids=["ev_email"]),
        UiElement(id="ui_save", page_id="page", selector_fingerprint="b", label="Save settings", control_type="submit", evidence_ids=["ev_save"]),
        UiElement(id="ui_unknown", page_id="page", selector_fingerprint="c", label="Mystery", control_type="text", evidence_ids=["ev_email"]),
    ]
    ontology = [
        DomainTerm(id="term_a", canonical_name="retention days", constraints=["min 1"], sources=["ev_doc"]),
        DomainTerm(id="term_b", canonical_name="retention days", constraints=["max 365"], sources=["ev_doc"]),
    ]
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=ontology,
        mappings=[
            ConceptMapping("ui_email", "term_email", "alert email", ["Alert email"], 1.0, ["ev_email", "ev_doc"], "ready", "ok"),
            ConceptMapping("ui_save", None, "save settings", ["Save settings"], 0.0, ["ev_save"], "internal", "no"),
            ConceptMapping("ui_unknown", None, "mystery", ["Mystery"], 0.0, ["ev_email"], "internal", "no"),
        ],
        evidence=evidence,
    )
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run", elements=elements, evidence=evidence)
    report = build_ai_analysis_report(snapshot, schema, FakeAiBackend())
    assert report["field_classifications"][0]["semantic_type"] == "email_address"
    assert report["action_intents"][0]["intent"] == "save_settings"
    assert report["conflicts"]
    assert report["crawl_priorities"]


def test_openai_backend_requires_key(monkeypatch):
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "openai")
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
        get_ai_backend()


def test_fake_ai_docs_discovery_writes_evidence(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "fake")
    assert main(["profile", "init", "--name", "router", "--base-url", "https://192.0.2.1"]) == 0
    assert main(["docs", "discover", "--profile", "router", "--product-hint", "Example Router", "--max-sources", "2"]) == 0
    docs = list(Path("profiles/router/docs").glob("ai-research-*.md"))
    assert docs
    text = docs[0].read_text(encoding="utf-8")
    assert "# wan status" in text
    assert "https://example.com/manual" in text
