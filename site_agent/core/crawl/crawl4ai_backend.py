from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

from site_agent.core.crawl.playwright import CrawlError, CrawlProgress, emit_progress, validate_url_allowed
from site_agent.core.extract.html import extract_interactions
from site_agent.core.models import CrawlSnapshot, Evidence, Transition, new_id, utc_now
from site_agent.core.profiles import Profile, output_root, profile_root
from site_agent.core.storage import ensure_dir


CRAWL4AI_VERSION = "0.8.9"
CRAWL4AI_INSTALL_FIX = (
    "Install Crawl4AI with Python 3.11-3.13: "
    "python -m venv .venv && .venv/bin/python -m pip install -e '.[crawl]' && "
    ".venv/bin/python -m playwright install chromium"
)


@dataclass
class Crawl4AiPage:
    url: str
    html: str
    links: dict[str, list[dict[str, Any]]]


def crawl4ai_import_error() -> str | None:
    try:
        import crawl4ai  # noqa: F401
    except Exception as exc:
        return str(exc).splitlines()[0] or exc.__class__.__name__
    return None


def normalize_result_url(result: Any, requested_url: str) -> str:
    return str(getattr(result, "redirected_url", None) or getattr(result, "url", None) or requested_url)


def result_to_page(result: Any, requested_url: str) -> Crawl4AiPage:
    success = bool(getattr(result, "success", False))
    if not success:
        message = str(getattr(result, "error_message", "") or "unknown Crawl4AI failure")
        raise CrawlError(f"Crawl4AI failed for {requested_url}. Details: {message}")
    html = str(getattr(result, "html", "") or getattr(result, "cleaned_html", "") or "")
    if not html.strip():
        raise CrawlError(f"Crawl4AI returned no HTML for {requested_url}.")
    links = getattr(result, "links", {}) or {}
    if not isinstance(links, dict):
        links = {}
    return Crawl4AiPage(url=normalize_result_url(result, requested_url), html=html, links=links)


def allowed_transition(profile: Profile, transition: Transition) -> bool:
    host = urlparse(transition.target_url).netloc
    return bool(host) and host in set(profile.host_allowlist)


def transitions_from_crawl4ai_links(profile: Profile, page_id: str, base_url: str, links: dict[str, list[dict[str, Any]]]) -> list[Transition]:
    transitions: list[Transition] = []
    seen: set[tuple[str, str]] = set()
    for group in links.values():
        if not isinstance(group, list):
            continue
        for item in group:
            if not isinstance(item, dict):
                continue
            href = str(item.get("href") or item.get("url") or "").strip()
            if not href:
                continue
            target_url = urljoin(base_url, href)
            transition = Transition(
                source_page_id=page_id,
                target_url=target_url,
                trigger_label=" ".join(str(item.get("text") or item.get("title") or target_url).split())[:120],
                risk_level="low",
            )
            key = (transition.target_url, transition.trigger_label)
            if key not in seen and allowed_transition(profile, transition):
                transitions.append(transition)
                seen.add(key)
    return transitions


def record_crawl4ai_page(snapshot: CrawlSnapshot, profile: Profile, page: Crawl4AiPage) -> list[Transition]:
    validate_url_allowed(profile, page.url)
    title_page, forms, elements, transitions, evidence = extract_interactions(page.html, page.url)
    snapshot.pages.append(title_page)
    snapshot.forms.extend(forms)
    snapshot.elements.extend(elements)
    snapshot.evidence.extend(evidence)
    snapshot.evidence.append(
        Evidence(
            id=new_id("ev"),
            kind="system",
            source=page.url,
            summary="Rendered HTML captured through Crawl4AI backend.",
            locator="crawl4ai",
        )
    )
    c4ai_transitions = transitions_from_crawl4ai_links(profile, title_page.id, page.url, page.links)
    combined = transitions + c4ai_transitions
    deduped: list[Transition] = []
    seen: set[tuple[str, str, str]] = set()
    for transition in combined:
        key = (transition.source_page_id, transition.target_url, transition.trigger_label)
        if key not in seen and allowed_transition(profile, transition):
            deduped.append(transition)
            seen.add(key)
    return deduped


def crawl4ai_run_config(profile: Profile):
    try:
        from crawl4ai import CacheMode, CrawlerRunConfig
    except Exception as exc:
        raise CrawlError(f"Crawl4AI is required for backend 'crawl4ai'. {CRAWL4AI_INSTALL_FIX}. Details: {exc}") from exc

    return CrawlerRunConfig(
        cache_mode=CacheMode.BYPASS,
        wait_until="networkidle",
        page_timeout=max(10_000, profile.crawl.max_crawl_seconds * 1000 if profile.crawl.max_crawl_seconds > 0 else 60_000),
        delay_before_return_html=max(profile.crawl.navigation_wait_ms / 1000, 0.1),
        process_iframes=True,
        flatten_shadow_dom=True,
        remove_overlay_elements=False,
        remove_consent_popups=False,
        simulate_user=False,
        override_navigator=False,
        magic=False,
        verbose=False,
    )


async def crawl4ai_fetch_pages(workspace: Path, profile: Profile, target_url: str) -> list[Crawl4AiPage]:
    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig
    except Exception as exc:
        raise CrawlError(f"Crawl4AI is required for backend 'crawl4ai'. {CRAWL4AI_INSTALL_FIX}. Details: {exc}") from exc

    runtime_dir = ensure_dir(output_root(workspace, profile.name) / "runtime" / "crawl4ai")
    auth_state = profile_root(workspace, profile.name) / profile.auth.storage_state_path
    storage_state = str(auth_state) if auth_state.exists() else None
    browser_config = BrowserConfig(
        browser_type="chromium",
        headless=True,
        verbose=False,
        ignore_https_errors=profile.crawl.ignore_https_errors,
        storage_state=storage_state,
        accept_downloads=False,
        java_script_enabled=True,
    )
    run_config = crawl4ai_run_config(profile)
    pages: list[Crawl4AiPage] = []
    visited: set[str] = set()
    pending: list[str] = [target_url]

    async with AsyncWebCrawler(config=browser_config, base_directory=str(runtime_dir)) as crawler:
        while pending and len(visited) < profile.crawl.max_pages:
            current_url = pending.pop(0)
            if current_url in visited:
                continue
            validate_url_allowed(profile, current_url)
            visited.add(current_url)
            result = await crawler.arun(url=current_url, config=run_config)
            page = result_to_page(result, current_url)
            validate_url_allowed(profile, page.url)
            pages.append(page)
            for transition in transitions_from_crawl4ai_links(profile, "pending", page.url, page.links):
                if transition.target_url not in visited and transition.target_url not in pending:
                    pending.append(transition.target_url)
    return pages


def crawl_profile_with_crawl4ai(
    workspace: Path,
    profile: Profile,
    start_url: str | None = None,
    progress: CrawlProgress | None = None,
    progress_total: int | None = None,
) -> CrawlSnapshot:
    target_url = start_url or profile.base_url
    validate_url_allowed(profile, target_url)
    pages = asyncio.run(crawl4ai_fetch_pages(workspace, profile, target_url))
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id=new_id("run"))
    pending_transitions: list[Transition] = []
    for index, page in enumerate(pages, start=1):
        pending_transitions.extend(record_crawl4ai_page(snapshot, profile, page))
        emit_progress(
            progress,
            snapshot,
            phase="crawl4ai-page",
            current=page.url,
            scanned=index,
            total=progress_total,
        )
    snapshot.transitions.extend(pending_transitions)
    return snapshot
