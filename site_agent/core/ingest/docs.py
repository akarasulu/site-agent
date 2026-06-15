from __future__ import annotations

import re
from pathlib import Path

from site_agent.core.ai.backends import AiBackend, NoopAiBackend
from site_agent.core.models import DomainTerm, Evidence, new_id
from site_agent.core.profiles import Profile, profile_root
from site_agent.core.redact import redact_domain_terms, redact_evidence_items
from site_agent.core.storage import read_json, write_json


WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9 _/-]{1,60}")
HEADING_RE = re.compile(r"^#{1,3}\s+(.+)$", re.MULTILINE)
RANGE_RE = re.compile(
    r"\b(?:valid\s+range|allowed\s+range|range|length)\s*[:=]?\s*"
    r"([0-9]+(?:\.[0-9]+)?)\s*(?:-|~|to)\s*([0-9]+(?:\.[0-9]+)?)",
    re.I,
)
ALLOWED_VALUES_RE = re.compile(r"\b(?:allowed values|valid values|options|choices)\s*[:=]\s*([^\n.;]+)", re.I)
DEFAULT_RE = re.compile(r"\bdefault\s*[:=]\s*([^\n.;]+)", re.I)
UNIT_RE = re.compile(r"\b(ms|seconds?|minutes?|hours?|days?|kbps|mbps|gbps|hz|khz|mhz|ghz|dbm|%|percent)\b", re.I)
OPERATION_RE = re.compile(r"\b(create|add|update|edit|delete|remove|enable|disable|apply|restore|restart|reboot)\b", re.I)
CONSTRAINT_TOKEN_RE = re.compile(r"\b(required|optional|read[- ]only|immutable|case[- ]sensitive)\b", re.I)


def normalize_term(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).strip().lower()


def slug(value: str) -> str:
    normalized = normalize_term(value)
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def extract_document_clues(text: str) -> dict[str, list[str]]:
    constraints: list[str] = []
    units: list[str] = []
    for match in RANGE_RE.finditer(text):
        constraints.append(f"range: {match.group(1)}-{match.group(2)}")
    for match in ALLOWED_VALUES_RE.finditer(text):
        values = ", ".join(part.strip() for part in re.split(r"[,/|]", match.group(1)) if part.strip())
        if values:
            constraints.append(f"allowed values: {values}")
    for match in DEFAULT_RE.finditer(text):
        value = " ".join(match.group(1).split()).strip()
        if value:
            constraints.append(f"default: {value}")
    for match in CONSTRAINT_TOKEN_RE.finditer(text):
        constraints.append(normalize_term(match.group(1)))
    for match in OPERATION_RE.finditer(text):
        constraints.append(f"operation: {normalize_term(match.group(1))}")
    for match in UNIT_RE.finditer(text):
        units.append(normalize_term(match.group(1)))
    return {
        "constraints": sorted(set(constraints)),
        "units": sorted(set(units)),
    }


def heading_sections(text: str) -> list[tuple[str, str]]:
    matches = list(HEADING_RE.finditer(text))
    sections = []
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        sections.append((match.group(1), text[start:end]))
    return sections


def merge_document_clues(term: DomainTerm, text: str) -> None:
    clues = extract_document_clues(text)
    term.constraints = sorted(set([*term.constraints, *clues["constraints"]]))
    term.units = sorted(set([*term.units, *clues["units"]]))


def load_seed_terms(workspace: Path, profile: Profile) -> list[DomainTerm]:
    seed_path = profile_root(workspace, profile.name) / profile.ontology_seed_path
    if not seed_path.exists():
        return []
    raw = read_json(seed_path)
    terms = []
    for item in raw.get("terms", []):
        canonical = item["canonical_name"]
        terms.append(
            DomainTerm(
                id=item.get("id") or f"term_{slug(canonical)}",
                canonical_name=canonical,
                aliases=list(item.get("aliases", [])),
                units=list(item.get("units", [])),
                constraints=list(item.get("constraints", [])),
                sources=list(item.get("sources", [])),
                confidence=float(item.get("confidence", 0.9)),
            )
        )
    return terms


def ingest_documents(workspace: Path, profile: Profile, ai_backend: AiBackend | None = None) -> tuple[list[DomainTerm], list[Evidence]]:
    docs_dir = profile_root(workspace, profile.name) / profile.docs_path
    terms = {term.id: term for term in load_seed_terms(workspace, profile)}
    evidence: list[Evidence] = []
    doc_snippets: list[dict[str, str]] = []
    backend = ai_backend or NoopAiBackend()
    if docs_dir.exists():
        for path in sorted(docs_dir.glob("**/*")):
            if path.is_dir() or path.name == ".gitkeep" or path.suffix.lower() not in {".txt", ".md"}:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            doc_ev = Evidence(
                id=new_id("ev"),
                kind="doc",
                source=str(path),
                summary=f"Domain documentation ingested from {path.name}",
                locator=str(path),
            )
            evidence.append(doc_ev)
            doc_snippets.append({"evidence_id": doc_ev.id, "source": str(path), "text": text[:8000]})
            for heading, section_text in heading_sections(text):
                canonical = normalize_term(heading)
                if len(canonical) < 3:
                    continue
                term_id = f"term_{slug(canonical)}"
                if term_id in terms:
                    if doc_ev.id not in terms[term_id].sources:
                        terms[term_id].sources.append(doc_ev.id)
                    terms[term_id].confidence = max(terms[term_id].confidence, 0.75)
                else:
                    terms[term_id] = DomainTerm(
                        id=term_id,
                        canonical_name=canonical,
                        aliases=[],
                        sources=[doc_ev.id],
                        confidence=0.75,
                    )
                merge_document_clues(terms[term_id], section_text)
    for ai_term in backend.extract_terms(doc_snippets):
        term_id = ai_term.id or f"term_{slug(ai_term.canonical_name)}"
        if term_id in terms:
            existing = terms[term_id]
            existing.aliases = sorted(set(existing.aliases + ai_term.aliases))
            existing.units = sorted(set(existing.units + ai_term.units))
            existing.constraints = sorted(set(existing.constraints + ai_term.constraints))
            existing.sources = sorted(set(existing.sources + ai_term.sources))
            existing.confidence = max(existing.confidence, ai_term.confidence)
        else:
            terms[term_id] = ai_term
    return list(terms.values()), evidence


def build_ontology_artifact(workspace: Path, profile: Profile, ai_backend: AiBackend | None = None) -> tuple[list[DomainTerm], list[Evidence]]:
    terms, evidence = ingest_documents(workspace, profile, ai_backend)
    write_json(
        workspace / "output" / profile.name / "ontology" / "ontology.json",
        {
            "terms": redact_domain_terms(terms, profile.crawl.redaction_patterns),
            "evidence": redact_evidence_items(evidence, profile.crawl.redaction_patterns),
        },
    )
    return terms, evidence
