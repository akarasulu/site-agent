from __future__ import annotations

import re
from pathlib import Path

from site_agent.core.ai.backends import AiBackend
from site_agent.core.crawl_gain import gain_summary, score_crawl_candidates
from site_agent.core.debug import build_debug_report, state_path
from site_agent.core.evidence_cache import EvidenceCache
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm, MappedSchema, UiElement, new_id, utc_now
from site_agent.core.page_graph import build_page_graph, coverage_preservation_labels
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import latest_json, read_json, write_json


TERM_SPLIT_RE = re.compile(r"[/(),&|]+")


def title_label(value: str) -> str:
    return " ".join(part.capitalize() for part in normalize_term(value).split())


def term_label_candidates(term: DomainTerm) -> list[str]:
    labels: list[str] = []
    for value in [term.canonical_name, *term.aliases]:
        for part in TERM_SPLIT_RE.split(value):
            clean = normalize_term(part)
            if len(clean) >= 3:
                labels.append(title_label(clean))
        clean = normalize_term(value)
        if len(clean) >= 3:
            labels.append(title_label(clean))
    unique = []
    seen = set()
    for label in labels:
        key = normalize_term(label)
        if key not in seen:
            unique.append(label)
            seen.add(key)
    return unique[:8]


def observed_navigation_labels(snapshot: CrawlSnapshot) -> list[str]:
    labels = []
    for transition in snapshot.transitions:
        labels.append(transition.trigger_label)
    for page in snapshot.pages:
        labels.extend(title_label(label.replace("-", " ")) for label in state_path(page))
        labels.extend(page.headings[:5])
    unique = []
    seen = set()
    for label in labels:
        clean = " ".join(str(label).split()).strip()
        key = normalize_term(clean)
        if clean and key not in seen:
            unique.append(clean)
            seen.add(key)
    return unique


def overlap_score(term: DomainTerm, label: str) -> float:
    label_tokens = {part for part in normalize_term(label).split() if len(part) > 2}
    term_tokens = set()
    for value in [term.canonical_name, *term.aliases]:
        term_tokens.update(part for part in normalize_term(value).split() if len(part) > 2)
    if not label_tokens or not term_tokens:
        return 0.0
    return len(label_tokens & term_tokens) / len(label_tokens | term_tokens)


def ai_plan_scores(labels: list[str], missing_terms: list[DomainTerm], ai_backend: AiBackend) -> dict[str, float]:
    if not labels or not missing_terms:
        return {}
    synthetic = [
        UiElement(
            id=f"candidate_{idx}",
            page_id="crawl_plan",
            selector_fingerprint=f"candidate|{label}",
            label=label,
            control_type="navigation_candidate",
            context={"candidate_label": label},
            evidence_ids=[],
        )
        for idx, label in enumerate(labels[:80])
    ]
    try:
        priorities = ai_backend.prioritize_crawl(synthetic, missing_terms[:40])
    except Exception:
        return {}
    scores: dict[str, float] = {}
    normalized_labels = {normalize_term(label): label for label in labels}
    for priority in priorities:
        target = normalize_term(priority.target)
        if target in normalized_labels:
            scores[target] = max(scores.get(target, 0.0), float(priority.priority))
        expected_tokens = set()
        for concept in priority.expected_concepts:
            expected_tokens.update(part for part in normalize_term(concept).split() if len(part) > 2)
        for normalized in normalized_labels:
            if expected_tokens & set(normalized.split()):
                scores[normalized] = max(scores.get(normalized, 0.0), float(priority.priority) * 0.5)
    return scores


def plan_missing_terms(schema: MappedSchema, limit: int) -> list[DomainTerm]:
    mapped_term_ids = {mapping.domain_term_id for mapping in schema.mappings if mapping.domain_term_id and mapping.status in {"ready", "review"}}
    missing = [term for term in schema.ontology if term.id not in mapped_term_ids]
    missing.sort(key=lambda term: (-term.confidence, term.canonical_name))
    return missing[:limit]


def snapshot_summary(snapshot: CrawlSnapshot, schema: MappedSchema) -> dict:
    mapped_ids = {mapping.domain_term_id for mapping in schema.mappings if mapping.domain_term_id and mapping.status in {"ready", "review"}}
    page_paths = []
    for page in snapshot.pages[:80]:
        path = state_path(page)
        page_paths.append({"url": page.url, "path": path, "headings": page.headings[:5]})
    return {
        "run_id": snapshot.run_id,
        "pages": len(snapshot.pages),
        "forms": len(snapshot.forms),
        "elements": len(snapshot.elements),
        "transitions": len(snapshot.transitions),
        "mapped_terms": len(mapped_ids),
        "ontology_terms": len(schema.ontology),
        "page_paths": page_paths,
        "observed_navigation_labels": observed_navigation_labels(snapshot)[:120],
    }


def weak_areas_from_missing_terms(missing_terms: list[DomainTerm]) -> list[dict]:
    return [
        {
            "term_id": term.id,
            "canonical_name": term.canonical_name,
            "aliases": term.aliases,
            "confidence": term.confidence,
            "source_evidence_ids": list(term.sources),
            "weakness": "ontology term has no ready/review UI mapping",
        }
        for term in missing_terms
    ]


def directional_targets(
    snapshot: CrawlSnapshot,
    schema: MappedSchema,
    missing_terms: list[DomainTerm],
    ai_backend: AiBackend,
    research_memory: dict | None,
) -> list[dict]:
    weak_areas = weak_areas_from_missing_terms(missing_terms)
    try:
        targets = ai_backend.plan_directional_crawl(snapshot_summary(snapshot, schema), weak_areas, schema.ontology, research_memory)
    except Exception:
        return []
    planned = []
    for target in targets:
        labels = []
        seen = set()
        for label in [*target.branch_path, *target.labels]:
            clean = " ".join(label.split()).strip()
            key = normalize_term(clean)
            if clean and key not in seen:
                labels.append(clean)
                seen.add(key)
        if not labels:
            continue
        planned.append(
            {
                "branch_path": target.branch_path,
                "labels": labels,
                "missing_concepts": target.missing_concepts,
                "reason": target.reason,
                "priority": round(max(0.0, min(1.0, target.priority)), 3),
                "confidence": round(max(0.0, min(1.0, target.confidence)), 3),
            }
        )
    planned.sort(key=lambda item: (-item["priority"], -item["confidence"], " > ".join(item["branch_path"])))
    return planned[:20]


def disproven_directional_labels(research_memory: dict | None) -> set[str]:
    if not research_memory:
        return set()
    negative_concepts = {normalize_term(concept) for concept in research_memory.get("negative_concepts", [])}
    labels: set[str] = set()
    for outcome in research_memory.get("directional_outcomes", []):
        missing = {normalize_term(concept) for concept in outcome.get("missing_concepts", [])}
        branch = [str(label) for label in outcome.get("branch_path", []) if str(label).strip()]
        if outcome.get("status") == "reached" and concepts_overlap(negative_concepts, missing) and branch:
            labels.add(normalize_term(branch[-1]))
    return labels


def concepts_overlap(left: set[str], right: set[str]) -> bool:
    for left_item in left:
        left_tokens = {part for part in left_item.split() if len(part) > 2}
        for right_item in right:
            right_tokens = {part for part in right_item.split() if len(part) > 2}
            if left_item in right_item or right_item in left_item or (left_tokens and left_tokens <= right_tokens):
                return True
    return False


def build_crawl_plan(
    profile: Profile,
    snapshot: CrawlSnapshot,
    schema: MappedSchema,
    ai_backend: AiBackend,
    max_terms: int = 20,
    memory: dict | None = None,
    evidence_cache: EvidenceCache | dict | None = None,
    evidence_cache_diff: dict | None = None,
) -> dict:
    debug_report = build_debug_report(snapshot, schema)
    page_graph = build_page_graph(snapshot)
    preservation_labels = coverage_preservation_labels(snapshot)
    missing_terms = plan_missing_terms(schema, max_terms)
    observed_labels = observed_navigation_labels(snapshot)
    all_candidates: dict[str, dict] = {}
    ai_scores = ai_plan_scores(observed_labels, missing_terms, ai_backend)
    promoted = {normalize_term(label) for label in (memory or {}).get("promoted_labels", [])}
    demoted = {normalize_term(label) for label in (memory or {}).get("demoted_labels", [])}
    research_memory = (memory or {}).get("research_session") or memory
    disproven = disproven_directional_labels(research_memory)
    demoted.update(disproven)
    directed_targets = directional_targets(snapshot, schema, missing_terms, ai_backend, research_memory)
    directed_targets = [
        target
        for target in directed_targets
        if not (
            target.get("branch_path")
            and normalize_term(target["branch_path"][-1]) in disproven
            and concepts_overlap(
                {normalize_term(concept) for concept in target.get("missing_concepts", [])},
                {normalize_term(concept) for concept in (research_memory or {}).get("negative_concepts", [])},
            )
        )
    ]

    target_terms = []
    for term in missing_terms:
        candidates = []
        generated = term_label_candidates(term)
        for label in [*generated, *observed_labels]:
            lexical = overlap_score(term, label)
            if label not in generated and lexical <= 0:
                continue
            normalized = normalize_term(label)
            memory_boost = 0.25 if normalized in promoted else -0.35 if normalized in demoted else 0.0
            score = min(1.0, max(0.0, max(0.25 if label in generated else 0.0, lexical) + ai_scores.get(normalized, 0.0) + memory_boost))
            candidates.append(
                {
                    "label": label,
                    "score": round(score, 3),
                    "source": "ontology" if label in generated else "observed_ui",
                    "reason": f"Candidate label for missing concept '{term.canonical_name}'.",
                }
            )
            existing = all_candidates.get(normalized)
            if existing is None or score > existing["score"]:
                all_candidates[normalized] = {
                    "label": label,
                    "score": round(score, 3),
                    "concepts": [term.canonical_name],
                    "sources": [("ontology" if label in generated else "observed_ui")],
                    "memory": "promoted" if normalized in promoted else "demoted" if normalized in demoted else "neutral",
                }
            else:
                if term.canonical_name not in existing["concepts"]:
                    existing["concepts"].append(term.canonical_name)
                source = "ontology" if label in generated else "observed_ui"
                if source not in existing.get("sources", []):
                    existing.setdefault("sources", []).append(source)
        candidates.sort(key=lambda item: (-item["score"], item["label"]))
        target_terms.append(
            {
                "term_id": term.id,
                "canonical_name": term.canonical_name,
                "confidence": term.confidence,
                "source_evidence_ids": list(term.sources),
                "candidate_labels": candidates[:10],
            }
        )

    for target in directed_targets:
        for label in target["labels"]:
            normalized = normalize_term(label)
            score = target["priority"] * target["confidence"]
            existing = all_candidates.get(normalized)
            concepts = target.get("missing_concepts", [])
            if existing is None or score > existing["score"]:
                all_candidates[normalized] = {
                    "label": label,
                    "score": round(score, 3),
                    "concepts": concepts,
                    "sources": ["ai_directional"],
                    "memory": "promoted" if normalized in promoted else "demoted" if normalized in demoted else "neutral",
                    "branch_path": target.get("branch_path", []),
                    "reason": target.get("reason", ""),
                }
            else:
                existing.setdefault("sources", [])
                if "ai_directional" not in existing["sources"]:
                    existing["sources"].append("ai_directional")
                for concept in concepts:
                    if concept not in existing.get("concepts", []):
                        existing.setdefault("concepts", []).append(concept)
                existing.setdefault("branch_path", target.get("branch_path", []))
                existing.setdefault("reason", target.get("reason", ""))

    for item in preservation_labels:
        label = item["label"]
        normalized = normalize_term(label)
        memory_boost = 0.08 if normalized in promoted else -0.18 if normalized in demoted else 0.0
        score = round(min(0.92, max(0.12, float(item["score"]) + memory_boost)), 3)
        existing = all_candidates.get(normalized)
        concepts = ["coverage preservation"]
        if existing is None or score > existing["score"]:
            all_candidates[normalized] = {
                "label": label,
                "score": score,
                "concepts": concepts,
                "sources": ["coverage_preservation"],
                "memory": "promoted" if normalized in promoted else "demoted" if normalized in demoted else "neutral",
                "branch_path": item.get("state_path", []),
                "reason": item.get("reason", ""),
                "coverage_signals": item.get("signals", {}),
            }
        else:
            existing.setdefault("sources", [])
            if "coverage_preservation" not in existing["sources"]:
                existing["sources"].append("coverage_preservation")
            for concept in concepts:
                if concept not in existing.get("concepts", []):
                    existing.setdefault("concepts", []).append(concept)
            existing.setdefault("coverage_signals", item.get("signals", {}))

    gain_candidates = score_crawl_candidates(
        snapshot,
        missing_terms,
        cache=evidence_cache,
        cache_diff=evidence_cache_diff,
        memory=memory,
        observed_labels=observed_labels,
    )
    for candidate in gain_candidates:
        normalized = normalize_term(candidate["label"])
        gain_score = float(candidate["score"])
        gain_sources = ["crawl_gain", *candidate.get("sources", [])]
        existing = all_candidates.get(normalized)
        if existing is None:
            all_candidates[normalized] = {
                "label": candidate["label"],
                "score": round(gain_score, 3),
                "concepts": list(candidate.get("concepts", [])),
                "sources": gain_sources,
                "memory": candidate.get("memory", "neutral"),
                "reason": candidate.get("reason", ""),
                "gain_score": round(gain_score, 3),
                "gain_signals": candidate.get("signals", {}),
            }
            continue
        existing["score"] = round(max(float(existing["score"]), gain_score), 3)
        for source in gain_sources:
            if source not in existing.get("sources", []):
                existing.setdefault("sources", []).append(source)
        for concept in candidate.get("concepts", []):
            if concept not in existing.get("concepts", []):
                existing.setdefault("concepts", []).append(concept)
        if candidate.get("memory") == "demoted":
            existing["memory"] = "demoted"
        elif existing.get("memory") == "neutral" and candidate.get("memory") == "promoted":
            existing["memory"] = "promoted"
        existing["gain_score"] = round(gain_score, 3)
        existing["gain_signals"] = candidate.get("signals", {})

    prioritized = sorted(
        [item for item in all_candidates.values() if item["score"] > 0],
        key=lambda item: (item.get("memory") == "demoted", -item["score"], item["label"]),
    )
    noisy_labels = []
    for state in debug_report.get("likely_noise_states", []):
        if state.get("state_path"):
            noisy_labels.append(title_label(state["state_path"][-1].replace("-", " ")))
    cache_diff = evidence_cache_diff or {}
    gain_report = gain_summary(gain_candidates)

    return {
        "plan_id": new_id("plan"),
        "profile_id": profile.id,
        "profile_name": profile.name,
        "source_run_id": snapshot.run_id,
        "generated_at": utc_now(),
        "summary": {
            "missing_terms": len(missing_terms),
            "observed_labels": len(observed_labels),
            "prioritized_labels": len(prioritized),
            "noise_labels": len(set(normalize_term(label) for label in noisy_labels)),
            "memory_promoted_labels": len(promoted),
            "memory_demoted_labels": len(demoted),
            "memory_disproven_labels": len(disproven),
            "directional_targets": len(directed_targets),
            "coverage_preservation_labels": len(preservation_labels),
            "page_graph_nodes": page_graph["summary"]["nodes"],
            "page_graph_edges": page_graph["summary"]["edges"],
            "page_graph_roles": page_graph["summary"]["role_counts"],
            "crawl_gain_candidates": gain_report["candidates"],
            "crawl_gain_sources": gain_report["source_counts"],
            "evidence_cache_new_page_families": len(cache_diff.get("added_cache_keys", [])),
            "evidence_cache_changed_page_families": len(cache_diff.get("changed_content", [])),
        },
        "target_terms": target_terms,
        "directional_targets": directed_targets,
        "coverage_preservation_labels": preservation_labels,
        "crawl_gain_summary": gain_report,
        "page_graph_summary": page_graph["summary"],
        "prioritized_labels": prioritized[:60],
        "deprioritized_labels": sorted(set(noisy_labels)),
        "debug_summary": debug_report["summary"],
    }


def write_crawl_plan(workspace: Path, profile: Profile, plan: dict) -> Path:
    path = output_root(workspace, profile.name) / "reports" / f"crawl-plan-{plan['source_run_id']}.json"
    write_json(path, plan)
    return path


def latest_crawl_plan(workspace: Path, profile_name: str) -> dict:
    path = latest_json(output_root(workspace, profile_name) / "reports", "crawl-plan-*.json")
    return read_json(path)
