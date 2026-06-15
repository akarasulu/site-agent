from __future__ import annotations

from collections import defaultdict
from typing import Any

from site_agent.core.debug import state_path
from site_agent.core.evidence_cache import EvidenceCache, PageEvidenceCacheRecord
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm
from site_agent.core.page_graph import coverage_preservation_labels


def score_crawl_candidates(
    snapshot: CrawlSnapshot,
    missing_terms: list[DomainTerm] | None = None,
    cache: EvidenceCache | dict[str, Any] | None = None,
    cache_diff: dict[str, Any] | None = None,
    memory: dict[str, Any] | None = None,
    observed_labels: list[str] | None = None,
    limit: int = 80,
) -> list[dict[str, Any]]:
    candidates: dict[str, dict[str, Any]] = {}
    for label in observed_labels or snapshot_labels(snapshot):
        _add_signal(candidates, label, "observed_ui", 0.16)

    for record in _cache_records(cache):
        for label in [*record.get("link_labels", []), *record.get("control_labels", [])]:
            _add_signal(candidates, label, "evidence_cache", 0.10)

    for term in missing_terms or []:
        for label in _term_labels(term):
            _add_signal(candidates, label, "missing_term", 0.24, concept=term.canonical_name)
        for candidate in list(candidates.values()):
            overlap = _term_overlap(term, candidate["label"])
            if overlap > 0:
                candidate["score"] += min(0.34, overlap * max(0.2, term.confidence))
                candidate["signals"]["term_overlap"] = round(
                    max(candidate["signals"].get("term_overlap", 0.0), overlap),
                    3,
                )
                _append_unique(candidate["concepts"], term.canonical_name)
                _append_unique(candidate["sources"], "term_overlap")

    for label_key, gain in _cache_gain_by_label(cache, cache_diff).items():
        candidate = candidates.get(label_key)
        if not candidate:
            continue
        if gain["new_page_families"]:
            candidate["score"] += min(0.26, 0.13 * gain["new_page_families"])
            candidate["signals"]["new_page_families"] = gain["new_page_families"]
            _append_unique(candidate["sources"], "cache_new_family")
        if gain["changed_content"]:
            candidate["score"] += min(0.12, 0.04 * gain["changed_content"])
            candidate["signals"]["changed_content"] = gain["changed_content"]
            _append_unique(candidate["sources"], "cache_changed_content")

    for item in coverage_preservation_labels(snapshot):
        candidate = candidates.get(normalize_term(item["label"]))
        if not candidate:
            continue
        candidate["score"] += min(0.16, float(item.get("score", 0.0)) * 0.18)
        candidate["signals"]["coverage_preservation"] = item.get("signals", {})
        _append_unique(candidate["sources"], "coverage_preservation")

    promoted = {normalize_term(label) for label in (memory or {}).get("promoted_labels", [])}
    demoted = {normalize_term(label) for label in (memory or {}).get("demoted_labels", [])}
    for label_key, candidate in candidates.items():
        if label_key in promoted:
            candidate["score"] += 0.12
            candidate["memory"] = "promoted"
        elif label_key in demoted:
            candidate["score"] -= 0.28
            candidate["memory"] = "demoted"
        else:
            candidate["memory"] = "neutral"
        candidate["score"] = round(max(0.0, min(1.0, candidate["score"])), 3)
        candidate["reason"] = _candidate_reason(candidate)

    return sorted(
        [candidate for candidate in candidates.values() if candidate["score"] > 0],
        key=lambda item: (item["memory"] == "demoted", -item["score"], item["label"]),
    )[:limit]


def gain_summary(candidates: list[dict[str, Any]]) -> dict[str, Any]:
    source_counts: dict[str, int] = defaultdict(int)
    memory_counts: dict[str, int] = defaultdict(int)
    for candidate in candidates:
        for source in candidate.get("sources", []):
            source_counts[source] += 1
        memory_counts[candidate.get("memory", "neutral")] += 1
    return {
        "candidates": len(candidates),
        "source_counts": dict(sorted(source_counts.items())),
        "memory_counts": dict(sorted(memory_counts.items())),
        "top_labels": [candidate["label"] for candidate in candidates[:10]],
    }


def snapshot_labels(snapshot: CrawlSnapshot) -> list[str]:
    labels: list[str] = []
    for transition in snapshot.transitions:
        labels.append(transition.trigger_label)
    for page in snapshot.pages:
        labels.extend(_title_label(part.replace("-", " ")) for part in state_path(page))
        labels.extend(page.headings[:5])
    for element in snapshot.elements:
        labels.append(element.label)
    return _ordered_labels(labels)


def _cache_gain_by_label(
    cache: EvidenceCache | dict[str, Any] | None,
    cache_diff: dict[str, Any] | None,
) -> dict[str, dict[str, int]]:
    if not cache or not cache_diff:
        return {}
    added = set(cache_diff.get("added_cache_keys", []))
    changed = {item.get("cache_key") for item in cache_diff.get("changed_content", [])}
    signals: dict[str, dict[str, int]] = defaultdict(lambda: {"new_page_families": 0, "changed_content": 0})
    for record in _cache_records(cache):
        labels = [*record.get("link_labels", []), *record.get("control_labels", [])]
        for label in labels:
            key = normalize_term(label)
            if record.get("cache_key") in added:
                signals[key]["new_page_families"] += 1
            if record.get("cache_key") in changed:
                signals[key]["changed_content"] += 1
    return signals


def _add_signal(
    candidates: dict[str, dict[str, Any]],
    label: str,
    source: str,
    score: float,
    concept: str | None = None,
) -> None:
    clean = " ".join(str(label).split()).strip()
    key = normalize_term(clean)
    if not clean or not key:
        return
    candidate = candidates.setdefault(
        key,
        {
            "label": clean,
            "score": 0.0,
            "concepts": [],
            "sources": [],
            "signals": {},
            "memory": "neutral",
        },
    )
    candidate["score"] = max(candidate["score"], score)
    _append_unique(candidate["sources"], source)
    if concept:
        _append_unique(candidate["concepts"], concept)


def _cache_records(cache: EvidenceCache | dict[str, Any] | None) -> list[dict[str, Any]]:
    if not cache:
        return []
    records = cache.records if isinstance(cache, EvidenceCache) else cache.get("records", [])
    normalized = []
    for record in records:
        if isinstance(record, PageEvidenceCacheRecord):
            normalized.append(record.__dict__)
        else:
            normalized.append(dict(record))
    return normalized


def _term_labels(term: DomainTerm) -> list[str]:
    labels = []
    for value in [term.canonical_name, *term.aliases]:
        clean = normalize_term(value)
        if clean:
            labels.append(_title_label(clean))
    return _ordered_labels(labels)


def _term_overlap(term: DomainTerm, label: str) -> float:
    label_tokens = _tokens(label)
    term_tokens = set()
    for value in [term.canonical_name, *term.aliases]:
        term_tokens.update(_tokens(value))
    if not label_tokens or not term_tokens:
        return 0.0
    return len(label_tokens & term_tokens) / len(label_tokens | term_tokens)


def _tokens(value: str) -> set[str]:
    return {part for part in normalize_term(value).split() if len(part) > 2}


def _title_label(value: str) -> str:
    return " ".join(part.capitalize() for part in normalize_term(value).split())


def _ordered_labels(labels: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for label in labels:
        clean = " ".join(str(label).split()).strip()
        key = normalize_term(clean)
        if clean and key not in seen:
            result.append(clean)
            seen.add(key)
    return result


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


def _candidate_reason(candidate: dict[str, Any]) -> str:
    sources = ", ".join(candidate.get("sources", []))
    concepts = ", ".join(candidate.get("concepts", []))
    if concepts:
        return f"Expected crawl gain for {concepts} from {sources}."
    return f"Expected crawl gain from {sources}."
