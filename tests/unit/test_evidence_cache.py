from pathlib import Path

from site_agent.core.evidence_cache import (
    build_evidence_cache,
    diff_evidence_caches,
    load_evidence_cache,
    write_evidence_cache,
)
from site_agent.core.models import CrawlSnapshot, Evidence, Form, Page, Transition, UiElement, utc_now


def make_snapshot(run_id: str, status_text: str = "Connected") -> CrawlSnapshot:
    return CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id=run_id,
        pages=[
            Page(
                id="page_status",
                url="https://example.test/admin?token=secret#state=status/wan",
                title="WAN Status",
                headings=["Internet Status"],
                html_snapshot=f"""
                <html>
                  <body>
                    <nav><a href="#status">Status</a><a href="#wifi">Wi-Fi</a></nav>
                    <section><h1>Internet Status</h1><label>WAN Status</label>
                    <span>{status_text}</span></section>
                  </body>
                </html>
                """,
            ),
            Page(
                id="page_lan",
                url="https://example.test/admin?token=other#state=status/lan",
                title="LAN Status",
                headings=["Local Network Status"],
                html_snapshot="""
                <html>
                  <body>
                    <nav><a href="#status">Status</a><a href="#wifi">Wi-Fi</a></nav>
                    <section><h1>Local Network Status</h1><label>LAN Status</label>
                    <span>Ready</span></section>
                  </body>
                </html>
                """,
            ),
        ],
        forms=[Form(id="form_status", page_id="page_status", label="Status", field_ids=["ui_status"])],
        elements=[
            UiElement(
                id="ui_status",
                page_id="page_status",
                selector_fingerprint="fp_status",
                label="WAN Status",
                control_type="readonly_status",
                context={"read_value": status_text},
                evidence_ids=["ev_status"],
            ),
            UiElement(
                id="ui_lan",
                page_id="page_lan",
                selector_fingerprint="fp_lan",
                label="LAN Status",
                control_type="readonly_status",
                context={"read_value": "Ready"},
                evidence_ids=["ev_lan"],
            ),
        ],
        transitions=[Transition(source_page_id="page_status", target_url="https://example.test/admin#state=status/lan", trigger_label="LAN")],
        evidence=[
            Evidence(id="ev_status", kind="ui", source="https://example.test/admin", summary="WAN status label"),
            Evidence(id="ev_lan", kind="ui", source="https://example.test/admin", summary="LAN status label"),
        ],
    )


def test_evidence_cache_groups_repeated_page_templates_without_query_values():
    cache = build_evidence_cache(make_snapshot("run_1"))

    assert cache.summary["pages"] == 2
    assert cache.summary["templates"] == 2
    assert cache.summary["cacheable_pages"] == 2
    status_record = next(record for record in cache.records if record.page_id == "page_status")
    assert status_record.url_family["query_keys"] == ["token"]
    assert status_record.state_path == ["status", "wan"]
    assert status_record.evidence_density == {"ui": 1}
    assert "Status" in status_record.link_labels
    assert "WAN Status" in status_record.control_labels


def test_cache_key_ignores_raw_selector_fingerprints_and_query_values():
    first = build_evidence_cache(make_snapshot("run_1"))
    changed = make_snapshot("run_2")
    changed.elements[0].selector_fingerprint = "different_selector"
    changed.pages[0].url = "https://example.test/admin?token=rotated#state=status/wan"
    second = build_evidence_cache(changed)

    first_record = next(record for record in first.records if record.page_id == "page_status")
    second_record = next(record for record in second.records if record.page_id == "page_status")
    assert first_record.cache_key == second_record.cache_key


def test_cache_diff_detects_content_changes_for_same_page_family(tmp_path: Path):
    previous = build_evidence_cache(make_snapshot("run_1", "Connected"))
    current = build_evidence_cache(make_snapshot("run_2", "Disconnected"))

    diff = diff_evidence_caches(previous, current)

    assert diff["added_cache_keys"] == []
    assert diff["removed_cache_keys"] == []
    assert [item["url"] for item in diff["changed_content"]] == [
        "https://example.test/admin?token=secret#state=status/wan"
    ]

    path = write_evidence_cache(tmp_path, "demo", current)
    loaded = load_evidence_cache(path)
    assert loaded["run_id"] == "run_2"
    assert loaded["summary"]["pages"] == 2
