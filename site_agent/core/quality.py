from __future__ import annotations

from collections import Counter
from pathlib import Path

from site_agent.core.debug import build_debug_report
from site_agent.core.models import CrawlSnapshot, MappedSchema, ToolSpec, utc_now
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import read_json, write_json


def page_keys(snapshot: CrawlSnapshot) -> set[str]:
    return {page.url.split("#", 1)[-1] if "#state=" in page.url else page.url for page in snapshot.pages}


def element_keys(snapshot: CrawlSnapshot) -> set[str]:
    return {f"{element.label}|{element.control_type}|{element.selector_fingerprint}" for element in snapshot.elements}


def form_keys(snapshot: CrawlSnapshot) -> set[str]:
    return {f"{form.label}|{form.method}|{form.action}" for form in snapshot.forms}


def mapped_terms(schema: MappedSchema | None) -> set[str]:
    if schema is None:
        return set()
    return {
        mapping.canonical_name
        for mapping in schema.mappings
        if mapping.status in {"ready", "review"} and mapping.domain_term_id
    }


def tool_names(tools: list[dict] | list[ToolSpec]) -> set[str]:
    names = set()
    for tool in tools:
        if isinstance(tool, dict):
            names.add(tool.get("name", ""))
        else:
            names.add(tool.name)
    return {name for name in names if name}


def tool_value(tool: dict | ToolSpec, key: str, default=None):
    if isinstance(tool, dict):
        return tool.get(key, default)
    return getattr(tool, key, default)


def contract_quality_report(profile: Profile, tools: list[dict] | list[ToolSpec]) -> dict:
    names = [tool_value(tool, "name", "") for tool in tools]
    duplicate_names = sorted(name for name, count in Counter(names).items() if name and count > 1)
    awkward_read_names = sorted(name for name in names if name.startswith("read_"))
    read_tools = [tool for tool in tools if tool_value(tool, "risk_level") == "low" and tool_value(tool, "source_type") in {"canonical_concept", "ui_page"}]
    page_shaped_reads = [tool_value(tool, "name") for tool in read_tools if tool_value(tool, "source_type") == "ui_page"]
    low_confidence_public = [
        tool_value(tool, "name")
        for tool in tools
        if tool_value(tool, "exposure_level") == "ready_public" and float(tool_value(tool, "confidence", 0.0) or 0.0) < 0.60
    ]
    missing_provenance = [name for name, tool in zip(names, tools) if not tool_value(tool, "source_type")]
    warnings = []
    failures = []
    if awkward_read_names:
        failures.append(f"Public read tools use deprecated read_ prefix: {', '.join(awkward_read_names[:20])}")
    if duplicate_names:
        failures.append(f"Duplicate public tool names: {', '.join(duplicate_names)}")
    if low_confidence_public:
        failures.append(f"Low-confidence public tools should be internal/reviewed: {', '.join(low_confidence_public[:20])}")
    if missing_provenance:
        failures.append(f"Tools missing source_type provenance: {', '.join(missing_provenance[:20])}")
    if page_shaped_reads:
        warnings.append(
            f"{len(page_shaped_reads)} UI page/status read tool(s) are exposed as get_* with ui_page provenance; consider merging stable ones into canonical concepts after review."
        )
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "generated_at": utc_now(),
        "passed": not failures,
        "warnings": warnings,
        "failures": failures,
        "metrics": {
            "tools": len(tools),
            "read_tools": len(read_tools),
            "action_tools": sum(1 for tool in tools if tool_value(tool, "source_type") in {"ui_form", "ui_flow"}),
            "canonical_read_tools": sum(1 for tool in read_tools if tool_value(tool, "source_type") == "canonical_concept"),
            "ui_page_read_tools": len(page_shaped_reads),
            "deprecated_read_prefix_tools": len(awkward_read_names),
            "duplicate_names": len(duplicate_names),
        },
        "page_shaped_read_tools": page_shaped_reads[:100],
    }


def compare_coverage(
    profile: Profile,
    previous: CrawlSnapshot,
    current: CrawlSnapshot,
    previous_schema: MappedSchema | None = None,
    current_schema: MappedSchema | None = None,
    previous_tools: list[dict] | None = None,
    current_tools: list[dict] | None = None,
) -> dict:
    previous_debug = build_debug_report(previous, previous_schema)
    current_debug = build_debug_report(current, current_schema)
    previous_state_counts = Counter(state["kind"] for state in previous_debug["state_classifications"])
    current_state_counts = Counter(state["kind"] for state in current_debug["state_classifications"])
    previous_pages = page_keys(previous)
    current_pages = page_keys(current)
    previous_elements = element_keys(previous)
    current_elements = element_keys(current)
    previous_forms = form_keys(previous)
    current_forms = form_keys(current)
    previous_mapped = mapped_terms(previous_schema)
    current_mapped = mapped_terms(current_schema)
    previous_tool_names = tool_names(previous_tools or [])
    current_tool_names = tool_names(current_tools or [])
    widget_growth = current_state_counts.get("widget_state", 0) - previous_state_counts.get("widget_state", 0)
    high_value_growth = (
        current_state_counts.get("form_or_settings_state", 0)
        + current_state_counts.get("data_or_status_state", 0)
        - previous_state_counts.get("form_or_settings_state", 0)
        - previous_state_counts.get("data_or_status_state", 0)
    )
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "previous_run_id": previous.run_id,
        "current_run_id": current.run_id,
        "generated_at": utc_now(),
        "summary": {
            "new_states": len(current_pages - previous_pages),
            "removed_states": len(previous_pages - current_pages),
            "new_forms": len(current_forms - previous_forms),
            "new_ui_elements": len(current_elements - previous_elements),
            "new_mapped_terms": len(current_mapped - previous_mapped),
            "new_tools": len(current_tool_names - previous_tool_names),
            "widget_state_growth": widget_growth,
            "high_value_state_growth": high_value_growth,
        },
        "new_states": sorted(current_pages - previous_pages)[:100],
        "new_mapped_terms": sorted(current_mapped - previous_mapped),
        "new_tools": sorted(current_tool_names - previous_tool_names),
        "state_kind_delta": {
            kind: current_state_counts.get(kind, 0) - previous_state_counts.get(kind, 0)
            for kind in sorted(set(previous_state_counts) | set(current_state_counts))
        },
        "previous_debug_summary": previous_debug["summary"],
        "current_debug_summary": current_debug["summary"],
    }


def update_crawl_memory(workspace: Path, profile: Profile, comparison: dict, merge_report: dict | None = None) -> Path:
    memory_path = output_root(workspace, profile.name) / "reports" / "crawl-memory.json"
    if memory_path.exists():
        memory = read_json(memory_path)
    else:
        memory = {"profile_id": profile.id, "profile_name": profile.name, "runs": [], "promoted_labels": [], "demoted_labels": []}
    summary = comparison["summary"]
    promoted = set(memory.get("promoted_labels", []))
    demoted = set(memory.get("demoted_labels", []))
    attribution = (merge_report or {}).get("attribution", {})
    attributed_labels = set(attribution.get("promotable_labels", []))
    probe_labels = set(attribution.get("probe_labels", []))
    memory["runs"].append(
        {
            "previous_run_id": comparison["previous_run_id"],
            "current_run_id": comparison["current_run_id"],
            "generated_at": comparison["generated_at"],
            "summary": summary,
            "attributed_labels": sorted(attributed_labels),
        }
    )
    if attributed_labels and (summary["new_ui_elements"] > 0 or summary["new_forms"] > 0 or summary["new_states"] > 0):
        promoted.update(attributed_labels)
        demoted.difference_update(attributed_labels)
    if probe_labels and summary["new_mapped_terms"] > 0:
        promoted.update(probe_labels)
        demoted.difference_update(probe_labels)
    if summary["high_value_state_growth"] <= 0 and summary["new_mapped_terms"] <= 0 and not attributed_labels:
        memory["last_outcome"] = "no_material_gain"
    elif summary["widget_state_growth"] > max(2, summary["high_value_state_growth"]):
        memory["last_outcome"] = "noisy_gain"
        demoted.update(attributed_labels)
    else:
        memory["last_outcome"] = "useful_gain"
    memory["promoted_labels"] = sorted(promoted)
    memory["demoted_labels"] = sorted(demoted)
    write_json(memory_path, memory)
    return memory_path


def quality_gate_report(
    profile: Profile,
    snapshot: CrawlSnapshot,
    schema: MappedSchema,
    tools: list[dict],
    comparison: dict | None = None,
    config_coverage: dict | None = None,
) -> dict:
    debug = build_debug_report(snapshot, schema)
    coverage = debug["evidence_coverage"]
    tools_with_evidence = sum(1 for tool in tools if tool.get("evidence_ids"))
    high_risk_without_confirmation = [
        tool.get("name")
        for tool in tools
        if tool.get("risk_level") == "high" and not tool.get("requires_confirmation")
    ]
    warnings = []
    failures = []
    dual_ratio = coverage.get("dual_evidence_ratio", 0.0)
    if coverage.get("exposed_mappings", 0) and dual_ratio < 0.90:
        warnings.append(f"Dual evidence ratio is {dual_ratio:.2f}; target is >= 0.90 unless reviewed exception exists.")
    if tools and tools_with_evidence / len(tools) < 0.90:
        failures.append("Fewer than 90 percent of generated tools include evidence IDs.")
    if high_risk_without_confirmation:
        failures.append(f"High-risk tools missing confirmation: {', '.join(high_risk_without_confirmation)}")
    if comparison:
        summary = comparison["summary"]
        if summary["removed_states"] > summary["new_states"] and summary["new_forms"] == 0:
            failures.append("Coverage regression: current crawl lost states without discovering replacement forms.")
        if summary["new_states"] == 0 and summary["new_mapped_terms"] == 0:
            warnings.append("Plan-guided comparison found no new states or mapped terms.")
        if summary["widget_state_growth"] > max(2, summary["high_value_state_growth"] * 2):
            warnings.append("Widget/noise state growth outpaced high-value state growth.")
    if config_coverage:
        confidence = config_coverage.get("confidence", {})
        score = float(confidence.get("score", 0.0) or 0.0)
        if score < 0.60:
            failures.append(f"Configuration coverage confidence is low ({score:.2f}); inspect latest config-coverage report.")
        elif score < 0.85:
            warnings.append(f"Configuration coverage confidence is below high-confidence target ({score:.2f}).")
        for gap in config_coverage.get("gaps", []):
            summary_text = gap.get("summary", "")
            if gap.get("severity") == "error":
                failures.append(f"Configuration coverage gap: {summary_text}")
            elif gap.get("severity") == "warning":
                warnings.append(f"Configuration coverage gap: {summary_text}")
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "run_id": snapshot.run_id,
        "generated_at": utc_now(),
        "passed": not failures,
        "warnings": warnings,
        "failures": failures,
        "metrics": {
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "tools": len(tools),
            "tools_with_evidence": tools_with_evidence,
            "dual_evidence_ratio": dual_ratio,
            "state_kinds": debug["summary"]["state_kinds"],
            "config_coverage_score": (config_coverage or {}).get("confidence", {}).get("score"),
        },
    }
