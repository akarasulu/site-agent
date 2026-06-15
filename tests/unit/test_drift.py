from site_agent.core.drift.check import compare_snapshots
from site_agent.core.drift.reuse import build_adapter_reuse_report
from site_agent.core.models import CrawlSnapshot, Page, UiElement, utc_now


def snapshot_with_selectors(*selectors: str) -> CrawlSnapshot:
    return CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        elements=[
            UiElement(
                id=f"ui_{index}",
                page_id="page",
                selector_fingerprint=selector,
                label=selector,
                control_type="input",
            )
            for index, selector in enumerate(selectors)
        ],
    )


def finding_kinds(report) -> list[str]:
    return [finding.kind for finding in report.findings]


def test_compare_snapshots_reports_no_drift():
    report = compare_snapshots("profile", snapshot_with_selectors("a", "b"), snapshot_with_selectors("a", "b"))

    assert finding_kinds(report) == ["no_drift"]
    assert report.findings[0].severity == "info"


def test_compare_snapshots_reports_added_and_removed_ui():
    report = compare_snapshots("profile", snapshot_with_selectors("a", "removed"), snapshot_with_selectors("a", "added"))

    assert finding_kinds(report) == ["removed_ui", "added_ui"]
    assert report.findings[0].severity == "warning"
    assert report.findings[1].severity == "info"
    assert "1 previously known" in report.findings[0].summary
    assert "1 new UI" in report.findings[1].summary


def test_adapter_reuse_report_flags_semantic_selector_drift():
    previous = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run_1",
        pages=[Page(id="page_wifi", url="https://example.com/#state=local-network/wlan")],
        elements=[
            UiElement(
                id="old_ssid",
                page_id="page_wifi",
                selector_fingerprint="old-selector",
                label="SSID",
                control_type="text",
                context={"visual_bbox": {"x": 20, "y": 80, "width": 200, "height": 28}},
            )
        ],
    )
    current = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run_2",
        pages=[Page(id="page_wifi_new", url="https://example.com/#state=local-network/wlan")],
        elements=[
            UiElement(
                id="new_ssid",
                page_id="page_wifi_new",
                selector_fingerprint="new-selector",
                label="SSID",
                control_type="text",
                context={"visual_bbox": {"x": 22, "y": 82, "width": 200, "height": 28}},
            )
        ],
    )
    bindings = {
        "bindings": [
            {
                "tool_name": "wifi_ssid_update",
                "selector_action_bindings": {
                    "action": "submit_form",
                    "fields": [{"ui_element_id": "old_ssid", "arg": "ssid"}],
                },
            }
        ]
    }

    report = build_adapter_reuse_report(previous, current, bindings)

    assert report["summary"]["reuse_candidates"] == 1
    candidate = report["candidates"][0]
    assert candidate["status"] == "reuse_candidate"
    assert candidate["field_matches"][0]["current_element_id"] == "new_ssid"
    assert candidate["field_matches"][0]["signals"]["state_path"] == ["local-network", "wlan"]


def test_adapter_reuse_report_flags_broken_bindings_when_no_semantic_match():
    previous = snapshot_with_selectors("old-selector")
    previous.elements[0].id = "old_field"
    previous.elements[0].label = "SSID"
    previous.elements[0].control_type = "text"
    current = snapshot_with_selectors("other-selector")
    current.elements[0].label = "Firewall"
    current.elements[0].control_type = "checkbox"

    report = build_adapter_reuse_report(
        previous,
        current,
        {"bindings": [{"tool_name": "wifi_ssid_get", "selector_action_bindings": {"ui_element_id": "old_field"}}]},
    )

    assert report["summary"]["broken"] == 1
    assert report["candidates"][0]["field_matches"][0]["status"] == "broken"
