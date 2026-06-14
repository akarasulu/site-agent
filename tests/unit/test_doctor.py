import sys
import types

from site_agent.core import doctor


class FakeBrowser:
    def close(self):
        pass


class FakeChromium:
    def launch(self, headless=True):
        return FakeBrowser()


class FakePlaywright:
    chromium = FakeChromium()


class FakePlaywrightContext:
    def __enter__(self):
        return FakePlaywright()

    def __exit__(self, exc_type, exc, traceback):
        return False


def install_fake_playwright(monkeypatch, sync_playwright):
    playwright_module = types.ModuleType("playwright")
    sync_api_module = types.ModuleType("playwright.sync_api")
    sync_api_module.sync_playwright = sync_playwright
    monkeypatch.setitem(sys.modules, "playwright", playwright_module)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", sync_api_module)


def test_doctor_checks_skips_browser_checks_when_disabled(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/bin/site-agent" if command == "site-agent" else None)

    results = doctor.doctor_checks(include_playwright=False)

    assert [result.name for result in results] == ["python", "site-agent command"]
    assert all(result.ok for result in results)


def test_doctor_checks_reports_playwright_and_crawl4ai_success(monkeypatch):
    monkeypatch.setattr(doctor.shutil, "which", lambda command: "/bin/site-agent" if command == "site-agent" else None)
    monkeypatch.setattr(doctor, "has_module", lambda name: name in {"playwright", "crawl4ai"})
    monkeypatch.setattr(doctor.importlib.metadata, "version", lambda name: "0.8.9")
    install_fake_playwright(monkeypatch, lambda: FakePlaywrightContext())

    results = doctor.doctor_checks()
    by_name = {result.name: result for result in results}

    assert by_name["playwright package"].ok is True
    assert by_name["chromium browser"].detail == "launch ok"
    assert by_name["crawl4ai package"].detail == "0.8.9"


def test_doctor_checks_reports_browser_launch_failure(monkeypatch):
    def broken_sync_playwright():
        raise RuntimeError("browser missing")

    monkeypatch.setattr(doctor.shutil, "which", lambda command: None)
    monkeypatch.setattr(doctor, "has_module", lambda name: name == "playwright")
    install_fake_playwright(monkeypatch, broken_sync_playwright)

    results = doctor.doctor_checks()
    by_name = {result.name: result for result in results}

    assert by_name["site-agent command"].ok is False
    assert by_name["chromium browser"].ok is False
    assert by_name["chromium browser"].fix == "Run: site-agent install browsers"
    assert by_name["crawl4ai package"].ok is False
