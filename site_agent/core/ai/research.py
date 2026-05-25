from __future__ import annotations

from pathlib import Path

from site_agent.core.ai.backends import AiBackend, ProductResearchResult
from site_agent.core.ingest.docs import slug
from site_agent.core.models import utc_now
from site_agent.core.profiles import Profile, profile_root
from site_agent.core.profiles import output_root
from site_agent.core.storage import ensure_dir, read_json, write_json


def research_session_path(workspace: Path, profile: Profile) -> Path:
    return output_root(workspace, profile.name) / "reports" / "research-session.json"


def load_research_session(workspace: Path, profile: Profile) -> dict:
    path = research_session_path(workspace, profile)
    if path.exists():
        return read_json(path)
    return {
        "profile_id": profile.id,
        "profile_name": profile.name,
        "domain_hypotheses": [],
        "sources": [],
        "terms": [],
        "weak_areas": [],
        "directional_targets": [],
        "passes": [],
    }


def write_research_session(workspace: Path, profile: Profile, session: dict) -> Path:
    session["profile_id"] = profile.id
    session["profile_name"] = profile.name
    session["updated_at"] = utc_now()
    path = research_session_path(workspace, profile)
    write_json(path, session)
    return path


def merge_research_result(session: dict, result: ProductResearchResult, pass_kind: str, artifact_paths: tuple[Path, Path]) -> dict:
    normalized_sources = {(source.get("url", ""), source.get("title", "")) for source in session.get("sources", [])}
    sources = list(session.get("sources", []))
    for source in result.sources:
        key = (source.get("url", ""), source.get("title", ""))
        if key not in normalized_sources:
            sources.append(source)
            normalized_sources.add(key)

    normalized_terms = {term.get("canonical_name", "").strip().lower() for term in session.get("terms", [])}
    terms = list(session.get("terms", []))
    for term in result.terms:
        canonical = term.get("canonical_name", "").strip()
        if canonical and canonical.lower() not in normalized_terms:
            terms.append(term)
            normalized_terms.add(canonical.lower())

    hypotheses = list(session.get("domain_hypotheses", []))
    if result.product_name and result.product_name not in hypotheses:
        hypotheses.append(result.product_name)

    passes = list(session.get("passes", []))
    passes.append(
        {
            "kind": pass_kind,
            "product_name": result.product_name,
            "source_count": len(result.sources),
            "term_count": len(result.terms),
            "markdown_path": str(artifact_paths[0]),
            "json_path": str(artifact_paths[1]),
            "created_at": utc_now(),
        }
    )
    return {**session, "domain_hypotheses": hypotheses, "sources": sources, "terms": terms, "passes": passes}


def write_research_artifacts(workspace: Path, profile: Profile, result: ProductResearchResult) -> tuple[Path, Path]:
    docs_dir = ensure_dir(profile_root(workspace, profile.name) / profile.docs_path)
    stem = f"ai-research-{slug(result.product_name or profile.name)}"
    markdown_path = docs_dir / f"{stem}.md"
    json_path = docs_dir / f"{stem}.json"

    lines = [f"# {result.product_name}", "", "## Sources", ""]
    for source in result.sources:
        lines.append(f"- {source.get('title', 'Untitled')} ({source.get('source_type', 'source')}): {source.get('url', '')}")
        if source.get("summary"):
            lines.append(f"  - {source['summary']}")
    lines.extend(["", "## Terms", ""])
    for term in result.terms:
        canonical = term.get("canonical_name", "").strip()
        if not canonical:
            continue
        lines.append(f"# {canonical}")
        if term.get("summary"):
            lines.append("")
            lines.append(term["summary"])
        if term.get("aliases"):
            lines.append(f"Aliases: {', '.join(term['aliases'])}")
        if term.get("units"):
            lines.append(f"Units: {', '.join(term['units'])}")
        if term.get("constraints"):
            lines.append(f"Constraints: {', '.join(term['constraints'])}")
        if term.get("source_urls"):
            lines.append(f"Sources: {', '.join(term['source_urls'])}")
        lines.append("")

    markdown_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")
    write_json(json_path, {"product_name": result.product_name, "sources": result.sources, "terms": result.terms})
    return markdown_path, json_path


def discover_docs(workspace: Path, profile: Profile, ai_backend: AiBackend, product_hint: str, max_sources: int = 5) -> tuple[Path, Path]:
    result = ai_backend.research_product_docs(product_hint, profile.base_url, max_sources)
    if result is None:
        raise RuntimeError("The configured AI backend does not support product documentation discovery.")
    artifacts = write_research_artifacts(workspace, profile, result)
    session = merge_research_result(load_research_session(workspace, profile), result, "product_docs", artifacts)
    write_research_session(workspace, profile, session)
    return artifacts


def discover_ui_domain(workspace: Path, profile: Profile, ai_backend: AiBackend, ui_text: str, max_sources: int = 5) -> tuple[Path, Path]:
    result = ai_backend.discover_ui_domain(ui_text, profile.base_url, max_sources)
    if result is None:
        raise RuntimeError("The configured AI backend does not support UI domain discovery.")
    artifacts = write_research_artifacts(workspace, profile, result)
    session = merge_research_result(load_research_session(workspace, profile), result, "ui_domain_discovery", artifacts)
    write_research_session(workspace, profile, session)
    return artifacts
