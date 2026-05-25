from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from .models import ConceptMapping, Evidence, MappedSchema, new_id, utc_now
from .storage import latest_json, read_json, write_json


class ReviewError(RuntimeError):
    pass


def schema_from_json(raw: dict) -> MappedSchema:
    from .models import DomainTerm

    return MappedSchema(
        profile_id=raw["profile_id"],
        run_id=raw["run_id"],
        generated_at=raw["generated_at"],
        ontology=[DomainTerm(**item) for item in raw.get("ontology", [])],
        mappings=[ConceptMapping(**item) for item in raw.get("mappings", [])],
        evidence=[Evidence(**item) for item in raw.get("evidence", [])],
    )


def latest_schema(schema_dir: Path) -> tuple[Path, MappedSchema]:
    path = latest_json(schema_dir, "mapped-schema-*.json")
    return path, schema_from_json(read_json(path))


def review_queue(schema: MappedSchema) -> list[ConceptMapping]:
    return [mapping for mapping in schema.mappings if mapping.status == "review"]


def _find_mapping(schema: MappedSchema, ui_element_id: str) -> int:
    for index, mapping in enumerate(schema.mappings):
        if mapping.ui_element_id == ui_element_id:
            return index
    raise ReviewError(f"No mapping found for ui_element_id: {ui_element_id}")


def apply_review(
    schema: MappedSchema,
    ui_element_id: str,
    decision: str,
    canonical_name: str | None = None,
    confidence: float | None = None,
    note: str | None = None,
) -> MappedSchema:
    index = _find_mapping(schema, ui_element_id)
    mapping = schema.mappings[index]
    review_evidence = Evidence(
        id=new_id("ev"),
        kind="review",
        source="human-review",
        summary=note or f"Reviewer decision: {decision}",
    )
    evidence_ids = [*mapping.evidence_ids, review_evidence.id]
    if decision == "approve":
        updated = replace(
            mapping,
            status="ready",
            confidence=max(confidence if confidence is not None else mapping.confidence, 0.85),
            canonical_name=canonical_name or mapping.canonical_name,
            evidence_ids=evidence_ids,
            reasoning_summary=f"{mapping.reasoning_summary} Reviewer approved exposure.",
        )
    elif decision == "edit":
        if not canonical_name:
            raise ReviewError("Editing a mapping requires --canonical-name.")
        updated = replace(
            mapping,
            status="ready",
            confidence=max(confidence if confidence is not None else mapping.confidence, 0.85),
            canonical_name=canonical_name,
            evidence_ids=evidence_ids,
            reasoning_summary=f"{mapping.reasoning_summary} Reviewer edited canonical concept.",
        )
    elif decision == "reject":
        updated = replace(
            mapping,
            status="internal",
            confidence=min(confidence if confidence is not None else mapping.confidence, 0.59),
            evidence_ids=evidence_ids,
            reasoning_summary=f"{mapping.reasoning_summary} Reviewer rejected public exposure.",
        )
    else:
        raise ReviewError(f"Unknown review decision: {decision}")

    mappings = list(schema.mappings)
    mappings[index] = updated
    return MappedSchema(
        profile_id=schema.profile_id,
        run_id=schema.run_id,
        generated_at=utc_now(),
        ontology=schema.ontology,
        mappings=mappings,
        evidence=[*schema.evidence, review_evidence],
    )


def write_reviewed_schema(schema_dir: Path, schema: MappedSchema) -> Path:
    path = schema_dir / f"mapped-schema-{schema.run_id}-reviewed-{new_id('rev')}.json"
    write_json(path, schema)
    return path
