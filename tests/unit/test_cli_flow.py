import os
from pathlib import Path

from site_agent.cli import load_synthesis_snapshot, main, planned_crawl_inputs
from site_agent.core.models import CrawlSnapshot, Page, utc_now
from site_agent.core.storage import read_json, write_json


def test_cli_fixture_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Settings</h1><form><input aria-label='SSID'></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    seed = Path("profiles/demo/ontology.seed.json")
    write_json(seed, {"terms": [{"canonical_name": "ssid", "aliases": ["wifi name"], "sources": ["manual"], "confidence": 0.9}]})
    assert main(["auth", "setup", "--profile", "demo", "--username-env", "DEMO_USER"]) == 0
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "demo"]) == 0
    assert main(["mcp", "build", "--profile", "demo"]) == 0

    cache_files = list(Path("output/demo/reports").glob("evidence-cache-*.json"))
    assert len(cache_files) == 1
    cache = read_json(cache_files[0])
    assert cache["summary"]["pages"] == 1

    tools = read_json(Path("output/demo/mcp/tools.json"))["tools"]
    assert {tool["name"] for tool in tools} == {"home_overview_get", "settings_update", "ssid_get"}
    assert all("selector_fingerprint" not in tool for tool in tools)


def test_fixture_site_crawl_prints_progress(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    site = tmp_path / "site"
    site.mkdir()
    (site / "index.html").write_text("<a href='/settings.html'>Settings</a>", encoding="utf-8")
    (site / "settings.html").write_text("<h1>Settings</h1><form><input aria-label='SSID'></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    assert main(["crawl", "run", "--profile", "demo", "--fixture-site", str(site)]) == 0

    output = capsys.readouterr().out
    assert "Crawl progress:" in output
    assert "total unknown" in output
    assert "pages=" in output


def test_doctor_and_install_browser_commands(monkeypatch, capsys):
    assert main(["doctor", "--no-playwright"]) == 0
    assert "python" in capsys.readouterr().out

    called = {}

    def fake_install(browser):
        called["browser"] = browser
        return 0

    monkeypatch.setattr("site_agent.cli.run_playwright_install", fake_install)
    assert main(["install", "browsers", "--browser", "chromium"]) == 0
    assert called["browser"] == "chromium"
    assert "Installed Playwright browser" in capsys.readouterr().out


def test_synthesis_snapshot_prefers_newer_merged_snapshot_over_complete_collection(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    crawl_dir = Path("output/demo/crawl")
    reports_dir = Path("output/demo/reports")

    old_snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_demo",
        run_id="run_old_complete",
        pages=[Page(id="page_old", url="https://example.com/old")],
    )
    old_path = crawl_dir / f"snapshot-{old_snapshot.run_id}.json"
    write_json(old_path, old_snapshot)
    write_json(
        reports_dir / f"collection-{old_snapshot.run_id}.json",
        {"complete": True, "run_id": old_snapshot.run_id},
    )

    merged_snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_demo",
        run_id="merged_new",
        pages=[Page(id="page_new", url="https://example.com/new")],
    )
    merged_path = crawl_dir / f"snapshot-merged-{merged_snapshot.run_id}.json"
    write_json(merged_path, merged_snapshot)
    os.utime(old_path, (100, 100))
    os.utime(reports_dir / f"collection-{old_snapshot.run_id}.json", (100, 100))
    os.utime(merged_path, (200, 200))

    selected = load_synthesis_snapshot("demo")

    assert selected.run_id == "merged_new"


def test_crawl_run_loads_coverage_preservation_labels_from_plan(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SITE_AGENT_ALLOW_NO_AI", "1")
    monkeypatch.setenv("SITE_AGENT_AI_PROVIDER", "none")
    captured = {}

    def fake_inventory_profile(*args, **kwargs):
        return {"nodes": [], "node_count": 0, "coverage": {"complete": True}}

    def fake_build_ontology_artifact(*args, **kwargs):
        return [], []

    def fake_crawl_profile(
        workspace,
        profile,
        start_url=None,
        ontology=None,
        ai_backend=None,
        planned_labels=None,
        planned_paths=None,
        deprioritized_labels=None,
        progress=None,
        progress_total=None,
    ):
        captured["planned_labels"] = planned_labels
        captured["planned_paths"] = planned_paths
        return CrawlSnapshot(timestamp=utc_now(), profile_id=profile.id, run_id="run")

    monkeypatch.setattr("site_agent.cli.inventory_profile", fake_inventory_profile)
    monkeypatch.setattr("site_agent.cli.build_ontology_artifact", fake_build_ontology_artifact)
    monkeypatch.setattr("site_agent.cli.crawl_profile", fake_crawl_profile)

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    write_json(
        Path("output/demo/reports/crawl-plan-run_old.json"),
        {
            "plan_id": "plan_test",
            "prioritized_labels": [
                {"label": "Port Forwarding", "sources": ["ontology"], "score": 1.0},
            ],
            "coverage_preservation_labels": [
                {
                    "label": "Local Network",
                    "path": "Local Network > WLAN Basic",
                    "score": 0.76,
                }
            ],
            "directional_targets": [],
            "deprioritized_labels": [],
        },
    )

    assert main(["crawl", "run", "--profile", "demo", "--use-plan", "latest"]) == 0

    assert captured["planned_labels"] == ["Local Network", "Port Forwarding"]
    assert ["Local Network", "WLAN Basic"] in captured["planned_paths"]
    assert "coverage preservation label(s)" in capsys.readouterr().out


def test_planned_crawl_inputs_interleave_directional_and_preservation_paths():
    planned_labels, planned_paths, _ = planned_crawl_inputs(
        {
            "prioritized_labels": [
                {"label": "Port Forwarding", "sources": ["ontology"]},
                {"label": "WAN Status", "sources": ["observed_ui"]},
            ],
            "directional_targets": [
                {
                    "branch_path": ["Local Network", "LAN"],
                    "labels": ["DHCP Server", "Allocated Address"],
                },
                {
                    "branch_path": ["Internet", "Status", "WAN"],
                    "labels": ["WAN Connection", "PPPoE Username"],
                },
            ],
            "coverage_preservation_labels": [
                {"label": "WLAN", "path": "Local Network > WLAN"},
                {"label": "Management", "path": "Management & Diagnosis > Status"},
            ],
            "deprioritized_labels": [],
        },
        max_planned_labels=8,
    )

    assert planned_labels == ["WAN Status", "WLAN", "Management", "Port Forwarding"]
    assert planned_paths[:4] == [
        ["Local Network", "LAN"],
        ["Local Network", "WLAN"],
        ["Internet", "Status", "WAN"],
        ["Management & Diagnosis", "Status"],
    ]
    assert ["Local Network", "LAN", "DHCP Server"] in planned_paths
    assert ["Internet", "Status", "WAN", "WAN Connection"] in planned_paths


def test_crawl_compare_reports_evidence_cache_diff(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    first = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_demo",
        run_id="run_1",
        pages=[
            Page(
                id="page_status",
                url="https://example.com/#state=status",
                title="Status",
                html_snapshot="<html><body><a>Status</a></body></html>",
            )
        ],
    )
    second = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_demo",
        run_id="run_2",
        pages=[
            Page(
                id="page_status",
                url="https://example.com/#state=status",
                title="Status",
                html_snapshot="<html><body><a>Status</a></body></html>",
            ),
            Page(
                id="page_forwarding",
                url="https://example.com/#state=security/port-forwarding",
                title="Port Forwarding",
                html_snapshot="<html><body><a>Port Forwarding</a></body></html>",
            ),
        ],
    )
    write_json(Path("output/demo/crawl/snapshot-run_1.json"), first)
    write_json(Path("output/demo/crawl/snapshot-run_2.json"), second)

    assert main(["crawl", "compare", "--profile", "demo"]) == 0

    report = read_json(Path("output/demo/reports/coverage-compare-run_1-to-run_2.json"))
    assert report["summary"]["new_page_families"] == 1
    assert report["evidence_cache"]["added_cache_keys"]
    assert "new page family" in capsys.readouterr().out
