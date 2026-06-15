from __future__ import annotations

import argparse
import os
import shutil
import sys
import time
from pathlib import Path

from site_agent.core.completion import bash_script, complete, fish_script, zsh_script
from site_agent.core.actions import build_action_report
from site_agent.core.ai.analyze import build_ai_analysis_report
from site_agent.core.ai.backends import NoopAiBackend, get_ai_backend
from site_agent.core.ai.research import discover_docs, discover_ui_domain, load_research_session, write_research_session
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
from site_agent.core.crawl.crawl4ai_backend import crawl_profile_with_crawl4ai
from site_agent.core.crawl.playwright import CrawlError, crawl_collect_profile, crawl_fixture_site, crawl_html_fixture, crawl_profile, sample_landing_page_text
from site_agent.core.debug import build_debug_report
from site_agent.core.debug import state_path
from site_agent.core.doctor import doctor_checks, run_playwright_install
from site_agent.core.drift.check import compare_snapshots
from site_agent.core.evidence_cache import build_evidence_cache, diff_evidence_caches, load_evidence_cache, write_evidence_cache
from site_agent.core.explorer import write_explorer
from site_agent.core.form_classify import classify_forms
from site_agent.core.ingest.docs import build_ontology_artifact
from site_agent.core.inventory import inventory_profile
from site_agent.core.merge import merge_snapshots, write_merged_snapshot
from site_agent.core.models import CrawlSnapshot, Evidence, Form, InteractionFlow, Page, Transition, UiElement, utc_now
from site_agent.core.package import build_profile_package
from site_agent.core.plan import build_crawl_plan, latest_crawl_plan, write_crawl_plan
from site_agent.core.profiles import configure_auth, import_example_profile, init_profile, load_profile, output_root
from site_agent.core.quality import compare_coverage, contract_quality_report, quality_gate_report, update_crawl_memory
from site_agent.core.redact import redact_schema, redact_snapshot
from site_agent.core.review import ReviewError, apply_review, latest_schema, review_queue, write_reviewed_schema
from site_agent.core.storage import latest_json, read_json, write_json
from site_agent.core.synthesize.contracts import contract_from_tools, diff_contracts, write_contract
from site_agent.core.synthesize.ansible import write_ansible_collection
from site_agent.core.synthesize.api import write_api_package
from site_agent.core.synthesize.capabilities import synthesize_capabilities
from site_agent.core.synthesize.mcp import synthesize_form_tools, synthesize_tools, synthesize_unmapped_page_tools, write_mcp_package
from site_agent.core.synthesize.mcp_import import build_mcp_import_spec, install_codex_config, marked_block, render_codex_toml, render_mcp_json
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


def latest_complete_collection_snapshot(profile_name: str) -> CrawlSnapshot | None:
    snapshot_path = latest_complete_collection_snapshot_path(profile_name)
    if snapshot_path is None:
        return None
    return snapshot_from_json(read_json(snapshot_path))


def latest_complete_collection_snapshot_path(profile_name: str) -> Path | None:
    root = output_root(workspace(), profile_name)
    reports = sorted((root / "reports").glob("collection-*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
    for report_path in reports:
        try:
            report = read_json(report_path)
        except Exception:
            continue
        if not report.get("complete"):
            continue
        run_id = report.get("run_id")
        if not run_id:
            continue
        snapshot_path = root / "crawl" / f"snapshot-{run_id}.json"
        if snapshot_path.exists():
            return snapshot_path
    return None


def load_synthesis_snapshot(profile_name: str) -> CrawlSnapshot:
    crawl_dir = output_root(workspace(), profile_name) / "crawl"
    paths = sorted(crawl_dir.glob("snapshot-*.json"), key=lambda p: p.stat().st_mtime)
    latest_path = paths[-1] if paths else None
    preferred_paths = [
        path
        for path in [
            latest_json(crawl_dir, "snapshot-merged-*.json") if list(crawl_dir.glob("snapshot-merged-*.json")) else None,
            latest_complete_collection_snapshot_path(profile_name),
        ]
        if path is not None
    ]
    if preferred_paths:
        preferred = max(preferred_paths, key=lambda p: p.stat().st_mtime)
        if latest_path is None or preferred.stat().st_mtime >= latest_path.stat().st_mtime:
            return snapshot_from_json(read_json(preferred))

    snapshots: list[CrawlSnapshot] = []
    for path in paths:
        try:
            snapshots.append(snapshot_from_json(read_json(path)))
        except Exception:
            continue
    if not snapshots:
        return load_latest_snapshot(profile_name)
    if len(snapshots) == 1:
        return snapshots[0]

    pages_by_signature: dict[tuple[str, tuple[str, ...]], Page] = {}
    forms_by_id: dict[str, Form] = {}
    elements_by_id: dict[str, UiElement] = {}
    transitions_by_key: dict[tuple[str, str, str], Transition] = {}
    flows_by_id: dict[str, InteractionFlow] = {}
    evidence_by_id: dict[str, Evidence] = {}
    for snapshot in snapshots:
        for page in snapshot.pages:
            signature = (page.url, tuple(page.headings))
            existing = pages_by_signature.get(signature)
            if existing is None or (page.html_snapshot and not existing.html_snapshot):
                pages_by_signature[signature] = page
        for form in snapshot.forms:
            forms_by_id.setdefault(form.id, form)
        for element in snapshot.elements:
            elements_by_id.setdefault(element.id, element)
        for transition in snapshot.transitions:
            transitions_by_key.setdefault((transition.source_page_id, transition.target_url, transition.trigger_label), transition)
        for flow in snapshot.interaction_flows:
            flows_by_id.setdefault(flow.id, flow)
        for evidence in snapshot.evidence:
            evidence_by_id.setdefault(evidence.id, evidence)

    latest = snapshots[-1]
    return CrawlSnapshot(
        timestamp=latest.timestamp,
        profile_id=latest.profile_id,
        run_id=f"aggregate_{latest.run_id}",
        pages=list(pages_by_signature.values()),
        forms=list(forms_by_id.values()),
        elements=list(elements_by_id.values()),
        transitions=list(transitions_by_key.values()),
        interaction_flows=list(flows_by_id.values()),
        evidence=list(evidence_by_id.values()),
    )


def load_snapshot_path(path: Path) -> CrawlSnapshot:
    return snapshot_from_json(read_json(path))


def evidence_cache_path(profile_name: str, run_id: str) -> Path:
    return output_root(workspace(), profile_name) / "reports" / f"evidence-cache-{run_id}.json"


def load_or_build_evidence_cache(profile_name: str, snapshot: CrawlSnapshot) -> dict:
    path = evidence_cache_path(profile_name, snapshot.run_id)
    if path.exists():
        return load_evidence_cache(path)
    cache = build_evidence_cache(snapshot)
    write_evidence_cache(workspace(), profile_name, cache)
    return read_json(path)


def previous_evidence_cache(profile_name: str, current_run_id: str) -> dict | None:
    reports_dir = output_root(workspace(), profile_name) / "reports"
    caches = sorted(reports_dir.glob("evidence-cache-*.json"), key=lambda path: path.stat().st_mtime)
    previous = [
        path
        for path in caches
        if path.name != f"evidence-cache-{current_run_id}.json"
    ]
    if not previous:
        return None
    return load_evidence_cache(previous[-1])


def cache_and_recent_diff(profile_name: str, snapshot: CrawlSnapshot) -> tuple[dict, dict | None]:
    current_cache = load_or_build_evidence_cache(profile_name, snapshot)
    previous_cache = previous_evidence_cache(profile_name, snapshot.run_id)
    if previous_cache is None:
        return current_cache, None
    return current_cache, diff_evidence_caches(previous_cache, current_cache)


def latest_tools(profile_name: str) -> list[dict]:
    path = output_root(workspace(), profile_name) / "mcp" / "tools.json"
    return read_json(path).get("tools", []) if path.exists() else []


def latest_bindings(profile_name: str) -> dict:
    path = output_root(workspace(), profile_name) / "mcp" / "adapter.bindings.json"
    return read_json(path) if path.exists() else {"bindings": []}


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
    if args.backend:
        profile.crawl.browser_backend = args.backend
    crawl_plan = None
    planned_labels: list[str] = []
    planned_paths: list[list[str]] = []
    deprioritized_labels: list[str] = []
    progress_total = previous_snapshot_total(profile.name)
    if getattr(args, "use_plan", None):
        crawl_plan = latest_crawl_plan(workspace(), profile.name) if args.use_plan == "latest" else read_json(Path(args.use_plan))
        planned_labels, planned_paths, deprioritized_labels = planned_crawl_inputs(crawl_plan, args.max_planned_labels)
        progress_total = progress_total or len(planned_paths) or len(planned_labels) or None
        print(
            f"Loaded crawl plan {crawl_plan.get('plan_id', args.use_plan)} with "
            f"{len(planned_labels)} prioritized label(s), "
            f"{len(crawl_plan.get('coverage_preservation_labels', []))} coverage preservation label(s), "
            f"and {len(planned_paths)} directed path(s)."
        )
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
        allow_no_ai = os.environ.get("SITE_AGENT_ALLOW_NO_AI", "").strip().lower() in {"1", "true", "yes", "on"}
        if type(ai_backend) is NoopAiBackend and not allow_no_ai:
            raise RuntimeError(
                "Live crawl requires an active AI backend for autonomous UI domain discovery. "
                "Set SITE_AGENT_AI_PROVIDER=openai with OPENAI_API_KEY, or set SITE_AGENT_ALLOW_NO_AI=1 for an explicit offline/debug crawl."
            )
        if type(ai_backend) is not NoopAiBackend:
            research_session = load_research_session(workspace(), profile)
            reuse_research = bool(getattr(args, "use_plan", None)) and bool(research_session.get("terms")) and not getattr(args, "refresh_ai_domain", False)
            if reuse_research:
                print(
                    "Pre-crawl AI UI domain discovery skipped: reusing existing research session "
                    f"with {len(research_session.get('terms', []))} term(s)."
                )
            else:
                ui_text = sample_landing_page_text(workspace(), profile, args.url)
                markdown_path, _ = discover_ui_domain(workspace(), profile, ai_backend, ui_text, args.max_research_sources)
                print(f"Pre-crawl AI UI domain evidence saved: {markdown_path}")
        if args.research_product_hint:
            markdown_path, _ = discover_docs(workspace(), profile, ai_backend, args.research_product_hint, args.max_research_sources)
            print(f"Pre-crawl AI documentation evidence saved: {markdown_path}")
        ontology, doc_evidence = build_ontology_artifact(workspace(), profile, ai_backend)
        print(f"Pre-crawl ontology ready: {len(ontology)} term(s), {len(doc_evidence)} documentation evidence item(s).")
        inventory_deadline = None
        if profile.crawl.max_crawl_seconds > 0:
            inventory_deadline = time.monotonic() + min(120, max(20, profile.crawl.max_crawl_seconds // 3))
        site_inventory = inventory_profile(
            workspace(),
            profile,
            ontology,
            max_nodes=profile.crawl.max_js_states,
            max_depth=profile.crawl.max_js_depth,
            deadline=inventory_deadline,
        )
        inventory_path = output_root(workspace(), profile.name) / "reports" / f"site-tree-{utc_now().replace(':', '').replace('+', '_')}.json"
        write_json(inventory_path, site_inventory)
        inventory_paths = [node["path"] for node in site_inventory.get("nodes", []) if node.get("path")]
        existing_path_keys = {tuple(normalize_label(label) for label in path) for path in planned_paths}
        for path in inventory_paths:
            key = tuple(normalize_label(label) for label in path)
            if key not in existing_path_keys:
                planned_paths.append(path)
                existing_path_keys.add(key)
        planned_paths = dedupe_planned_paths(planned_paths)
        print(
            f"Mandatory site inventory saved: {inventory_path} "
            f"({site_inventory.get('node_count', 0)} node(s), complete={site_inventory.get('coverage', {}).get('complete', False)})."
        )
        if progress_total:
            print(f"Crawl progress estimate: using previous/plan total of {progress_total} state(s).")
        else:
            print("Crawl progress estimate: first pass has unknown total; showing discovered counts.")
        if profile.crawl.browser_backend == "crawl4ai":
            snapshot = crawl_profile_with_crawl4ai(
                workspace(),
                profile,
                args.url,
                crawl_progress_printer(progress_total),
                progress_total,
            )
        elif profile.crawl.browser_backend == "playwright":
            snapshot = crawl_profile(
                workspace(),
                profile,
                args.url,
                ontology,
                ai_backend,
                planned_labels,
                planned_paths,
                deprioritized_labels,
                crawl_progress_printer(progress_total),
                progress_total,
            )
        else:
            raise ValueError("crawl backend must be one of: playwright, crawl4ai")
    snapshot = redact_snapshot(snapshot, profile.crawl.redaction_patterns)
    path = output_root(workspace(), profile.name) / "crawl" / f"snapshot-{snapshot.run_id}.json"
    write_json(path, snapshot)
    cache_path = write_evidence_cache(workspace(), profile.name, build_evidence_cache(snapshot))
    if crawl_plan:
        research_session = load_research_session(workspace(), profile)
        outcomes = directional_target_outcomes(crawl_plan, snapshot)
        research_session["directional_outcomes"] = outcomes
        research_session.setdefault("passes", []).append(
            {
                "kind": "directional_crawl_execution",
                "source_plan_id": crawl_plan.get("plan_id"),
                "run_id": snapshot.run_id,
                "targets": len(outcomes),
                "reached": sum(1 for item in outcomes if item["status"] == "reached"),
                "partial": sum(1 for item in outcomes if item["status"] == "partial"),
                "failed": sum(1 for item in outcomes if item["status"] == "failed"),
            }
        )
        session_path = write_research_session(workspace(), profile, research_session)
        print(f"Updated research session with directional crawl outcomes: {session_path}")
    print(f"Saved crawl snapshot: {path}")
    print(f"Saved evidence cache: {cache_path}")
    print(f"Found {len(snapshot.pages)} page(s), {len(snapshot.forms)} form(s), {len(snapshot.elements)} UI element(s), {len(snapshot.transitions)} transition(s).")
    print(f"Next: site-agent schema review --profile {profile.name}")
    return 0


def cmd_crawl_collect(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    if args.probe_budget_seconds is not None:
        profile.crawl.max_crawl_seconds = args.probe_budget_seconds
    if args.target_depth is not None:
        profile.crawl.max_js_depth = args.target_depth
    if args.max_states is not None:
        profile.crawl.max_js_states = args.max_states
    snapshot, collection_report = crawl_collect_profile(
        workspace(),
        profile,
        args.url,
        crawl_progress_printer(args.max_states),
        args.max_states,
    )
    snapshot = redact_snapshot(snapshot, profile.crawl.redaction_patterns)
    path = output_root(workspace(), profile.name) / "crawl" / f"snapshot-{snapshot.run_id}.json"
    write_json(path, snapshot)
    cache_path = write_evidence_cache(workspace(), profile.name, build_evidence_cache(snapshot))
    report_path = output_root(workspace(), profile.name) / "reports" / f"collection-{snapshot.run_id}.json"
    write_json(report_path, collection_report)
    captured_html = sum(1 for page in snapshot.pages if page.html_snapshot)
    print(f"Saved fast collection snapshot: {path}")
    print(f"Saved evidence cache: {cache_path}")
    print(f"Saved exhaustive collection report: {report_path}")
    print(
        f"Collected {len(snapshot.pages)} page state(s), {len(snapshot.forms)} form(s), "
        f"{len(snapshot.elements)} UI element(s), {captured_html} visual HTML snapshot(s)."
    )
    print(
        "Coverage: "
        f"complete={collection_report.get('complete', False)}; "
        f"visited_paths={collection_report.get('visited_count', 0)}; "
        f"queued_remaining={collection_report.get('queued_remaining_count', 0)}; "
        f"failed_paths={collection_report.get('failed_count', 0)}; "
        f"duplicates={collection_report.get('duplicate_count', 0)}."
    )
    if not collection_report.get("complete", False) and not args.allow_incomplete:
        print("Exhaustive collection did not complete; rerun with more budget/depth/states or pass --allow-incomplete for exploratory output.", file=sys.stderr)
        return 1
    print(f"Next: site-agent schema review --profile {profile.name}; site-agent mcp build --profile {profile.name}; site-agent explorer serve --profile {profile.name}")
    return 0


def cmd_crawl_inventory(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    ontology, doc_evidence = build_ontology_artifact(workspace(), profile, NoopAiBackend())
    deadline = time.monotonic() + args.budget_seconds if args.budget_seconds and args.budget_seconds > 0 else None
    site_inventory = inventory_profile(
        workspace(),
        profile,
        ontology,
        max_nodes=args.max_nodes or profile.crawl.max_js_states,
        max_depth=args.max_depth or profile.crawl.max_js_depth,
        deadline=deadline,
    )
    path = output_root(workspace(), profile.name) / "reports" / f"site-tree-{utc_now().replace(':', '').replace('+', '_')}.json"
    write_json(path, site_inventory)
    print(f"Saved mandatory site inventory: {path}")
    print(
        f"Visited {site_inventory.get('node_count', 0)} node(s); "
        f"queued={site_inventory.get('coverage', {}).get('queued_paths', 0)}; "
        f"complete={site_inventory.get('coverage', {}).get('complete', False)}; "
        f"ontology_terms={len(ontology)}; doc_evidence={len(doc_evidence)}."
    )
    return 0


def directional_target_outcomes(crawl_plan: dict, snapshot: CrawlSnapshot) -> list[dict]:
    observed_paths = [state_path(page) for page in snapshot.pages]
    observed_labels = {normalize_label(label) for transition in snapshot.transitions for label in [transition.trigger_label]}
    for path in observed_paths:
        observed_labels.update(normalize_label(label) for label in path)
    outcomes = []
    for target in crawl_plan.get("directional_targets", []):
        branch = [str(label) for label in target.get("branch_path", []) if str(label).strip()]
        labels = [str(label) for label in target.get("labels", []) if str(label).strip()]
        normalized_branch = [normalize_label(label) for label in branch]
        normalized_labels = {normalize_label(label) for label in labels}
        reached = False
        partial = False
        for path in observed_paths:
            normalized_path = [normalize_label(label) for label in path]
            if normalized_branch and normalized_path[: len(normalized_branch)] == normalized_branch:
                reached = True
                break
            if normalized_branch and any(label in normalized_path for label in normalized_branch):
                partial = True
        if not reached and normalized_labels & observed_labels:
            partial = True
        outcomes.append(
            {
                "branch_path": branch,
                "labels": labels,
                "missing_concepts": target.get("missing_concepts", []),
                "status": "reached" if reached else "partial" if partial else "failed",
                "reason": target.get("reason", ""),
                "priority": target.get("priority", 0.0),
                "confidence": target.get("confidence", 0.0),
            }
        )
    return outcomes


def normalize_label(value: str) -> str:
    from site_agent.core.ingest.docs import normalize_term

    return normalize_term(value)


def dedupe_planned_paths(paths: list[list[str]]) -> list[list[str]]:
    deduped_paths: list[list[str]] = []
    seen_paths = set()
    for path in paths:
        clean_path = [" ".join(str(label).split()).strip() for label in path if str(label).strip()]
        key = tuple(normalize_label(label) for label in clean_path)
        if clean_path and key not in seen_paths:
            deduped_paths.append(clean_path)
            seen_paths.add(key)
    return deduped_paths


def planned_path_group_key(path: list[str]) -> tuple[str, ...]:
    normalized = [normalize_label(label) for label in path if normalize_label(label)]
    if len(normalized) >= 2:
        return tuple(normalized[:2])
    return tuple(normalized[:1])


def group_planned_paths(paths: list[list[str]]) -> list[list[list[str]]]:
    groups: dict[tuple[str, ...], list[list[str]]] = {}
    order: list[tuple[str, ...]] = []
    for path in dedupe_planned_paths(paths):
        key = planned_path_group_key(path)
        if not key:
            continue
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(path)
    return [groups[key] for key in order]


def interleave_group_lists(*group_lists: list[list[list[str]]]) -> list[list[list[str]]]:
    interleaved: list[list[list[str]]] = []
    max_groups = max((len(groups) for groups in group_lists), default=0)
    for index in range(max_groups):
        for groups in group_lists:
            if index < len(groups):
                interleaved.append(groups[index])
    return interleaved


def round_robin_planned_paths(groups: list[list[list[str]]], limit: int | None = None) -> list[list[str]]:
    result: list[list[str]] = []
    positions = [0 for _ in groups]
    seen = set()
    while groups:
        progressed = False
        for index, group in enumerate(groups):
            if positions[index] >= len(group):
                continue
            path = group[positions[index]]
            positions[index] += 1
            key = tuple(normalize_label(label) for label in path)
            if key not in seen:
                result.append(path)
                seen.add(key)
                progressed = True
                if limit is not None and len(result) >= limit:
                    return result
        if not progressed:
            break
    return result


def planned_crawl_inputs(crawl_plan: dict, max_planned_labels: int | None = None) -> tuple[list[str], list[list[str]], list[str]]:
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
    preservation_plan_labels = [
        item["label"]
        for item in crawl_plan.get("coverage_preservation_labels", [])
        if item.get("label")
    ]
    max_planned = max_planned_labels if max_planned_labels is not None else len(observed_plan_labels) + len(preservation_plan_labels) + 15
    planned_labels: list[str] = []
    seen_labels = set()
    for label in [*observed_plan_labels, *preservation_plan_labels, *generated_plan_labels[:15]]:
        key = normalize_label(label)
        if key not in seen_labels:
            planned_labels.append(label)
            seen_labels.add(key)
        if len(planned_labels) >= max_planned:
            break

    directional_groups: list[list[list[str]]] = []
    for target in crawl_plan.get("directional_targets", []):
        branch = [str(label) for label in target.get("branch_path", []) if str(label).strip()]
        labels = [str(label) for label in target.get("labels", []) if str(label).strip()]
        group: list[list[str]] = []
        if branch:
            group.append(branch)
        branch_keys = {label.lower() for label in branch}
        for label in labels:
            if branch and label.lower() in branch_keys:
                continue
            group.append([*branch, label] if branch else [label])
        if group:
            directional_groups.append(dedupe_planned_paths(group))

    preservation_paths: list[list[str]] = []
    for item in crawl_plan.get("coverage_preservation_labels", []):
        path_label = str(item.get("path") or item.get("label") or "")
        path = [part.strip() for part in path_label.split(">") if part.strip()]
        if path:
            preservation_paths.append(path)
    preservation_groups = group_planned_paths(preservation_paths)
    planned_paths = round_robin_planned_paths(
        interleave_group_lists(directional_groups, preservation_groups),
        max_planned,
    )
    deprioritized_labels = [str(label) for label in crawl_plan.get("deprioritized_labels", [])]
    return planned_labels, planned_paths, deprioritized_labels


def cmd_crawl_plan(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_latest_snapshot(profile.name)
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    memory = crawl_memory(profile.name) or {}
    memory["research_session"] = load_research_session(workspace(), profile)
    evidence_cache, evidence_cache_diff = cache_and_recent_diff(profile.name, snapshot)
    plan = build_crawl_plan(
        profile,
        snapshot,
        schema,
        get_ai_backend(),
        args.max_terms,
        memory,
        evidence_cache=evidence_cache,
        evidence_cache_diff=evidence_cache_diff,
    )
    path = write_crawl_plan(workspace(), profile, plan)
    research_session = memory["research_session"]
    research_session["weak_areas"] = plan.get("target_terms", [])
    research_session["directional_targets"] = plan.get("directional_targets", [])
    research_session.setdefault("passes", []).append(
        {
            "kind": "directional_crawl_planning",
            "source_run_id": snapshot.run_id,
            "missing_terms": plan["summary"]["missing_terms"],
            "directional_targets": plan["summary"].get("directional_targets", 0),
            "plan_path": str(path),
        }
    )
    session_path = write_research_session(workspace(), profile, research_session)
    print(f"Saved crawl plan: {path}")
    print(f"Updated research session: {session_path}")
    print(
        "Plan: "
        f"{plan['summary']['missing_terms']} missing term(s), "
        f"{plan['summary']['prioritized_labels']} prioritized label(s), "
        f"{plan['summary']['noise_labels']} deprioritized label(s), "
        f"{plan['summary'].get('directional_targets', 0)} directional target(s), "
        f"{plan['summary'].get('coverage_preservation_labels', 0)} coverage preservation label(s), "
        f"{plan['summary'].get('crawl_gain_candidates', 0)} gain candidate(s)."
    )
    print(
        "Page graph: "
        f"{plan['summary'].get('page_graph_nodes', 0)} node(s), "
        f"{plan['summary'].get('page_graph_edges', 0)} edge(s)."
    )
    if plan.get("directional_targets"):
        print("Directional targets:")
        for item in plan["directional_targets"][: args.limit]:
            branch = " > ".join(item.get("branch_path", [])) or "(unknown branch)"
            labels = ", ".join(item.get("labels", [])[:6])
            print(f"- {branch} ({item['priority']:.2f}/{item['confidence']:.2f}) labels={labels}")
    if plan.get("coverage_preservation_labels"):
        print("Coverage preservation labels:")
        for item in plan["coverage_preservation_labels"][: args.limit]:
            print(f"- {item['label']} ({item['score']:.2f}) path={item.get('path', item['label'])}")
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
    previous_cache = load_or_build_evidence_cache(profile.name, previous)
    current_cache = load_or_build_evidence_cache(profile.name, current)
    cache_diff = diff_evidence_caches(previous_cache, current_cache)
    comparison["evidence_cache"] = cache_diff
    comparison["summary"]["new_page_families"] = len(cache_diff["added_cache_keys"])
    comparison["summary"]["changed_page_families"] = len(cache_diff["changed_content"])
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
        f"{summary['new_page_families']} new page family/families, "
        f"{summary['changed_page_families']} changed page family/families, "
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


def synthesize_profile_tooling(profile, no_page_tools: bool = False, no_action_tools: bool = False):
    _, schema = latest_schema(output_root(workspace(), profile.name) / "schema")
    snapshot = load_synthesis_snapshot(profile.name)
    selector_lookup = {element.id: element.selector_fingerprint for element in snapshot.elements}
    value_lookup = {element.id: str(element.context["read_value"]) for element in snapshot.elements if "read_value" in element.context}
    ai_backend = get_ai_backend()
    research_session = load_research_session(workspace(), profile)
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
    if not no_page_tools:
        page_tools, page_bindings = synthesize_unmapped_page_tools(profile.id, snapshot, covered_read_element_ids, seen_tool_names)
        tools.extend(page_tools)
        bindings.extend(page_bindings)
    if not no_action_tools:
        form_classifications, _ = classify_forms(workspace(), profile, snapshot, schema.ontology, ai_backend, research_session)
        if form_classifications:
            research_session["form_classifications"] = list(form_classifications.values())
            negative_concepts = sorted(
                {
                    concept
                    for classification in form_classifications.values()
                    for concept in classification.get("negative_concepts", [])
                }
            )
            if negative_concepts:
                research_session["negative_concepts"] = negative_concepts
            write_research_session(workspace(), profile, research_session)
        write_tools, write_bindings = synthesize_form_tools(profile.id, snapshot, seen_tool_names, form_classifications)
        tools.extend(write_tools)
        bindings.extend(write_bindings)
    return snapshot, tools, bindings


def synthesize_profile_capabilities(profile, no_page_tools: bool = False, no_action_tools: bool = False):
    snapshot, adapter_tools, adapter_bindings = synthesize_profile_tooling(profile, no_page_tools, no_action_tools)
    tools, bindings, report = synthesize_capabilities(adapter_tools, adapter_bindings, snapshot)
    capabilities_path = output_root(workspace(), profile.name) / "capabilities" / "capabilities.json"
    write_json(
        capabilities_path,
        {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "run_id": snapshot.run_id,
            "capabilities": tools,
            "projection_report": report,
        },
    )
    path = output_root(workspace(), profile.name) / "reports" / f"capabilities-{snapshot.run_id}.json"
    write_json(path, report)
    return snapshot, tools, bindings, report, path


def cmd_mcp_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot, tools, bindings, capability_report, capability_report_path = synthesize_profile_capabilities(profile, args.no_page_tools, args.no_action_tools)
    write_mcp_package(workspace(), profile.name, tools, bindings, profile.base_url if args.include_writes else None)
    if (output_root(workspace(), profile.name) / "api" / "api-spec.json").exists():
        write_api_package(workspace(), profile.name, [tool.__dict__ if hasattr(tool, "__dict__") else tool for tool in tools])
    write_contract(output_root(workspace(), profile.name) / "mcp")
    contract_report = contract_quality_report(profile, tools)
    contract_report_path = output_root(workspace(), profile.name) / "reports" / f"contract-quality-{snapshot.run_id}.json"
    write_json(contract_report_path, contract_report)
    print(f"Generated MCP package: {output_root(workspace(), profile.name) / 'mcp'}")
    print(f"Exposed {len(tools)} semantic capability tool(s). Raw adapters are not public API.")
    print(f"Saved capability report: {capability_report_path}")
    if capability_report["quality"]["numbered_public_names"] or capability_report["quality"]["generic_public_names"]:
        print("Capability quality failures detected.")
    print(f"Saved contract quality report: {contract_report_path}")
    if contract_report["warnings"]:
        print(f"Contract warnings: {len(contract_report['warnings'])}")
    if contract_report["failures"]:
        print(f"Contract failures: {len(contract_report['failures'])}")
    print(f"Next: site-agent mcp serve --profile {profile.name}")
    return 0


def cmd_api_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    tools_path = package_dir / "tools.json"
    if not tools_path.exists():
        _, tools, bindings, _, _ = synthesize_profile_capabilities(profile, args.no_page_tools, args.no_action_tools)
        write_mcp_package(workspace(), profile.name, tools, bindings, profile.base_url)
        write_contract(output_root(workspace(), profile.name) / "mcp")
    api_dir, spec = write_api_package(workspace(), profile.name, read_json(tools_path).get("tools", []))
    print(f"Generated Python API package: {api_dir}")
    print(f"API methods: {len(spec.methods)}; package={spec.package_name}")
    print(f"Next: site-agent ansible build --profile {profile.name} or site-agent mcp serve --profile {profile.name}")
    return 0


def cmd_ansible_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    tools_path = package_dir / "tools.json"
    if not tools_path.exists():
        raise FileNotFoundError(f"No MCP package found. Run: site-agent mcp build --profile {profile.name}")
    api_dir = output_root(workspace(), profile.name) / "api"
    if not (api_dir / "api-spec.json").exists():
        write_api_package(workspace(), profile.name, read_json(tools_path).get("tools", []))
    api_spec = read_json(api_dir / "api-spec.json")
    from site_agent.core.models import PythonApiMethod, PythonApiSpec

    spec_obj = PythonApiSpec(
        package_name=api_spec["package_name"],
        version=api_spec["version"],
        methods=[PythonApiMethod(**method) for method in api_spec.get("methods", [])],
        evidence_ids=api_spec.get("evidence_ids", []),
        adapter_version=api_spec.get("adapter_version", "0.1.0"),
    )
    collection_dir, collection_spec = write_ansible_collection(workspace(), profile.name, read_json(tools_path).get("tools", []), spec_obj)
    print(f"Generated Ansible collection: {collection_dir}")
    print(f"Ansible modules: {len(collection_spec.modules)}; collection={collection_spec.namespace}.{collection_spec.name}")
    print(f"Next: run ansible-playbook with ANSIBLE_COLLECTIONS_PATH={output_root(workspace(), profile.name) / 'ansible'}")
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


def cmd_mcp_import(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    package_dir = output_root(workspace(), profile.name) / "mcp"
    if not (package_dir / "server.json").exists():
        raise FileNotFoundError(f"No MCP package found. Run: site-agent mcp build --profile {profile.name}")
    spec = build_mcp_import_spec(
        profile_name=profile.name,
        server_name=args.server_name,
        project_dir=Path(args.project_dir) if args.project_dir else workspace(),
        python_bin=Path(args.python) if args.python else None,
        engine_dir=Path(args.engine_dir) if args.engine_dir else None,
    )
    if args.target == "json":
        print(render_mcp_json(spec))
        return 0
    if args.target == "kimi-code":
        print(render_mcp_json(spec))
        print(
            "\nUse this standard mcpServers JSON in Kimi Code or another MCP client if it accepts that shape. "
            "If the client uses a different wrapper, keep command, args, cwd, and env unchanged."
        )
        return 0
    block = marked_block("codex", spec.name, render_codex_toml(spec))
    if not args.apply:
        print(block, end="")
        print("\nRun again with --apply to update the Codex config automatically.")
        return 0
    config_path = Path(args.config or __import__("os").environ.get("CODEX_CONFIG", "~/.codex/config.toml"))
    install_codex_config(config_path, spec)
    print(f"Installed MCP server '{spec.name}' into {config_path.expanduser()}")
    print("Restart Codex so it reloads MCP configuration.")
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
        bindings=latest_bindings(profile.name),
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


def cmd_explorer_build(args: argparse.Namespace) -> int:
    profile = load_profile(workspace(), args.profile)
    snapshot = load_synthesis_snapshot(profile.name)
    explorer_dir, data = write_explorer(workspace(), profile, snapshot)
    print(f"Built semantic API explorer: {explorer_dir / 'index.html'}")
    print(
        "Explorer contents: "
        f"{data['summary']['methods']} method(s), "
        f"{data['summary']['groups']} semantic group(s), "
        f"{data['summary']['pages']} page(s), "
        f"{data['summary']['forms']} form(s)."
    )
    return 0


def cmd_explorer_serve(args: argparse.Namespace) -> int:
    import functools
    import socket
    from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

    profile = load_profile(workspace(), args.profile)
    snapshot = load_synthesis_snapshot(profile.name)
    explorer_dir, data = write_explorer(workspace(), profile, snapshot)
    port = args.port
    while True:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind((args.host, port))
                break
            except OSError:
                if not args.auto_port:
                    raise
                port += 1
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(explorer_dir))
    server = ThreadingHTTPServer((args.host, port), handler)
    url_host = "127.0.0.1" if args.host in {"0.0.0.0", ""} else args.host
    print(f"Serving semantic API explorer: http://{url_host}:{port}/", flush=True)
    print(
        "Explorer contents: "
        f"{data['summary']['methods']} method(s), "
        f"{data['summary']['groups']} semantic group(s), "
        f"{data['summary']['pages']} page(s), "
        f"{data['summary']['forms']} form(s).",
        flush=True,
    )
    print("Press Ctrl-C to stop.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        return 0
    finally:
        server.server_close()
    return 0


def cmd_completion_script(args: argparse.Namespace) -> int:
    scripts = {
        "bash": bash_script,
        "zsh": zsh_script,
        "fish": fish_script,
    }
    print(scripts[args.shell](args.program), end="")
    return 0


def cmd_completion_complete(args: argparse.Namespace) -> int:
    parser = build_parser(include_completion=True)
    words = args.words[1:] if args.words and args.words[0] == "--" else args.words
    for item in complete(parser, words, args.cword, workspace()):
        print(item)
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    results = doctor_checks(include_playwright=not args.no_playwright)
    for result in results:
        status = "ok" if result.ok else "missing"
        print(f"{status:7} {result.name}: {result.detail}")
        if not result.ok and result.fix:
            print(f"        fix: {result.fix}")
    failed = [result for result in results if not result.ok]
    if failed:
        print("Next: apply the suggested fixes, then run site-agent doctor again.")
        return 1 if args.fail_on_error else 0
    print("Environment looks ready.")
    return 0


def cmd_install_browsers(args: argparse.Namespace) -> int:
    rc = run_playwright_install(args.browser)
    if rc == 0:
        print(f"Installed Playwright browser: {args.browser}")
        print("Next: site-agent doctor")
    return rc


def build_parser(include_completion: bool = True) -> argparse.ArgumentParser:
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
    run.add_argument("--research-product-hint", help="Optionally add product-specific AI documentation research; initial live crawls run AI UI domain discovery before ontology planning.")
    run.add_argument("--refresh-ai-domain", action="store_true", help="Refresh AI UI domain discovery even when --use-plan can reuse the existing research session.")
    run.add_argument("--max-research-sources", type=int, default=5)
    run.add_argument("--use-plan", help="Use a crawl plan path or 'latest' to prioritize navigation labels.")
    run.add_argument("--max-planned-labels", type=int, help="Limit labels loaded from the crawl plan for a targeted probe.")
    run.add_argument("--probe-budget-seconds", type=int, help="Override max crawl seconds for this run.")
    run.add_argument("--target-depth", type=int, help="Override JS state depth for this run.")
    run.add_argument("--backend", choices=["playwright", "crawl4ai"], help="Browser crawl backend for live crawls. Defaults to the profile crawl policy.")
    run.set_defaults(func=cmd_crawl_run)
    collect = crawl_sub.add_parser("collect", help="Fast rendered-HTML collection pass for offline analysis and visual explorer review.")
    collect.add_argument("--profile", required=True)
    collect.add_argument("--url")
    collect.add_argument("--probe-budget-seconds", type=int, default=600)
    collect.add_argument("--target-depth", type=int, default=8)
    collect.add_argument("--max-states", type=int, default=500)
    collect.add_argument("--allow-incomplete", action="store_true", help="Write the capture artifacts even when queued or failed paths remain.")
    collect.set_defaults(func=cmd_crawl_collect)
    inventory = crawl_sub.add_parser("inventory")
    inventory.add_argument("--profile", required=True)
    inventory.add_argument("--max-nodes", type=int)
    inventory.add_argument("--max-depth", type=int)
    inventory.add_argument("--budget-seconds", type=int, default=120)
    inventory.set_defaults(func=cmd_crawl_inventory)
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

    api = sub.add_parser("api")
    api_sub = api.add_subparsers(dest="api_command", required=True)
    api_build = api_sub.add_parser("build")
    api_build.add_argument("--profile", required=True)
    api_build.add_argument("--no-action-tools", action="store_true", help="Skip generated form/action candidate methods.")
    api_build.add_argument("--no-page-tools", action="store_true", help="Skip generated UI-backed page/status read methods.")
    api_build.set_defaults(func=cmd_api_build)

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
    mcp_import = mcp_sub.add_parser("import", help="Emit or install MCP client configuration for a generated profile.")
    mcp_import.add_argument("--profile", required=True)
    mcp_import.add_argument("--target", choices=["json", "codex", "kimi-code"], default="json")
    mcp_import.add_argument("--server-name", help="MCP server name exposed to the client. Defaults to the profile name.")
    mcp_import.add_argument("--project-dir", help="Working directory for the MCP server. Defaults to the current workspace.")
    mcp_import.add_argument("--python", help="Python executable used to run the MCP server. Defaults to the current interpreter.")
    mcp_import.add_argument("--engine-dir", help="Optional site-agent source directory to place in PYTHONPATH.")
    mcp_import.add_argument("--config", help="Target config path. For Codex this defaults to ~/.codex/config.toml.")
    mcp_import.add_argument("--apply", action="store_true", help="Write the target config when supported.")
    mcp_import.set_defaults(func=cmd_mcp_import)
    diff = mcp_sub.add_parser("diff")
    diff.add_argument("--profile", required=True)
    diff.add_argument("--baseline", required=True)
    diff.add_argument("--fail-on-breaking", action="store_true")
    diff.set_defaults(func=cmd_mcp_diff)
    refresh = mcp_sub.add_parser("refresh-adapter")
    refresh.add_argument("--profile", required=True)
    refresh.add_argument("--include-writes", action="store_true")
    refresh.set_defaults(func=cmd_mcp_refresh_adapter)

    ansible = sub.add_parser("ansible")
    ansible_sub = ansible.add_subparsers(dest="ansible_command", required=True)
    ansible_build = ansible_sub.add_parser("build")
    ansible_build.add_argument("--profile", required=True)
    ansible_build.set_defaults(func=cmd_ansible_build)

    explorer = sub.add_parser("explorer")
    explorer_sub = explorer.add_subparsers(dest="explorer_command", required=True)
    explorer_build = explorer_sub.add_parser("build")
    explorer_build.add_argument("--profile", required=True)
    explorer_build.set_defaults(func=cmd_explorer_build)
    explorer_serve = explorer_sub.add_parser("serve")
    explorer_serve.add_argument("--profile", required=True)
    explorer_serve.add_argument("--host", default="127.0.0.1")
    explorer_serve.add_argument("--port", type=int, default=8765)
    explorer_serve.add_argument("--auto-port", action="store_true", default=True, help="Use the next available port if the requested port is busy.")
    explorer_serve.set_defaults(func=cmd_explorer_serve)

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

    doctor = sub.add_parser("doctor", help="Check local dependencies and browser readiness.")
    doctor.add_argument("--no-playwright", action="store_true", help="Skip Playwright package/browser checks.")
    doctor.add_argument("--fail-on-error", action="store_true")
    doctor.set_defaults(func=cmd_doctor)

    install = sub.add_parser("install", help="Install optional runtime assets.")
    install_sub = install.add_subparsers(dest="install_command", required=True)
    install_browsers = install_sub.add_parser("browsers", help="Install Playwright browser binaries.")
    install_browsers.add_argument("--browser", default="chromium", choices=["chromium", "firefox", "webkit"])
    install_browsers.set_defaults(func=cmd_install_browsers)

    if include_completion:
        completion = sub.add_parser("completion", help="Generate shell completion scripts.")
        completion_sub = completion.add_subparsers(dest="completion_command", required=True)
        for shell in ("bash", "zsh", "fish"):
            completion_script = completion_sub.add_parser(shell, help=f"Print {shell} completion script.")
            completion_script.add_argument("--program", default="site-agent", help="Program name to register for completion.")
            completion_script.set_defaults(func=cmd_completion_script, shell=shell)
        completion_complete = completion_sub.add_parser("complete", help=argparse.SUPPRESS)
        completion_complete.add_argument("--cword", type=int, required=True)
        completion_complete.add_argument("words", nargs=argparse.REMAINDER)
        completion_complete.set_defaults(func=cmd_completion_complete)
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
