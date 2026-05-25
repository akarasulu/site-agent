from pathlib import Path

from site_agent.cli import main
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

    tools = read_json(Path("output/demo/mcp/tools.json"))["tools"]
    assert tools[0]["name"] == "get_ssid"
    assert "selector_fingerprint" not in tools[0]


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
