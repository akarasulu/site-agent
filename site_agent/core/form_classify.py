from __future__ import annotations

from pathlib import Path
from typing import Any

from site_agent.core.ai.backends import AiBackend, FormPurposeClassification
from site_agent.core.debug import state_path
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm, Form, UiElement, utc_now
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import write_json


def page_label_from_path(path: list[str]) -> str:
    if path:
        return " ".join(part.replace("-", " ").title() for part in path[-2:])
    return "Page"


def form_context(form: Form, snapshot: CrawlSnapshot) -> dict[str, Any]:
    element_by_id = {element.id: element for element in snapshot.elements}
    page_by_id = {page.id: page for page in snapshot.pages}
    page = page_by_id.get(form.page_id)
    path = state_path(page) if page else []
    fields = [element_by_id[field_id] for field_id in form.field_ids if field_id in element_by_id]
    evidence_ids = [eid for field in fields for eid in field.evidence_ids]
    return {
        "form_id": form.id,
        "label": form.label,
        "method": form.method,
        "action": form.action,
        "page_id": form.page_id,
        "page_url": page.url if page else "",
        "page_title": page.title if page else "",
        "page_path": path,
        "page_label": page_label_from_path(path),
        "fields": [
            {
                "ui_element_id": field.id,
                "label": field.label,
                "control_type": field.control_type,
                "selector_fingerprint": field.selector_fingerprint,
                "context": field.context,
                "evidence_ids": field.evidence_ids,
            }
            for field in fields
        ],
        "evidence_ids": evidence_ids,
    }


def heuristic_form_classification(context: dict[str, Any]) -> FormPurposeClassification | None:
    field_text = normalize_term(" ".join(field.get("label", "") for field in context.get("fields", [])))
    text = normalize_term(
        " ".join(
            [
                " ".join(context.get("page_path", [])),
                context.get("page_label", ""),
                context.get("label", ""),
                " ".join(field.get("label", "") for field in context.get("fields", [])),
            ]
        )
    )
    field_tokens = set(field_text.split())
    has_forwarding_fields = (
        {"external", "internal", "protocol"} <= field_tokens
        or ("protocol" in field_tokens and "wan" in field_tokens and "lan" in field_tokens and "host" in field_tokens and "port" in field_tokens)
    )
    if has_forwarding_fields and "port" in text:
        return FormPurposeClassification(
            form_id=context.get("form_id", ""),
            semantic_purpose="port forwarding rule",
            operation="create_or_update",
            confidence=0.84,
            evidence_ids=context.get("evidence_ids", []),
            reasoning_summary="Fields mention protocol plus WAN/LAN host and port fields, matching external-to-internal port forwarding semantics.",
            negative_concepts=["port binding"],
        )
    if "port binding" in text and any(token in field_tokens for token in ["lan1", "lan2", "lan3", "lan4", "ssid1", "ssid8"]):
        return FormPurposeClassification(
            form_id=context.get("form_id", ""),
            semantic_purpose="port binding",
            operation="update",
            confidence=0.82,
            evidence_ids=context.get("evidence_ids", []),
            reasoning_summary="Fields indicate WAN/LAN/SSID interface binding rather than external-to-internal port forwarding.",
            negative_concepts=["port forwarding", "virtual server", "nat rule"],
        )
    return None


def classify_forms(
    workspace: Path,
    profile: Profile,
    snapshot: CrawlSnapshot,
    ontology: list[DomainTerm],
    ai_backend: AiBackend,
    research_memory: dict[str, Any] | None = None,
    max_ai_forms: int = 20,
) -> tuple[dict[str, dict], Path]:
    classifications: dict[str, dict] = {}
    ai_calls = 0
    for form in snapshot.forms:
        context = form_context(form, snapshot)
        classification = heuristic_form_classification(context)
        if classification is None and ai_calls < max_ai_forms:
            try:
                classification = ai_backend.classify_form_purpose(context, ontology, research_memory)
                ai_calls += 1
            except Exception:
                classification = None
        if classification is None:
            continue
        classifications[form.id] = {
            "form_id": classification.form_id,
            "semantic_purpose": classification.semantic_purpose,
            "operation": classification.operation,
            "confidence": round(max(0.0, min(1.0, classification.confidence)), 3),
            "evidence_ids": classification.evidence_ids,
            "reasoning_summary": classification.reasoning_summary,
            "negative_concepts": classification.negative_concepts,
            "page_path": context.get("page_path", []),
            "page_label": context.get("page_label", ""),
        }
    path = output_root(workspace, profile.name) / "reports" / f"form-classifications-{snapshot.run_id}.json"
    write_json(
        path,
        {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "run_id": snapshot.run_id,
            "generated_at": utc_now(),
            "classifications": list(classifications.values()),
        },
    )
    return classifications, path
