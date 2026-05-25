from __future__ import annotations

from collections import Counter, defaultdict
from urllib.parse import urlparse

from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, MappedSchema, Page, utc_now


WIDGET_LABELS = {
    "hide",
    "show",
    "all day",
    "select all",
    "select none",
    "expand",
    "collapse",
}


def state_path(page: Page) -> list[str]:
    try:
        fragment = urlparse(page.url).fragment
    except ValueError:
        fragment = page.url.split("#", 1)[1] if "#" in page.url else ""
    if not fragment.startswith("state="):
        return []
    return [part for part in fragment.removeprefix("state=").split("/") if part]


def classify_state(page: Page, snapshot: CrawlSnapshot) -> dict:
    elements = [element for element in snapshot.elements if element.page_id == page.id]
    forms = [form for form in snapshot.forms if form.page_id == page.id]
    path = state_path(page)
    labels = [element.label for element in elements if element.label]
    controls = Counter(element.control_type for element in elements)
    readonly_count = controls.get("readonly_status", 0)
    field_count = sum(count for kind, count in controls.items() if kind in {"text", "number", "email", "password", "select", "checkbox", "radio", "textarea", "hidden"})
    action_count = controls.get("button", 0) + controls.get("submit", 0)
    last_label = normalize_term(path[-1].replace("-", " ")) if path else ""

    if len(path) >= 2 and (last_label in WIDGET_LABELS or last_label.startswith("select ")):
        kind = "widget_state"
        confidence = 0.82
        reason = "State path ends with a generic widget/control label."
    elif forms and (field_count >= 2 or readonly_count >= 1):
        kind = "form_or_settings_state"
        confidence = 0.86
        reason = "State contains forms with fields or nearby status evidence."
    elif readonly_count >= 2:
        kind = "data_or_status_state"
        confidence = 0.85
        reason = "State contains multiple read-only status facts."
    elif page.headings or labels:
        kind = "content_state"
        confidence = 0.70
        reason = "State contains visible headings or labelled UI content."
    else:
        kind = "empty_or_duplicate_state"
        confidence = 0.65
        reason = "State has little extractable content."

    return {
        "page_id": page.id,
        "url": page.url,
        "state_path": path,
        "kind": kind,
        "confidence": confidence,
        "reason": reason,
        "counts": {
            "forms": len(forms),
            "elements": len(elements),
            "readonly_status": readonly_count,
            "fields": field_count,
            "actions": action_count,
        },
        "headings": page.headings[:5],
    }


def evidence_coverage(schema: MappedSchema | None) -> dict:
    if schema is None:
        return {"schema_available": False}
    evidence_by_id = {item.id: item for item in schema.evidence}
    exposed = [mapping for mapping in schema.mappings if mapping.status in {"ready", "review"}]
    dual_evidence = 0
    ui_only = 0
    doc_only = 0
    no_evidence = 0
    for mapping in exposed:
        kinds = {evidence_by_id[eid].kind for eid in mapping.evidence_ids if eid in evidence_by_id}
        if {"ui", "doc"} <= kinds:
            dual_evidence += 1
        elif "ui" in kinds:
            ui_only += 1
        elif "doc" in kinds:
            doc_only += 1
        else:
            no_evidence += 1
    total = len(exposed)
    return {
        "schema_available": True,
        "exposed_mappings": total,
        "dual_evidence": dual_evidence,
        "ui_only": ui_only,
        "doc_only": doc_only,
        "no_evidence": no_evidence,
        "dual_evidence_ratio": round(dual_evidence / total, 3) if total else 0.0,
    }


def missing_ontology_terms(schema: MappedSchema | None, limit: int = 40) -> list[dict]:
    if schema is None:
        return []
    mapped_term_ids = {mapping.domain_term_id for mapping in schema.mappings if mapping.domain_term_id and mapping.status in {"ready", "review"}}
    missing = [term for term in schema.ontology if term.id not in mapped_term_ids]
    missing.sort(key=lambda term: (-term.confidence, term.canonical_name))
    return [
        {
            "term_id": term.id,
            "canonical_name": term.canonical_name,
            "aliases": term.aliases,
            "confidence": term.confidence,
            "sources": term.sources,
        }
        for term in missing[:limit]
    ]


def build_debug_report(snapshot: CrawlSnapshot, schema: MappedSchema | None = None) -> dict:
    states = [classify_state(page, snapshot) for page in snapshot.pages]
    state_counts = Counter(state["kind"] for state in states)
    elements_by_page = defaultdict(list)
    for element in snapshot.elements:
        elements_by_page[element.page_id].append(element)

    noisy_states = [
        state
        for state in states
        if state["kind"] in {"widget_state", "empty_or_duplicate_state"}
    ][:30]
    high_value_states = [
        state
        for state in states
        if state["kind"] in {"form_or_settings_state", "data_or_status_state"}
    ][:30]

    return {
        "run_id": snapshot.run_id,
        "profile_id": snapshot.profile_id,
        "generated_at": utc_now(),
        "summary": {
            "pages": len(snapshot.pages),
            "forms": len(snapshot.forms),
            "elements": len(snapshot.elements),
            "transitions": len(snapshot.transitions),
            "state_kinds": dict(state_counts),
        },
        "state_classifications": states,
        "high_value_states": high_value_states,
        "likely_noise_states": noisy_states,
        "evidence_coverage": evidence_coverage(schema),
        "missing_ontology_terms": missing_ontology_terms(schema),
        "next_crawl_targets": [
            {
                "kind": "missing_ontology_concept",
                "target": item["canonical_name"],
                "reason": "Documented ontology term has no ready/review UI mapping yet.",
                "priority": round(float(item["confidence"]), 3),
            }
            for item in missing_ontology_terms(schema, limit=15)
        ],
    }
