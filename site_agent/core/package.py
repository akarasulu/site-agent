from __future__ import annotations

import hashlib
import json
import re
import shutil
import zipfile
from pathlib import Path
from typing import Any

from site_agent.core.models import utc_now
from site_agent.core.profiles import Profile, output_root, profile_root
from site_agent.core.redact import redact_text
from site_agent.core.storage import ensure_dir, latest_json, read_json, write_json


IDENTITY_LABEL_RE = re.compile(
    r"\b(serial|uuid|instance\s*id|instance\s*uuid|product\s*id|device\s*id|asset\s*id|service\s*tag|system\s*id|hardware\s*id)\b",
    re.IGNORECASE,
)


def redact_json(value: Any, extra_patterns: list[str] | None = None) -> Any:
    if isinstance(value, str):
        return redact_text(value, extra_patterns)
    if isinstance(value, list):
        return [redact_json(item, extra_patterns) for item in value]
    if isinstance(value, dict):
        return {key: redact_json(item, extra_patterns) for key, item in value.items()}
    return value


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    ensure_dir(path.parent)
    path.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows), encoding="utf-8")


def chunk_text(text: str, max_chars: int = 1200) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if current and len(current) + len(paragraph) + 2 > max_chars:
            chunks.append(current)
            current = paragraph
        else:
            current = f"{current}\n\n{paragraph}".strip()
    if current:
        chunks.append(current)
    return chunks


def build_interaction_graph(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile_id": snapshot["profile_id"],
        "run_id": snapshot["run_id"],
        "pages": snapshot.get("pages", []),
        "forms": snapshot.get("forms", []),
        "transitions": snapshot.get("transitions", []),
        "elements": snapshot.get("elements", []),
    }


def build_identity_candidates(snapshot: dict[str, Any], extra_patterns: list[str] | None = None) -> list[dict[str, Any]]:
    candidates = []
    for element in snapshot.get("elements", []):
        label = str(element.get("label", ""))
        value = str(element.get("context", {}).get("read_value", ""))
        context_text = " ".join(str(item) for item in element.get("context", {}).get("headings", []))
        haystack = f"{label} {context_text}"
        if IDENTITY_LABEL_RE.search(haystack):
            candidates.append(
                {
                    "ui_element_id": element.get("id"),
                    "label": redact_text(label, extra_patterns),
                    "value": redact_text(value, extra_patterns) if value else "",
                    "evidence_ids": element.get("evidence_ids", []),
                    "sensitivity": "private_instance_context",
                    "reasoning_summary": "Generic identity candidate inferred from identifier-like UI label/context. Not assumed unique until reviewed.",
                }
            )
    return candidates


def build_rag_chunks(
    workspace: Path,
    profile: Profile,
    snapshot: dict[str, Any],
    schema: dict[str, Any],
    tools: dict[str, Any],
    config_coverage: dict[str, Any] | None = None,
    extra_patterns: list[str] | None = None,
) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    for evidence in snapshot.get("evidence", []) + schema.get("evidence", []):
        text = redact_text(str(evidence.get("summary", "")), extra_patterns)
        if not text:
            continue
        chunks.append(
            {
                "id": f"evidence:{evidence.get('id')}",
                "text": text,
                "metadata": {
                    "profile_id": profile.id,
                    "source": redact_text(str(evidence.get("source", "")), extra_patterns),
                    "kind": evidence.get("kind"),
                    "evidence_id": evidence.get("id"),
                    "safe_for_agent_context": evidence.get("kind") in {"doc", "ui", "review", "system"},
                },
            }
        )
    for tool in tools.get("tools", []):
        chunks.append(
            {
                "id": f"tool:{tool.get('name')}",
                "text": redact_text(f"{tool.get('name')}: {tool.get('description', '')}", extra_patterns),
                "metadata": {
                    "profile_id": profile.id,
                    "kind": "mcp_tool",
                    "tool_name": tool.get("name"),
                    "risk_level": tool.get("risk_level"),
                    "source_type": tool.get("source_type"),
                    "evidence_ids": tool.get("evidence_ids", []),
                    "safe_for_agent_context": True,
                },
            }
        )
    if config_coverage:
        confidence = config_coverage.get("confidence", {})
        scope = config_coverage.get("scope", {})
        chunks.append(
            {
                "id": f"config_coverage:{config_coverage.get('run_id')}",
                "text": redact_text(
                    "Configuration coverage confidence "
                    f"{confidence.get('score')} ({confidence.get('band')}). "
                    f"Pages {scope.get('pages_seen')}, forms {scope.get('forms_seen')}, "
                    f"fields {scope.get('fields_seen')}, settings extracted {scope.get('settings_extracted')}.",
                    extra_patterns,
                ),
                "metadata": {
                    "profile_id": profile.id,
                    "kind": "configuration_coverage",
                    "run_id": config_coverage.get("run_id"),
                    "confidence_score": confidence.get("score"),
                    "safe_for_agent_context": True,
                },
            }
        )
        for index, gap in enumerate(config_coverage.get("gaps", [])[:100]):
            chunks.append(
                {
                    "id": f"config_gap:{config_coverage.get('run_id')}:{index}",
                    "text": redact_text(f"Configuration coverage gap: {gap.get('kind')}: {gap.get('summary')}", extra_patterns),
                    "metadata": {
                        "profile_id": profile.id,
                        "kind": "configuration_coverage_gap",
                        "severity": gap.get("severity"),
                        "safe_for_agent_context": True,
                    },
                }
            )
    docs_root = profile_root(workspace, profile.name) / profile.docs_path
    if docs_root.exists():
        for path in sorted(docs_root.rglob("*")):
            if path.is_file() and path.suffix.lower() in {".md", ".txt", ".json"}:
                text = redact_text(path.read_text(encoding="utf-8", errors="replace"), extra_patterns)
                for index, chunk in enumerate(chunk_text(text)):
                    chunks.append(
                        {
                            "id": f"doc:{path.relative_to(docs_root)}:{index}",
                            "text": chunk,
                            "metadata": {
                                "profile_id": profile.id,
                                "kind": "document_chunk",
                                "source": str(path.relative_to(docs_root)),
                                "safe_for_agent_context": True,
                            },
                        }
                    )
    return chunks


def copy_json_artifact(source: Path, destination: Path, extra_patterns: list[str] | None = None) -> dict[str, Any]:
    raw = read_json(source)
    write_json(destination, redact_json(raw, extra_patterns))
    return {
        "path": str(destination),
        "source_path": str(source),
        "sha256": sha256_file(destination),
    }


def zip_directory(source_dir: Path, zip_path: Path) -> None:
    ensure_dir(zip_path.parent)
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir))


def build_profile_package(workspace: Path, profile: Profile, include_private: bool = True, zip_bundle: bool = True) -> tuple[Path, Path | None, dict[str, Any]]:
    root = output_root(workspace, profile.name)
    snapshot_path = latest_json(root / "crawl", "snapshot*.json")
    schema_path = latest_json(root / "schema", "mapped-schema*.json")
    tools_path = root / "mcp" / "tools.json"
    contract_path = root / "mcp" / "contract.json"
    bindings_path = root / "mcp" / "adapter.bindings.json"
    if not tools_path.exists() or not contract_path.exists():
        raise FileNotFoundError(f"MCP artifacts missing for profile '{profile.name}'. Run: site-agent mcp build --profile {profile.name}")

    snapshot = redact_json(read_json(snapshot_path), profile.crawl.redaction_patterns)
    schema = redact_json(read_json(schema_path), profile.crawl.redaction_patterns)
    tools = redact_json(read_json(tools_path), profile.crawl.redaction_patterns)
    run_id = snapshot["run_id"]
    package_dir = root / "packages" / f"{profile.name}-{run_id}"
    if package_dir.exists():
        shutil.rmtree(package_dir)

    write_json(package_dir / "public" / "interaction-graph.json", build_interaction_graph(snapshot))
    write_json(package_dir / "public" / "mapped-schema.json", schema)
    write_json(package_dir / "public" / "ontology.json", {"ontology": schema.get("ontology", [])})
    write_json(package_dir / "public" / "mcp" / "tools.json", tools)
    copied = [
        copy_json_artifact(contract_path, package_dir / "public" / "mcp" / "contract.json", profile.crawl.redaction_patterns),
    ]
    identity_candidates = build_identity_candidates(snapshot, profile.crawl.redaction_patterns)
    if include_private:
        copied.append(copy_json_artifact(bindings_path, package_dir / "private" / "adapter.bindings.json", profile.crawl.redaction_patterns))
        copied.append(copy_json_artifact(profile_root(workspace, profile.name) / "profile.json", package_dir / "private" / "profile.json", profile.crawl.redaction_patterns))
        write_json(package_dir / "private" / "identity-candidates.json", {"candidates": identity_candidates})

    config_coverage = None
    reports_dir = root / "reports"
    coverage_reports = sorted(reports_dir.glob("config-coverage-*.json"), key=lambda p: p.stat().st_mtime) if reports_dir.exists() else []
    if coverage_reports:
        config_coverage = redact_json(read_json(coverage_reports[-1]), profile.crawl.redaction_patterns)
    rag_chunks = build_rag_chunks(workspace, profile, snapshot, schema, tools, config_coverage, profile.crawl.redaction_patterns)
    write_jsonl(package_dir / "rag" / "chunks.jsonl", rag_chunks)
    write_json(
        package_dir / "rag" / "index.json",
        {
            "chunk_count": len(rag_chunks),
            "formats": ["jsonl"],
            "embedding_ready": True,
            "notes": "Chunks include provenance metadata. Re-embed after package rebuilds.",
        },
    )

    report_entries = []
    if reports_dir.exists():
        for report_path in sorted(reports_dir.glob("*.json")):
            destination = package_dir / "reports" / report_path.name
            report_entries.append(copy_json_artifact(report_path, destination, profile.crawl.redaction_patterns))

    manifest = {
        "package_schema_version": "0.1.0",
        "generated_at": utc_now(),
        "profile_id": profile.id,
        "profile_name": profile.name,
        "run_id": run_id,
        "source_artifacts": {
            "snapshot": str(snapshot_path),
            "schema": str(schema_path),
            "tools": str(tools_path),
            "contract": str(contract_path),
        },
        "artifact_classes": {
            "public": {
                "safe_for_agent_context": True,
                "description": "Ontology, interaction graph, mapped schema, and public MCP contract/tool metadata. Review before sharing externally.",
            },
            "rag": {
                "safe_for_agent_context": True,
                "description": "Evidence, documentation, and tool chunks with provenance for agent retrieval. Review before sharing externally.",
            },
            "private": {
                "safe_for_agent_context": False,
                "description": "Private profile/adapter/identity candidate data. Do not embed wholesale or expose as public API.",
            },
            "reports": {
                "safe_for_agent_context": True,
                "description": "Quality, drift, debug, action, and contract reports. Review before sharing externally.",
            },
        },
        "sensitivity_policy": {
            "default_redacted": False,
            "do_not_embed": ["private/adapter.bindings.json", "private/profile.json"],
            "review_before_embedding": ["private/identity-candidates.json"] if include_private else [],
            "selector_private": True,
            "secrets_policy": "Auth state is excluded from public packages; other captured values are preserved and must be protected by the operator.",
        },
        "identity_policy": {
            "strategy": "generic_identifier_candidates",
            "notes": "Identity candidates are extracted from identifier-like labels such as serial, UUID, instance ID, product ID, asset ID, service tag, system ID, or hardware ID. Domain-specific fields are not assumed unique unless reviewed.",
            "candidate_count": len(identity_candidates),
        },
        "counts": {
            "pages": len(snapshot.get("pages", [])),
            "forms": len(snapshot.get("forms", [])),
            "elements": len(snapshot.get("elements", [])),
            "tools": len(tools.get("tools", [])),
            "rag_chunks": len(rag_chunks),
            "reports": len(report_entries),
        },
    }
    write_json(package_dir / "manifest.json", manifest)
    zip_path = root / "packages" / f"{profile.name}-{run_id}.zip" if zip_bundle else None
    if zip_path:
        zip_directory(package_dir, zip_path)
    return package_dir, zip_path, manifest
