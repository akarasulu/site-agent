from __future__ import annotations

import re
from collections import Counter
from pathlib import Path
from typing import Any

from site_agent.core.models import CrawlSnapshot, MappedSchema, ToolSpec, UiElement, utc_now
from site_agent.core.storage import read_json


CONFIG_FIELD_TYPES = {
    "checkbox",
    "color",
    "date",
    "datetime-local",
    "email",
    "file",
    "hidden",
    "input",
    "month",
    "number",
    "password",
    "radio",
    "range",
    "search",
    "select",
    "tel",
    "text",
    "textarea",
    "time",
    "url",
    "week",
}
ACTION_FIELD_TYPES = {"button", "submit"}
FORM_ACTION_BINDING_TYPES = {"submit", "submit_form", "staged_flow", "execute_flow"}
DISCOVERY_ACTION_RE = re.compile(r"\b(add|new|create|edit|modify|advanced|more|show|open|expand)\b", re.I)
INTERNAL_FIELD_RE = re.compile(
    r"^(?:_?stopformautosubmit|confirm(?:ok|cancel|stop)|sercuritynoticeok|securitynoticeok)(?::\d+)?$",
    re.I,
)


def tool_value(tool: dict | ToolSpec, key: str, default: Any = None) -> Any:
    if isinstance(tool, dict):
        return tool.get(key, default)
    return getattr(tool, key, default)


def binding_value(binding: dict | Any, key: str, default: Any = None) -> Any:
    if isinstance(binding, dict):
        return binding.get(key, default)
    return getattr(binding, key, default)


def binding_adapter(binding: dict | Any) -> dict[str, Any]:
    adapter = binding_value(binding, "selector_action_bindings", {})
    return adapter if isinstance(adapter, dict) else {}


def iter_bindings(bindings: dict[str, Any] | list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    if not bindings:
        return []
    if isinstance(bindings, dict):
        items = bindings.get("bindings", [])
        return items if isinstance(items, list) else []
    return bindings


def _ratio(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 1.0
    return round(max(0.0, min(1.0, numerator / denominator)), 4)


def _field_text(element: UiElement) -> str:
    return " ".join(part for part in [element.label, element.id, element.selector_fingerprint] if part)


def _is_internal_config_field(element: UiElement) -> bool:
    if (
        element.control_type == "text"
        and str(element.label).strip().casefold() in {"on", "off"}
        and element.context.get("read_value", "") in {"", None}
    ):
        return True
    return any(
        INTERNAL_FIELD_RE.match(str(part).strip())
        for part in (element.label, element.id, element.selector_fingerprint)
        if part
    )


def _is_config_field(element: UiElement, *, include_hidden: bool = False) -> bool:
    if element.control_type not in CONFIG_FIELD_TYPES:
        return False
    if element.control_type == "hidden" and not include_hidden:
        return False
    return not _is_internal_config_field(element)


def _element_has_value(element: UiElement) -> bool:
    return any(key in element.context for key in ("read_value", "value", "checked", "selected", "current_value"))


def _settings_count(snapshot: CrawlSnapshot, settings_snapshot: dict | None) -> int:
    if settings_snapshot:
        settings = settings_snapshot.get("settings")
        if isinstance(settings, list):
            return len(settings)
        if isinstance(settings, dict):
            return len(settings)
    return sum(1 for element in snapshot.elements if _element_has_value(element))


def _restorable_settings_count(settings_snapshot: dict | None) -> int:
    if not settings_snapshot:
        return 0
    settings = settings_snapshot.get("settings", [])
    if isinstance(settings, dict):
        settings = list(settings.values())
    return sum(1 for setting in settings if isinstance(setting, dict) and setting.get("restorable"))


def _settings_snapshot_run_id(settings_snapshot: dict | None) -> str | None:
    if not settings_snapshot:
        return None
    return settings_snapshot.get("source_run_id") or settings_snapshot.get("run_id")


def load_settings_snapshot(path: Path | None = None, repo: Path | None = None) -> dict | None:
    if path:
        return read_json(path)
    if repo:
        latest = repo / "snapshots" / "latest.json"
        if latest.exists():
            return read_json(latest)
    return None


def build_config_coverage_report(
    profile_id: str,
    profile_name: str,
    snapshot: CrawlSnapshot,
    schema: MappedSchema | None = None,
    tools: list[dict] | list[ToolSpec] | None = None,
    bindings: dict[str, Any] | list[dict[str, Any]] | None = None,
    settings_snapshot: dict | None = None,
    previous_snapshot: CrawlSnapshot | None = None,
) -> dict:
    tools = tools or []
    elements_by_id = {element.id: element for element in snapshot.elements}
    form_field_ids = {field_id for form in snapshot.forms for field_id in form.field_ids}
    field_elements = [element for element in snapshot.elements if _is_config_field(element, include_hidden=True)]
    visible_fields = [element for element in field_elements if element.control_type != "hidden"]
    hidden_fields = [element for element in field_elements if element.control_type == "hidden"]
    action_elements = [element for element in snapshot.elements if element.control_type in ACTION_FIELD_TYPES]
    readonly_elements = [
        element
        for element in snapshot.elements
        if element.control_type == "readonly_status" or element.context.get("read_only") or _element_has_value(element)
    ]
    forms_with_values = []
    forms_without_values = []
    forms_without_action_tools = []
    forms_requiring_action_tools = []
    binding_items = iter_bindings(bindings)
    action_binding_tool_names: set[str] = set()
    action_binding_form_ids: set[str] = set()
    action_binding_field_ids: set[str] = set()
    for binding in binding_items:
        adapter = binding_adapter(binding)
        if adapter.get("action") not in FORM_ACTION_BINDING_TYPES:
            continue
        tool_name = binding_value(binding, "tool_name")
        if tool_name:
            action_binding_tool_names.add(str(tool_name))
        form_id = adapter.get("form_id")
        if form_id:
            action_binding_form_ids.add(str(form_id))
        action_binding_form_ids.update(str(value) for value in adapter.get("source_form_ids", []) if value)
        action_binding_field_ids.update(str(value) for value in adapter.get("source_field_ids", []) if value)
        for field in adapter.get("fields", []) or []:
            if not isinstance(field, dict):
                continue
            ui_element_id = field.get("ui_element_id")
            if ui_element_id:
                action_binding_field_ids.add(str(ui_element_id))
    action_tool_evidence = {
        evidence_id
        for tool in tools
        if tool_value(tool, "source_type") in {"ui_form", "ui_flow"} or str(tool_value(tool, "name", "")) in action_binding_tool_names
        for evidence_id in tool_value(tool, "evidence_ids", []) or []
    }
    for form in snapshot.forms:
        form_fields = [elements_by_id[field_id] for field_id in form.field_ids if field_id in elements_by_id]
        configurable = [element for element in form_fields if _is_config_field(element)]
        if configurable and any(_element_has_value(element) for element in configurable):
            forms_with_values.append(form.id)
        elif configurable:
            forms_without_values.append(form.id)
        field_evidence = {evidence_id for element in form_fields for evidence_id in element.evidence_ids}
        field_ids = {element.id for element in form_fields}
        if configurable:
            forms_requiring_action_tools.append(form.id)
        has_action_tool = (
            bool(field_evidence & action_tool_evidence)
            or form.id in action_binding_form_ids
            or bool(field_ids & action_binding_field_ids)
        )
        if configurable and not has_action_tool:
            forms_without_action_tools.append(form.id)

    triggered_labels = {flow.trigger_label.casefold() for flow in snapshot.interaction_flows}
    unprobed_actions = [
        {
            "id": element.id,
            "page_id": element.page_id,
            "label": element.label,
            "reason": "action label implies a reveal/edit flow but no matching interaction_flow evidence was captured",
        }
        for element in action_elements
        if DISCOVERY_ACTION_RE.search(element.label or "") and element.label.casefold() not in triggered_labels
    ]
    opened_and_canceled = sum(1 for flow in snapshot.interaction_flows if flow.cancel_supported)
    settings_extracted = _settings_count(snapshot, settings_snapshot)
    restorable_settings = _restorable_settings_count(settings_snapshot)
    evidence_ids = {evidence.id for evidence in snapshot.evidence}
    elements_with_evidence = sum(1 for element in snapshot.elements if element.evidence_ids or element.id in evidence_ids)
    ready_mappings = review_mappings = internal_mappings = 0
    mapped_term_names: set[str] = set()
    unmapped_doc_terms = []
    if schema:
        ready_mappings = sum(1 for mapping in schema.mappings if mapping.status == "ready")
        review_mappings = sum(1 for mapping in schema.mappings if mapping.status == "review")
        internal_mappings = sum(1 for mapping in schema.mappings if mapping.status == "internal")
        mapped_term_names = {mapping.canonical_name.casefold() for mapping in schema.mappings if mapping.status in {"ready", "review"}}
        for term in schema.ontology:
            if term.canonical_name.casefold() not in mapped_term_names:
                unmapped_doc_terms.append(
                    {
                        "id": term.id,
                        "canonical_name": term.canonical_name,
                        "confidence": term.confidence,
                        "sources": term.sources,
                    }
                )
    source_counts = Counter(str(tool_value(tool, "source_type", "unknown")) for tool in tools)
    risk_counts = Counter(str(tool_value(tool, "risk_level", "unknown")) for tool in tools)
    previous_counts = None
    convergence = {
        "status": "unknown",
        "previous_run_id": previous_snapshot.run_id if previous_snapshot else None,
        "new_pages": None,
        "new_forms": None,
        "new_fields": None,
        "new_flows": None,
        "new_settings": None,
    }
    if previous_snapshot:
        previous_field_keys = {f"{element.page_id}|{element.label}|{element.control_type}" for element in previous_snapshot.elements if _is_config_field(element, include_hidden=True)}
        current_field_keys = {f"{element.page_id}|{element.label}|{element.control_type}" for element in field_elements}
        previous_form_keys = {f"{form.page_id}|{form.label}|{form.action}|{form.method}" for form in previous_snapshot.forms}
        current_form_keys = {f"{form.page_id}|{form.label}|{form.action}|{form.method}" for form in snapshot.forms}
        previous_page_keys = {page.url for page in previous_snapshot.pages}
        current_page_keys = {page.url for page in snapshot.pages}
        previous_flow_keys = {f"{flow.page_id}|{flow.trigger_label}|{flow.flow_type}" for flow in previous_snapshot.interaction_flows}
        current_flow_keys = {f"{flow.page_id}|{flow.trigger_label}|{flow.flow_type}" for flow in snapshot.interaction_flows}
        previous_counts = {
            "pages": len(previous_snapshot.pages),
            "forms": len(previous_snapshot.forms),
            "fields": sum(1 for element in previous_snapshot.elements if _is_config_field(element, include_hidden=True)),
            "flows": len(previous_snapshot.interaction_flows),
        }
        convergence.update(
            {
                "status": "converged"
                if not (current_page_keys - previous_page_keys or current_form_keys - previous_form_keys or current_field_keys - previous_field_keys or current_flow_keys - previous_flow_keys)
                else "still_discovering",
                "new_pages": len(current_page_keys - previous_page_keys),
                "new_forms": len(current_form_keys - previous_form_keys),
                "new_fields": len(current_field_keys - previous_field_keys),
                "new_flows": len(current_flow_keys - previous_flow_keys),
                "new_settings": None,
            }
        )

    page_field_counts = Counter(element.page_id for element in field_elements)
    page_value_counts = Counter(element.page_id for element in field_elements if _element_has_value(element))
    invariant_gaps = [
        {
            "page_id": page_id,
            "fields": count,
            "values": page_value_counts.get(page_id, 0),
            "reason": "page exposes many configurable controls but few/no current values were extracted",
        }
        for page_id, count in sorted(page_field_counts.items())
        if count >= 5 and page_value_counts.get(page_id, 0) < max(1, count // 4)
    ]
    config_surface_count = len(visible_fields) + len(readonly_elements)
    value_ratio = _ratio(settings_extracted, config_surface_count)
    evidence_ratio = _ratio(elements_with_evidence, len(snapshot.elements))
    flow_ratio = _ratio(opened_and_canceled, len(snapshot.interaction_flows))
    action_tool_ratio = _ratio(len(forms_requiring_action_tools) - len(forms_without_action_tools), len(forms_requiring_action_tools))
    restorable_settings_ratio = _ratio(restorable_settings, settings_extracted)
    doc_mapping_ratio = _ratio(len(schema.ontology) - len(unmapped_doc_terms), len(schema.ontology)) if schema else 1.0
    convergence_ratio = 1.0 if convergence["status"] in {"converged", "unknown"} else 0.65
    confidence = round(
        0.16 * value_ratio
        + 0.12 * evidence_ratio
        + 0.12 * flow_ratio
        + 0.16 * action_tool_ratio
        + 0.14 * doc_mapping_ratio
        + 0.10 * _ratio(len(snapshot.forms) - len(forms_without_values), len(snapshot.forms))
        + 0.08 * convergence_ratio
        + 0.12 * restorable_settings_ratio,
        4,
    )
    gaps = []
    if forms_without_values:
        gaps.append(
            {
                "severity": "warning",
                "kind": "missing_current_values",
                "summary": f"{len(forms_without_values)} form(s) have configurable fields but no extracted current values.",
                "ids": forms_without_values[:100],
            }
        )
    if forms_without_action_tools:
        gaps.append(
            {
                "severity": "error",
                "kind": "missing_restore_or_write_tools",
                "summary": f"{len(forms_without_action_tools)} form(s) have configurable fields without matching ui_form/ui_flow tool evidence.",
                "ids": forms_without_action_tools[:100],
            }
        )
    if unprobed_actions:
        gaps.append(
            {
                "severity": "warning",
                "kind": "unprobed_dynamic_actions",
                "summary": f"{len(unprobed_actions)} likely reveal/edit action(s) were not probed and canceled.",
                "ids": [item["id"] for item in unprobed_actions[:100]],
            }
        )
    if unmapped_doc_terms:
        gaps.append(
            {
                "severity": "warning",
                "kind": "documentation_concepts_not_seen",
                "summary": f"{len(unmapped_doc_terms)} ontology term(s) were not mapped to UI elements.",
                "ids": [item["id"] for item in unmapped_doc_terms[:100]],
            }
        )
    if invariant_gaps:
        gaps.append(
            {
                "severity": "warning",
                "kind": "ui_invariant_gap",
                "summary": f"{len(invariant_gaps)} page(s) look under-extracted based on field/value ratios.",
                "ids": [item["page_id"] for item in invariant_gaps[:100]],
            }
        )
    return {
        "profile_id": profile_id,
        "profile_name": profile_name,
        "run_id": snapshot.run_id,
        "settings_snapshot_run_id": _settings_snapshot_run_id(settings_snapshot),
        "generated_at": utc_now(),
        "confidence": {
            "score": confidence,
            "band": "high" if confidence >= 0.85 else "medium" if confidence >= 0.60 else "low",
            "weights": {
                "settings_value_coverage": 0.16,
                "ui_evidence_coverage": 0.12,
                "dynamic_flow_cancel_coverage": 0.12,
                "restore_or_write_tool_coverage": 0.16,
                "documentation_mapping_coverage": 0.14,
                "form_value_coverage": 0.10,
                "convergence": 0.08,
                "restorable_settings": 0.12,
            },
            "components": {
                "settings_value_coverage": value_ratio,
                "ui_evidence_coverage": evidence_ratio,
                "dynamic_flow_cancel_coverage": flow_ratio,
                "restore_or_write_tool_coverage": action_tool_ratio,
                "documentation_mapping_coverage": doc_mapping_ratio,
                "form_value_coverage": _ratio(len(snapshot.forms) - len(forms_without_values), len(snapshot.forms)),
                "convergence": convergence_ratio,
                "restorable_settings": restorable_settings_ratio,
            },
        },
        "scope": {
            "pages_seen": len(snapshot.pages),
            "forms_seen": len(snapshot.forms),
            "fields_seen": len(field_elements),
            "visible_fields_seen": len(visible_fields),
            "hidden_fields_seen": len(hidden_fields),
            "actions_seen": len(action_elements),
            "readonly_values_seen": len(readonly_elements),
            "interaction_flows_seen": len(snapshot.interaction_flows),
            "settings_extracted": settings_extracted,
            "restorable_settings": restorable_settings,
            "non_restorable_settings": max(0, settings_extracted - restorable_settings),
            "previous_counts": previous_counts,
        },
        "evidence_coverage": {
            "ui_elements_with_evidence": elements_with_evidence,
            "ui_elements_without_evidence": max(0, len(snapshot.elements) - elements_with_evidence),
            "forms_with_current_values": len(forms_with_values),
            "forms_without_current_values": len(forms_without_values),
            "dynamic_flows_opened_and_canceled": opened_and_canceled,
            "dynamic_flows_without_cancel_evidence": max(0, len(snapshot.interaction_flows) - opened_and_canceled),
            "mappings_ready": ready_mappings,
            "mappings_review": review_mappings,
            "mappings_internal": internal_mappings,
        },
        "tool_coverage": {
            "tools": len(tools),
            "source_type_counts": dict(source_counts),
            "risk_counts": dict(risk_counts),
            "form_action_binding_tools": len(action_binding_tool_names),
            "forms_requiring_restore_or_write_tools": len(forms_requiring_action_tools),
            "forms_without_restore_or_write_tools": forms_without_action_tools,
            "uncovered_form_ratio": 1.0 - action_tool_ratio,
            "restorable_settings": restorable_settings,
            "non_restorable_settings": max(0, settings_extracted - restorable_settings),
            "restorable_setting_ratio": restorable_settings_ratio,
        },
        "dynamic_probing": {
            "probed_action_labels": sorted(triggered_labels),
            "unprobed_actions": unprobed_actions,
        },
        "documentation_gap_check": {
            "ontology_terms": len(schema.ontology) if schema else 0,
            "unmapped_terms": unmapped_doc_terms,
        },
        "ui_invariant_gaps": invariant_gaps,
        "convergence": convergence,
        "gaps": gaps,
        "recommended_next_actions": [
            "Run an AI/doc-guided crawl plan for documentation terms that are not mapped.",
            "Probe Add/Edit/Advanced flows in dry-run/cancel mode until no new forms or fields appear.",
            "Extract current values for every configurable form before treating restore coverage as complete.",
            "Generate or refresh ui_form/ui_flow tools for every discovered form, then rerun this report.",
            "Repeat crawl/merge/coverage until the convergence section reports no new pages, forms, fields, or flows.",
        ],
    }
