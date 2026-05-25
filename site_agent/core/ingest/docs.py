from __future__ import annotations

import re
from pathlib import Path

from site_agent.core.ai.backends import AiBackend, NoopAiBackend
from site_agent.core.models import DomainTerm, Evidence, new_id
from site_agent.core.profiles import Profile, profile_root
from site_agent.core.redact import redact_domain_terms, redact_evidence_items
from site_agent.core.storage import read_json, write_json


WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9 _/-]{1,60}")


def normalize_term(value: str) -> str:
    return " ".join(value.replace("_", " ").replace("-", " ").split()).strip().lower()


def slug(value: str) -> str:
    normalized = normalize_term(value)
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


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
            for heading in re.findall(r"^#{1,3}\s+(.+)$", text, re.MULTILINE):
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
