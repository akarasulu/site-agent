from pathlib import Path

from site_agent.cli import main
from site_agent.core.config_coverage import build_config_coverage_report
from site_agent.core.config_versioning import build_config_snapshot, build_restore_plan, build_restore_readiness_report, execute_restore_plan, verify_restore_snapshot
from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, Form, InteractionFlow, MappedSchema, Page, ToolSpec, UiElement, utc_now
from site_agent.core.storage import read_json, write_json


def config_snapshot_with_settings(values: dict[str, str], run_id: str = "run") -> dict:
    settings = []
    for name, value in values.items():
        settings.append(
            {
                "id": f"cfg_{name}",
                "canonical_name": name.replace("_", " "),
                "path": ["Settings", name.replace("_", " ").title()],
                "value": value,
                "value_type": "string",
                "source_tool": f"get_{name}",
                "restore_tool": "save_settings",
                "restore_arg": name,
                "evidence_ids": [f"ev_{name}"],
                "confidence": 0.9,
                "sensitivity": "operator_managed",
                "restorable": True,
            }
        )
    return {
        "schema_version": "0.1.0",
        "id": f"cfgsnap_{run_id}",
        "timestamp": utc_now(),
        "profile_id": "profile",
        "profile_name": "demo",
        "source_run_id": run_id,
        "settings": settings,
        "value_policy": "preserve-captured-values",
    }


def test_config_coverage_scores_all_eight_confidence_signals():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/settings", title="Settings")],
        forms=[Form(id="form", page_id="page", label="Port Forwarding", field_ids=["name", "port", "advanced"])],
        elements=[
            UiElement(id="name", page_id="page", selector_fingerprint="name", label="Name", control_type="text", evidence_ids=["ev_name"]),
            UiElement(id="port", page_id="page", selector_fingerprint="port", label="Port", control_type="number", evidence_ids=["ev_port"]),
            UiElement(id="advanced", page_id="page", selector_fingerprint="advanced", label="Advanced", control_type="button", evidence_ids=["ev_adv"]),
            UiElement(
                id="status",
                page_id="page",
                selector_fingerprint="status",
                label="Rule Status",
                control_type="readonly_status",
                context={"read_value": "Off"},
                evidence_ids=["ev_status"],
            ),
        ],
        interaction_flows=[
            InteractionFlow(
                id="flow",
                page_id="page",
                trigger_label="Advanced",
                flow_type="reveal_form",
                discovered_field_ids=["name", "port"],
                cancel_supported=True,
                evidence_ids=["ev_adv"],
            )
        ],
        evidence=[
            Evidence(id="ev_name", kind="ui", source="ui", summary="Name label"),
            Evidence(id="ev_port", kind="ui", source="ui", summary="Port label"),
            Evidence(id="ev_adv", kind="ui", source="ui", summary="Advanced opens dialog"),
            Evidence(id="ev_status", kind="ui", source="ui", summary="Status value"),
        ],
    )
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[
            DomainTerm(id="term_port", canonical_name="port", confidence=0.9, sources=["manual"]),
            DomainTerm(id="term_schedule", canonical_name="schedule", confidence=0.8, sources=["manual"]),
        ],
        mappings=[
            ConceptMapping("port", "term_port", "port", ["Port"], 0.91, ["ev_port"], "ready", "matched label"),
        ],
        evidence=[],
    )
    tools = [
        ToolSpec(
            name="create_port_forwarding",
            description="Create port forwarding entry.",
            args={},
            return_schema={},
            risk_level="medium",
            evidence_ids=["ev_name", "ev_port", "ev_adv"],
            source_type="ui_flow",
            confidence=0.85,
            requires_confirmation=True,
        )
    ]
    settings_snapshot = {"source_run_id": "run", "settings": [{"path": "status", "value": "Off"}]}

    report = build_config_coverage_report("profile", "demo", snapshot, schema, tools, settings_snapshot)

    assert report["scope"]["pages_seen"] == 1
    assert report["scope"]["forms_seen"] == 1
    assert report["scope"]["fields_seen"] == 2
    assert report["scope"]["settings_extracted"] == 1
    assert report["evidence_coverage"]["dynamic_flows_opened_and_canceled"] == 1
    assert report["tool_coverage"]["source_type_counts"]["ui_flow"] == 1
    assert report["dynamic_probing"]["unprobed_actions"] == []
    assert report["documentation_gap_check"]["unmapped_terms"][0]["canonical_name"] == "schedule"
    assert report["confidence"]["components"]["restore_or_write_tool_coverage"] == 1.0
    assert report["confidence"]["band"] in {"medium", "low"}


def test_config_coverage_flags_unprobed_actions_and_missing_restore_tools():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/settings")],
        forms=[Form(id="form", page_id="page", label="Settings", field_ids=["ssid", "add"])],
        elements=[
            UiElement(id="ssid", page_id="page", selector_fingerprint="ssid", label="SSID", control_type="text", evidence_ids=["ev_ssid"]),
            UiElement(id="add", page_id="page", selector_fingerprint="add", label="Add", control_type="button", evidence_ids=["ev_add"]),
        ],
        evidence=[Evidence(id="ev_ssid", kind="ui", source="ui", summary="SSID label")],
    )

    report = build_config_coverage_report("profile", "demo", snapshot, tools=[])

    assert report["confidence"]["band"] == "low"
    assert report["tool_coverage"]["forms_without_restore_or_write_tools"] == ["form"]
    assert report["dynamic_probing"]["unprobed_actions"][0]["label"] == "Add"
    assert {gap["kind"] for gap in report["gaps"]} >= {
        "missing_current_values",
        "missing_restore_or_write_tools",
        "unprobed_dynamic_actions",
    }


def test_config_coverage_counts_canonical_tools_with_submit_form_bindings():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/settings")],
        forms=[Form(id="form", page_id="page", label="WAN", field_ids=["connection"])],
        elements=[
            UiElement(
                id="connection",
                page_id="page",
                selector_fingerprint="connection",
                label="Connection Name",
                control_type="text",
                evidence_ids=["ev_connection"],
            )
        ],
        evidence=[Evidence(id="ev_connection", kind="ui", source="ui", summary="Connection Name label")],
    )
    tools = [
        {
            "name": "internet_wan_update",
            "description": "Configure WAN.",
            "args": {},
            "return_schema": {},
            "risk_level": "medium",
            "evidence_ids": ["ev_connection"],
            "source_type": "canonical_concept",
            "confidence": 0.85,
        }
    ]
    bindings = {
        "bindings": [
            {
                "tool_name": "internet_wan_update",
                "selector_action_bindings": {
                    "action": "submit_form",
                    "form_id": "form",
                    "fields": [{"ui_element_id": "connection", "arg": "connection_name", "label": "Connection Name"}],
                },
            }
        ]
    }

    report = build_config_coverage_report("profile", "demo", snapshot, tools=tools, bindings=bindings)

    assert report["tool_coverage"]["source_type_counts"]["canonical_concept"] == 1
    assert report["tool_coverage"]["form_action_binding_tools"] == 1
    assert report["tool_coverage"]["forms_requiring_restore_or_write_tools"] == 1
    assert report["tool_coverage"]["forms_without_restore_or_write_tools"] == []
    assert report["confidence"]["components"]["restore_or_write_tool_coverage"] == 1.0


def test_config_coverage_ignores_internal_form_sentinel_fields():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/status")],
        forms=[Form(id="form", page_id="page", label="Status", field_ids=["sentinel"])],
        elements=[
            UiElement(
                id="sentinel",
                page_id="page",
                selector_fingerprint="sentinel",
                label="_stopFormAutoSubmit",
                control_type="text",
                context={"read_value": ""},
                evidence_ids=["ev_sentinel"],
            )
        ],
        evidence=[Evidence(id="ev_sentinel", kind="ui", source="ui", summary="Internal form sentinel")],
    )

    report = build_config_coverage_report("profile", "demo", snapshot, tools=[])

    assert report["scope"]["fields_seen"] == 0
    assert report["tool_coverage"]["forms_requiring_restore_or_write_tools"] == 0
    assert report["tool_coverage"]["forms_without_restore_or_write_tools"] == []
    assert not any(gap["kind"] == "missing_restore_or_write_tools" for gap in report["gaps"])


def test_config_coverage_ignores_empty_binary_text_shadow_fields():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/status")],
        forms=[Form(id="form", page_id="page", label="Status", field_ids=["off_shadow"])],
        elements=[
            UiElement(
                id="off_shadow",
                page_id="page",
                selector_fingerprint="off-shadow",
                label="Off",
                control_type="text",
                context={"read_value": ""},
                evidence_ids=["ev_off"],
            )
        ],
        evidence=[Evidence(id="ev_off", kind="ui", source="ui", summary="Empty text shadow for an Off control")],
    )

    report = build_config_coverage_report("profile", "demo", snapshot, tools=[])

    assert report["scope"]["fields_seen"] == 0
    assert report["tool_coverage"]["forms_requiring_restore_or_write_tools"] == 0


def test_config_coverage_convergence_uses_previous_snapshot():
    previous = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="old",
        pages=[Page(id="page", url="https://example.com/settings")],
        forms=[Form(id="form", page_id="page", label="Settings", field_ids=["ssid"])],
        elements=[UiElement(id="ssid", page_id="page", selector_fingerprint="ssid", label="SSID", control_type="text")],
    )
    current = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="new",
        pages=[Page(id="page", url="https://example.com/settings")],
        forms=[Form(id="form", page_id="page", label="Settings", field_ids=["ssid"])],
        elements=[UiElement(id="ssid", page_id="page", selector_fingerprint="ssid", label="SSID", control_type="text")],
    )

    report = build_config_coverage_report("profile", "demo", current, previous_snapshot=previous)

    assert report["convergence"]["status"] == "converged"
    assert report["convergence"]["new_pages"] == 0
    assert report["confidence"]["components"]["convergence"] == 1.0


def test_cli_config_coverage_writes_report(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Settings</h1><form><input aria-label='SSID'></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    settings_snapshot = Path("settings.json")
    write_json(settings_snapshot, {"source_run_id": "manual", "settings": [{"path": "wifi.ssid", "value": "demo"}]})

    assert main(["config", "coverage", "--profile", "demo", "--settings-snapshot", str(settings_snapshot), "--no-schema"]) == 0

    output = capsys.readouterr().out
    assert "Saved configuration coverage report" in output
    assert "Confidence:" in output
    reports = list(Path("output/demo/reports").glob("config-coverage-*.json"))
    assert reports
    report = read_json(reports[0])
    assert report["scope"]["settings_extracted"] == 1


def test_cli_config_save_diff_and_restore_plan(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Settings</h1><p>Mode: auto</p><p>Revision: 1</p>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "demo"]) == 0
    assert main(["mcp", "build", "--profile", "demo"]) == 0
    repo = tmp_path / "settings-repo"

    assert main(["config", "save", "--profile", "demo", "--repo", str(repo), "--commit", "--tag", "v1"]) == 0
    saved = read_json(repo / "snapshots/latest.json")
    assert saved["settings"]
    saved["settings"][0]["value"] = "manual"
    saved["settings"][0]["restore_tool"] = "update_mode"
    write_json(repo / "snapshots/latest.json", saved)

    tools_path = Path("output/demo/mcp/tools.json")
    tools = read_json(tools_path)
    tools["tools"].append(
        {
            "name": "update_mode",
            "description": "Update mode.",
            "args": {},
            "return_schema": {},
            "risk_level": "medium",
            "evidence_ids": saved["settings"][0]["evidence_ids"],
            "source_type": "ui_form",
            "confidence": 0.85,
        }
    )
    write_json(tools_path, tools)

    assert main(["config", "diff", "--profile", "demo", "--repo", str(repo), "--ref", "v1"]) == 0
    assert main(["config", "restore-plan", "--profile", "demo", "--repo", str(repo), "--ref", "v1"]) == 0
    plans = list(Path("output/demo/restore-plans").glob("restore-v1-to-current.json"))
    assert plans
    plan = read_json(plans[0])
    assert plan["steps"]
    assert plan["steps"][0]["args"]["dry_run"] is True
    assert plan["requires_review"] is True
    assert main(["config", "restore", "--profile", "demo", "--repo", str(repo), "--ref", "v1"]) == 0
    restore_reports = list(Path("output/demo/reports").glob("restore-*.json"))
    assert restore_reports
    restore_report = read_json(restore_reports[0])
    assert restore_report["summary"]["dry_run"] == 1


def test_config_snapshot_links_settings_to_restore_tool_and_arg():
    raw_snapshot = {
        "profile_id": "profile",
        "run_id": "run",
        "elements": [
            {
                "id": "mode",
                "page_id": "page",
                "label": "Mode",
                "context": {"read_value": "auto", "page_title": "Settings"},
                "evidence_ids": ["ev_mode"],
            }
        ],
    }
    schema = {
        "mappings": [
            {
                "ui_element_id": "mode",
                "canonical_name": "mode",
                "confidence": 0.9,
                "evidence_ids": ["ev_mode"],
                "status": "ready",
            }
        ]
    }
    tools = {
        "tools": [
            {
                "name": "update_mode",
                "source_type": "ui_form",
                "risk_level": "medium",
                "evidence_ids": ["ev_mode"],
            }
        ]
    }
    bindings = {
        "bindings": [
            {
                "tool_name": "update_mode",
                "selector_action_bindings": {
                    "action": "submit_form",
                    "fields": [{"ui_element_id": "mode", "label": "Mode", "arg": "mode"}],
                },
            }
        ]
    }

    snapshot = build_config_snapshot("demo", "profile", "run", raw_snapshot, schema, bindings, tools)

    setting = snapshot["settings"][0]
    assert setting["restorable"] is True
    assert setting["restore_tool"] == "update_mode"
    assert setting["restore_arg"] == "mode"
    assert setting["restore_binding"]["confidence"] >= 0.85


def test_grouped_restore_plan_contract_and_readiness(tmp_path):
    target = config_snapshot_with_settings({"alert_email": "alerts@example.test", "retention_days": "30"}, "run2")
    current = config_snapshot_with_settings({"alert_email": "changed@example.test", "retention_days": "60"}, "run2")
    tools = [{"name": "save_settings", "risk_level": "medium", "source_type": "ui_form", "evidence_ids": ["ev_alert_email", "ev_retention_days"]}]
    plan = build_restore_plan("demo", "v1", target, current, tools)

    assert len(plan["steps"]) == 1
    step = plan["steps"][0]
    assert step["setting_ids"] == ["cfg_alert_email", "cfg_retention_days"]
    assert step["restore_args"] == {"cfg_alert_email": "alert_email", "cfg_retention_days": "retention_days"}
    assert step["args"]["alert_email"] == "alerts@example.test"
    assert step["args"]["retention_days"] == "30"

    repo = tmp_path / "settings"
    repo.mkdir()
    (repo / ".git").mkdir()
    readiness = build_restore_readiness_report(
        "demo",
        plan,
        settings_repo=None,
        current_snapshot=current,
        latest_run_id="run2",
        apply_requested=False,
    )
    assert readiness["grouped_steps"] == 1
    assert readiness["checks"]


def test_restore_readiness_fails_stale_snapshot_for_apply():
    target = config_snapshot_with_settings({"mode": "auto"}, "fresh")
    current = config_snapshot_with_settings({"mode": "manual"}, "old")
    tools = [{"name": "save_settings", "risk_level": "medium", "source_type": "ui_form", "evidence_ids": ["ev_mode"]}]
    plan = build_restore_plan("demo", "v1", target, current, tools)

    readiness = build_restore_readiness_report(
        "demo",
        plan,
        settings_repo=None,
        current_snapshot=current,
        latest_run_id="fresh",
        max_snapshot_age_minutes=30,
        apply_requested=True,
        profile_write_mode="apply",
        confirm=True,
    )

    assert not readiness["ready_for_apply"]
    assert any(check["name"] == "fresh_current_snapshot" and not check["passed"] for check in readiness["checks"])


def test_restore_execution_records_recovery_when_step_fails(tmp_path):
    package_dir = tmp_path / "mcp"
    write_json(package_dir / "tools.json", {"tools": []})
    write_json(package_dir / "adapter.bindings.json", {"bindings": []})
    plan = {
        "id": "restore_demo",
        "target_ref": "v1",
        "rollback_snapshot_id": "cfgsnap_before",
        "non_restorable": [],
        "steps": [
            {"setting_id": "cfg_mode", "setting_ids": ["cfg_mode"], "tool_name": "missing_tool", "args": {"mode": "auto"}, "risk_level": "medium"},
            {"setting_id": "cfg_other", "setting_ids": ["cfg_other"], "tool_name": "missing_tool_2", "args": {"other": "x"}, "risk_level": "medium"},
        ],
    }

    report = execute_restore_plan(package_dir, plan)

    assert report["summary"]["failed"] == 1
    assert report["recovery"]["rollback_snapshot_id"] == "cfgsnap_before"
    assert report["recovery"]["skipped_setting_ids"] == ["cfg_other"]


def test_pure_restore_verification_detects_match_without_socket():
    target = config_snapshot_with_settings({"alert_email": "alerts@example.test", "retention_days": "30"}, "target")
    after = config_snapshot_with_settings({"alert_email": "alerts@example.test", "retention_days": "30"}, "after")

    verification = verify_restore_snapshot(target, after)

    assert verification["verified"]
    assert verification["diff_summary"]["changed"] == 0


def test_quality_check_consumes_config_coverage(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Settings</h1><form><input aria-label='SSID'><button>Add</button></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "demo"]) == 0
    assert main(["mcp", "build", "--profile", "demo", "--no-action-tools"]) == 0
    assert main(["config", "coverage", "--profile", "demo"]) == 0

    assert main(["quality", "check", "--profile", "demo", "--fail-on-error"]) == 1
    reports = list(Path("output/demo/reports").glob("quality-gates-*.json"))
    report = read_json(reports[0])
    assert any("Configuration coverage" in failure for failure in report["failures"])


def test_staged_dialog_fixture_is_flagged_when_add_flow_is_not_probed(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    repo = Path(__file__).resolve().parents[2]
    fixture = repo / "profiles" / "fixtures" / "benchmark_pack" / "staged_dialog"

    assert main(["profile", "init", "--name", "staged", "--base-url", "https://staged.example"]) == 0
    write_json(Path("profiles/staged/ontology.seed.json"), read_json(fixture / "ontology.seed.json"))
    assert main(["crawl", "run", "--profile", "staged", "--fixture-site", str(fixture / "site")]) == 0
    assert main(["schema", "review", "--profile", "staged"]) == 0
    assert main(["mcp", "build", "--profile", "staged"]) == 0
    assert main(["config", "coverage", "--profile", "staged"]) == 0

    report_path = sorted(Path("output/staged/reports").glob("config-coverage-*.json"))[-1]
    report = read_json(report_path)
    assert any(action["label"] == "Add Rule" for action in report["dynamic_probing"]["unprobed_actions"])
    assert any(gap["kind"] == "unprobed_dynamic_actions" for gap in report["gaps"])
