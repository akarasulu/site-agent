import json
import os
from pathlib import Path
import urllib.error

import pytest

from site_agent.cli import main
from site_agent.cli import directional_target_outcomes
from site_agent.core.ai.backends import FakeAiBackend, OpenAiResponsesBackend, get_ai_backend
from site_agent.core.models import ConceptMapping, DomainTerm, Evidence, UiElement
from site_agent.core.ai.research import discover_ui_domain
from site_agent.core.models import CrawlSnapshot, Page, utc_now
from site_agent.core.profiles import load_profile
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
    tool = next(tool for tool in read_json(Path("output/demo/mcp/tools.json"))["tools"] if tool["name"] == "wan_connection_get")
    assert tool["name"] == "wan_connection_get"
    assert tool["description"] == "Read wan connection get."

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
    session = read_json(Path("output/router/reports/research-session.json"))
    assert session["domain_hypotheses"] == ["Example Router"]
    assert session["terms"]


def test_fake_ai_ui_domain_discovery_writes_router_capability_ontology(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert main(["profile", "init", "--name", "router", "--base-url", "https://192.0.2.1"]) == 0
    profile = load_profile(Path.cwd(), "router")

    markdown_path, json_path = discover_ui_domain(
        Path.cwd(),
        profile,
        FakeAiBackend(),
        "ZTE Router WAN Status LAN Wi-Fi Security",
        max_sources=2,
    )

    text = markdown_path.read_text(encoding="utf-8")
    raw = read_json(json_path)
    session = read_json(Path("output/router/reports/research-session.json"))
    assert "# port forwarding rule" in text
    assert any(term["canonical_name"] == "port forwarding rule" for term in raw["terms"])
    assert "Example Router Admin UI" in session["domain_hypotheses"]


def test_live_crawl_requires_active_ai_backend(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("SITE_AGENT_AI_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("SITE_AGENT_ALLOW_NO_AI", raising=False)

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    assert main(["crawl", "run", "--profile", "demo"]) == 2
    captured = capsys.readouterr()
    assert "Live crawl requires an active AI backend" in captured.err


def test_live_crawl_with_active_ai_runs_ui_domain_discovery(tmp_path, monkeypatch, capsys):
    import site_agent.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "fake")
    monkeypatch.setattr(cli, "sample_landing_page_text", lambda *args, **kwargs: "Router WAN Status Security")
    monkeypatch.setattr(
        cli,
        "crawl_profile",
        lambda workspace, profile, *args, **kwargs: CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run_live_ai"),
    )
    monkeypatch.setattr(cli, "inventory_profile", lambda *args, **kwargs: {"nodes": [], "node_count": 0, "coverage": {"complete": True}})

    assert main(["profile", "init", "--name", "router", "--base-url", "https://192.0.2.1"]) == 0
    assert main(["crawl", "run", "--profile", "router"]) == 0
    captured = capsys.readouterr()
    assert "Pre-crawl AI UI domain evidence saved" in captured.out
    docs = list(Path("profiles/router/docs").glob("ai-research-*.md"))
    assert any("# port forwarding rule" in path.read_text(encoding="utf-8") for path in docs)


def test_planned_live_crawl_reuses_existing_research_session(tmp_path, monkeypatch, capsys):
    import site_agent.cli as cli

    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "fake")
    assert main(["profile", "init", "--name", "router", "--base-url", "https://192.0.2.1"]) == 0
    write_json(
        Path("output/router/reports/research-session.json"),
        {
            "profile_id": "profile",
            "profile_name": "router",
            "terms": [{"canonical_name": "port forwarding"}],
            "sources": [],
        },
    )
    monkeypatch.setattr(
        cli,
        "latest_crawl_plan",
        lambda workspace, profile_name: {"plan_id": "plan", "prioritized_labels": [{"label": "Virtual Server", "sources": ["ai_directional"]}]},
    )
    monkeypatch.setattr(cli, "sample_landing_page_text", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("should reuse research")))
    monkeypatch.setattr(cli, "build_ontology_artifact", lambda *args, **kwargs: ([], []))
    monkeypatch.setattr(
        cli,
        "crawl_profile",
        lambda workspace, profile, *args, **kwargs: CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run_planned"),
    )
    monkeypatch.setattr(cli, "inventory_profile", lambda *args, **kwargs: {"nodes": [], "node_count": 0, "coverage": {"complete": True}})

    assert main(["crawl", "run", "--profile", "router", "--use-plan", "latest"]) == 0
    captured = capsys.readouterr()
    assert "reusing existing research session" in captured.out


def test_directional_target_outcomes_report_reached_partial_and_failed():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[
            Page(id="p1", url="https://example.test/#state=internet/port-binding"),
            Page(id="p2", url="https://example.test/#state=local-network"),
        ],
    )
    plan = {
        "directional_targets": [
            {"branch_path": ["Internet", "Port Binding"], "labels": ["Virtual Server"]},
            {"branch_path": ["Local Network", "UPnP"], "labels": ["UPnP"]},
            {"branch_path": ["Management", "Logs"], "labels": ["Logs"]},
        ]
    }

    outcomes = directional_target_outcomes(plan, snapshot)

    assert [item["status"] for item in outcomes] == ["reached", "partial", "failed"]


def test_openai_backend_is_default_when_key_exists(monkeypatch):
    monkeypatch.delenv("SITE_AGENT_AI_PROVIDER", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    assert isinstance(get_ai_backend(), OpenAiResponsesBackend)


def test_openai_backend_request_json_parses_output_chunks_and_wraps_errors(monkeypatch):
    captured = {}

    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return json_bytes({"output": [{"content": [{"text": "{\"ok\": true}"}]}]})

    def fake_urlopen(request, timeout):
        captured["url"] = request.full_url
        captured["data"] = request.data
        captured["headers"] = request.headers
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    backend = OpenAiResponsesBackend(api_key="secret", model="test-model", base_url="https://api.test/v1")

    result = backend._request_json("Use JSON.", "input", "test_schema", {"type": "object"})

    assert result == {"ok": True}
    assert captured["url"] == "https://api.test/v1/responses"
    assert captured["timeout"] == backend.timeout
    payload = json.loads(captured["data"].decode("utf-8"))
    assert payload["model"] == "test-model"
    assert payload["text"]["format"]["name"] == "test_schema"

    def failing_urlopen(request, timeout):
        raise urllib.error.URLError("network down")

    monkeypatch.setattr("urllib.request.urlopen", failing_urlopen)
    with pytest.raises(RuntimeError, match="OpenAI Responses API request failed"):
        backend._request_json("Use JSON.", "input", "test_schema", {"type": "object"})


def test_openai_build_enrichment_budgets_default_to_zero(monkeypatch):
    monkeypatch.delenv("SITE_AGENT_AI_TOOL_DESCRIPTION_BUDGET", raising=False)
    monkeypatch.delenv("SITE_AGENT_AI_FORM_CLASSIFICATION_BUDGET", raising=False)
    backend = OpenAiResponsesBackend(api_key="secret", model="test-model", base_url="https://api.test/v1")

    def fail_request(*args, **kwargs):
        raise AssertionError("optional build enrichment should not call OpenAI by default")

    monkeypatch.setattr(backend, "_request_json", fail_request)
    mapping = ConceptMapping("ui_ssid", "term_ssid", "ssid", ["SSID"], 0.9, ["ev_ssid"], "ready", "matched")

    assert backend.describe_tool(mapping, []) is None
    assert backend.classify_form_purpose({"form_id": "form_ssid", "evidence_ids": ["ev_ssid"]}, [], {}) is None


def test_openai_build_enrichment_budgets_are_explicit_and_capped(monkeypatch):
    monkeypatch.setenv("SITE_AGENT_AI_TOOL_DESCRIPTION_BUDGET", "1")
    monkeypatch.setenv("SITE_AGENT_AI_FORM_CLASSIFICATION_BUDGET", "1")
    backend = OpenAiResponsesBackend(api_key="secret", model="test-model", base_url="https://api.test/v1")
    calls = []

    def fake_request(instructions, input_text, schema_name, schema, tools=None):
        calls.append(schema_name)
        if schema_name == "tool_description":
            return {"description": "Read SSID from approved evidence."}
        if schema_name == "form_purpose_classification":
            return {
                "semantic_purpose": "wireless settings",
                "operation": "update",
                "confidence": 0.7,
                "evidence_ids": ["ev_ssid"],
                "reasoning_summary": "Fields reference SSID settings.",
                "negative_concepts": [],
            }
        raise AssertionError(schema_name)

    monkeypatch.setattr(backend, "_request_json", fake_request)
    mapping = ConceptMapping("ui_ssid", "term_ssid", "ssid", ["SSID"], 0.9, ["ev_ssid"], "ready", "matched")

    assert backend.describe_tool(mapping, []) == "Read SSID from approved evidence."
    assert backend.describe_tool(mapping, []) is None
    classification = backend.classify_form_purpose({"form_id": "form_ssid", "evidence_ids": ["ev_ssid"]}, [], {})
    assert classification is not None
    assert classification.semantic_purpose == "wireless settings"
    assert backend.classify_form_purpose({"form_id": "form_ssid_2", "evidence_ids": ["ev_ssid"]}, [], {}) is None
    assert calls == ["tool_description", "form_purpose_classification"]


def test_mcp_build_with_openai_key_skips_optional_network_enrichment_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "none")
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Settings</h1><form><input aria-label='SSID'></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    write_json(
        Path("profiles/demo/ontology.seed.json"),
        {"terms": [{"canonical_name": "ssid", "aliases": ["wifi name"], "sources": ["manual"], "confidence": 0.9}]},
    )
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "demo"]) == 0

    def fail_urlopen(*args, **kwargs):
        raise AssertionError("mcp build should not call OpenAI for optional enrichment by default")

    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.delenv("SITE_AGENT_AI_TOOL_DESCRIPTION_BUDGET", raising=False)
    monkeypatch.delenv("SITE_AGENT_AI_FORM_CLASSIFICATION_BUDGET", raising=False)
    monkeypatch.setattr("urllib.request.urlopen", fail_urlopen)

    assert main(["mcp", "build", "--profile", "demo", "--include-writes"]) == 0


def json_bytes(payload):
    import json

    return json.dumps(payload).encode("utf-8")


class ScriptedOpenAiBackend(OpenAiResponsesBackend):
    def __init__(self):
        super().__init__(api_key="test-key", model="test-model")
        self.description_budget = 100
        self.form_classification_budget = 100
        self.calls = []

    def _request_json(self, instructions, input_text, schema_name, schema, tools=None):
        self.calls.append({"schema_name": schema_name, "input_text": input_text, "tools": tools})
        responses = {
            "ontology_terms": {
                "terms": [
                    {
                        "canonical_name": "WAN_Status",
                        "aliases": ["WAN State"],
                        "units": [],
                        "constraints": ["read-only"],
                        "confidence": 0.91,
                        "evidence_ids": ["ev_doc"],
                    }
                ]
            },
            "concept_mapping": {
                "matched": True,
                "canonical_name": "WAN Status",
                "aliases": ["WAN State"],
                "confidence": 0.88,
                "evidence_ids": ["ev_ui", "missing"],
                "reasoning_summary": "matched",
            },
            "tool_description": {"description": "Read WAN status."},
            "field_classification": {
                "matched": True,
                "semantic_type": "Admin Email",
                "value_type": "String",
                "confidence": 0.9,
                "evidence_ids": ["ev_ui", "missing"],
                "reasoning_summary": "field",
            },
            "action_intent": {
                "matched": True,
                "intent": "Save Settings",
                "risk_level": "medium",
                "confidence": 0.87,
                "evidence_ids": ["ev_ui"],
                "reasoning_summary": "action",
            },
            "constraint_conflicts": {
                "conflicts": [
                    {
                        "kind": "unit_conflict",
                        "severity": "warning",
                        "summary": "conflict",
                        "evidence_ids": ["ev_doc", "missing"],
                    }
                ]
            },
            "crawl_priorities": {
                "priorities": [
                    {
                        "target": "security",
                        "reason": "missing firewall terms",
                        "expected_concepts": ["firewall"],
                        "priority": 0.75,
                    }
                ]
            },
            "directional_crawl_plan": {
                "targets": [
                    {
                        "branch_path": ["Internet", ""],
                        "labels": ["Virtual Server", ""],
                        "missing_concepts": ["Port Forwarding"],
                        "reason": "target NAT branch",
                        "priority": 0.95,
                        "confidence": 0.82,
                    }
                ]
            },
            "form_purpose_classification": {
                "semantic_purpose": "Port Binding",
                "operation": "Create Or Update",
                "confidence": 0.7,
                "evidence_ids": ["missing"],
                "reasoning_summary": "form",
                "negative_concepts": ["Port Forwarding"],
            },
            "product_doc_research": {
                "product_name": "Router",
                "sources": [{"title": "Manual"}, {"title": "Forum"}],
                "terms": [{"canonical_name": "wan status"}],
            },
            "ui_domain_discovery": {
                "product_name": "Router UI",
                "sources": [{"title": "Manual"}, {"title": "Forum"}],
                "terms": [{"canonical_name": "firewall rule"}],
            },
        }
        return responses[schema_name]


def test_openai_backend_structured_methods_filter_and_normalize_evidence():
    backend = ScriptedOpenAiBackend()
    evidence = [
        Evidence(id="ev_ui", kind="ui", source="fixture", summary="WAN State"),
        Evidence(id="ev_doc", kind="doc", source="manual", summary="WAN Status"),
    ]
    element = UiElement(
        id="ui_1",
        page_id="page",
        selector_fingerprint="fp",
        label="WAN State",
        control_type="submit",
        evidence_ids=["ev_ui"],
    )
    ontology = [DomainTerm(id="term_wan", canonical_name="wan status", sources=["ev_doc"], confidence=0.9)]

    terms = backend.extract_terms([{"evidence_id": "ev_doc", "text": "# WAN Status"}])
    mapping = backend.align_element(element, ontology, evidence)
    description = backend.describe_tool(
        ConceptMapping("ui_1", "term_wan", "wan status", ["WAN State"], 0.9, ["ev_ui"], "ready", "ok"),
        evidence,
    )
    field = backend.classify_field(element, evidence)
    action = backend.normalize_action(element, evidence)
    conflicts = backend.detect_conflicts(ontology, evidence)
    priorities = backend.prioritize_crawl([element], ontology)
    targets = backend.plan_directional_crawl({"pages": 1}, [{"canonical_name": "port forwarding"}], ontology)
    form = backend.classify_form_purpose({"form_id": "form", "evidence_ids": ["ev_form"]}, ontology)
    docs = backend.research_product_docs("Router", max_sources=1)
    domain = backend.discover_ui_domain("Router WAN", base_url="https://example.test", max_sources=1)

    assert terms[0].canonical_name == "wan status"
    assert terms[0].sources == ["ev_doc"]
    assert mapping.evidence_ids == ["ev_ui"]
    assert description == "Read WAN status."
    assert field.semantic_type == "admin_email"
    assert action.intent == "save_settings"
    assert conflicts[0].evidence_ids == ["ev_doc"]
    assert priorities[0].target == "security"
    assert targets[0].missing_concepts == ["port forwarding"]
    assert form.evidence_ids == ["ev_form"]
    assert form.negative_concepts == ["port forwarding"]
    assert docs.sources == [{"title": "Manual"}]
    assert domain.terms == [{"canonical_name": "firewall rule"}]
    assert backend.prioritize_crawl([], ontology) == []
    assert backend.plan_directional_crawl({}, [], ontology) == []
    assert backend.align_element(
        UiElement("ui_2", "page", "fp2", "No Evidence", "text", evidence_ids=[]),
        ontology,
        evidence,
    ) is None
    assert backend.normalize_action(
        UiElement("ui_3", "page", "fp3", "Plain Field", "text", evidence_ids=["ev_ui"]),
        evidence,
    ) is None
