from __future__ import annotations

import re
from pathlib import Path

from site_agent.core.actions import classify_action_risk
from site_agent.core.models import AdapterBinding, CrawlSnapshot, Form, MappedSchema, ToolSpec
from site_agent.core.storage import write_json


ACTIVATION_LABEL_RE = re.compile(r"\b(enable|enabled|active|activate|on|status|state)\b", re.I)
DELETE_TRIGGER_RE = re.compile(r"\b(delete|remove|trash|discard)\b", re.I)


def unique_name(name: str, seen: set[str]) -> str:
    if name not in seen:
        seen.add(name)
        return name
    index = 2
    while f"{name}_{index}" in seen:
        index += 1
    candidate = f"{name}_{index}"
    seen.add(candidate)
    return candidate


def tool_name(canonical_name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", canonical_name.lower()).strip("_")
    return f"get_{slug}" if slug else "get_concept"


def action_tool_name(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    if not slug or slug == "form":
        slug = "submit_form"
    if not slug.startswith(("submit_", "save_", "apply_", "send_", "export_")):
        slug = f"submit_{slug}"
    return slug


def generic_form_label(label: str) -> bool:
    clean = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    return clean in {"", "form", "submit", "save", "apply", "ok", "refresh", "off", "on", "low", "middle", "high"}


def machine_like_label(label: str) -> bool:
    clean = label.strip()
    normalized = re.sub(r"[^a-zA-Z0-9]+", "_", clean).strip("_")
    if not normalized:
        return True
    if " " not in clean and re.search(r"\d", normalized):
        return True
    if "_" in normalized and normalized.lower() == normalized:
        return True
    return normalized.lower() in {"password", "hash", "dscp"}


def form_purpose_label(form: Form, page_label: str, fields: list, classification: dict | None = None) -> str:
    if classification and float(classification.get("confidence", 0.0) or 0.0) >= 0.65:
        purpose = str(classification.get("semantic_purpose", "")).strip()
        if purpose and purpose != "unknown":
            return purpose
    button = next((field for field in fields if field.control_type in {"submit", "button"}), None)
    candidate = button.label if button else form.label
    if page_label and not generic_form_label(page_label):
        if generic_form_label(candidate) or machine_like_label(candidate):
            return page_label
    if not generic_form_label(candidate):
        return candidate
    if page_label and not generic_form_label(page_label):
        return page_label
    useful_fields = [
        field.label
        for field in fields
        if field.control_type not in {"submit", "button", "hidden"} and not generic_form_label(field.label)
    ]
    if useful_fields:
        return " ".join(useful_fields[:3])
    return form.label or "form"


def classified_action_tool_name(label: str, classification: dict | None = None) -> str:
    if not classification or float(classification.get("confidence", 0.0) or 0.0) < 0.75:
        return action_tool_name(label)
    operation = str(classification.get("operation", "")).lower()
    subject = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or "form"
    if operation in {"create", "add"}:
        return f"create_{subject}"
    if operation in {"create_or_update", "update", "configure", "set"}:
        return f"submit_{subject}"
    if operation in {"delete", "remove"}:
        return f"delete_{subject}"
    if operation in {"enable", "disable", "activate", "deactivate"}:
        return f"{operation}_{subject}"
    return action_tool_name(label)


def field_shape_label(label: str) -> str:
    clean = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
    clean = re.sub(r"\b\d+\b", "", clean)
    return re.sub(r"\s+", " ", clean).strip()


def semantic_form_dedupe_key(label: str, fields: list, classification: dict | None = None) -> tuple | None:
    classified = bool(classification and float(classification.get("confidence", 0.0) or 0.0) >= 0.65)
    useful = [
        (field_shape_label(field.label), field.control_type)
        for field in fields
        if field.control_type not in {"submit", "button", "hidden", "radio"} and not generic_form_label(field.label)
    ]
    useful = [(field_label, control_type) for field_label, control_type in useful if field_label]
    if not useful:
        return None
    if not classified and len(useful) < 4:
        return None
    purpose = str(classification.get("semantic_purpose", "")).strip().lower() if classified and classification else field_shape_label(label)
    operation = str(classification.get("operation", "")).strip().lower() if classified and classification else "submit"
    return (purpose, operation, tuple(sorted(useful)))


def staged_subject(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    parts = [part for part in slug.split("_") if part]
    while parts and parts[0] in {"add", "create", "new", "open", "show"}:
        parts.pop(0)
    if parts == ["item"] or not parts:
        return "item"
    return "_".join(parts)


def staged_tool_name(stage: str, label: str) -> str:
    return f"{stage}_{staged_subject(label)}"


def page_tool_name(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_")
    return f"get_{slug or 'page'}"


def synthesize_tools(
    profile_id: str,
    schema: MappedSchema,
    selector_lookup: dict[str, str],
    value_lookup: dict[str, str] | None = None,
    description_lookup: dict[str, str] | None = None,
) -> tuple[list[ToolSpec], list[AdapterBinding]]:
    tools: list[ToolSpec] = []
    bindings: list[AdapterBinding] = []
    seen: set[str] = set()
    for mapping in schema.mappings:
        if mapping.status != "ready":
            continue
        name = tool_name(mapping.canonical_name)
        name = unique_name(name, seen)
        tools.append(
            ToolSpec(
                name=name,
                description=(description_lookup or {}).get(mapping.ui_element_id)
                or f"Read {mapping.canonical_name} using approved profile evidence.",
                args={"type": "object", "properties": {}, "additionalProperties": False},
                return_schema={"type": "object", "properties": {"value": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                risk_level="low",
                evidence_ids=mapping.evidence_ids,
                confidence=mapping.confidence,
                source_type="canonical_concept",
                reasoning_summary=mapping.reasoning_summary,
            )
        )
        bindings.append(
            AdapterBinding(
                tool_name=name,
                profile_id=profile_id,
                version="0.1.0",
                selector_action_bindings={
                    "ui_element_id": mapping.ui_element_id,
                    "selector_fingerprint": selector_lookup.get(mapping.ui_element_id),
                    "action": "read",
                    "read_value": (value_lookup or {}).get(mapping.ui_element_id),
                },
            )
        )
    return tools, bindings


def apply_tool_aliases(tools: list[ToolSpec], aliases: dict[str, str]) -> list[str]:
    """Attach profile-declared compatibility aliases to their target tools."""
    if not aliases:
        return []
    by_name = {tool.name: tool for tool in tools}
    applied: list[str] = []
    public_names = set(by_name)
    for alias, target in sorted(aliases.items()):
        alias = alias.strip()
        target = target.strip()
        if not alias or not target or alias in public_names or target not in by_name:
            continue
        target_tool = by_name[target]
        if alias not in target_tool.compatibility_aliases:
            target_tool.compatibility_aliases.append(alias)
            applied.append(alias)
    return applied


def readable_page_label(url: str, title: str, headings: list[str]) -> str:
    if headings:
        return headings[0]
    fragment = url.split("#state=", 1)[1] if "#state=" in url else ""
    if fragment:
        return " ".join(part.replace("-", " ").title() for part in fragment.split("/")[-2:])
    return title or "Page"


def field_arg_name(label: str, fallback: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", label.lower()).strip("_") or fallback


def unique_arg_name(base: str, seen: set[str]) -> str:
    if base not in seen:
        seen.add(base)
        return base
    index = 2
    while f"{base}_{index}" in seen:
        index += 1
    candidate = f"{base}_{index}"
    seen.add(candidate)
    return candidate


def json_schema_for_field(label: str, constraints: dict) -> dict:
    schema: dict = {"type": "string", "description": label}
    if "maxlength" in constraints:
        try:
            schema["maxLength"] = int(constraints["maxlength"])
        except (TypeError, ValueError):
            pass
    if "minlength" in constraints:
        try:
            schema["minLength"] = int(constraints["minlength"])
        except (TypeError, ValueError):
            pass
    if "pattern" in constraints:
        schema["pattern"] = str(constraints["pattern"])
    if "range" in constraints and isinstance(constraints["range"], list) and len(constraints["range"]) == 2:
        schema["description"] = f"{label}. Observed range: {constraints['range'][0]} to {constraints['range'][1]}."
    return schema


def action_required_args() -> list[str]:
    # UI actions are dry-run by default and the runtime can plan/apply with
    # partial arguments. Marking every captured form control as required makes
    # generated MCP/Ansible tasks unusable for review-first workflows.
    return []


def flow_field_specs(flow, element_by_id: dict) -> tuple[dict, list[str], list[dict]]:
    properties: dict = {}
    required: list[str] = []
    bindings: list[dict] = []
    seen_args: set[str] = set()
    for field_id in flow.discovered_field_ids:
        field = element_by_id.get(field_id)
        if not field or field.control_type in {"submit", "button", "hidden"}:
            continue
        arg = unique_arg_name(field_arg_name(field.label, field.id), seen_args)
        constraints = {}
        constraints.update(field.context.get("constraints", {}) if isinstance(field.context, dict) else {})
        constraints.update(flow.constraints.get(field_id, {}) if isinstance(flow.constraints, dict) else {})
        properties[arg] = json_schema_for_field(field.label, constraints)
        required.append(arg)
        bindings.append(
            {
                "ui_element_id": field.id,
                "label": field.label,
                "arg": arg,
                "control_type": field.control_type,
                "selector_fingerprint": field.selector_fingerprint,
                "selector_id": field.context.get("selector_id") if isinstance(field.context, dict) else None,
                "selector_name": field.context.get("selector_name") if isinstance(field.context, dict) else None,
                "constraints": constraints,
            }
        )
    return properties, required, bindings


def flow_has_activation_field(flow, element_by_id: dict) -> bool:
    for field_id in flow.discovered_field_ids:
        field = element_by_id.get(field_id)
        if field and ACTIVATION_LABEL_RE.search(f"{field.label} {field.id} {field.control_type}"):
            return True
    return False


def flow_has_delete_evidence(flow, element_by_id: dict) -> bool:
    text = flow.trigger_label
    for field_id in flow.discovered_field_ids:
        field = element_by_id.get(field_id)
        if field:
            text += f" {field.label} {field.id}"
    return bool(DELETE_TRIGGER_RE.search(text))


def synthesize_page_tools(profile_id: str, snapshot: CrawlSnapshot, seen_names: set[str] | None = None) -> tuple[list[ToolSpec], list[AdapterBinding]]:
    return synthesize_unmapped_page_tools(profile_id, snapshot, set(), seen_names)


def synthesize_flow_tools(
    profile_id: str,
    snapshot: CrawlSnapshot,
    element_by_id: dict,
    seen_names: set[str],
) -> tuple[list[ToolSpec], list[AdapterBinding]]:
    tools: list[ToolSpec] = []
    bindings: list[AdapterBinding] = []
    page_by_id = {page.id: page for page in snapshot.pages}
    for flow in snapshot.interaction_flows:
        field_properties, discovered_required, field_bindings = flow_field_specs(flow, element_by_id)
        required = action_required_args()
        subject = staged_subject(flow.trigger_label)
        evidence_ids = list(flow.evidence_ids)
        for field in field_bindings:
            element = element_by_id.get(field["ui_element_id"])
            if element:
                evidence_ids.extend(element.evidence_ids)
        common_properties = {
            **field_properties,
            "dry_run": {"type": "boolean", "default": True},
            "confirm": {"type": "boolean", "default": False, "description": "Required for apply mode when this tool requires confirmation."},
        }
        create_name = unique_name(staged_tool_name("create", flow.trigger_label), seen_names)
        tools.append(
            ToolSpec(
                name=create_name,
                description=(
                    f"Stage the {flow.trigger_label} workflow to create {subject}. "
                    "The adapter opens the discovered dynamic form, fills observed fields, and is dry-run by default. "
                    "Observed cancel support is recorded so probing can avoid unnecessary changes."
                ),
                args={"type": "object", "properties": common_properties, "required": required, "additionalProperties": False},
                return_schema={"type": "object", "properties": {"status": {"type": "string"}, "planned_steps": {"type": "array"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                risk_level="medium",
                evidence_ids=evidence_ids,
                confidence=0.82 if discovered_required else 0.68,
                requires_confirmation=True,
                dry_run_supported=True,
                exposure_level="review_required",
                source_type="ui_flow",
                reasoning_summary=(
                    "Generated from an observed dynamic form flow. The crawler opened the flow, captured newly visible controls and constraints, "
                    "then used cancel/backout evidence instead of applying changes."
                ),
            )
        )
        bindings.append(
            AdapterBinding(
                tool_name=create_name,
                profile_id=profile_id,
                version="0.1.0",
                selector_action_bindings={
                    "action": "open_fill_dynamic_form",
                    "flow_id": flow.id,
                    "page_id": flow.page_id,
                    "page_url": page_by_id.get(flow.page_id).url if page_by_id.get(flow.page_id) else "",
                    "trigger_label": flow.trigger_label,
                    "flow_type": flow.flow_type,
                    "fields": field_bindings,
                    "requires_open_before_submit": flow.requires_open_before_submit,
                    "cancel_supported": flow.cancel_supported,
                    "constraints": flow.constraints,
                    "evidence_ids": flow.evidence_ids,
                },
            )
        )
        if flow_has_activation_field(flow, element_by_id):
            for stage, desired_state in (("activate", "on"), ("deactivate", "off")):
                state_name = unique_name(staged_tool_name(stage, flow.trigger_label), seen_names)
                tools.append(
                    ToolSpec(
                        name=state_name,
                        description=f"Stage a state change that sets {subject} to {desired_state}. Dry-run by default and requires confirmation before apply.",
                        args={
                            "type": "object",
                            "properties": {
                                "item_match": {"type": "object", "description": "Stable field values used to identify the existing item."},
                                "dry_run": {"type": "boolean", "default": True},
                                "confirm": {"type": "boolean", "default": False},
                            },
                            "required": ["item_match"],
                            "additionalProperties": False,
                        },
                        return_schema={"type": "object", "properties": {"status": {"type": "string"}, "planned_steps": {"type": "array"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                        risk_level="medium",
                        evidence_ids=evidence_ids,
                        confidence=0.72,
                        requires_confirmation=True,
                        dry_run_supported=True,
                        exposure_level="review_required",
                        source_type="ui_flow",
                        reasoning_summary="Generated because the discovered flow includes activation/state-like controls. Human review should confirm the target identity fields.",
                    )
                )
                bindings.append(
                    AdapterBinding(
                        tool_name=state_name,
                        profile_id=profile_id,
                        version="0.1.0",
                        selector_action_bindings={
                            "action": "set_dynamic_item_state",
                            "flow_id": flow.id,
                            "page_id": flow.page_id,
                            "page_url": page_by_id.get(flow.page_id).url if page_by_id.get(flow.page_id) else "",
                            "trigger_label": flow.trigger_label,
                            "desired_state": desired_state,
                            "fields": field_bindings,
                            "constraints": flow.constraints,
                            "evidence_ids": flow.evidence_ids,
                        },
                    )
                )
        explicit_delete_evidence = flow_has_delete_evidence(flow, element_by_id)
        if explicit_delete_evidence or field_bindings:
            delete_name = unique_name(staged_tool_name("delete", flow.trigger_label), seen_names)
            tools.append(
                ToolSpec(
                    name=delete_name,
                    description=f"Stage deletion/removal of {subject}. This high-risk tool is generated only as an internal candidate until reviewed.",
                    args={
                        "type": "object",
                        "properties": {
                            "item_match": {"type": "object", "description": "Stable field values used to identify the existing item."},
                            "dry_run": {"type": "boolean", "default": True},
                            "confirm": {"type": "boolean", "default": False},
                        },
                        "required": ["item_match"],
                        "additionalProperties": False,
                    },
                    return_schema={"type": "object", "properties": {"status": {"type": "string"}, "planned_steps": {"type": "array"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                    risk_level="high",
                    evidence_ids=evidence_ids,
                    confidence=0.62 if explicit_delete_evidence else 0.45,
                    requires_confirmation=True,
                    dry_run_supported=True,
                    exposure_level="internal_disabled",
                    source_type="ui_flow",
                    reasoning_summary=(
                        "Generated from delete/remove evidence in the observed flow. Kept internal until human review approves the identity and rollback policy."
                        if explicit_delete_evidence
                        else "Generated as an internal lifecycle candidate from an observed item-creation flow. Safe probing did not prove delete controls, so this remains disabled until reviewed."
                    ),
                )
            )
            bindings.append(
                AdapterBinding(
                    tool_name=delete_name,
                    profile_id=profile_id,
                    version="0.1.0",
                    selector_action_bindings={
                        "action": "delete_dynamic_item",
                        "flow_id": flow.id,
                        "page_id": flow.page_id,
                        "page_url": page_by_id.get(flow.page_id).url if page_by_id.get(flow.page_id) else "",
                        "trigger_label": flow.trigger_label,
                        "fields": field_bindings,
                        "constraints": flow.constraints,
                        "evidence_ids": flow.evidence_ids,
                    },
                )
            )
    return tools, bindings


def synthesize_unmapped_page_tools(
    profile_id: str,
    snapshot: CrawlSnapshot,
    covered_element_ids: set[str],
    seen_names: set[str] | None = None,
) -> tuple[list[ToolSpec], list[AdapterBinding]]:
    seen = seen_names if seen_names is not None else set()
    elements_by_page: dict[str, list] = {}
    for element in snapshot.elements:
        if element.id in covered_element_ids:
            continue
        if element.control_type == "readonly_status" or "read_value" in element.context:
            elements_by_page.setdefault(element.page_id, []).append(element)
    page_by_id = {page.id: page for page in snapshot.pages}
    tools: list[ToolSpec] = []
    bindings: list[AdapterBinding] = []
    for page_id, elements in elements_by_page.items():
        if not elements:
            continue
        page = page_by_id.get(page_id)
        label = readable_page_label(page.url, page.title, page.headings) if page else "Page"
        name = unique_name(page_tool_name(label), seen)
        values = {re.sub(r"[^a-z0-9]+", "_", element.label.lower()).strip("_") or element.id: element.context.get("read_value", "") for element in elements}
        evidence_ids = [eid for element in elements for eid in element.evidence_ids]
        tools.append(
            ToolSpec(
                name=name,
                description=f"Read UI-backed status values from {label}. This tool is generated from discovered UI evidence even when no external documentation exists.",
                args={"type": "object", "properties": {}, "additionalProperties": False},
                return_schema={"type": "object", "properties": {"values": {"type": "object"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                risk_level="low",
                evidence_ids=evidence_ids,
                confidence=0.8,
                exposure_level="ready_public",
                source_type="ui_page",
                reasoning_summary="Generated from discovered read-only UI values. External documentation is helpful but not required for UI-backed read coverage.",
            )
        )
        bindings.append(
            AdapterBinding(
                tool_name=name,
                profile_id=profile_id,
                version="0.1.0",
                selector_action_bindings={
                    "action": "read_page",
                    "page_id": page_id,
                    "values": values,
                    "element_ids": [element.id for element in elements],
                },
            )
        )
    return tools, bindings


def synthesize_form_tools(
    profile_id: str,
    snapshot: CrawlSnapshot,
    seen_names: set[str] | None = None,
    form_classifications: dict[str, dict] | None = None,
) -> tuple[list[ToolSpec], list[AdapterBinding]]:
    element_by_id = {element.id: element for element in snapshot.elements}
    flows_by_page: dict[str, list] = {}
    for flow in snapshot.interaction_flows:
        flows_by_page.setdefault(flow.page_id, []).append(flow)
    tools: list[ToolSpec] = []
    bindings: list[AdapterBinding] = []
    seen = seen_names if seen_names is not None else set()
    page_by_id = {page.id: page for page in snapshot.pages}
    emitted_semantic_forms: dict[tuple, int] = {}
    for form in snapshot.forms:
        fields = [element_by_id[field_id] for field_id in form.field_ids if field_id in element_by_id]
        if not fields:
            continue
        page = page_by_id.get(form.page_id)
        page_label = readable_page_label(page.url, page.title, page.headings) if page else ""
        classification = (form_classifications or {}).get(form.id)
        label = form_purpose_label(form, page_label, fields, classification)
        dedupe_key = semantic_form_dedupe_key(label, fields, classification)
        if dedupe_key and dedupe_key in emitted_semantic_forms:
            index = emitted_semantic_forms[dedupe_key]
            tool = tools[index]
            binding = bindings[index]
            tool.evidence_ids = sorted(dict.fromkeys([*tool.evidence_ids, *(eid for field in fields for eid in field.evidence_ids)]))
            adapter = binding.selector_action_bindings
            source_form_ids = {str(value) for value in adapter.get("source_form_ids", []) if value}
            if adapter.get("form_id"):
                source_form_ids.add(str(adapter["form_id"]))
            source_form_ids.add(form.id)
            source_field_ids = {str(value) for value in adapter.get("source_field_ids", []) if value}
            for field in adapter.get("fields", []) or []:
                if isinstance(field, dict) and field.get("ui_element_id"):
                    source_field_ids.add(str(field["ui_element_id"]))
            source_field_ids.update(field.id for field in fields if field.control_type not in {"submit", "button", "hidden"})
            adapter["source_form_ids"] = sorted(source_form_ids)
            adapter["source_field_ids"] = sorted(source_field_ids)
            continue
        if dedupe_key:
            emitted_semantic_forms[dedupe_key] = len(tools)
        risk_level, risk_reason = classify_action_risk(label, [field.label for field in fields])
        name = unique_name(classified_action_tool_name(label, classification), seen)
        properties = {}
        required = action_required_args()
        form_field_bindings = []
        seen_args: set[str] = set()
        for field in fields:
            if field.control_type in {"submit", "button", "hidden"}:
                continue
            arg = unique_arg_name(field_arg_name(field.label, field.id), seen_args)
            properties[arg] = {"type": "string", "description": field.label}
            form_field_bindings.append(
                {
                    "ui_element_id": field.id,
                    "label": field.label,
                    "arg": arg,
                    "control_type": field.control_type,
                }
            )
        properties["dry_run"] = {"type": "boolean", "default": True}
        properties["confirm"] = {"type": "boolean", "default": False, "description": "Required for apply mode when this tool requires confirmation."}
        evidence_ids = [eid for field in fields for eid in field.evidence_ids]
        page_flows = flows_by_page.get(form.page_id, [])
        if page_flows:
            evidence_ids.extend(eid for flow in page_flows for eid in flow.evidence_ids)
        exposure = "ready_public" if risk_level == "low" else "review_required" if risk_level == "medium" else "internal_disabled"
        flow_summary = (
            " Observed dynamic form flow: "
            + "; ".join(f"{flow.trigger_label} opens {len(flow.discovered_field_ids)} field(s)" for flow in page_flows[:2])
            if page_flows
            else ""
        )
        classification_summary = ""
        if classification:
            negatives = ", ".join(classification.get("negative_concepts", [])[:4])
            classification_summary = (
                f" Classified purpose: {classification.get('semantic_purpose')} ({classification.get('operation')}, "
                f"confidence {classification.get('confidence')}). {classification.get('reasoning_summary', '')}"
                + (f" Not: {negatives}." if negatives else "")
            )
        tools.append(
            ToolSpec(
                name=name,
                description=f"UI-backed form action for {label}. Generated from discovered UI evidence even without external documentation. Dry-run by default. Risk: {risk_level}. {risk_reason}{flow_summary}{classification_summary}",
                args={"type": "object", "properties": properties, "required": required, "additionalProperties": False},
                return_schema={"type": "object", "properties": {"status": {"type": "string"}, "evidence_ids": {"type": "array", "items": {"type": "string"}}}},
                risk_level=risk_level,
                evidence_ids=evidence_ids,
                confidence=0.85,
                requires_confirmation=risk_level in {"medium", "high"},
                dry_run_supported=True,
                exposure_level=exposure,
                source_type="ui_form",
                reasoning_summary=(classification.get("reasoning_summary") if classification else f"Generated from discovered form controls and action labels. {risk_reason}"),
            )
        )
        bindings.append(
            AdapterBinding(
                tool_name=name,
                profile_id=profile_id,
                version="0.1.0",
                selector_action_bindings={
                    "action": "submit_form",
                    "method": form.method or "get",
                    "action_url": form.action,
                    "form_id": form.id,
                    "purpose_label": label,
                    "page_label": page_label,
                    "form_classification": classification,
                    "fields": form_field_bindings,
                    "interaction_flows": [
                        {
                            "flow_id": flow.id,
                            "trigger_label": flow.trigger_label,
                            "flow_type": flow.flow_type,
                            "requires_open_before_submit": flow.requires_open_before_submit,
                            "cancel_supported": flow.cancel_supported,
                            "constraints": flow.constraints,
                            "evidence_ids": flow.evidence_ids,
                        }
                        for flow in page_flows
                    ],
                },
            )
        )
    flow_tools, flow_bindings = synthesize_flow_tools(profile_id, snapshot, element_by_id, seen)
    tools.extend(flow_tools)
    bindings.extend(flow_bindings)
    return tools, bindings


def write_mcp_package(base_dir: Path, profile_name: str, tools: list[ToolSpec], bindings: list[AdapterBinding], base_url: str | None = None) -> None:
    package_dir = base_dir / "output" / profile_name / "mcp"
    write_json(package_dir / "tools.json", {"tools": tools})
    write_json(package_dir / "adapter.bindings.json", {"bindings": bindings})
    server = {
        "name": f"site-agent-{profile_name}",
        "version": "0.1.0",
        "description": "Generated MCP contract metadata. Runtime adapters resolve private selector bindings.",
        "tools_file": "tools.json",
        "adapter_file": "adapter.bindings.json",
        "base_url": base_url,
    }
    write_json(package_dir / "server.json", server)
