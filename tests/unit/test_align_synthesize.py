from site_agent.core.align.lexical import align_snapshot
from site_agent.core.models import CrawlSnapshot, DomainTerm, Evidence, UiElement, utc_now
from site_agent.core.synthesize.mcp import synthesize_tools


def test_alignment_gates_low_confidence_and_synthesizes_public_tools():
    ui_ev = Evidence(id="ev_ui", kind="ui", source="fixture", summary="SSID field")
    doc_ev = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="SSID documentation")
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile_1",
        run_id="run_1",
        elements=[
            UiElement(id="ui_1", page_id="page_1", selector_fingerprint="abc", label="SSID", control_type="text", evidence_ids=["ev_ui"]),
            UiElement(id="ui_2", page_id="page_1", selector_fingerprint="def", label="Mystery", control_type="text", evidence_ids=["ev_ui"]),
        ],
        evidence=[ui_ev],
    )
    ontology = [DomainTerm(id="term_ssid", canonical_name="ssid", aliases=["network name"], sources=["ev_doc"], confidence=0.9)]

    schema = align_snapshot("profile_1", snapshot, ontology, [doc_ev])
    assert schema.mappings[0].status == "ready"
    assert schema.mappings[1].status == "internal"

    tools, bindings = synthesize_tools("profile_1", schema, {"ui_1": "abc", "ui_2": "def"})
    assert [tool.name for tool in tools] == ["get_ssid"]
    assert tools[0].evidence_ids == ["ev_ui", "ev_doc"]
    assert bindings[0].selector_action_bindings["selector_fingerprint"] == "abc"
