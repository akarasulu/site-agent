from __future__ import annotations

import re
from pathlib import Path

from site_agent.core.ai.backends import AiBackend
from site_agent.core.debug import build_debug_report, state_path
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm, MappedSchema, UiElement, new_id, utc_now
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


def build_crawl_plan(
    profile: Profile,
    snapshot: CrawlSnapshot,
    schema: MappedSchema,
    ai_backend: AiBackend,
    max_terms: int = 20,
    memory: dict | None = None,
) -> dict:
    debug_report = build_debug_report(snapshot, schema)
    missing_terms = plan_missing_terms(schema, max_terms)
    observed_labels = observed_navigation_labels(snapshot)
    all_candidates: dict[str, dict] = {}
    ai_scores = ai_plan_scores(observed_labels, missing_terms, ai_backend)
    promoted = {normalize_term(label) for label in (memory or {}).get("promoted_labels", [])}
    demoted = {normalize_term(label) for label in (memory or {}).get("demoted_labels", [])}

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

    prioritized = sorted(
        [item for item in all_candidates.values() if item["score"] > 0],
        key=lambda item: (item.get("memory") == "demoted", -item["score"], item["label"]),
    )
    noisy_labels = []
    for state in debug_report.get("likely_noise_states", []):
        if state.get("state_path"):
            noisy_labels.append(title_label(state["state_path"][-1].replace("-", " ")))

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
        },
        "target_terms": target_terms,
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
