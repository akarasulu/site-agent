from pathlib import Path

from site_agent.cli import main
from site_agent.core.storage import read_json, write_json


def test_schema_review_queue_and_edit_approval(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    html = tmp_path / "fixture.html"
    html.write_text("<h1>Status</h1><form><input aria-label='WAN Status'></form>", encoding="utf-8")

    assert main(["profile", "init", "--name", "demo", "--base-url", "https://example.com"]) == 0
    write_json(
        Path("profiles/demo/ontology.seed.json"),
        {"terms": [{"canonical_name": "wan connection status", "confidence": 0.9}]},
    )
    assert main(["crawl", "run", "--profile", "demo", "--fixture-html", str(html)]) == 0
    assert main(["schema", "review", "--profile", "demo"]) == 0

    schema_path = sorted(Path("output/demo/schema").glob("mapped-schema-*.json"))[-1]
    schema = read_json(schema_path)
    mapping = schema["mappings"][0]
    assert mapping["status"] == "review"

    assert main(["schema", "queue", "--profile", "demo"]) == 0
    assert (
        main(
            [
                "schema",
                "edit",
                "--profile",
                "demo",
                "--ui-element-id",
                mapping["ui_element_id"],
                "--canonical-name",
                "wan status",
                "--note",
                "Fixture reviewer accepted canonical WAN status.",
            ]
        )
        == 0
    )
    assert main(["mcp", "build", "--profile", "demo"]) == 0

    tools = read_json(Path("output/demo/mcp/tools.json"))["tools"]
    assert "wan_connection_get" in [tool["name"] for tool in tools]
    assert "status_update" in [tool["name"] for tool in tools]
    reviewed = read_json(sorted(Path("output/demo/schema").glob("*reviewed*.json"))[-1])
    assert reviewed["mappings"][0]["status"] == "ready"
    assert any(item["kind"] == "review" for item in reviewed["evidence"])
