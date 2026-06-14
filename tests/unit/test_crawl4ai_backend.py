import asyncio
import builtins
import sys
import types

import pytest

from site_agent.cli import build_parser
from site_agent.core.crawl.crawl4ai_backend import (
    Crawl4AiPage,
    crawl4ai_fetch_pages,
    crawl4ai_import_error,
    crawl4ai_run_config,
    crawl_profile_with_crawl4ai,
    record_crawl4ai_page,
    result_to_page,
    transitions_from_crawl4ai_links,
)
from site_agent.core.crawl.playwright import CrawlError
from site_agent.core.models import CrawlSnapshot, utc_now
from site_agent.core.profiles import Profile


def make_profile() -> Profile:
    return Profile(
        id="profile",
        name="demo",
        base_url="https://example.com",
        host_allowlist=["example.com"],
        created_at=utc_now(),
    )


class FakeResult:
    def __init__(self, **values):
        self.__dict__.update(values)


def test_crawl4ai_result_normalizes_successful_rendered_page():
    page = result_to_page(
        FakeResult(
            success=True,
            url="https://example.com/start",
            redirected_url="https://example.com/dashboard",
            html="<h1>Dashboard</h1>",
            links={"internal": [{"href": "/settings", "text": "Settings"}]},
        ),
        "https://example.com/start",
    )

    assert page.url == "https://example.com/dashboard"
    assert page.html == "<h1>Dashboard</h1>"
    assert page.links["internal"][0]["href"] == "/settings"


def test_crawl4ai_result_rejects_failures_and_empty_html():
    with pytest.raises(CrawlError, match="blocked"):
        result_to_page(FakeResult(success=False, error_message="blocked"), "https://example.com")

    with pytest.raises(CrawlError, match="no HTML"):
        result_to_page(FakeResult(success=True, html=""), "https://example.com")


def test_crawl4ai_links_are_normalized_and_allowlisted():
    profile = make_profile()

    transitions = transitions_from_crawl4ai_links(
        profile,
        "page_1",
        "https://example.com/admin/index.html",
        {
            "internal": [
                {"href": "/settings.html", "text": "Settings"},
                {"href": "reports.html", "text": "Reports"},
            ],
            "external": [{"href": "https://evil.test/logout", "text": "Offsite"}],
        },
    )

    assert [transition.target_url for transition in transitions] == [
        "https://example.com/settings.html",
        "https://example.com/admin/reports.html",
    ]


def test_record_crawl4ai_page_uses_site_agent_snapshot_contract():
    profile = make_profile()
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run")

    transitions = record_crawl4ai_page(
        snapshot,
        profile,
        Crawl4AiPage(
            url="https://example.com/dashboard",
            html="<h1>Settings</h1><form><input aria-label='SSID'></form>",
            links={"internal": [{"href": "/settings", "text": "Settings"}]},
        ),
    )

    assert len(snapshot.pages) == 1
    assert snapshot.pages[0].headings == ["Settings"]
    assert snapshot.forms[0].label == "form"
    assert snapshot.elements[0].label == "SSID"
    assert any(evidence.locator == "crawl4ai" for evidence in snapshot.evidence)
    assert transitions[0].target_url == "https://example.com/settings"


def test_record_crawl4ai_page_rejects_off_allowlist_redirect():
    profile = make_profile()
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run")

    with pytest.raises(CrawlError, match="not in profile allowlist"):
        record_crawl4ai_page(
            snapshot,
            profile,
            Crawl4AiPage(url="https://evil.test/dashboard", html="<h1>Bad</h1>", links={}),
        )


def test_crawl_profile_with_crawl4ai_uses_fetch_adapter(monkeypatch, tmp_path):
    profile = make_profile()

    async def fake_fetch_pages(workspace, profile, target_url):
        return [
            Crawl4AiPage(
                url=target_url,
                html="<h1>Dashboard</h1><a href='/settings'>Settings</a>",
                links={},
            )
        ]

    monkeypatch.setattr("site_agent.core.crawl.crawl4ai_backend.crawl4ai_fetch_pages", fake_fetch_pages)

    snapshot = crawl_profile_with_crawl4ai(tmp_path, profile)

    assert snapshot.profile_id == profile.id
    assert snapshot.pages[0].headings == ["Dashboard"]
    assert snapshot.transitions[0].target_url == "https://example.com/settings"


def test_crawl_run_accepts_crawl4ai_backend_argument():
    parser = build_parser()

    args = parser.parse_args(["crawl", "run", "--profile", "demo", "--backend", "crawl4ai"])

    assert args.backend == "crawl4ai"


def test_crawl4ai_import_error_and_run_config_failure(monkeypatch):
    real_import = builtins.__import__

    def blocked_import(name, *args, **kwargs):
        if name == "crawl4ai":
            raise ImportError("missing crawl4ai")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked_import)

    assert crawl4ai_import_error() == "missing crawl4ai"
    with pytest.raises(CrawlError, match="Crawl4AI is required"):
        crawl4ai_run_config(make_profile())


def test_crawl4ai_fetch_pages_uses_fake_async_crawler_and_session_state(monkeypatch, tmp_path):
    profile = make_profile()
    profile.crawl.max_pages = 2
    profile.crawl.max_crawl_seconds = 3
    profile.crawl.navigation_wait_ms = 250
    profile.crawl.ignore_https_errors = True
    auth_state = tmp_path / "profiles" / profile.name / profile.auth.storage_state_path
    auth_state.parent.mkdir(parents=True)
    auth_state.write_text("{}", encoding="utf-8")

    class CacheMode:
        BYPASS = "bypass"

    class CrawlerRunConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class BrowserConfig:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class FakeCrawler:
        instances = []

        def __init__(self, *, config, base_directory):
            self.config = config
            self.base_directory = base_directory
            self.requests = []
            FakeCrawler.instances.append(self)

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, tb):
            return False

        async def arun(self, *, url, config):
            self.requests.append((url, config))
            if url.endswith("/settings"):
                return FakeResult(success=True, url=url, cleaned_html="<title>Settings</title><h1>Settings</h1>", links={})
            return FakeResult(
                success=True,
                url=url,
                html="<title>Home</title><h1>Home</h1>",
                links={
                    "internal": [
                        {"href": "/settings", "text": "Settings"},
                        {"href": "/settings", "text": "Settings"},
                        {"href": "https://evil.test/logout", "text": "Offsite"},
                    ]
                },
            )

    monkeypatch.setitem(
        sys.modules,
        "crawl4ai",
        types.SimpleNamespace(
            AsyncWebCrawler=FakeCrawler,
            BrowserConfig=BrowserConfig,
            CacheMode=CacheMode,
            CrawlerRunConfig=CrawlerRunConfig,
        ),
    )

    pages = asyncio.run(crawl4ai_fetch_pages(tmp_path, profile, profile.base_url))

    crawler = FakeCrawler.instances[0]
    assert [page.url for page in pages] == ["https://example.com", "https://example.com/settings"]
    assert crawler.base_directory.endswith("output/demo/runtime/crawl4ai")
    assert crawler.config.ignore_https_errors is True
    assert crawler.config.storage_state == str(auth_state)
    assert crawler.requests[0][1].cache_mode == "bypass"
    assert crawler.requests[0][1].page_timeout == 10_000
    assert crawler.requests[0][1].delay_before_return_html == 0.25
