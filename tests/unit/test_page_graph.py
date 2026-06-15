from site_agent.core.models import CrawlSnapshot, Form, Page, UiElement, utc_now
from site_agent.core.page_graph import build_page_graph, coverage_preservation_labels, visual_block_groups


def test_page_graph_fuses_page_form_element_visual_and_accessibility_features():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page_wifi", url="https://example.com/#state=local-network/wlan", headings=["WLAN Basic"])],
        forms=[Form(id="form_wifi", page_id="page_wifi", label="Wi-Fi settings", field_ids=["ui_ssid"])],
        elements=[
            UiElement(
                id="ui_ssid",
                page_id="page_wifi",
                selector_fingerprint="fp_ssid",
                label="SSID",
                control_type="text",
                context={
                    "read_value": "Office",
                    "visual_bbox": {"x": 20, "y": 80, "width": 240, "height": 32},
                    "dom_tag": "input",
                    "selector_id": "ssid",
                    "accessibility_role": "textbox",
                    "accessibility_name": "SSID",
                    "computed_style": {"fontSize": "14px"},
                },
                evidence_ids=["ev_ssid"],
            )
        ],
    )

    graph = build_page_graph(snapshot)

    assert graph["summary"]["nodes"] == 3
    assert graph["summary"]["edges"] == 2
    assert graph["summary"]["role_counts"]["field"] == 1
    assert graph["summary"]["visual_nodes"] == 1
    assert graph["summary"]["visual_blocks"] == 1
    element_node = next(node for node in graph["nodes"] if node["id"] == "ui_ssid")
    assert element_node["features"]["bbox"]["width"] == 240.0
    assert element_node["features"]["accessibility"]["role"] == "textbox"
    assert element_node["features"]["visual_block_ids"] == ["vblock_page_wifi_1"]
    assert graph["visual_blocks"][0]["labels"] == ["SSID"]
    assert {"page_contains_form", "form_contains_element"} == {edge["relationship"] for edge in graph["edges"]}


def test_visual_blocks_mark_repeated_settings_rows_without_selector_coupling():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page_wifi", url="https://example.com/#state=local-network/wlan", headings=["WLAN Basic"])],
        elements=[
            UiElement(
                id="label_ssid",
                page_id="page_wifi",
                selector_fingerprint="fp_label_ssid",
                label="SSID",
                control_type="readonly_status",
                context={"visual_bbox": {"x": 20, "y": 80, "width": 110, "height": 24}, "dom_tag": "label"},
            ),
            UiElement(
                id="field_ssid",
                page_id="page_wifi",
                selector_fingerprint="fp_field_ssid",
                label="Network Name",
                control_type="text",
                context={"visual_bbox": {"x": 180, "y": 78, "width": 220, "height": 28}, "dom_tag": "input"},
            ),
            UiElement(
                id="label_pass",
                page_id="page_wifi",
                selector_fingerprint="fp_label_pass",
                label="Password",
                control_type="readonly_status",
                context={"visual_bbox": {"x": 20, "y": 128, "width": 110, "height": 24}, "dom_tag": "label"},
            ),
            UiElement(
                id="field_pass",
                page_id="page_wifi",
                selector_fingerprint="fp_field_pass",
                label="Passphrase",
                control_type="password",
                context={"visual_bbox": {"x": 180, "y": 126, "width": 220, "height": 28}, "dom_tag": "input"},
            ),
        ],
    )

    blocks = visual_block_groups(snapshot)
    graph = build_page_graph(snapshot)

    assert [block["element_ids"] for block in blocks] == [
        ["label_ssid", "field_ssid"],
        ["label_pass", "field_pass"],
    ]
    assert all(block["repeated_candidate"] for block in blocks)
    assert graph["summary"]["repeated_visual_blocks"] == 2
    field_node = next(node for node in graph["nodes"] if node["id"] == "field_pass")
    assert field_node["features"]["visual_block_ids"] == ["vblock_page_wifi_2"]


def test_coverage_preservation_labels_prioritize_value_rich_states():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[
            Page(id="page_status", url="https://example.com/#state=internet/status", headings=["Status"]),
            Page(id="page_empty", url="https://example.com/#state=help", headings=["Help"]),
        ],
        forms=[Form(id="form_status", page_id="page_status", label="Status", field_ids=["ui_wan", "ui_ip"])],
        elements=[
            UiElement(
                id="ui_wan",
                page_id="page_status",
                selector_fingerprint="fp_wan",
                label="WAN Status",
                control_type="readonly_status",
                context={"read_value": "Connected"},
            ),
            UiElement(
                id="ui_ip",
                page_id="page_status",
                selector_fingerprint="fp_ip",
                label="IP Address",
                control_type="text",
                context={"read_value": "192.0.2.10"},
            ),
        ],
    )

    labels = coverage_preservation_labels(snapshot)

    by_label = {item["label"]: item for item in labels}
    assert "Internet" in by_label
    assert "Status" in by_label
    assert by_label["Status"]["signals"]["current_values"] == 2
    assert by_label["Status"]["score"] > by_label["Help"]["score"]
