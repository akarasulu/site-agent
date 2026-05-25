from __future__ import annotations

from site_agent.core.models import CrawlSnapshot, DriftFinding, DriftReport, new_id, utc_now


def compare_snapshots(profile_id: str, previous: CrawlSnapshot, current: CrawlSnapshot) -> DriftReport:
    previous_selectors = {element.selector_fingerprint: element for element in previous.elements}
    current_selectors = {element.selector_fingerprint: element for element in current.elements}
    findings: list[DriftFinding] = []

    removed = set(previous_selectors) - set(current_selectors)
    added = set(current_selectors) - set(previous_selectors)
    if removed:
        findings.append(DriftFinding(kind="removed_ui", severity="warning", summary=f"{len(removed)} previously known UI elements were not found."))
    if added:
        findings.append(DriftFinding(kind="added_ui", severity="info", summary=f"{len(added)} new UI elements were found."))
    if not findings:
        findings.append(DriftFinding(kind="no_drift", severity="info", summary="No selector or field drift detected."))

    return DriftReport(profile_id=profile_id, run_id=new_id("run"), generated_at=utc_now(), findings=findings)
