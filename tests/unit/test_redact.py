from site_agent.core.models import (
    ConceptMapping,
    CrawlSnapshot,
    DomainTerm,
    Evidence,
    Form,
    MappedSchema,
    Page,
    Transition,
    UiElement,
    utc_now,
)
from site_agent.core.redact import REDACTED, redact_context, redact_schema, redact_snapshot, redact_text


def test_redact_text_masks_default_key_value_secrets_and_extra_patterns():
    value = "password=hunter2 token:abc123 serial=SN-12345"

    redacted = redact_text(value, [r"SN-\d+"])

    assert "hunter2" not in redacted
    assert "abc123" not in redacted
    assert "SN-12345" not in redacted
    assert f"password={REDACTED}" in redacted
    assert f"token:{REDACTED}" in redacted


def test_redact_context_uses_sensitive_keys_and_nested_values():
    context = {
        "admin_password": "secret-value",
        "headers": {"cookie": "session=abc", "safe": "mode=read-only"},
        "notes": ["token=abc", "public"],
        "count": 3,
    }

    redacted = redact_context(context)

    assert redacted["admin_password"] == REDACTED
    assert redacted["headers"]["cookie"] == REDACTED
    assert redacted["headers"]["safe"] == "mode=read-only"
    assert redacted["notes"] == [f"token={REDACTED}", "public"]
    assert redacted["count"] == 3


def test_redact_snapshot_preserves_structure_while_masking_values():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/?token=abc", title="Admin", headings=["SSID SN-123"])],
        forms=[Form(id="form", page_id="page", label="Password form", action="/save?password=hunter2", method="post", field_ids=["ui"])],
        elements=[
            UiElement(
                id="ui",
                page_id="page",
                selector_fingerprint="fp",
                label="Password",
                control_type="password",
                context={"read_value": "password=hunter2", "api_key": "abc"},
                evidence_ids=["ev"],
            )
        ],
        transitions=[Transition(source_page_id="page", target_url="https://example.test/settings?token=abc", trigger_label="Settings")],
        evidence=[Evidence(id="ev", kind="ui", source="https://example.test/?token=abc", summary="password=hunter2", locator="loc")],
    )

    redacted = redact_snapshot(snapshot, [r"SN-\d+"])

    assert redacted.run_id == snapshot.run_id
    assert redacted.pages[0].headings == [f"SSID {REDACTED}"]
    assert "abc" not in redacted.pages[0].url
    assert "hunter2" not in redacted.forms[0].action
    assert redacted.elements[0].context["read_value"] == f"password={REDACTED}"
    assert redacted.elements[0].context["api_key"] == REDACTED
    assert redacted.evidence[0].summary == f"password={REDACTED}"


def test_redact_schema_masks_ontology_mapping_and_evidence_text():
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term", canonical_name="api key", aliases=["SN-123"], sources=["password=hunter2"], confidence=0.9)],
        mappings=[
            ConceptMapping(
                ui_element_id="ui",
                domain_term_id="term",
                canonical_name="token:abc",
                aliases_seen=["SN-123"],
                confidence=0.9,
                evidence_ids=["ev"],
                status="ready",
                reasoning_summary="password=hunter2",
            )
        ],
        evidence=[Evidence(id="ev", kind="doc", source="manual SN-123", summary="token=abc")],
    )

    redacted = redact_schema(schema, [r"SN-\d+"])

    assert redacted.ontology[0].aliases == [REDACTED]
    assert redacted.ontology[0].sources == [f"password={REDACTED}"]
    assert redacted.mappings[0].canonical_name == f"token:{REDACTED}"
    assert redacted.mappings[0].aliases_seen == [REDACTED]
    assert redacted.evidence[0].source == f"manual {REDACTED}"
