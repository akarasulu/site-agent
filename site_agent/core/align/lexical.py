from __future__ import annotations

from site_agent.core.ai.backends import AiBackend, NoopAiBackend
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, MappedSchema, confidence_band, utc_now


def token_set(value: str) -> set[str]:
    return {part for part in normalize_term(value).split() if len(part) > 1}


def score_label(label: str, term: DomainTerm) -> float:
    label_tokens = token_set(label)
    candidates = [term.canonical_name, *term.aliases]
    best = 0.0
    for candidate in candidates:
        candidate_tokens = token_set(candidate)
        if not label_tokens or not candidate_tokens:
            continue
        overlap = len(label_tokens & candidate_tokens) / len(label_tokens | candidate_tokens)
        exact_bonus = 0.25 if normalize_term(label) == normalize_term(candidate) else 0.0
        best = max(best, min(1.0, overlap + exact_bonus))
    return best


def align_snapshot(
    profile_id: str,
    snapshot: CrawlSnapshot,
    ontology: list[DomainTerm],
    doc_evidence: list[Evidence],
    ai_backend: AiBackend | None = None,
) -> MappedSchema:
    mappings: list[ConceptMapping] = []
    backend = ai_backend or NoopAiBackend()
    all_evidence = [*snapshot.evidence, *doc_evidence]
    for element in snapshot.elements:
        scored = sorted(((score_label(element.label, term), term) for term in ontology), key=lambda item: item[0], reverse=True)
        best_score, best_term = scored[0] if scored else (0.0, None)
        evidence_ids = list(element.evidence_ids)
        if best_term:
            evidence_ids.extend(best_term.sources[:2])
        band = confidence_band(best_score)
        status = "ready" if band == "stable" and best_term else "review" if band == "experimental" else "internal"
        mapping = ConceptMapping(
            ui_element_id=element.id,
            domain_term_id=best_term.id if best_term and best_score >= 0.60 else None,
            canonical_name=best_term.canonical_name if best_term and best_score >= 0.60 else normalize_term(element.label),
            aliases_seen=[element.label],
            confidence=round(best_score, 3),
            evidence_ids=evidence_ids,
            status=status,
            reasoning_summary=(
                "Mapped by lexical overlap between UI label and ontology term."
                if best_term and best_score >= 0.60
                else "Insufficient ontology evidence for public mapping."
            ),
        )
        suggestion = backend.align_element(element, ontology, all_evidence)
        doc_ids = {item.id for item in doc_evidence}
        has_doc_requirement = bool(doc_ids)
        has_doc_evidence = bool(doc_ids & set(suggestion.evidence_ids)) if suggestion else False
        if suggestion and suggestion.confidence >= mapping.confidence and suggestion.evidence_ids and (not has_doc_requirement or has_doc_evidence):
            suggested_term = next((term for term in ontology if normalize_term(term.canonical_name) == normalize_term(suggestion.canonical_name)), None)
            suggested_band = confidence_band(suggestion.confidence)
            mapping = ConceptMapping(
                ui_element_id=element.id,
                domain_term_id=suggested_term.id if suggested_term else None,
                canonical_name=normalize_term(suggestion.canonical_name),
                aliases_seen=suggestion.aliases or [element.label],
                confidence=round(min(max(suggestion.confidence, 0.0), 1.0), 3),
                evidence_ids=suggestion.evidence_ids,
                status="ready" if suggested_band == "stable" else "review" if suggested_band == "experimental" else "internal",
                reasoning_summary=suggestion.reasoning_summary,
            )
        mappings.append(mapping)
    return MappedSchema(
        profile_id=profile_id,
        run_id=snapshot.run_id,
        generated_at=utc_now(),
        ontology=ontology,
        mappings=mappings,
        evidence=all_evidence,
    )
