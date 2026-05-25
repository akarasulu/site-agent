from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

from site_agent.core.actions import build_action_report
from site_agent.core.ai.analyze import build_ai_analysis_report
from site_agent.core.ai.backends import get_ai_backend
from site_agent.core.ai.research import discover_docs
from site_agent.core.align.lexical import align_snapshot
from site_agent.core.config_coverage import build_config_coverage_report, load_settings_snapshot
from site_agent.core.config_versioning import (
    build_config_snapshot,
    build_restore_plan,
    build_restore_readiness_report,
    commit_and_tag,
    diff_config_snapshots,
    execute_restore_plan,
    git,
    init_settings_repo,
    load_snapshot_at_ref,
    verify_restore_snapshot,
    write_config_snapshot,
)
from site_agent.core.crawl.playwright import CrawlError, crawl_fixture_site, crawl_html_fixture, crawl_profile
from site_agent.core.debug import build_debug_report
from site_agent.core.drift.check import compare_snapshots
from site_agent.core.ingest.docs import build_ontology_artifact
from site_agent.core.merge import merge_snapshots, write_merged_snapshot
from site_agent.core.models import CrawlSnapshot, Evidence, Form, InteractionFlow, Page, Transition, UiElement
from site_agent.core.package import build_profile_package
from site_agent.core.plan import build_crawl_plan, latest_crawl_plan, write_crawl_plan
from site_agent.core.profiles import configure_auth, import_example_profile, init_profile, load_profile, output_root
from site_agent.core.quality import compare_coverage, contract_quality_report, quality_gate_report, update_crawl_memory
from site_agent.core.redact import redact_schema, redact_snapshot
from site_agent.core.review import ReviewError, apply_review, latest_schema, review_queue, write_reviewed_schema
from site_agent.core.storage import latest_json, read_json, write_json
from site_agent.core.synthesize.contracts import contract_from_tools, diff_contracts, write_contract
from site_agent.core.synthesize.mcp import synthesize_form_tools, synthesize_tools, synthesize_unmapped_page_tools, write_mcp_package
from site_agent.core.synthesize.runtime import RuntimeErrorForTool, call_tool, serve_json_lines


def workspace() -> Path:
    return Path.cwd()


def snapshot_from_json(raw: dict) -> CrawlSnapshot:
    return CrawlSnapshot(
        timestamp=raw["timestamp"],
        profile_id=raw["profile_id"],
        run_id=raw["run_id"],
        pages=[Page(**item) for item in raw.get("pages", [])],
        forms=[Form(**item) for item in raw.get("forms", [])],
        elements=[UiElement(**item) for item in raw.get("elements", [])],
        transitions=[Transition(**item) for item in raw.get("transitions", [])],
        interaction_flows=[InteractionFlow(**item) for item in raw.get("interaction_flows", [])],
        evidence=[Evidence(**item) for item in raw.get("evidence", [])],
    )


def load_latest_snapshot(profile_name: str) -> CrawlSnapshot:
    path = latest_json(output_root(workspace(), profile_name) / "crawl", "snapshot-*.json")
    return snapshot_from_json(read_json(path))


def load_snapshot_path(path: Path) -> CrawlSnapshot:
    return snapshot_from_json(read_json(path))


def latest_tools(profile_name: str) -> list[dict]:
    path = output_root(workspace(), profile_name) / "mcp" / "tools.json"
    return read_json(path).get("tools", []) if path.exists() else []


def latest_merge_report(profile_name: str) -> dict | None:
    report_dir = output_root(workspace(), profile_name) / "reports"
    reports = sorted(report_dir.glob("merge-*.json"), key=lambda p: p.stat().st_mtime)
    return read_json(reports[-1]) if reports else None


def crawl_memory(profile_name: str) -> dict | None:
    path = output_root(workspace(), profile_name) / "reports" / "crawl-memory.json"
    return read_json(path) if path.exists() else None


def previous_snapshot_total(profile_name: str) -> int | None:
    crawl_dir = output_root(workspace(), profile_name) / "crawl"
    snapshots = sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for path in snapshots:
        try:
            raw = read_json(path)
        except Exception:
            continue
        pages = len(raw.get("pages", []))
        if pages:
            return pages
    return None


def crawl_progress_printer(total_hint: int | None = None):
    started = __import__("time").monotonic()
    last_key = None

    def progress(event: dict) -> None:
        nonlocal last_key
        total = event.get("total") or total_hint
        scanned = int(event.get("scanned") or 0)
        key = (event.get("phase"), scanned, event.get("pages"), event.get("forms"), event.get("elements"))
        if key == last_key:
            return
        last_key = key
        elapsed = int(__import__("time").monotonic() - started)
        if total:
            pct = min(100, int(scanned * 100 / max(int(total), 1)))
            prefix = f"Crawl progress: {pct:3d}% scanned {scanned}/{total}"
        else:
            prefix = f"Crawl progress: scanned {scanned}, total unknown"
        current = str(event.get("current") or "")
        if len(current) > 90:
            current = current[:87] + "..."
        print(
            f"{prefix}; pages={event.get('pages', 0)} forms={event.get('forms', 0)} "
            f"elements={event.get('elements', 0)} flows={event.get('interaction_flows', 0)} "
            f"elapsed={elapsed}s current={current}",
            flush=True,
        )

    return progress


def snapshot_path_for_run(profile_name: str, run_id: str) -> Path | None:
    crawl_dir = output_root(workspace(), profile_name) / "crawl"
    for path in sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        if read_json(path).get("run_id") == run_id:
            return path
    return None


def schema_for_run(profile_name: str, run_id: str):
    schema_dir = output_root(workspace(), profile_name) / "schema"
    for path in sorted(schema_dir.glob("mapped-schema-*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        raw = read_json(path)
        if raw.get("run_id") == run_id:
            return schema_from_json(raw)
    return None


def cmd_profile_init(args: argparse.Namespace) -> int:
    profile = init_profile(workspace(), args.name, args.base_url)
    print(f"Created profile '{profile.name}' for {profile.base_url}")
    print(f"Host allowlist: {', '.join(profile.host_allowlist)}")
    print(f"Next: site-agent auth setup --profile {profile.name}")
    return 0


def cmd_profile_import_example(args: argparse.Namespace) -> int:
    source = Path(args.source)
    if not source.is_absolute():
        source = workspace() / source
    profile = import_example_profile(workspace(), source, args.name)
    print(f"Imported example profile '{profile.name}' from {source}")
    print(f"Host allowlist: {', '.join(profile.host_allowlist)}")
    print(f"Next: site-agent auth setup --profile {profile.name}")
    return 0


def cmd_auth_setup(args: argparse.Namespace) -> int:
    profile = configure_auth(workspace(), args.profile, args.username_env, args.password_env)
    print(f"Configured auth strategy '{profile.auth.strategy}' for profile '{profile.name}'.")
    print("No secret values were stored; only environment variable references and auth state paths are kept.")
    print(f"Next: site-agent crawl run --profile {profile.name}")
    return 0


def cmd_crawl_run(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    crawl_plan = None
    planned_labels: list[str] = []
    deprioritized_labels: list[str] = []
    progress_total = previous_snapshot_total(profile.name)
    if getattr(args, "use_plan", None):
        crawl_plan = latest_crawl_plan(workspace(), profile.name) if args.use_plan == "latest" else read_json(Path(args.use_plan))
        observed_plan_labels = [
            item["label"]
            for item in crawl_plan.get("prioritized_labels", [])
            if item.get("label") and "observed_ui" in item.get("sources", [])
        ]
        generated_plan_labels = [
            item["label"]
            for item in crawl_plan.get("prioritized_labels", [])
            if item.get("label") and "observed_ui" not in item.get("sources", [])
        ]
        max_planned = args.max_planned_labels if args.max_planned_labels is not None else len(observed_plan_labels) + 15
        planned_labels = [*observed_plan_labels, *generated_plan_labels[:15]][:max_planned]
        deprioritized_labels = [str(label) for label in crawl_plan.get("deprioritized_labels", [])]
        progress_total = progress_total or len(planned_labels) or None
        print(f"Loaded crawl plan {crawl_plan.get('plan_id', args.use_plan)} with {len(planned_labels)} prioritized label(s).")
    if args.probe_budget_seconds is not None:
        profile.crawl.max_crawl_seconds = args.probe_budget_seconds
    if args.target_depth is not None:
        profile.crawl.max_js_depth = args.target_depth
    if args.fixture_site:
        snapshot = crawl_fixture_site(profile, Path(args.fixture_site), args.start_path, crawl_progress_printer(progress_total), progress_total)
    elif args.fixture_html:
        html = Path(args.fixture_html).read_text(encoding="utf-8")
        snapshot = crawl_html_fixture(profile, html, args.url)
    else:
        ai_backend = get_ai_backend()
        if args.research_product_hint:
            markdown_path, _ = discover_docs(workspace(), profile, ai_backend, args.research_product_hint, args.max_research_sources)
            print(f"Pre-crawl AI documentation evidence saved: {markdown_path}")
        ontology, doc_evidence = build_ontology_artifact(workspace(), profile, ai_backend)
        print(f"Pre-crawl ontology ready: {len(ontology)} term(s), {len(doc_evidence)} documentation evidence item(s).")
        if progress_total:
            print(f"Crawl progress estimate: using previous/plan total of {progress_total} state(s).")
        else:
            print("Crawl progress estimate: first pass has unknown total; showing discovered counts.")
        snapshot = crawl_profile(
            workspace(),
            profile,
            args.url,
            ontology,
            ai_backend,
            planned_labels,
            deprioritized_labels,
            crawl_progress_printer(progress_total),
            progress_total,
        )
    snapshot = redact_snapshot(snapshot, profile.crawl.redaction_patterns)
    path = output_root(workspace(), profile.name) / "crawl" / f"snapshot-{snapshot.run_id}.json"
    write_json(path, snapshot)
    print(f"Saved crawl snapshot: {path}")
    print(f"Found {len(snapshot.pages)} page(s), {len(snapshot.forms)} form(s), {len(snapshot.elements)} UI element(s), {len(snapshot.transitions)} transition(s).")
    print(f"Next: site-agent schema review --profile {profile.name}")
    return 0


def cmd_crawl_plan(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    plan = build_crawl_plan(profile, snapshot, schema, get_ai_backend(), args.max_terms, crawl_memory(profile.name))
    path = write_crawl_plan(workspace(), profile, plan)
    print(f"Saved crawl plan: {path}")
    print(
        "Plan: "
        f"{plan['summary']['missing_terms']} missing term(s), "
        f"{plan['summary']['prioritized_labels']} prioritized label(s), "
        f"{plan['summary']['noise_labels']} deprioritized label(s)."
    )
    if plan["prioritized_labels"]:
        print("Top planned labels:")
        for item in plan["prioritized_labels"][: args.limit]:
            concepts = ", ".join(item.get("concepts", [])[:3])
            print(f"- {item['label']} ({item['score']:.2f}) {concepts}")
    print(f"Next: site-agent crawl run --profile {profile.name} --use-plan latest")
    return 0


def cmd_crawl_compare(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    crawl_dir = output_root(workspace(), profile.name) / "crawl"
    if args.previous and args.current:
        previous = load_snapshot_path(Path(args.previous))
        current = load_snapshot_path(Path(args.current))
    else:
        merge_reports = sorted((output_root(workspace(), profile.name) / "reports").glob("merge-*.json"), key=lambda p: p.stat().st_mtime)
        if merge_reports:
            merge_report = read_json(merge_reports[-1])
            previous_path = snapshot_path_for_run(profile.name, merge_report["base_run_id"])
            current_path = snapshot_path_for_run(profile.name, merge_report["merged_run_id"])
            if not previous_path or not current_path:
                raise FileNotFoundError("Could not locate snapshots referenced by latest merge report.")
            previous = load_snapshot_path(previous_path)
            current = load_snapshot_path(current_path)
        else:
            snapshots = sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime)
            if len(snapshots) < 2:
                raise FileNotFoundError(f"Need at least two crawl snapshots in {crawl_dir}.")
            previous = load_snapshot_path(snapshots[-2])
            current = load_snapshot_path(snapshots[-1])
    previous_schema = schema_for_run(profile.name, previous.run_id)
    current_schema = schema_for_run(profile.name, current.run_id)
    comparison = compare_coverage(profile, previous, current, previous_schema, current_schema, None, latest_tools(profile.name))
    path = output_root(workspace(), profile.name) / "reports" / f"coverage-compare-{previous.run_id}-to-{current.run_id}.json"
    write_json(path, comparison)
    memory_path = update_crawl_memory(workspace(), profile, comparison, latest_merge_report(profile.name))
    print(f"Saved coverage comparison: {path}")
    print(f"Updated crawl memory: {memory_path}")
    summary = comparison["summary"]
    print(
        "Delta: "
        f"{summary['new_states']} new state(s), "
        f"{summary['new_forms']} new form(s), "
        f"{summary['new_ui_elements']} new UI element(s), "
        f"{summary['new_mapped_terms']} new mapped term(s), "
        f"{summary['widget_state_growth']} widget-state growth."
    )
    print(f"Next: site-agent quality check --profile {profile.name}")
    return 0


def cmd_crawl_merge(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    crawl_dir = output_root(workspace(), profile.name) / "crawl"
    if args.base and args.probe:
        base = load_snapshot_path(Path(args.base))
        probe = load_snapshot_path(Path(args.probe))
    else:
        snapshots = sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime)
        non_merged = [path for path in snapshots if "snapshot-merged-" not in path.name]
        if len(non_merged) < 2:
            raise FileNotFoundError(f"Need at least two non-merged crawl snapshots in {crawl_dir}.")
        base = load_snapshot_path(non_merged[-2])
        probe = load_snapshot_path(non_merged[-1])
    merged, report = merge_snapshots(profile, base, probe)
    snapshot_path, report_path = write_merged_snapshot(workspace(), profile, merged, report)
    print(f"Saved merged snapshot: {snapshot_path}")
    print(f"Saved merge report: {report_path}")
    summary = report["summary"]
    print(
        "Merged: "
        f"{summary['merged_pages']} state(s), {summary['merged_forms']} form(s), "
        f"{summary['merged_elements']} UI element(s), added "
        f"{summary['added_pages']} state(s), {summary['added_forms']} form(s), {summary['added_elements']} UI element(s)."
    )
    print(f"Next: site-agent schema review --profile {profile.name}")
    return 0


def cmd_schema_review(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_snapshot_path(Path(args.snapshot)) if getattr(args, "snapshot", None) else load_latest_snapshot(profile.name)
    ai_backend = get_ai_backend()
    ontology, doc_evidence = build_ontology_artifact(workspace(), profile, ai_backend)
    schema = align_snapshot(profile.id, snapshot, ontology, doc_evidence, ai_backend)
    schema = redact_schema(schema, profile.crawl.redaction_patterns)
    path = output_root(workspace(), profile.name) / "schema" / f"mapped-schema-{schema.run_id}.json"
    write_json(path, schema)
    ready = sum(1 for mapping in schema.mappings if mapping.status == "ready")
    review = sum(1 for mapping in schema.mappings if mapping.status == "review")
    internal = sum(1 for mapping in schema.mappings if mapping.status == "internal")
    print(f"Saved mapped schema: {path}")
    print(f"Mappings: {ready} ready, {review} queued for review, {internal} internal only.")
    if review:
        print("Review queue:")
        for mapping in schema.mappings:
            if mapping.status == "review":
                print(f"- {mapping.canonical_name} ({mapping.confidence:.2f}) evidence={','.join(mapping.evidence_ids)}")
    print(f"Next: site-agent mcp build --profile {profile.name}")
    return 0


def cmd_schema_queue(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    queue = review_queue(schema)
    if not queue:
        print("Review queue is empty.")
    for mapping in queue:
        print(f"{mapping.ui_element_id}\t{mapping.canonical_name}\t{mapping.confidence:.2f}\t{','.join(mapping.evidence_ids)}")
    print(f"Next: site-agent schema approve --profile {profile.name} --ui-element-id <id>")
    return 0


def cmd_schema_decide(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    schema_dir = output_root(workspace(), profile.name) / "schema"
    _, schema = latest_schema(schema_dir)
    updated = apply_review(
        schema,
        ui_element_id=args.ui_element_id,
        decision=args.schema_command,
        canonical_name=getattr(args, "canonical_name", None),
        confidence=getattr(args, "confidence", None),
        note=getattr(args, "note", None),
    )
    path = write_reviewed_schema(schema_dir, updated)
    print(f"Saved reviewed schema: {path}")
    print(f"Next: site-agent mcp build --profile {profile.name}")
    return 0


def cmd_mcp_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    snapshot = load_latest_snapshot(profile.name)
    selector_lookup = {element.id: element.selector_fingerprint for element in snapshot.elements}
    value_lookup = {element.id: str(element.context["read_value"]) for element in snapshot.elements if "read_value" in element.context}
    ai_backend = get_ai_backend()
    description_lookup = {
        mapping.ui_element_id: description
        for mapping in schema.mappings
        if mapping.status != "internal"
        for description in [ai_backend.describe_tool(mapping, schema.evidence)]
        if description
    }
    tools, bindings = synthesize_tools(profile.id, schema, selector_lookup, value_lookup, description_lookup)
    covered_read_element_ids = {mapping.ui_element_id for mapping in schema.mappings if mapping.status == "ready"}
    seen_tool_names = {tool.name for tool in tools}
    if not args.no_page_tools:
        page_tools, page_bindings = synthesize_unmapped_page_tools(profile.id, snapshot, covered_read_element_ids, seen_tool_names)
        tools.extend(page_tools)
        bindings.extend(page_bindings)
    if not args.no_action_tools:
        write_tools, write_bindings = synthesize_form_tools(profile.id, snapshot, seen_tool_names)
        tools.extend(write_tools)
        bindings.extend(write_bindings)
    write_mcp_package(workspace(), profile.name, tools, bindings, profile.base_url if args.include_writes else None)
    write_contract(output_root(workspace(), profile.name) / "mcp")
    contract_report = contract_quality_report(profile, tools)
    contract_report_path = output_root(workspace(), profile.name) / "reports" / f"contract-quality-{snapshot.run_id}.json"
    write_json(contract_report_path, contract_report)
    print(f"Generated MCP package: {output_root(workspace(), profile.name) / 'mcp'}")
    print(f"Exposed {len(tools)} tool(s). Selector bindings are adapter metadata, not public API.")
    print(f"Saved contract quality report: {contract_report_path}")
    if contract_report["warnings"]:
        print(f"Contract warnings: {len(contract_report['warnings'])}")
    if contract_report["failures"]:
        print(f"Contract failures: {len(contract_report['failures'])}")
    print(f"Next: site-agent mcp serve --profile {profile.name}")
    return 0


def schema_from_json(raw: dict):
    from site_agent.core.models import ConceptMapping, DomainTerm, MappedSchema

    return MappedSchema(
        profile_id=raw["profile_id"],
        run_id=raw["run_id"],
        generated_at=raw["generated_at"],
        ontology=[DomainTerm(**item) for item in raw.get("ontology", [])],
        mappings=[ConceptMapping(**item) for item in raw.get("mappings", [])],
        evidence=[Evidence(**item) for item in raw.get("evidence", [])],
    )


def cmd_mcp_serve(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    server_path = package_dir / "server.json"
    if not server_path.exists():
        raise FileNotFoundError(f"No MCP package found. Run: site-agent mcp build --profile {profile.name}")
    if args.once:
        print(f"MCP metadata ready: {server_path}")
        print(f"Next: site-agent drift check --profile {profile.name}")
    else:
        serve_json_lines(package_dir)
    return 0


def cmd_mcp_call(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    if not (package_dir / "tools.json").exists():
        raise FileNotFoundError(f"No MCP package found. Run: site-agent mcp build --profile {profile.name}")
    call_args = read_json(Path(args.args_json)) if args.args_json else {}
    print(json_dump(call_tool(package_dir, args.tool, call_args, args.mode, args.browser)))
    return 0


def cmd_mcp_diff(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    current = contract_from_tools(read_json(package_dir / "tools.json")["tools"])
    baseline = read_json(Path(args.baseline))
    report = diff_contracts(baseline, current)
    path = output_root(workspace(), profile.name) / "reports" / "contract-diff.json"
    write_json(path, report)
    print(json_dump(report))
    print(f"Saved contract diff: {path}")
    if report["breaking"] and not report.get("version_ok", False):
        print("Breaking contract changes require a major version bump.")
    return 1 if report["breaking"] and args.fail_on_breaking else 0


def cmd_mcp_refresh_adapter(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    old_tools = read_json(package_dir / "tools.json")["tools"]
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    snapshot = load_latest_snapshot(profile.name)
    selector_lookup = {element.id: element.selector_fingerprint for element in snapshot.elements}
    value_lookup = {element.id: str(element.context["read_value"]) for element in snapshot.elements if "read_value" in element.context}
    _, bindings = synthesize_tools(profile.id, schema, selector_lookup, value_lookup, {})
    seen_tool_names = {tool["name"] for tool in old_tools}
    covered_read_element_ids = {mapping.ui_element_id for mapping in schema.mappings if mapping.status == "ready"}
    _, page_bindings = synthesize_unmapped_page_tools(profile.id, snapshot, covered_read_element_ids, seen_tool_names)
    bindings.extend(page_bindings)
    if args.include_writes:
        _, write_bindings = synthesize_form_tools(profile.id, snapshot, seen_tool_names)
        bindings.extend(write_bindings)
    old_names = {tool["name"] for tool in old_tools}
    bindings = [binding for binding in bindings if binding.tool_name in old_names]
    write_json(package_dir / "adapter.bindings.json", {"bindings": bindings})
    print(f"Refreshed {len(bindings)} adapter binding(s) without changing tools.json.")
    return 0


def json_dump(data: dict) -> str:
    import json

    return json.dumps(data, indent=2, sort_keys=True)


def cmd_drift_check(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    crawl_dir = output_root(workspace(), profile.name) / "crawl"
    snapshots = sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime)
    if len(snapshots) < 2:
        report = {
            "profile_id": profile.id,
            "findings": [{"kind": "insufficient_history", "severity": "info", "summary": "Need at least two crawl snapshots to compare drift."}],
        }
        path = output_root(workspace(), profile.name) / "reports" / "drift-latest.json"
        write_json(path, report)
        print(f"Saved drift report: {path}")
        print(f"Next: re-run site-agent crawl run --profile {profile.name} after UI changes, then run drift check again.")
        return 0
    previous = snapshot_from_json(read_json(snapshots[-2]))
    current = snapshot_from_json(read_json(snapshots[-1]))
    report = compare_snapshots(profile.id, previous, current)
    path = output_root(workspace(), profile.name) / "reports" / f"drift-{report.run_id}.json"
    write_json(path, report)
    print(f"Saved drift report: {path}")
    for finding in report.findings:
        print(f"- {finding.severity}: {finding.summary}")
    print(f"Next: site-agent schema review --profile {profile.name} if drift changed semantics.")
    return 0


def cmd_ai_analyze(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    report = build_ai_analysis_report(snapshot, schema, get_ai_backend(), args.max_elements)
    path = output_root(workspace(), profile.name) / "reports" / f"ai-analysis-{schema.run_id}.json"
    write_json(path, report)
    print(f"Saved AI analysis report: {path}")
    print(
        "Findings: "
        f"{len(report['field_classifications'])} field classifications, "
        f"{len(report['action_intents'])} action intents, "
        f"{len(report['conflicts'])} conflicts, "
        f"{len(report['crawl_priorities'])} crawl priorities, "
        f"{len(report.get('interaction_flow_guidance', []))} flow guidance item(s)."
    )
    print(f"Next: site-agent mcp build --profile {profile.name}")
    return 0


def cmd_debug_report(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    schema = None
    try:
        _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    except FileNotFoundError:
        pass
    report = build_debug_report(snapshot, schema)
    path = output_root(workspace(), profile.name) / "reports" / f"debug-report-{snapshot.run_id}.json"
    write_json(path, report)
    summary = report["summary"]
    kinds = ", ".join(f"{kind}={count}" for kind, count in sorted(summary["state_kinds"].items())) or "none"
    print(f"Saved debug report: {path}")
    print(
        "Coverage: "
        f"{summary['pages']} state(s), {summary['forms']} form(s), "
        f"{summary['elements']} UI element(s), {summary['transitions']} transition(s)."
    )
    print(f"State kinds: {kinds}")
    if report["missing_ontology_terms"]:
        print("Top missing ontology terms:")
        for item in report["missing_ontology_terms"][: min(args.limit, len(report["missing_ontology_terms"]))]:
            print(f"- {item['canonical_name']} ({item['confidence']:.2f})")
    print(f"Next: site-agent schema review --profile {profile.name} or tune profile crawl policy and re-run crawl.")
    return 0


def cmd_actions_report(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    report = build_action_report(snapshot)
    path = output_root(workspace(), profile.name) / "reports" / f"action-report-{snapshot.run_id}.json"
    write_json(path, report)
    counts = report["summary"]["risk_counts"]
    print(f"Saved action report: {path}")
    print(f"Actions: {report['summary']['forms']} form action(s), low={counts['low']}, medium={counts['medium']}, high={counts['high']}.")
    print(f"Next: review medium/high actions before building MCP with --include-writes.")
    return 0


def cmd_quality_check(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    comparison = None
    comparison_files = sorted((output_root(workspace(), profile.name) / "reports").glob("coverage-compare-*.json"), key=lambda p: p.stat().st_mtime)
    if comparison_files:
        comparison = read_json(comparison_files[-1])
    config_coverage = None
    coverage_files = sorted((output_root(workspace(), profile.name) / "reports").glob("config-coverage-*.json"), key=lambda p: p.stat().st_mtime)
    if coverage_files:
        config_coverage = read_json(coverage_files[-1])
    report = quality_gate_report(profile, snapshot, schema, latest_tools(profile.name), comparison, config_coverage)
    path = output_root(workspace(), profile.name) / "reports" / f"quality-gates-{snapshot.run_id}.json"
    write_json(path, report)
    print(f"Saved quality gate report: {path}")
    print(f"Quality gates: {'passed' if report['passed'] else 'failed'}")
    for warning in report["warnings"]:
        print(f"- warning: {warning}")
    for failure in report["failures"]:
        print(f"- failure: {failure}")
    return 1 if report["failures"] and args.fail_on_error else 0


def cmd_config_save(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    root = output_root(workspace(), profile.name)
    snapshot_path = latest_json(root / "crawl", "snapshot-*.json")
    schema_path = latest_json(root / "schema", "mapped-schema-*.json")
    bindings_path = root / "mcp" / "adapter.bindings.json"
    tools_path = root / "mcp" / "tools.json"
    snapshot = read_json(snapshot_path)
    schema = read_json(schema_path)
    bindings = read_json(bindings_path) if bindings_path.exists() else {"bindings": []}
    tools = read_json(tools_path) if tools_path.exists() else {"tools": []}
    repo = Path(args.repo)
    config_snapshot = build_config_snapshot(profile.name, snapshot["profile_id"], snapshot["run_id"], snapshot, schema, bindings, tools)
    init_settings_repo(repo, profile.name)
    write_config_snapshot(repo, config_snapshot)
    committed = False
    if args.commit or args.tag:
        committed = commit_and_tag(repo, args.tag)
    print(f"Saved configuration snapshot: {repo / 'snapshots' / 'latest.json'}")
    print(f"Settings: {len(config_snapshot['settings'])}; snapshot_id={config_snapshot['id']}; committed={committed}; tag={args.tag or 'none'}")
    print(f"Next: site-agent config coverage --profile {profile.name} --settings-repo {repo}")
    return 0


def cmd_config_diff(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    repo = Path(args.repo)
    baseline = load_snapshot_at_ref(repo, args.ref)
    current = read_json(Path(args.current_snapshot)) if args.current_snapshot else load_snapshot_at_ref(repo, "current")
    report = diff_config_snapshots(profile.name, baseline, current, args.ref)
    path = output_root(workspace(), profile.name) / "reports" / f"config-diff-{args.ref.replace('/', '_')}-to-current.json"
    write_json(path, report)
    summary = report["summary"]
    print(f"Saved configuration diff: {path}")
    print(f"Diff: added={summary['added']} removed={summary['removed']} changed={summary['changed']} unchanged={summary['unchanged']}")
    print(f"Next: site-agent config restore-plan --profile {profile.name} --repo {repo} --ref {args.ref}")
    return 0


def cmd_config_restore_plan(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    repo = Path(args.repo)
    target = load_snapshot_at_ref(repo, args.ref)
    current = read_json(Path(args.current_snapshot)) if args.current_snapshot else load_snapshot_at_ref(repo, "current")
    plan = build_restore_plan(profile.name, args.ref, target, current, latest_tools(profile.name))
    path = output_root(workspace(), profile.name) / "restore-plans" / f"restore-{args.ref.replace('/', '_')}-to-current.json"
    write_json(path, plan)
    print(f"Saved restore plan: {path}")
    print(f"Steps: {len(plan['steps'])}; non-restorable={len(plan['non_restorable'])}; requires_review={plan['requires_review']}")
    print("Restore execution is not applied by this command; planned tool calls are dry-run and confirmation-gated.")
    return 0


def latest_run_id_for_profile(profile_name: str) -> str | None:
    try:
        return load_latest_snapshot(profile_name).run_id
    except FileNotFoundError:
        return None


def cmd_config_restore_readiness(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    repo = Path(args.repo) if args.repo else None
    if args.plan:
        plan = read_json(Path(args.plan))
        current = read_json(Path(args.current_snapshot)) if args.current_snapshot else (load_snapshot_at_ref(repo, "current") if repo else None)
    else:
        if not repo or not args.ref:
            raise ValueError("config restore-readiness requires --repo and --ref unless --plan is supplied.")
        target = load_snapshot_at_ref(repo, args.ref)
        current = read_json(Path(args.current_snapshot)) if args.current_snapshot else load_snapshot_at_ref(repo, "current")
        plan = build_restore_plan(profile.name, args.ref, target, current, latest_tools(profile.name))
    report = build_restore_readiness_report(
        profile.name,
        plan,
        settings_repo=repo,
        current_snapshot=current,
        latest_run_id=latest_run_id_for_profile(profile.name),
        max_snapshot_age_minutes=args.max_snapshot_age_minutes,
        apply_requested=args.apply,
        profile_write_mode=profile.risk.write_mode,
        confirm=args.confirm,
    )
    path = output_root(workspace(), profile.name) / "reports" / f"restore-readiness-{plan['id']}.json"
    write_json(path, report)
    print(f"Saved restore readiness report: {path}")
    print(f"Ready for apply: {report['ready_for_apply']}; errors={len(report['errors'])}; warnings={len(report['warnings'])}; grouped_steps={report['grouped_steps']}")
    for check in report["checks"]:
        status = "ok" if check["passed"] else check["severity"]
        print(f"- {status}: {check['name']}: {check['summary']}")
    return 1 if report["errors"] and args.fail_on_error else 0


def cmd_config_restore(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    if args.plan:
        plan = read_json(Path(args.plan))
    else:
        if not args.repo or not args.ref:
            raise ValueError("config restore requires --repo and --ref unless --plan is supplied.")
        repo = Path(args.repo)
        target = load_snapshot_at_ref(repo, args.ref)
        current = read_json(Path(args.current_snapshot)) if args.current_snapshot else load_snapshot_at_ref(repo, "current")
        plan = build_restore_plan(profile.name, args.ref, target, current, latest_tools(profile.name))
    readiness = None
    if args.mode == "apply":
        if not args.repo:
            raise ValueError("Apply restore requires --repo so guardrails can check repository state.")
        current_for_readiness = read_json(Path(args.current_snapshot)) if args.current_snapshot else load_snapshot_at_ref(Path(args.repo), "current")
        readiness = build_restore_readiness_report(
            profile.name,
            plan,
            settings_repo=Path(args.repo),
            current_snapshot=current_for_readiness,
            latest_run_id=latest_run_id_for_profile(profile.name),
            max_snapshot_age_minutes=args.max_snapshot_age_minutes,
            apply_requested=True,
            profile_write_mode=profile.risk.write_mode,
            confirm=args.confirm,
        )
        if not readiness["ready_for_apply"]:
            raise ValueError("Restore apply readiness failed. Run config restore-readiness for details.")
    report = execute_restore_plan(package_dir, plan, mode=args.mode, confirm=args.confirm)
    if readiness:
        report["readiness"] = readiness
    if args.verify_snapshot:
        target_snapshot = load_snapshot_at_ref(Path(args.repo), args.ref) if args.repo and args.ref else {}
        report["post_restore_verification"] = verify_restore_snapshot(target_snapshot, read_json(Path(args.verify_snapshot)))
    path = output_root(workspace(), profile.name) / "reports" / f"restore-{plan['id']}.json"
    write_json(path, report)
    summary = report["summary"]
    print(f"Saved restore execution report: {path}")
    print(f"Restore {args.mode}: steps={summary['steps']} dry_run={summary['dry_run']} applied={summary['applied']} failed={summary['failed']} non_restorable={summary['non_restorable']}")
    return 1 if summary["failed"] and args.fail_on_error else 0


def cmd_config_coverage(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_snapshot_path(Path(args.snapshot)) if args.snapshot else load_latest_snapshot(profile.name)
    schema = None
    if not args.no_schema:
        try:
            _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
        except FileNotFoundError:
            schema = None
    previous = load_snapshot_path(Path(args.previous_snapshot)) if args.previous_snapshot else None
    settings_snapshot = load_settings_snapshot(
        Path(args.settings_snapshot) if args.settings_snapshot else None,
        Path(args.settings_repo) if args.settings_repo else None,
    )
    report = build_config_coverage_report(
        profile.id,
        profile.name,
        snapshot,
        schema=schema,
        tools=latest_tools(profile.name),
        settings_snapshot=settings_snapshot,
        previous_snapshot=previous,
    )
    path = output_root(workspace(), profile.name) / "reports" / f"config-coverage-{snapshot.run_id}.json"
    write_json(path, report)
    confidence = report["confidence"]
    scope = report["scope"]
    print(f"Saved configuration coverage report: {path}")
    print(
        "Confidence: "
        f"{confidence['score']:.2f} ({confidence['band']}); "
        f"pages={scope['pages_seen']} forms={scope['forms_seen']} fields={scope['fields_seen']} "
        f"settings={scope['settings_extracted']} tools={report['tool_coverage']['tools']}."
    )
    if report["gaps"]:
        print("Coverage gaps:")
        for gap in report["gaps"]:
            print(f"- {gap['severity']}: {gap['summary']}")
    print("Next: address reported gaps, then re-run site-agent config coverage --profile " + profile.name)
    return 0


def cmd_benchmark_run(args: argparse.Namespace) -> int:
    fixtures_root = Path(args.fixtures_root)
    if not fixtures_root.is_absolute():
        fixtures_root = workspace() / fixtures_root
    expectations = read_json(fixtures_root / "expectations.json")
    reports = []
    for fixture in expectations["profiles"]:
        name = f"{args.name_prefix}-{fixture['name']}"
        fixture_root = fixtures_root / fixture["name"]
        profile = init_profile(workspace(), name, fixture["base_url"])
        seed_path = fixture_root / "ontology.seed.json"
        if seed_path.exists():
            write_json(Path("profiles") / name / "ontology.seed.json", read_json(seed_path))
        docs_source = fixture_root / "docs"
        docs_target = Path("profiles") / name / "docs"
        if docs_source.exists():
            shutil.copytree(docs_source, docs_target, dirs_exist_ok=True)
        snapshot = crawl_fixture_site(profile, fixture_root / "site", fixture.get("start_path", "index.html"))
        snapshot = redact_snapshot(snapshot, profile.crawl.redaction_patterns)
        crawl_path = output_root(workspace(), profile.name) / "crawl" / f"snapshot-{snapshot.run_id}.json"
        write_json(crawl_path, snapshot)
        ontology, doc_evidence = build_ontology_artifact(workspace(), profile, get_ai_backend())
        schema = align_snapshot(profile.id, snapshot, ontology, doc_evidence, get_ai_backend())
        schema_path = output_root(workspace(), profile.name) / "schema" / f"mapped-schema-{schema.run_id}.json"
        write_json(schema_path, schema)
        selector_lookup = {element.id: element.selector_fingerprint for element in snapshot.elements}
        value_lookup = {element.id: str(element.context["read_value"]) for element in snapshot.elements if "read_value" in element.context}
        tools, bindings = synthesize_tools(profile.id, schema, selector_lookup, value_lookup, {})
        seen_tool_names = {tool.name for tool in tools}
        covered_read_element_ids = {mapping.ui_element_id for mapping in schema.mappings if mapping.status == "ready"}
        page_tools, page_bindings = synthesize_unmapped_page_tools(profile.id, snapshot, covered_read_element_ids, seen_tool_names)
        form_tools, form_bindings = synthesize_form_tools(profile.id, snapshot, seen_tool_names)
        tools.extend(page_tools)
        tools.extend(form_tools)
        bindings.extend(page_bindings)
        bindings.extend(form_bindings)
        write_mcp_package(workspace(), profile.name, tools, bindings, profile.base_url)
        write_contract(output_root(workspace(), profile.name) / "mcp")
        contract_report = contract_quality_report(profile, tools)
        write_json(output_root(workspace(), profile.name) / "reports" / f"contract-quality-{snapshot.run_id}.json", contract_report)
        expected = fixture["expected"]
        metrics = {
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "tools": len(tools),
            "ready_mappings": sum(1 for mapping in schema.mappings if mapping.status == "ready"),
            "deprecated_read_prefix_tools": sum(1 for tool in tools if tool.name.startswith("read_")),
            "contract_quality_passed": contract_report["passed"],
        }
        failures = []
        for key in ("pages", "forms", "tools", "ready_mappings"):
            if metrics[key] < expected.get(f"min_{key}", 0):
                failures.append(f"{key} {metrics[key]} below expected {expected.get(f'min_{key}', 0)}")
        if metrics["deprecated_read_prefix_tools"]:
            failures.append("Generated deprecated read_* tool names.")
        if not contract_report["passed"]:
            failures.extend(contract_report["failures"])
        reports.append({"name": name, "fixture": fixture["name"], "passed": not failures, "metrics": metrics, "expected": expected, "failures": failures})
    summary = {
        "passed": all(report["passed"] for report in reports),
        "profiles": len(reports),
        "reports": reports,
    }
    report_path = workspace() / "output" / "benchmark-pack-report.json"
    write_json(report_path, summary)
    print(f"Saved benchmark report: {report_path}")
    for report in reports:
        print(f"- {report['fixture']}: {'passed' if report['passed'] else 'failed'} pages={report['metrics']['pages']} forms={report['metrics']['forms']} tools={report['metrics']['tools']}")
        for failure in report["failures"]:
            print(f"  failure: {failure}")
    print("Next: inspect output/benchmark-pack-report.json or run site-agent mcp diff against saved baselines.")
    return 0 if summary["passed"] or not args.fail_on_error else 1


def cmd_docs_discover(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    markdown_path, json_path = discover_docs(workspace(), profile, get_ai_backend(), args.product_hint, args.max_sources)
    print(f"Saved discovered documentation evidence: {markdown_path}")
    print(f"Saved structured research artifact: {json_path}")
    print(f"Next: site-agent schema review --profile {profile.name}")
    return 0


def cmd_package_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir, zip_path, manifest = build_profile_package(workspace(), profile, include_private=not args.public_only, zip_bundle=not args.no_zip)
    print(f"Built profile knowledge package: {package_dir}")
    if zip_path:
        print(f"Built zip bundle: {zip_path}")
    print(
        "Package contents: "
        f"{manifest['counts']['tools']} tool(s), "
        f"{manifest['counts']['rag_chunks']} RAG chunk(s), "
        f"{manifest['counts']['reports']} report(s)."
    )
    print("Next: import rag/chunks.jsonl into your agent retrieval system, and keep private/ artifacts out of public prompts.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="site-agent", description="Evidence-backed website interaction mapper.")
    sub = parser.add_subparsers(dest="command", required=True)

    profile = sub.add_parser("profile")
    profile_sub = profile.add_subparsers(dest="profile_command", required=True)
    init = profile_sub.add_parser("init")
    init.add_argument("--name", required=True)
    init.add_argument("--base-url", required=True)
    init.set_defaults(func=cmd_profile_init)
    import_example = profile_sub.add_parser("import-example")
    import_example.add_argument("source", help="Path to an example profile directory.")
    import_example.add_argument("--name", help="Override the imported profile name.")
    import_example.set_defaults(func=cmd_profile_import_example)

    auth = sub.add_parser("auth")
    auth_sub = auth.add_subparsers(dest="auth_command", required=True)
    setup = auth_sub.add_parser("setup")
    setup.add_argument("--profile", required=True)
    setup.add_argument("--username-env")
    setup.add_argument("--password-env")
    setup.set_defaults(func=cmd_auth_setup)

    docs = sub.add_parser("docs")
    docs_sub = docs.add_subparsers(dest="docs_command", required=True)
    discover = docs_sub.add_parser("discover")
    discover.add_argument("--profile", required=True)
    discover.add_argument("--product-hint", required=True)
    discover.add_argument("--max-sources", type=int, default=5)
    discover.set_defaults(func=cmd_docs_discover)

    crawl = sub.add_parser("crawl")
    crawl_sub = crawl.add_subparsers(dest="crawl_command", required=True)
    run = crawl_sub.add_parser("run")
    run.add_argument("--profile", required=True)
    run.add_argument("--url")
    run.add_argument("--fixture-html", help="Use a saved HTML file instead of launching Chromium; intended for fixtures and tests.")
    run.add_argument("--fixture-site", help="Crawl a local directory of linked HTML files instead of launching Chromium.")
    run.add_argument("--start-path", default="index.html", help="Start page within --fixture-site.")
    run.add_argument("--research-product-hint", help="Use AI to collect product documentation before crawling, then feed the resulting ontology into navigation planning.")
    run.add_argument("--max-research-sources", type=int, default=5)
    run.add_argument("--use-plan", help="Use a crawl plan path or 'latest' to prioritize navigation labels.")
    run.add_argument("--max-planned-labels", type=int, help="Limit labels loaded from the crawl plan for a targeted probe.")
    run.add_argument("--probe-budget-seconds", type=int, help="Override max crawl seconds for this run.")
    run.add_argument("--target-depth", type=int, help="Override JS state depth for this run.")
    run.set_defaults(func=cmd_crawl_run)
    plan = crawl_sub.add_parser("plan")
    plan.add_argument("--profile", required=True)
    plan.add_argument("--max-terms", type=int, default=20)
    plan.add_argument("--limit", type=int, default=10)
    plan.set_defaults(func=cmd_crawl_plan)
    compare = crawl_sub.add_parser("compare")
    compare.add_argument("--profile", required=True)
    compare.add_argument("--previous")
    compare.add_argument("--current")
    compare.set_defaults(func=cmd_crawl_compare)
    merge = crawl_sub.add_parser("merge")
    merge.add_argument("--profile", required=True)
    merge.add_argument("--base")
    merge.add_argument("--probe")
    merge.set_defaults(func=cmd_crawl_merge)

    schema = sub.add_parser("schema")
    schema_sub = schema.add_subparsers(dest="schema_command", required=True)
    review = schema_sub.add_parser("review")
    review.add_argument("--profile", required=True)
    review.add_argument("--snapshot", help="Optional snapshot JSON path to review instead of latest.")
    review.set_defaults(func=cmd_schema_review)
    queue = schema_sub.add_parser("queue")
    queue.add_argument("--profile", required=True)
    queue.set_defaults(func=cmd_schema_queue)
    approve = schema_sub.add_parser("approve")
    approve.add_argument("--profile", required=True)
    approve.add_argument("--ui-element-id", required=True)
    approve.add_argument("--confidence", type=float)
    approve.add_argument("--note")
    approve.set_defaults(func=cmd_schema_decide)
    reject = schema_sub.add_parser("reject")
    reject.add_argument("--profile", required=True)
    reject.add_argument("--ui-element-id", required=True)
    reject.add_argument("--confidence", type=float)
    reject.add_argument("--note")
    reject.set_defaults(func=cmd_schema_decide)
    edit = schema_sub.add_parser("edit")
    edit.add_argument("--profile", required=True)
    edit.add_argument("--ui-element-id", required=True)
    edit.add_argument("--canonical-name", required=True)
    edit.add_argument("--confidence", type=float)
    edit.add_argument("--note")
    edit.set_defaults(func=cmd_schema_decide)

    mcp = sub.add_parser("mcp")
    mcp_sub = mcp.add_subparsers(dest="mcp_command", required=True)
    build = mcp_sub.add_parser("build")
    build.add_argument("--profile", required=True)
    build.add_argument("--include-writes", action="store_true", help="Deprecated: action tools are generated by default as dry-run/review-gated candidates.")
    build.add_argument("--no-action-tools", action="store_true", help="Skip generated form/action candidate tools.")
    build.add_argument("--no-page-tools", action="store_true", help="Skip generated UI-backed page/status read tools.")
    build.set_defaults(func=cmd_mcp_build)
    serve = mcp_sub.add_parser("serve")
    serve.add_argument("--profile", required=True)
    serve.add_argument("--once", action="store_true", help="Print metadata and exit instead of serving JSON-RPC lines on stdio.")
    serve.set_defaults(func=cmd_mcp_serve)
    call = mcp_sub.add_parser("call")
    call.add_argument("--profile", required=True)
    call.add_argument("--tool", required=True)
    call.add_argument("--args-json")
    call.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    call.add_argument("--browser", action="store_true", help="Use the browser-backed runtime for staged ui_flow apply calls.")
    call.set_defaults(func=cmd_mcp_call)
    diff = mcp_sub.add_parser("diff")
    diff.add_argument("--profile", required=True)
    diff.add_argument("--baseline", required=True)
    diff.add_argument("--fail-on-breaking", action="store_true")
    diff.set_defaults(func=cmd_mcp_diff)
    refresh = mcp_sub.add_parser("refresh-adapter")
    refresh.add_argument("--profile", required=True)
    refresh.add_argument("--include-writes", action="store_true")
    refresh.set_defaults(func=cmd_mcp_refresh_adapter)

    drift = sub.add_parser("drift")
    drift_sub = drift.add_subparsers(dest="drift_command", required=True)
    check = drift_sub.add_parser("check")
    check.add_argument("--profile", required=True)
    check.set_defaults(func=cmd_drift_check)

    ai = sub.add_parser("ai")
    ai_sub = ai.add_subparsers(dest="ai_command", required=True)
    analyze = ai_sub.add_parser("analyze")
    analyze.add_argument("--profile", required=True)
    analyze.add_argument("--max-elements", type=int, default=40)
    analyze.set_defaults(func=cmd_ai_analyze)

    debug = sub.add_parser("debug")
    debug_sub = debug.add_subparsers(dest="debug_command", required=True)
    report = debug_sub.add_parser("report")
    report.add_argument("--profile", required=True)
    report.add_argument("--limit", type=int, default=10)
    report.set_defaults(func=cmd_debug_report)

    actions = sub.add_parser("actions")
    actions_sub = actions.add_subparsers(dest="actions_command", required=True)
    action_report = actions_sub.add_parser("report")
    action_report.add_argument("--profile", required=True)
    action_report.set_defaults(func=cmd_actions_report)

    quality = sub.add_parser("quality")
    quality_sub = quality.add_subparsers(dest="quality_command", required=True)
    quality_check = quality_sub.add_parser("check")
    quality_check.add_argument("--profile", required=True)
    quality_check.add_argument("--fail-on-error", action="store_true")
    quality_check.set_defaults(func=cmd_quality_check)

    config = sub.add_parser("config")
    config_sub = config.add_subparsers(dest="config_command", required=True)
    config_save = config_sub.add_parser("save")
    config_save.add_argument("--profile", required=True)
    config_save.add_argument("--repo", required=True, help="Settings git repository path.")
    config_save.add_argument("--commit", action="store_true")
    config_save.add_argument("--tag", help="Optional git tag, for example v1 or v2.")
    config_save.set_defaults(func=cmd_config_save)
    config_diff = config_sub.add_parser("diff")
    config_diff.add_argument("--profile", required=True)
    config_diff.add_argument("--repo", required=True)
    config_diff.add_argument("--ref", required=True, help="Git branch, tag, or commit to compare against current snapshots/latest.json.")
    config_diff.add_argument("--current-snapshot", help="Optional current snapshot JSON path instead of repo snapshots/latest.json.")
    config_diff.set_defaults(func=cmd_config_diff)
    restore_plan = config_sub.add_parser("restore-plan")
    restore_plan.add_argument("--profile", required=True)
    restore_plan.add_argument("--repo", required=True)
    restore_plan.add_argument("--ref", required=True, help="Git branch, tag, or commit whose settings should be restored.")
    restore_plan.add_argument("--current-snapshot", help="Optional current snapshot JSON path instead of repo snapshots/latest.json.")
    restore_plan.set_defaults(func=cmd_config_restore_plan)
    readiness = config_sub.add_parser("restore-readiness")
    readiness.add_argument("--profile", required=True)
    readiness.add_argument("--repo", help="Settings git repository path.")
    readiness.add_argument("--ref", help="Git branch, tag, or commit whose settings should be restored.")
    readiness.add_argument("--plan", help="Existing restore plan JSON path.")
    readiness.add_argument("--current-snapshot", help="Optional current snapshot JSON path instead of repo snapshots/latest.json.")
    readiness.add_argument("--max-snapshot-age-minutes", type=int, default=30)
    readiness.add_argument("--apply", action="store_true", help="Evaluate apply-mode guardrails.")
    readiness.add_argument("--confirm", action="store_true")
    readiness.add_argument("--fail-on-error", action="store_true")
    readiness.set_defaults(func=cmd_config_restore_readiness)
    restore = config_sub.add_parser("restore")
    restore.add_argument("--profile", required=True)
    restore.add_argument("--repo", help="Settings git repository path. Required unless --plan is supplied.")
    restore.add_argument("--ref", help="Git branch, tag, or commit whose settings should be restored. Required unless --plan is supplied.")
    restore.add_argument("--plan", help="Existing restore plan JSON path.")
    restore.add_argument("--current-snapshot", help="Optional current snapshot JSON path instead of repo snapshots/latest.json.")
    restore.add_argument("--mode", choices=["dry-run", "apply"], default="dry-run")
    restore.add_argument("--confirm", action="store_true", help="Required for apply mode.")
    restore.add_argument("--verify-snapshot", help="Optional post-restore config snapshot JSON to compare against target ref.")
    restore.add_argument("--max-snapshot-age-minutes", type=int, default=30)
    restore.add_argument("--fail-on-error", action="store_true")
    restore.set_defaults(func=cmd_config_restore)
    config_coverage = config_sub.add_parser("coverage")
    config_coverage.add_argument("--profile", required=True)
    config_coverage.add_argument("--snapshot", help="Optional crawl snapshot JSON path instead of latest.")
    config_coverage.add_argument("--previous-snapshot", help="Optional previous crawl snapshot JSON path for convergence scoring.")
    config_coverage.add_argument("--settings-repo", help="Repository containing snapshots/latest.json from a configuration save.")
    config_coverage.add_argument("--settings-snapshot", help="Explicit configuration snapshot JSON path.")
    config_coverage.add_argument("--no-schema", action="store_true", help="Skip mapped schema/ontology gap analysis.")
    config_coverage.set_defaults(func=cmd_config_coverage)

    benchmark = sub.add_parser("benchmark")
    benchmark_sub = benchmark.add_subparsers(dest="benchmark_command", required=True)
    benchmark_run = benchmark_sub.add_parser("run")
    benchmark_run.add_argument("--fixtures-root", default="profiles/fixtures/benchmark_pack")
    benchmark_run.add_argument("--name-prefix", default="benchmark")
    benchmark_run.add_argument("--fail-on-error", action="store_true")
    benchmark_run.set_defaults(func=cmd_benchmark_run)

    package = sub.add_parser("package")
    package_sub = package.add_subparsers(dest="package_command", required=True)
    package_build = package_sub.add_parser("build")
    package_build.add_argument("--profile", required=True)
    package_build.add_argument("--public-only", action="store_true", help="Exclude private adapter/profile artifacts from the package.")
    package_build.add_argument("--no-zip", action="store_true", help="Write only the package directory, not a zip bundle.")
    package_build.set_defaults(func=cmd_package_build)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (CrawlError, FileExistsError, FileNotFoundError, ReviewError, RuntimeError, RuntimeErrorForTool, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
