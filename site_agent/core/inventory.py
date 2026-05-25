from __future__ import annotations

from collections import Counter, deque
import re
import time
from pathlib import Path
from typing import Any

from site_agent.core.crawl.playwright import (
    discover_navigation_labels,
    extract_browser_facts,
    path_revisit_allowed,
    replay_navigation_path,
    safe_click_patterns,
    state_text_hash,
)
from site_agent.core.ingest.docs import normalize_term
from site_agent.core.models import CrawlSnapshot, DomainTerm, Page, utc_now
from site_agent.core.profiles import Profile, profile_root


STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "has",
    "have",
    "in",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "this",
    "to",
    "was",
    "were",
    "when",
    "with",
    "you",
    "your",
}


def tokenize(text: str) -> list[str]:
    return [token for token in re.findall(r"[a-z0-9]+", normalize_term(text)) if len(token) > 1 and token not in STOPWORDS]


def domain_terms(ontology: list[DomainTerm]) -> tuple[set[str], dict[str, set[str]]]:
    vocabulary: set[str] = set()
    synonyms: dict[str, set[str]] = {}
    for term in ontology:
        names = [term.canonical_name, *term.aliases]
        canonical_tokens = set(tokenize(term.canonical_name))
        all_tokens: set[str] = set()
        for name in names:
            all_tokens.update(tokenize(name))
        if not all_tokens:
            continue
        vocabulary.update(all_tokens)
        canonical = normalize_term(term.canonical_name)
        synonyms.setdefault(canonical, set()).update(all_tokens | canonical_tokens)
    return vocabulary, synonyms


def word_histogram(text: str, vocabulary: set[str] | None = None, limit: int = 80) -> dict[str, int]:
    counts = Counter(tokenize(text))
    if vocabulary:
        counts = Counter({token: count for token, count in counts.items() if token in vocabulary})
    return dict(counts.most_common(limit))


def synonym_hits(histogram: dict[str, int], synonyms: dict[str, set[str]]) -> dict[str, int]:
    hits = {}
    for canonical, tokens in synonyms.items():
        score = sum(histogram.get(token, 0) for token in tokens)
        if score:
            hits[canonical] = score
    return dict(sorted(hits.items(), key=lambda item: item[1], reverse=True))


def add_tree_node(root: dict[str, Any], node: dict[str, Any]) -> None:
    current = root
    for label in node["path"]:
        child = next((item for item in current["children"] if item["label_key"] == normalize_term(label)), None)
        if child is None:
            child = {"label": label, "label_key": normalize_term(label), "children": []}
            current["children"].append(child)
        current = child
    current.update({key: value for key, value in node.items() if key != "path"})


def build_site_tree(nodes: list[dict[str, Any]]) -> dict[str, Any]:
    root: dict[str, Any] = {"label": "root", "label_key": "root", "children": []}
    for node in nodes:
        add_tree_node(root, node)
    return root


def inventory_profile(
    workspace: Path,
    profile: Profile,
    ontology: list[DomainTerm],
    *,
    max_nodes: int | None = None,
    max_depth: int | None = None,
    deadline: float | None = None,
) -> dict[str, Any]:
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise RuntimeError("Playwright is required for site inventory. Install browsers with: site-agent install-browsers") from exc

    vocabulary, synonyms = domain_terms(ontology)
    max_nodes = max_nodes or profile.crawl.max_js_states
    max_depth = max_depth or profile.crawl.max_js_depth
    auth_state = profile_root(workspace, profile.name) / profile.auth.storage_state_path
    storage_state = str(auth_state) if auth_state.exists() else None
    nodes: list[dict[str, Any]] = []
    failed_paths: list[dict[str, Any]] = []
    visited: set[tuple[str, ...]] = set()
    queued: set[tuple[str, ...]] = {()}
    pending = deque([((), set())])
    seen_hashes: set[str] = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context_kwargs = {"ignore_https_errors": profile.crawl.ignore_https_errors}
        if storage_state:
            context_kwargs["storage_state"] = storage_state
        context = browser.new_context(**context_kwargs)
        page = context.new_page()
        deny_patterns = safe_click_patterns(profile)
        while pending and len(nodes) < max_nodes:
            if deadline and time.monotonic() >= deadline:
                break
            path, parent_label_keys = pending.popleft()
            if path in visited:
                continue
            try:
                ok = replay_navigation_path(page, profile.base_url, path, profile)
            except Exception:
                ok = False
            if not ok:
                failed_paths.append({"path": list(path), "reason": "replay_failed"})
                continue
            visited.add(path)
            try:
                text = page.locator("body").inner_text(timeout=3000)
            except Exception:
                text = page.content()
            text_hash = state_text_hash(f"{page.url}\n{text}")
            visible_labels = discover_navigation_labels(page, profile)
            raw_hist = word_histogram(text, None)
            domain_hist = word_histogram(text, vocabulary) if vocabulary else raw_hist
            page_model = Page(id=f"inventory_{len(nodes)}", url=page.url, title=page.title(), headings=[])
            snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="inventory")
            snapshot.pages.append(page_model)
            extract_browser_facts(snapshot, page, page_model.id, page.url)
            headings = []
            for element in snapshot.elements:
                if element.control_type in {"heading", "section_heading"} and element.label not in headings:
                    headings.append(element.label)
            nodes.append(
                {
                    "path": list(path),
                    "path_key": "/".join(normalize_term(label) for label in path),
                    "url": page.url,
                    "title": page.title(),
                    "headings": headings,
                    "state_hash": text_hash,
                    "duplicate_state": text_hash in seen_hashes,
                    "navigation_labels": visible_labels,
                    "word_histogram": raw_hist,
                    "domain_histogram": domain_hist,
                    "synonym_hits": synonym_hits(domain_hist, synonyms),
                }
            )
            seen_hashes.add(text_hash)
            if len(path) >= max_depth:
                continue
            for label in visible_labels:
                label_key = normalize_term(label)
                if label_key in parent_label_keys:
                    continue
                if not path_revisit_allowed(path, label, profile):
                    continue
                next_path = (*path, label)
                if next_path not in visited and next_path not in queued:
                    pending.append((next_path, {normalize_term(item) for item in visible_labels}))
                    queued.add(next_path)
        context.close()
        browser.close()

    return {
        "generated_at": utc_now(),
        "profile_id": profile.id,
        "profile_name": profile.name,
        "base_url": profile.base_url,
        "node_count": len(nodes),
        "failed_paths": failed_paths,
        "domain_vocabulary": sorted(vocabulary),
        "nodes": nodes,
        "tree": build_site_tree(nodes),
        "coverage": {
            "queued_paths": len(queued),
            "visited_paths": len(visited),
            "complete": not pending and not failed_paths,
            "remaining_paths": [list(path) for path, _ in list(pending)[:100]],
        },
    }
