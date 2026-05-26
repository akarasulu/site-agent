from __future__ import annotations

import re
from dataclasses import replace

from .models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, Form, InteractionFlow, MappedSchema, Page, Transition, UiElement


DEFAULT_REDACTIONS: list[tuple[re.Pattern[str], str]] = []


def redact_text(value: str, extra_patterns: list[str] | None = None) -> str:
    return value


def redact_context(context: dict, extra_patterns: list[str] | None = None) -> dict:
    safe = {}
    for key, value in context.items():
        if isinstance(value, str):
            safe[key] = redact_text(value, extra_patterns)
        elif isinstance(value, list):
            safe[key] = [redact_text(item, extra_patterns) if isinstance(item, str) else item for item in value]
        else:
            safe[key] = value
    return safe


def redact_snapshot(snapshot: CrawlSnapshot, extra_patterns: list[str] | None = None) -> CrawlSnapshot:
    return CrawlSnapshot(
        timestamp=snapshot.timestamp,
        profile_id=snapshot.profile_id,
        run_id=snapshot.run_id,
        pages=[
            Page(
                id=page.id,
                url=redact_text(page.url, extra_patterns),
                title=redact_text(page.title, extra_patterns),
                headings=[redact_text(heading, extra_patterns) for heading in page.headings],
                html_snapshot=redact_text(page.html_snapshot, extra_patterns) if page.html_snapshot else None,
            )
            for page in snapshot.pages
        ],
        forms=[
            Form(
                id=form.id,
                page_id=form.page_id,
                label=redact_text(form.label, extra_patterns),
                action=redact_text(form.action, extra_patterns) if form.action else None,
                method=form.method,
                field_ids=list(form.field_ids),
            )
            for form in snapshot.forms
        ],
        elements=[
            UiElement(
                id=element.id,
                page_id=element.page_id,
                selector_fingerprint=element.selector_fingerprint,
                label=redact_text(element.label, extra_patterns),
                control_type=element.control_type,
                context=redact_context(element.context, extra_patterns),
                evidence_ids=list(element.evidence_ids),
            )
            for element in snapshot.elements
        ],
        transitions=[
            Transition(
                source_page_id=transition.source_page_id,
                target_url=redact_text(transition.target_url, extra_patterns),
                trigger_label=redact_text(transition.trigger_label, extra_patterns),
                risk_level=transition.risk_level,
            )
            for transition in snapshot.transitions
        ],
        interaction_flows=[
            InteractionFlow(
                id=flow.id,
                page_id=flow.page_id,
                trigger_label=redact_text(flow.trigger_label, extra_patterns),
                flow_type=flow.flow_type,
                discovered_field_ids=list(flow.discovered_field_ids),
                constraints=redact_context(flow.constraints, extra_patterns),
                cancel_supported=flow.cancel_supported,
                requires_open_before_submit=flow.requires_open_before_submit,
                evidence_ids=list(flow.evidence_ids),
                reasoning_summary=redact_text(flow.reasoning_summary, extra_patterns),
            )
            for flow in snapshot.interaction_flows
        ],
        evidence=[
            Evidence(
                id=evidence.id,
                kind=evidence.kind,
                source=redact_text(evidence.source, extra_patterns),
                summary=redact_text(evidence.summary, extra_patterns),
                locator=evidence.locator,
                created_at=evidence.created_at,
            )
            for evidence in snapshot.evidence
        ],
    )


def redact_domain_terms(terms: list[DomainTerm], extra_patterns: list[str] | None = None) -> list[DomainTerm]:
    return [
        DomainTerm(
            id=term.id,
            canonical_name=redact_text(term.canonical_name, extra_patterns),
            aliases=[redact_text(alias, extra_patterns) for alias in term.aliases],
            units=[redact_text(unit, extra_patterns) for unit in term.units],
            constraints=[redact_text(constraint, extra_patterns) for constraint in term.constraints],
            sources=[redact_text(source, extra_patterns) for source in term.sources],
            confidence=term.confidence,
        )
        for term in terms
    ]


def redact_evidence_items(evidence_items: list[Evidence], extra_patterns: list[str] | None = None) -> list[Evidence]:
    return [
        Evidence(
            id=evidence.id,
            kind=evidence.kind,
            source=redact_text(evidence.source, extra_patterns),
            summary=redact_text(evidence.summary, extra_patterns),
            locator=redact_text(evidence.locator, extra_patterns) if evidence.locator else None,
            created_at=evidence.created_at,
        )
        for evidence in evidence_items
    ]


def redact_schema(schema: MappedSchema, extra_patterns: list[str] | None = None) -> MappedSchema:
    return MappedSchema(
        profile_id=schema.profile_id,
        run_id=schema.run_id,
        generated_at=schema.generated_at,
        ontology=redact_domain_terms(schema.ontology, extra_patterns),
        mappings=[
            ConceptMapping(
                ui_element_id=mapping.ui_element_id,
                domain_term_id=mapping.domain_term_id,
                canonical_name=redact_text(mapping.canonical_name, extra_patterns),
                aliases_seen=[redact_text(alias, extra_patterns) for alias in mapping.aliases_seen],
                confidence=mapping.confidence,
                evidence_ids=list(mapping.evidence_ids),
                status=mapping.status,
                reasoning_summary=redact_text(mapping.reasoning_summary, extra_patterns),
            )
            for mapping in schema.mappings
        ],
        evidence=redact_evidence_items(schema.evidence, extra_patterns),
    )
