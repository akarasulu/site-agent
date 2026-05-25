from __future__ import annotations

from pathlib import Path

from site_agent.core.ai.backends import AiBackend, ProductResearchResult
from site_agent.core.ingest.docs import slug
from site_agent.core.profiles import Profile, profile_root
from site_agent.core.storage import ensure_dir, write_json


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
    return write_research_artifacts(workspace, profile, result)
