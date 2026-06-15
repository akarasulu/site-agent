from pathlib import Path
from typing import Any
import importlib
import sys

from site_agent.cli import main
from site_agent.core.models import CrawlSnapshot, Evidence, Form, InteractionFlow, Page, UiElement, utc_now
from site_agent.core.storage import read_json, write_json
from site_agent.core.synthesize.mcp import synthesize_form_tools, write_mcp_package
from site_agent.core.synthesize.runtime import RuntimeErrorForTool, call_tool
from site_agent.core.synthesize.contracts import diff_contracts


def _schema_issues(value: Any, path: str = "$") -> list[str]:
    issues: list[str] = []
    if isinstance(value, dict):
        properties = value.get("properties")
        required = value.get("required")
        if isinstance(properties, dict) or isinstance(required, list):
            property_names = set(properties or {})
            required_names = list(required or [])
            duplicated = sorted({name for name in required_names if required_names.count(name) > 1})
            missing = sorted(name for name in required_names if name not in property_names)
            if duplicated:
                issues.append(f"{path}: duplicate required entries: {duplicated}")
            if missing:
                issues.append(f"{path}: required entries missing from properties: {missing}")
        for key, child in value.items():
            issues.extend(_schema_issues(child, f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            issues.extend(_schema_issues(child, f"{path}[{index}]"))
    return issues


def assert_generated_schema_invariants(output_dir: Path) -> None:
    issues: list[str] = []
    for path in sorted(output_dir.rglob("*.json")):
        document = read_json(path)
        issues.extend(f"{path.relative_to(output_dir)} {issue}" for issue in _schema_issues(document))
        if path.name == "adapter.bindings.json":
            for index, binding in enumerate(document.get("bindings", [])):
                fields = binding.get("selector_action_bindings", {}).get("fields", [])
                args = [field.get("arg") for field in fields if field.get("arg")]
                duplicated = sorted({arg for arg in args if args.count(arg) > 1})
                if duplicated:
                    tool_name = binding.get("tool_name", f"binding[{index}]")
                    issues.append(f"{path.relative_to(output_dir)} {tool_name}: duplicate field args: {duplicated}")
    assert issues == []


def test_contract_diff_detects_renames_as_breaking_without_major_bump():
    old = {
        "version": "0.1.0",
        "tools": [
            {
                "name": "read_status",
                "args": {"type": "object"},
                "risk_level": "low",
                "return_schema": {"type": "object"},
            }
        ],
    }
    new = {
        "version": "0.1.0",
        "tools": [
            {
                "name": "get_status",
                "args": {"type": "object"},
                "risk_level": "low",
                "return_schema": {"type": "object"},
            }
        ],
    }
    report = diff_contracts(old, new)
    assert report["breaking"]
    assert report["semver_required"] == "major"
    assert not report["version_ok"]
    assert report["renamed"] == [{"from": "read_status", "to": "get_status"}]

    new["version"] = "1.0.0"
    assert diff_contracts(old, new)["version_ok"]


def test_contract_diff_and_write_tool_dry_run(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    assert main(["profile", "init", "--name", "opsboard", "--base-url", "http://127.0.0.1:8080"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["mcp", "build", "--profile", "opsboard", "--include-writes"]) == 0
    assert_generated_schema_invariants(Path("output/opsboard"))

    tools = read_json(Path("output/opsboard/mcp/tools.json"))["tools"]
    names = {tool["name"] for tool in tools}
    assert "settings_update" in names
    save_settings = next(tool for tool in tools if tool["name"] == "settings_update")
    assert save_settings["args"].get("required", []) == []
    assert Path("output/opsboard/mcp/contract.json").exists()

    args = tmp_path / "args.json"
    write_json(args, {"alert_email": "ops@example.test", "maintenance_window": "Sunday 02:00 UTC", "retention_days": "30", "dry_run": True})
    assert main(["mcp", "call", "--profile", "opsboard", "--tool", "settings_update", "--args-json", str(args)]) == 0
    write_json(args, {"dry_run": True})
    assert main(["mcp", "call", "--profile", "opsboard", "--tool", "settings_update", "--args-json", str(args)]) == 0

    baseline = Path("baseline.json")
    write_json(baseline, read_json(Path("output/opsboard/mcp/contract.json")))
    assert main(["mcp", "diff", "--profile", "opsboard", "--baseline", str(baseline)]) == 0
    assert main(["mcp", "refresh-adapter", "--profile", "opsboard", "--include-writes"]) == 0


def test_generated_python_api_imports_reads_and_dry_runs_writes(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    assert main(["profile", "init", "--name", "opsboard", "--base-url", "http://127.0.0.1:8080"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["api", "build", "--profile", "opsboard"]) == 0
    assert Path("output/opsboard/mcp/tools.json").exists()

    api_spec = read_json(Path("output/opsboard/api/api-spec.json"))
    assert api_spec["package_name"] == "opsboard_client"
    assert any(method["name"] == "settings_update" for method in api_spec["methods"])
    server = read_json(Path("output/opsboard/mcp/server.json"))
    assert server["python_api"]["package_name"] == "opsboard_client"

    sys.path.insert(0, str(Path("output/opsboard/api").resolve()))
    try:
        module = importlib.import_module("opsboard_client")
        client = module.OpsboardClient.from_package_dir(Path("output/opsboard/mcp"))
        result = client.settings_update(
            alert_email="ops@example.test",
            maintenance_window="Sunday 02:00 UTC",
            retention_days="30",
        )
        assert result["status"] == "dry_run"
        delegated = call_tool(Path("output/opsboard/mcp"), "settings_update", {"alert_email": "ops@example.test"})
        assert delegated["execution_surface"] == "python_api"
    finally:
        sys.path = [entry for entry in sys.path if entry != str(Path("output/opsboard/api").resolve())]


def test_generated_ansible_collection_wraps_python_api(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    assert main(["profile", "init", "--name", "opsboard", "--base-url", "http://127.0.0.1:8080"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["mcp", "build", "--profile", "opsboard"]) == 0
    assert main(["api", "build", "--profile", "opsboard"]) == 0
    assert main(["ansible", "build", "--profile", "opsboard"]) == 0

    spec = read_json(Path("output/opsboard/ansible/ansible-spec.json"))
    assert spec["python_api_dependency"] == "opsboard_client"
    module_path = Path("output/opsboard/ansible/ansible_collections/site_agent/opsboard/plugins/modules/opsboard_settings_update.py")
    assert module_path.exists()
    source = module_path.read_text(encoding="utf-8")
    assert "load_client" in source
    assert "client.settings_update" in source
    module_utils = Path("output/opsboard/ansible/ansible_collections/site_agent/opsboard/plugins/module_utils/client.py").read_text(encoding="utf-8")
    assert "from opsboard_client import OpsboardClient" in module_utils


def test_mcp_build_includes_ui_backed_page_and_form_tools_by_default(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    assert main(["profile", "init", "--name", "opsboard", "--base-url", "http://127.0.0.1:8080"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), {"terms": []})
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["mcp", "build", "--profile", "opsboard"]) == 0

    tools = read_json(Path("output/opsboard/mcp/tools.json"))["tools"]
    names = {tool["name"] for tool in tools}
    action_tools = [tool for tool in tools if tool["risk_level"] in {"medium", "high"}]

    assert "settings_update" in names
    assert action_tools
    assert all(tool["dry_run_supported"] for tool in action_tools)
    assert any(tool["exposure_level"] == "review_required" for tool in action_tools)

    args = tmp_path / "args.json"
    write_json(args, {"alert_email": "ops@example.test", "maintenance_window": "Sunday 02:00 UTC", "retention_days": "30", "dry_run": False})
    assert main(["mcp", "call", "--profile", "opsboard", "--tool", "settings_update", "--args-json", str(args), "--mode", "apply"]) == 2

    html = tmp_path / "status.html"
    html.write_text("<h1>Status</h1><p>WAN Status: Connected</p><p>Software Version: V1</p>", encoding="utf-8")
    assert main(["profile", "init", "--name", "statuspage", "--base-url", "https://status.example"]) == 0
    assert main(["crawl", "run", "--profile", "statuspage", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "statuspage"]) == 0
    assert main(["mcp", "build", "--profile", "statuspage"]) == 0
    status_tools = read_json(Path("output/statuspage/mcp/tools.json"))["tools"]
    assert any(tool["name"] == "status_get" for tool in status_tools)
    assert all(not tool["name"].startswith("read_") for tool in status_tools)
    assert all(tool["source_type"] == "canonical_concept" for tool in status_tools)
    report = read_json(sorted(Path("output/statuspage/reports").glob("contract-quality-*.json"))[-1])
    assert report["passed"]
    assert report["metrics"]["deprecated_read_prefix_tools"] == 0


def test_canonical_reads_suppress_overlapping_page_read_tools(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "status.html"
    html.write_text("<h1>Status</h1><p>WAN Status: Connected</p><p>Software Version: V1</p>", encoding="utf-8")
    assert main(["profile", "init", "--name", "statuspage", "--base-url", "https://status.example"]) == 0
    write_json(
        Path("profiles/statuspage/ontology.seed.json"),
        {
            "terms": [
                {"canonical_name": "wan status", "aliases": ["WAN Status"], "sources": ["seed"], "confidence": 0.9},
                {"canonical_name": "software version", "aliases": ["Software Version"], "sources": ["seed"], "confidence": 0.9},
            ]
        },
    )
    assert main(["crawl", "run", "--profile", "statuspage", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "statuspage"]) == 0
    assert main(["mcp", "build", "--profile", "statuspage"]) == 0
    tools = read_json(Path("output/statuspage/mcp/tools.json"))["tools"]
    names = {tool["name"] for tool in tools}
    assert {"wan_connection_get", "software_version_get"} <= names
    assert all(tool["source_type"] != "ui_page" for tool in tools)


def test_staged_action_tools_are_generated_from_dynamic_interaction_flows(tmp_path):
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=list", title="Items")],
        forms=[Form(id="form", page_id="page", label="Dynamic Items", field_ids=[])],
        elements=[
            UiElement(
                id="rule_name",
                page_id="page",
                selector_fingerprint="name-fp",
                label="Rule Name",
                control_type="text",
                context={"constraints": {"maxlength": "10"}},
                evidence_ids=["ev_name"],
            ),
            UiElement(
                id="service_port",
                page_id="page",
                selector_fingerprint="port-fp",
                label="Service Port",
                control_type="text",
                context={"constraints": {"range": [1, 65535]}},
                evidence_ids=["ev_port"],
            ),
            UiElement(
                id="rule_name_confirm",
                page_id="page",
                selector_fingerprint="name-confirm-fp",
                label="Rule Name",
                control_type="text",
                evidence_ids=["ev_name_confirm"],
            ),
            UiElement(
                id="enabled",
                page_id="page",
                selector_fingerprint="enabled-fp",
                label="Enabled",
                control_type="checkbox",
                evidence_ids=["ev_enabled"],
            ),
        ],
        evidence=[Evidence(id="ev_flow", kind="ui", source="probe", summary="Add Item opened a dynamic form and cancel was available.")],
        interaction_flows=[
            InteractionFlow(
                id="flow_add_item",
                page_id="page",
                trigger_label="Add Item",
                flow_type="dynamic_form",
                discovered_field_ids=["rule_name", "rule_name_confirm", "service_port", "enabled"],
                constraints={"rule_name": {"maxlength": "10"}},
                cancel_supported=True,
                requires_open_before_submit=True,
                evidence_ids=["ev_flow"],
            )
        ],
    )

    tools, bindings = synthesize_form_tools("profile", snapshot, set())
    names = {tool.name for tool in tools}
    assert {"create_item", "activate_item", "deactivate_item", "delete_item"} <= names
    create_tool = next(tool for tool in tools if tool.name == "create_item")
    assert create_tool.source_type == "ui_flow"
    assert create_tool.requires_confirmation
    assert create_tool.args.get("required", []) == []
    assert {"rule_name", "rule_name_2", "service_port", "enabled"} <= set(create_tool.args["properties"])
    assert create_tool.args["properties"]["rule_name"]["maxLength"] == 10
    delete_tool = next(tool for tool in tools if tool.name == "delete_item")
    assert delete_tool.risk_level == "high"
    assert delete_tool.exposure_level == "internal_disabled"

    write_mcp_package(tmp_path, "profile", tools, bindings, "https://example.test")
    assert_generated_schema_invariants(tmp_path / "output/profile")
    result = call_tool(
        tmp_path / "output/profile/mcp",
        "create_item",
        {"rule_name": "SA12121", "service_port": "12121", "enabled": "off", "dry_run": True},
    )
    assert result["status"] == "dry_run"
    assert result["adapter_action"] == "open_fill_dynamic_form"
    assert any(step["step"] == "fill_fields" for step in result["planned_steps"])
    partial_result = call_tool(
        tmp_path / "output/profile/mcp",
        "create_item",
        {"dry_run": True},
    )
    assert partial_result["status"] == "dry_run"
    try:
        call_tool(
            tmp_path / "output/profile/mcp",
            "activate_item",
            {"item_match": {"rule_name": "SA12121"}, "dry_run": False, "confirm": True},
            mode="apply",
        )
    except RuntimeErrorForTool as exc:
        assert "--browser" in str(exc)
    else:
        raise AssertionError("staged browser apply should be blocked until a browser-backed runtime exists")


def test_generic_form_action_uses_page_path_for_semantic_name():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=internet/port-binding", title="Router")],
        forms=[Form(id="form", page_id="page", label="form", field_ids=["submit"])],
        elements=[
            UiElement(
                id="submit",
                page_id="page",
                selector_fingerprint="submit-fp",
                label="Refresh",
                control_type="submit",
                evidence_ids=["ev_submit"],
            )
        ],
        evidence=[Evidence(id="ev_submit", kind="ui", source="fixture", summary="Refresh button")],
    )

    tools, bindings = synthesize_form_tools("profile", snapshot, set())

    assert any(tool.name == "submit_internet_port_binding" for tool in tools)
    binding = next(binding for binding in bindings if binding.tool_name == "submit_internet_port_binding")
    assert binding.selector_action_bindings["purpose_label"] == "Internet Port Binding"


def test_machine_like_form_action_prefers_page_path_name():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=internet/port-binding", title="Router")],
        forms=[Form(id="form", page_id="page", label="form", field_ids=["ssid8"])],
        elements=[
            UiElement(
                id="ssid8",
                page_id="page",
                selector_fingerprint="ssid8-fp",
                label="SSID8",
                control_type="submit",
                evidence_ids=["ev_submit"],
            )
        ],
        evidence=[Evidence(id="ev_submit", kind="ui", source="fixture", summary="Machine-like button")],
    )

    tools, _ = synthesize_form_tools("profile", snapshot, set())

    assert any(tool.name == "submit_internet_port_binding" for tool in tools)


def test_form_classification_marks_port_binding_as_not_port_forwarding(tmp_path, monkeypatch):
    from site_agent.core.form_classify import classify_forms
    from site_agent.core.ai.backends import FakeAiBackend
    from site_agent.core.profiles import Profile

    monkeypatch.chdir(tmp_path)
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=internet/port-binding", title="Router")],
        forms=[Form(id="form", page_id="page", label="form", field_ids=["lan1", "ssid1", "submit"])],
        elements=[
            UiElement(id="lan1", page_id="page", selector_fingerprint="lan1", label="LAN1", control_type="checkbox", evidence_ids=["ev_lan"]),
            UiElement(id="ssid1", page_id="page", selector_fingerprint="ssid1", label="SSID1", control_type="checkbox", evidence_ids=["ev_ssid"]),
            UiElement(id="submit", page_id="page", selector_fingerprint="submit", label="SSID8", control_type="submit", evidence_ids=["ev_submit"]),
        ],
    )
    profile = Profile(id="profile", name="router", base_url="https://example.test", host_allowlist=["example.test"], created_at=utc_now())

    classifications, _ = classify_forms(Path.cwd(), profile, snapshot, [], FakeAiBackend(), {})
    tools, bindings = synthesize_form_tools("profile", snapshot, set(), classifications)

    classification = classifications["form"]
    assert classification["semantic_purpose"] == "port binding"
    assert "port forwarding" in classification["negative_concepts"]
    assert any(tool.name == "submit_port_binding" for tool in tools)
    binding = next(binding for binding in bindings if binding.tool_name == "submit_port_binding")
    assert binding.selector_action_bindings["form_classification"]["negative_concepts"]


def test_semantic_form_tools_are_deduplicated_by_purpose_and_field_shape():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=internet/security/port-forwarding", title="Router")],
        forms=[
            Form(id="form_1", page_id="page", label="form", field_ids=["name_1", "protocol_1", "lan_1", "wan_1", "internal_1"]),
            Form(id="form_2", page_id="page", label="form", field_ids=["name_2", "protocol_2", "lan_2", "wan_2", "internal_2"]),
        ],
        elements=[
            UiElement(id="name_1", page_id="page", selector_fingerprint="name1", label="Name", control_type="text", evidence_ids=["ev1"]),
            UiElement(id="protocol_1", page_id="page", selector_fingerprint="protocol1", label="Protocol", control_type="select", evidence_ids=["ev1"]),
            UiElement(id="lan_1", page_id="page", selector_fingerprint="lan1", label="LAN Host", control_type="text", evidence_ids=["ev1"]),
            UiElement(id="wan_1", page_id="page", selector_fingerprint="wan1", label="WAN Port", control_type="text", evidence_ids=["ev1"]),
            UiElement(id="internal_1", page_id="page", selector_fingerprint="internal1", label="LAN Host Port", control_type="text", evidence_ids=["ev1"]),
            UiElement(id="name_2", page_id="page", selector_fingerprint="name2", label="Name", control_type="text", evidence_ids=["ev2"]),
            UiElement(id="protocol_2", page_id="page", selector_fingerprint="protocol2", label="Protocol", control_type="select", evidence_ids=["ev2"]),
            UiElement(id="lan_2", page_id="page", selector_fingerprint="lan2", label="LAN Host", control_type="text", evidence_ids=["ev2"]),
            UiElement(id="wan_2", page_id="page", selector_fingerprint="wan2", label="WAN Port", control_type="text", evidence_ids=["ev2"]),
            UiElement(id="internal_2", page_id="page", selector_fingerprint="internal2", label="LAN Host Port", control_type="text", evidence_ids=["ev2"]),
        ],
    )
    classifications = {
        "form_1": {
            "form_id": "form_1",
            "semantic_purpose": "port forwarding rule",
            "operation": "create_or_update",
            "confidence": 0.84,
            "negative_concepts": ["port binding"],
            "reasoning_summary": "port forwarding fields",
            "evidence_ids": ["ev1"],
        },
        "form_2": {
            "form_id": "form_2",
            "semantic_purpose": "port forwarding rule",
            "operation": "create_or_update",
            "confidence": 0.84,
            "negative_concepts": ["port binding"],
            "reasoning_summary": "port forwarding fields",
            "evidence_ids": ["ev2"],
        },
    }

    tools, bindings = synthesize_form_tools("profile", snapshot, set(), classifications)

    names = [tool.name for tool in tools]
    assert names.count("submit_port_forwarding_rule") == 1
    assert not any(name.startswith("submit_port_forwarding_rule_") for name in names)
    matching_bindings = [binding for binding in bindings if binding.tool_name == "submit_port_forwarding_rule"]
    assert len(matching_bindings) == 1
    assert matching_bindings[0].selector_action_bindings["source_form_ids"] == ["form_1", "form_2"]
    assert {"name_1", "name_2"} <= set(matching_bindings[0].selector_action_bindings["source_field_ids"])
    tool = next(tool for tool in tools if tool.name == "submit_port_forwarding_rule")
    assert {"ev1", "ev2"} <= set(tool.evidence_ids)


def test_benchmark_pack_runs_fixture_types_including_staged_dialogs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixtures_root = repo / "profiles" / "fixtures" / "benchmark_pack"
    assert main(["benchmark", "run", "--fixtures-root", str(fixtures_root), "--fail-on-error"]) == 0
    report = read_json(Path("output/benchmark-pack-report.json"))
    assert report["passed"]
    assert {item["fixture"] for item in report["reports"]} == {"docs_site", "workflow_dashboard", "settings_admin", "staged_dialog"}
    assert all(item["metrics"]["deprecated_read_prefix_tools"] == 0 for item in report["reports"])


def test_package_build_creates_rag_bundle_with_private_boundary(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "mock_app"
    assert main(["profile", "init", "--name", "opsboard", "--base-url", "http://127.0.0.1:8080"]) == 0
    write_json(Path("profiles/opsboard/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    docs = Path("profiles/opsboard/docs/opsboard-admin-guide.md")
    docs.write_text((fixture / "docs" / "opsboard-admin-guide.md").read_text(encoding="utf-8"), encoding="utf-8")
    assert main(["crawl", "run", "--profile", "opsboard", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "opsboard"]) == 0
    assert main(["mcp", "build", "--profile", "opsboard"]) == 0
    assert main(["api", "build", "--profile", "opsboard"]) == 0
    assert main(["ansible", "build", "--profile", "opsboard"]) == 0
    assert main(["config", "coverage", "--profile", "opsboard"]) == 0
    assert main(["package", "build", "--profile", "opsboard"]) == 0

    package_dirs = sorted((Path("output/opsboard/packages")).glob("opsboard-*"))
    package_dir = next(path for path in package_dirs if path.is_dir())
    manifest = read_json(package_dir / "manifest.json")
    assert manifest["counts"]["tools"] > 0
    assert manifest["counts"]["api_methods"] > 0
    assert manifest["counts"]["ansible_modules"] > 0
    assert manifest["counts"]["rag_chunks"] > 0
    assert manifest["artifact_classes"]["public"]["safe_for_agent_context"]
    assert not manifest["artifact_classes"]["private"]["safe_for_agent_context"]
    assert (package_dir / "rag/chunks.jsonl").exists()
    assert "configuration_coverage" in (package_dir / "rag/chunks.jsonl").read_text(encoding="utf-8")
    assert (package_dir / "public/mcp/tools.json").exists()
    assert (package_dir / "public/api/api-spec.json").exists()
    assert (package_dir / "public/ansible/ansible-spec.json").exists()
    assert (package_dir / "private/adapter.bindings.json").exists()
    assert (Path("output/opsboard/packages") / f"{package_dir.name}.zip").exists()
    assert_generated_schema_invariants(Path("output/opsboard"))

    assert main(["package", "build", "--profile", "opsboard", "--public-only", "--no-zip"]) == 0
    assert not (package_dir / "private/adapter.bindings.json").exists()
