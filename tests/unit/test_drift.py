from site_agent.core.drift.check import compare_snapshots
from site_agent.core.models import CrawlSnapshot, UiElement, utc_now


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
