from site_agent.core.merge import merge_snapshots
from site_agent.core.models import CrawlSnapshot, Evidence, Form, Page, Transition, UiElement, utc_now
from site_agent.core.profiles import Profile


def make_profile() -> Profile:
    return Profile(id="profile", name="demo", base_url="https://example.com", host_allowlist=["example.com"], created_at=utc_now())


def test_merge_preserves_base_and_adds_probe_delta():
    base = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="base",
        pages=[Page(id="page_home", url="https://example.com/#state=home")],
        forms=[Form(id="form_home", page_id="page_home", label="Home Form", field_ids=["ui_home"])],
        elements=[UiElement(id="ui_home", page_id="page_home", selector_fingerprint="fp_home", label="Status", control_type="readonly_status", evidence_ids=["ev_home"])],
        evidence=[Evidence(id="ev_home", kind="ui", source="home", summary="Home status")],
    )
    probe = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="probe",
        pages=[
            Page(id="page_home_probe", url="https://example.com/#state=home"),
            Page(id="page_settings", url="https://example.com/#state=settings"),
        ],
        forms=[Form(id="form_settings", page_id="page_settings", label="Settings", field_ids=["ui_settings"])],
        elements=[
            UiElement(id="ui_home_probe", page_id="page_home_probe", selector_fingerprint="fp_home", label="Status", control_type="readonly_status", evidence_ids=["ev_home_probe"]),
            UiElement(id="ui_settings", page_id="page_settings", selector_fingerprint="fp_settings", label="SSID", control_type="text", evidence_ids=["ev_settings"]),
        ],
        evidence=[
            Evidence(id="ev_home_probe", kind="ui", source="home", summary="Home status"),
            Evidence(id="ev_settings", kind="ui", source="settings", summary="SSID field"),
        ],
        transitions=[Transition(source_page_id="page_home_probe", target_url="https://example.com/#state=settings", trigger_label="Settings")],
    )

    merged, report = merge_snapshots(make_profile(), base, probe)

    assert len(merged.pages) == 2
    assert len(merged.forms) == 2
    assert len(merged.elements) == 2
    assert len(merged.evidence) == 2
    assert merged.transitions[0].source_page_id == "page_home"
    assert report["summary"]["added_pages"] == 1
    assert report["summary"]["added_elements"] == 1
    assert report["attribution"]["promotable_labels"] == ["Settings"]
    assert report["attribution"]["probe_labels"] == ["Home", "Settings"]
    assert report["attribution"]["added_elements"][0]["source_state_path"] == ["settings"]
