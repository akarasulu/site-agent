from site_agent.core.crawl_gain import gain_summary, score_crawl_candidates, snapshot_labels
from site_agent.core.evidence_cache import build_evidence_cache, diff_evidence_caches
from site_agent.core.models import CrawlSnapshot, DomainTerm, Form, Page, Transition, UiElement, utc_now


def make_snapshot(run_id: str, include_port_forwarding: bool = True) -> CrawlSnapshot:
    pages = [
        Page(
            id="page_status",
            url="https://example.com/#state=status",
            title="Status",
            headings=["WAN Status"],
            html_snapshot="<html><body><a>WAN Status</a><span>Connected</span></body></html>",
        )
    ]
    transitions = [Transition(source_page_id="page_status", target_url="https://example.com/#state=status", trigger_label="Status")]
    elements = [
        UiElement(
            id="ui_wan",
            page_id="page_status",
            selector_fingerprint="fp_wan",
            label="WAN Status",
            control_type="readonly_status",
            context={"read_value": "Connected"},
        )
    ]
    forms = [Form(id="form_status", page_id="page_status", label="Status", field_ids=["ui_wan"])]
    if include_port_forwarding:
        pages.append(
            Page(
                id="page_forwarding",
                url="https://example.com/#state=security/port-forwarding",
                title="Port Forwarding",
                headings=["Port Forwarding"],
                html_snapshot="""
                <html><body>
                  <nav><a>Port Forwarding</a><a>Firewall</a></nav>
                  <label>External Port</label><input name="external_port">
                </body></html>
                """,
            )
        )
        transitions.append(
            Transition(
                source_page_id="page_status",
                target_url="https://example.com/#state=security/port-forwarding",
                trigger_label="Port Forwarding",
            )
        )
        elements.append(
            UiElement(
                id="ui_port",
                page_id="page_forwarding",
                selector_fingerprint="fp_port",
                label="External Port",
                control_type="text",
                context={"visual_bbox": {"x": 180, "y": 80, "width": 140, "height": 28}},
            )
        )
    return CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id=run_id,
        pages=pages,
        forms=forms,
        elements=elements,
        transitions=transitions,
    )


def test_gain_scores_reward_missing_terms_and_new_cache_families():
    previous_cache = build_evidence_cache(make_snapshot("run_1", include_port_forwarding=False))
    current_snapshot = make_snapshot("run_2", include_port_forwarding=True)
    current_cache = build_evidence_cache(current_snapshot)
    cache_diff = diff_evidence_caches(previous_cache, current_cache)

    scores = score_crawl_candidates(
        current_snapshot,
        missing_terms=[
            DomainTerm(
                id="term_port_forwarding",
                canonical_name="port forwarding",
                aliases=["virtual server"],
                confidence=0.95,
            )
        ],
        cache=current_cache,
        cache_diff=cache_diff,
    )

    by_label = {item["label"]: item for item in scores}
    assert scores[0]["label"] == "Port Forwarding"
    assert by_label["Port Forwarding"]["signals"]["new_page_families"] == 1
    assert "missing_term" in by_label["Port Forwarding"]["sources"]
    assert "cache_new_family" in by_label["Port Forwarding"]["sources"]


def test_gain_scores_apply_memory_demotions_after_evidence_scoring():
    snapshot = make_snapshot("run")
    neutral = score_crawl_candidates(
        snapshot,
        missing_terms=[DomainTerm(id="term_port", canonical_name="port forwarding", confidence=0.95)],
    )
    demoted = score_crawl_candidates(
        snapshot,
        missing_terms=[DomainTerm(id="term_port", canonical_name="port forwarding", confidence=0.95)],
        memory={"demoted_labels": ["Port Forwarding"]},
    )

    neutral_score = next(item["score"] for item in neutral if item["label"] == "Port Forwarding")
    demoted_item = next(item for item in demoted if item["label"] == "Port Forwarding")
    assert demoted_item["memory"] == "demoted"
    assert demoted_item["score"] < neutral_score


def test_gain_scores_include_value_rich_preservation_states():
    snapshot = make_snapshot("run")

    scores = score_crawl_candidates(snapshot, observed_labels=snapshot_labels(snapshot))
    summary = gain_summary(scores)

    by_label = {item["label"]: item for item in scores}
    assert "coverage_preservation" in by_label["Status"]["sources"]
    assert by_label["Status"]["signals"]["coverage_preservation"]["current_values"] == 1
    assert summary["memory_counts"]["neutral"] == len(scores)
