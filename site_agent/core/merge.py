from __future__ import annotations

from pathlib import Path

from site_agent.core.models import CrawlSnapshot, Evidence, Form, InteractionFlow, Page, Transition, UiElement, new_id, utc_now
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import write_json


def page_key(page: Page) -> str:
    return page.url


def evidence_key(evidence: Evidence) -> tuple:
    return (evidence.kind, evidence.source, evidence.summary, evidence.locator)


def element_key(element: UiElement) -> tuple:
    return (element.page_id, element.selector_fingerprint, element.label, element.control_type)


def form_key(form: Form) -> tuple:
    return (form.page_id, form.label, form.action, form.method, tuple(form.field_ids))


def transition_key(transition: Transition) -> tuple:
    return (transition.source_page_id, transition.target_url, transition.trigger_label, transition.risk_level)


def flow_key(flow: InteractionFlow) -> tuple:
    return (flow.page_id, flow.trigger_label, flow.flow_type, tuple(flow.discovered_field_ids))


def state_path_from_url(url: str) -> list[str]:
    if "#state=" not in url:
        return []
    return [part for part in url.split("#state=", 1)[1].split("/") if part]


def label_from_slug(value: str) -> str:
    return " ".join(part.capitalize() for part in value.replace("-", " ").split())


def merge_snapshots(profile: Profile, base: CrawlSnapshot, probe: CrawlSnapshot) -> tuple[CrawlSnapshot, dict]:
    merged = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id=new_id("merged"))
    page_id_map: dict[str, str] = {}
    evidence_id_map: dict[str, str] = {}
    element_id_map: dict[str, str] = {}

    pages_by_key: dict[str, Page] = {}
    added_pages: list[dict] = []
    for snapshot in [base, probe]:
        for page in snapshot.pages:
            key = page_key(page)
            if key in pages_by_key:
                page_id_map[page.id] = pages_by_key[key].id
                continue
            pages_by_key[key] = page
            page_id_map[page.id] = page.id
            merged.pages.append(page)
            if snapshot is probe and key not in {page_key(item) for item in base.pages}:
                path = state_path_from_url(page.url)
                added_pages.append(
                    {
                        "page_id": page.id,
                        "url": page.url,
                        "source_run_id": probe.run_id,
                        "source_state_path": path,
                        "source_plan_labels": [label_from_slug(item) for item in path],
                    }
                )

    evidence_by_key: dict[tuple, Evidence] = {}
    for snapshot in [base, probe]:
        for evidence in snapshot.evidence:
            key = evidence_key(evidence)
            if key in evidence_by_key:
                evidence_id_map[evidence.id] = evidence_by_key[key].id
                continue
            evidence_by_key[key] = evidence
            evidence_id_map[evidence.id] = evidence.id
            merged.evidence.append(evidence)

    elements_by_key: dict[tuple, UiElement] = {}
    added_elements: list[dict] = []
    base_element_keys: set[tuple] = set()
    for snapshot in [base, probe]:
        for element in snapshot.elements:
            remapped_page_id = page_id_map.get(element.page_id, element.page_id)
            remapped = UiElement(
                id=element.id,
                page_id=remapped_page_id,
                selector_fingerprint=element.selector_fingerprint,
                label=element.label,
                control_type=element.control_type,
                context=dict(element.context),
                evidence_ids=[evidence_id_map.get(eid, eid) for eid in element.evidence_ids],
            )
            key = element_key(remapped)
            if snapshot is base:
                base_element_keys.add(key)
            if key in elements_by_key:
                element_id_map[element.id] = elements_by_key[key].id
                continue
            elements_by_key[key] = remapped
            element_id_map[element.id] = remapped.id
            merged.elements.append(remapped)
            if snapshot is probe and key not in base_element_keys:
                source_page = next((page for page in probe.pages if page.id == element.page_id), None)
                path = state_path_from_url(source_page.url) if source_page else []
                added_elements.append(
                    {
                        "ui_element_id": remapped.id,
                        "label": remapped.label,
                        "control_type": remapped.control_type,
                        "source_run_id": probe.run_id,
                        "source_state_path": path,
                        "source_plan_labels": [label_from_slug(item) for item in path],
                    }
                )

    forms_by_key: dict[tuple, Form] = {}
    added_forms: list[dict] = []
    base_form_keys: set[tuple] = set()
    for snapshot in [base, probe]:
        for form in snapshot.forms:
            remapped = Form(
                id=form.id,
                page_id=page_id_map.get(form.page_id, form.page_id),
                label=form.label,
                action=form.action,
                method=form.method,
                field_ids=[element_id_map.get(field_id, field_id) for field_id in form.field_ids],
            )
            key = form_key(remapped)
            if snapshot is base:
                base_form_keys.add(key)
            if key in forms_by_key:
                continue
            forms_by_key[key] = remapped
            merged.forms.append(remapped)
            if snapshot is probe and key not in base_form_keys:
                source_page = next((page for page in probe.pages if page.id == form.page_id), None)
                path = state_path_from_url(source_page.url) if source_page else []
                added_forms.append(
                    {
                        "form_id": remapped.id,
                        "label": remapped.label,
                        "source_run_id": probe.run_id,
                        "source_state_path": path,
                        "source_plan_labels": [label_from_slug(item) for item in path],
                    }
                )

    transitions_by_key: dict[tuple, Transition] = {}
    for snapshot in [base, probe]:
        for transition in snapshot.transitions:
            remapped = Transition(
                source_page_id=page_id_map.get(transition.source_page_id, transition.source_page_id),
                target_url=transition.target_url,
                trigger_label=transition.trigger_label,
                risk_level=transition.risk_level,
            )
            key = transition_key(remapped)
            if key in transitions_by_key:
                continue
            transitions_by_key[key] = remapped
            merged.transitions.append(remapped)

    flows_by_key: dict[tuple, InteractionFlow] = {}
    for snapshot in [base, probe]:
        for flow in snapshot.interaction_flows:
            remapped = InteractionFlow(
                id=flow.id,
                page_id=page_id_map.get(flow.page_id, flow.page_id),
                trigger_label=flow.trigger_label,
                flow_type=flow.flow_type,
                discovered_field_ids=[element_id_map.get(field_id, field_id) for field_id in flow.discovered_field_ids],
                constraints=dict(flow.constraints),
                cancel_supported=flow.cancel_supported,
                requires_open_before_submit=flow.requires_open_before_submit,
                evidence_ids=[evidence_id_map.get(eid, eid) for eid in flow.evidence_ids],
                reasoning_summary=flow.reasoning_summary,
            )
            key = flow_key(remapped)
            if key in flows_by_key:
                continue
            flows_by_key[key] = remapped
            merged.interaction_flows.append(remapped)

    base_pages = {page_key(page) for page in base.pages}
    base_forms = {form_key(form) for form in merged.forms if form.page_id in {page_id_map.get(page.id, page.id) for page in base.pages}}
    base_elements = {(page_id_map.get(element.page_id, element.page_id), element.selector_fingerprint, element.label, element.control_type) for element in base.elements}
    merged_forms = {form_key(form) for form in merged.forms}
    merged_elements = {element_key(element) for element in merged.elements}
    report = {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "base_run_id": base.run_id,
        "probe_run_id": probe.run_id,
        "merged_run_id": merged.run_id,
        "generated_at": merged.timestamp,
        "summary": {
            "base_pages": len(base.pages),
            "probe_pages": len(probe.pages),
            "merged_pages": len(merged.pages),
            "added_pages": len({page_key(page) for page in merged.pages} - base_pages),
            "base_forms": len(base.forms),
            "probe_forms": len(probe.forms),
            "merged_forms": len(merged.forms),
            "added_forms": max(0, len(merged_forms) - len(base_forms)),
            "base_elements": len(base.elements),
            "probe_elements": len(probe.elements),
            "merged_elements": len(merged.elements),
            "added_elements": max(0, len(merged_elements) - len(base_elements)),
            "merged_transitions": len(merged.transitions),
            "merged_interaction_flows": len(merged.interaction_flows),
        },
        "attribution": {
            "added_pages": added_pages,
            "added_forms": added_forms,
            "added_elements": added_elements,
            "probe_labels": sorted(
                {
                    label_from_slug(item)
                    for page in probe.pages
                    for item in state_path_from_url(page.url)
                    if item
                }
            ),
            "promotable_labels": sorted(
                {
                    label
                    for item in [*added_pages, *added_forms, *added_elements]
                    for label in item.get("source_plan_labels", [])
                    if label
                }
            ),
        },
    }
    return merged, report


def write_merged_snapshot(workspace: Path, profile: Profile, merged: CrawlSnapshot, report: dict) -> tuple[Path, Path]:
    crawl_dir = output_root(workspace, profile.name) / "crawl"
    report_dir = output_root(workspace, profile.name) / "reports"
    snapshot_path = crawl_dir / f"snapshot-merged-{merged.run_id}.json"
    report_path = report_dir / f"merge-{merged.run_id}.json"
    write_json(snapshot_path, merged)
    write_json(report_path, report)
    return snapshot_path, report_path
