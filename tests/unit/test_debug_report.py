from site_agent.core.debug import build_debug_report, classify_state
from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, Form, MappedSchema, Page, UiElement, utc_now


def test_state_classifier_separates_widget_and_settings_states():
    settings = Page(id="page_settings", url="https://example.com/#state=settings")
    widget = Page(id="page_widget", url="https://example.com/#state=settings/hide")
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[settings, widget],
        forms=[Form(id="form_settings", page_id="page_settings", label="Settings")],
        elements=[
            UiElement(id="ui_ssid", page_id="page_settings", selector_fingerprint="a", label="SSID", control_type="text"),
            UiElement(id="ui_status", page_id="page_settings", selector_fingerprint="b", label="WAN Status", control_type="readonly_status"),
            UiElement(id="ui_hide", page_id="page_widget", selector_fingerprint="c", label="Hide", control_type="button"),
        ],
    )

    assert classify_state(settings, snapshot)["kind"] == "form_or_settings_state"
    assert classify_state(widget, snapshot)["kind"] == "widget_state"


def test_debug_report_names_missing_terms_and_evidence_coverage():
    ev_ui = Evidence(id="ev_ui", kind="ui", source="https://example.com", summary="UI label")
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual term")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[
            DomainTerm(id="term_wan_status", canonical_name="wan status", sources=["ev_doc"], confidence=0.9),
            DomainTerm(id="term_uptime", canonical_name="system uptime", sources=["ev_doc"], confidence=0.8),
        ],
        mappings=[
            ConceptMapping(
                ui_element_id="ui_wan",
                domain_term_id="term_wan_status",
                canonical_name="wan status",
                aliases_seen=["WAN Status"],
                confidence=0.95,
                evidence_ids=["ev_ui", "ev_doc"],
                status="ready",
                reasoning_summary="Matched by evidence.",
            )
        ],
        evidence=[ev_ui, ev_doc],
    )
    snapshot = CrawlSnapshot(timestamp=utc_now(), profile_id="profile", run_id="run", pages=[Page(id="page", url="https://example.com")])

    report = build_debug_report(snapshot, schema)

    assert report["evidence_coverage"]["dual_evidence"] == 1
    assert report["missing_ontology_terms"][0]["canonical_name"] == "system uptime"
    assert report["next_crawl_targets"][0]["target"] == "system uptime"


def test_debug_report_accepts_redacted_urls():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://[redacted-ip]/#state=internet/wan")],
    )

    report = build_debug_report(snapshot)

    assert report["state_classifications"][0]["state_path"] == ["internet", "wan"]
