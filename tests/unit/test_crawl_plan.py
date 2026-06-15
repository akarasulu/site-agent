from site_agent.core.ai.backends import FakeAiBackend, NoopAiBackend
from site_agent.core.evidence_cache import build_evidence_cache, diff_evidence_caches
from site_agent.core.models import ConceptMapping, CrawlSnapshot, DomainTerm, Evidence, Form, MappedSchema, Page, Transition, UiElement, utc_now
from site_agent.core.plan import build_crawl_plan, term_label_candidates
from site_agent.core.profiles import Profile


def make_profile() -> Profile:
    return Profile(
        id="profile",
        name="demo",
        base_url="https://example.com",
        host_allowlist=["example.com"],
        created_at=utc_now(),
    )


def test_term_label_candidates_split_compound_domain_terms():
    term = DomainTerm(
        id="term_port_forwarding",
        canonical_name="port forwarding (virtual server)",
        aliases=["port mapping/NAT rule"],
        confidence=0.9,
    )

    labels = term_label_candidates(term)

    assert "Port Forwarding" in labels
    assert "Virtual Server" in labels
    assert "Port Mapping" in labels
    assert "Nat Rule" in labels


def test_crawl_plan_prioritizes_missing_terms_and_observed_labels():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[
            DomainTerm(id="term_wan_status", canonical_name="wan status", confidence=0.9, sources=["ev_doc"]),
            DomainTerm(id="term_port_forwarding", canonical_name="port forwarding", aliases=["port binding"], confidence=0.95, sources=["ev_doc"]),
        ],
        mappings=[
            ConceptMapping(
                ui_element_id="ui_wan",
                domain_term_id="term_wan_status",
                canonical_name="wan status",
                aliases_seen=["WAN Status"],
                confidence=0.95,
                evidence_ids=["ev_doc"],
                status="ready",
                reasoning_summary="covered",
            )
        ],
        evidence=[ev_doc],
    )
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/#state=internet")],
        transitions=[Transition(source_page_id="page", target_url="https://example.com/#state=port-binding", trigger_label="Port Binding")],
    )

    plan = build_crawl_plan(make_profile(), snapshot, schema, NoopAiBackend(), max_terms=5)

    assert plan["summary"]["missing_terms"] == 1
    assert plan["target_terms"][0]["canonical_name"] == "port forwarding"
    assert any(item["label"] == "Port Binding" for item in plan["prioritized_labels"])
    assert "page_graph_nodes" in plan["summary"]


def test_crawl_plan_uses_memory_to_demote_labels():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term_port_forwarding", canonical_name="port forwarding", aliases=["port binding"], confidence=0.95, sources=["ev_doc"])],
        mappings=[],
        evidence=[ev_doc],
    )
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/#state=port-binding")],
        transitions=[Transition(source_page_id="page", target_url="https://example.com/#state=port-binding", trigger_label="Port Binding")],
    )

    neutral = build_crawl_plan(make_profile(), snapshot, schema, NoopAiBackend(), max_terms=5)
    demoted = build_crawl_plan(make_profile(), snapshot, schema, NoopAiBackend(), max_terms=5, memory={"demoted_labels": ["Port Binding"]})

    neutral_score = next(item["score"] for item in neutral["prioritized_labels"] if item["label"] == "Port Binding")
    demoted_score = next(item["score"] for item in demoted["prioritized_labels"] if item["label"] == "Port Binding")
    assert demoted_score < neutral_score


def test_crawl_plan_uses_ai_directional_targets_for_weak_domain_areas():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term_port_forwarding", canonical_name="port forwarding", aliases=["virtual server"], confidence=0.95, sources=["ev_doc"])],
        mappings=[],
        evidence=[ev_doc],
    )
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/#state=internet")],
        transitions=[Transition(source_page_id="page", target_url="https://example.com/#state=internet", trigger_label="Internet")],
    )

    plan = build_crawl_plan(make_profile(), snapshot, schema, FakeAiBackend(), max_terms=5)

    assert plan["summary"]["directional_targets"] == 1
    assert plan["directional_targets"][0]["branch_path"] == ["Internet", "Security"]
    labels = {item["label"]: item for item in plan["prioritized_labels"]}
    assert "Virtual Server" in labels
    assert "ai_directional" in labels["Virtual Server"]["sources"]


def test_crawl_plan_demotes_reached_branch_when_form_classification_disproves_concept():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term_port_forwarding", canonical_name="port forwarding", aliases=["port binding"], confidence=0.95, sources=["ev_doc"])],
        mappings=[],
        evidence=[ev_doc],
    )
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/#state=internet/port-binding")],
        transitions=[Transition(source_page_id="page", target_url="https://example.com/#state=internet/port-binding", trigger_label="Port Binding")],
    )

    plan = build_crawl_plan(
        make_profile(),
        snapshot,
        schema,
        FakeAiBackend(),
        max_terms=5,
        memory={
            "research_session": {
                "negative_concepts": ["port forwarding"],
                "directional_outcomes": [
                    {
                        "status": "reached",
                        "branch_path": ["Internet", "Port Binding"],
                        "missing_concepts": ["port forwarding"],
                    }
                ],
            }
        },
    )

    assert plan["summary"]["memory_disproven_labels"] == 1
    port_binding = next(item for item in plan["prioritized_labels"] if item["label"] == "Port Binding")
    assert port_binding["memory"] == "demoted"


def test_crawl_plan_adds_coverage_preservation_labels_for_value_rich_states():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[DomainTerm(id="term_port_forwarding", canonical_name="port forwarding", confidence=0.95, sources=["ev_doc"])],
        mappings=[],
        evidence=[ev_doc],
    )
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.com/#state=local-network/wlan-basic", headings=["WLAN Basic"])],
        forms=[Form(id="form_wifi", page_id="page", label="Wi-Fi", field_ids=["ui_ssid"])],
        elements=[
            UiElement(
                id="ui_ssid",
                page_id="page",
                selector_fingerprint="fp_ssid",
                label="SSID",
                control_type="text",
                context={"read_value": "Office"},
            )
        ],
    )

    plan = build_crawl_plan(make_profile(), snapshot, schema, NoopAiBackend(), max_terms=5)

    assert plan["summary"]["coverage_preservation_labels"] >= 1
    labels = {item["label"]: item for item in plan["coverage_preservation_labels"]}
    assert "Local Network" in labels
    prioritized = {item["label"]: item for item in plan["prioritized_labels"]}
    assert "coverage_preservation" in prioritized["Local Network"]["sources"]
    assert prioritized["Local Network"]["coverage_signals"]["current_values"] == 1


def test_crawl_plan_augments_candidates_with_cache_gain_signals():
    ev_doc = Evidence(id="ev_doc", kind="doc", source="manual.md", summary="Manual")
    schema = MappedSchema(
        profile_id="profile",
        run_id="run",
        generated_at=utc_now(),
        ontology=[
            DomainTerm(
                id="term_port_forwarding",
                canonical_name="port forwarding",
                aliases=["virtual server"],
                confidence=0.95,
                sources=["ev_doc"],
            )
        ],
        mappings=[],
        evidence=[ev_doc],
    )
    previous = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run_1",
        pages=[Page(id="page_status", url="https://example.com/#state=status", html_snapshot="<a>Status</a>")],
    )
    current = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run_2",
        pages=[
            Page(id="page_status", url="https://example.com/#state=status", html_snapshot="<a>Status</a>"),
            Page(
                id="page_port",
                url="https://example.com/#state=security/port-forwarding",
                headings=["Port Forwarding"],
                html_snapshot="<a>Port Forwarding</a><label>External Port</label>",
            ),
        ],
        transitions=[
            Transition(
                source_page_id="page_status",
                target_url="https://example.com/#state=security/port-forwarding",
                trigger_label="Port Forwarding",
            )
        ],
    )
    previous_cache = build_evidence_cache(previous)
    current_cache = build_evidence_cache(current)

    plan = build_crawl_plan(
        make_profile(),
        current,
        schema,
        NoopAiBackend(),
        max_terms=5,
        evidence_cache=current_cache,
        evidence_cache_diff=diff_evidence_caches(previous_cache, current_cache),
    )

    port_forwarding = next(item for item in plan["prioritized_labels"] if item["label"] == "Port Forwarding")
    assert "crawl_gain" in port_forwarding["sources"]
    assert "cache_new_family" in port_forwarding["sources"]
    assert port_forwarding["gain_signals"]["new_page_families"] == 1
    assert plan["summary"]["evidence_cache_new_page_families"] == 1
