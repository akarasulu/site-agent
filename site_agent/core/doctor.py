from __future__ import annotations

import importlib.util
import importlib.metadata
import shutil
import subprocess
import sys
from dataclasses import dataclass


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str | None = None


def has_module(name: str) -> bool:
    return importlib.util.find_spec(name) is not None


def run_playwright_install(browser: str = "chromium") -> int:
    return subprocess.call([sys.executable, "-m", "playwright", "install", browser])


def doctor_checks(include_playwright: bool = True) -> list[CheckResult]:
    results = [
        CheckResult("python", sys.version_info >= (3, 11), sys.version.split()[0], "Install Python 3.11 or newer."),
        CheckResult("site-agent command", shutil.which("site-agent") is not None, shutil.which("site-agent") or "not on PATH", "Install with pipx or scripts/install-shell-commands.sh."),
    ]
    if include_playwright:
        playwright_ok = has_module("playwright")
        results.append(
            CheckResult(
                "playwright package",
                playwright_ok,
                "installed" if playwright_ok else "missing",
                "Install with: pipx inject site-agent playwright or pip install 'site-agent[crawl]'.",
            )
        )
        if playwright_ok:
            try:
                from playwright.sync_api import sync_playwright

                with sync_playwright() as p:
                    browser = p.chromium.launch(headless=True)
                    browser.close()
                results.append(CheckResult("chromium browser", True, "launch ok"))
            except Exception as exc:
                results.append(
                    CheckResult(
                        "chromium browser",
                        False,
                        str(exc).splitlines()[0],
                        "Run: site-agent install browsers",
                    )
                )
        crawl4ai_ok = has_module("crawl4ai")
        crawl4ai_detail = "missing"
        if crawl4ai_ok:
            try:
                crawl4ai_detail = importlib.metadata.version("crawl4ai")
            except importlib.metadata.PackageNotFoundError:
                crawl4ai_detail = "installed"
        crawl4ai_fix = "Install with: pipx install 'site-agent[crawl]' or pip install -e '.[crawl]'."
        if sys.version_info >= (3, 14):
            crawl4ai_fix = (
                "Use Python 3.11-3.13 for Crawl4AI today, then run: "
                "python -m venv .venv && .venv/bin/python -m pip install -e '.[crawl]'."
            )
        results.append(
            CheckResult(
                "crawl4ai package",
                crawl4ai_ok,
                crawl4ai_detail,
                None if crawl4ai_ok else crawl4ai_fix,
            )
        )
    return results
