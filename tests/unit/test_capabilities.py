from site_agent.core.models import AdapterBinding, CrawlSnapshot, Evidence, Page, ToolSpec, UiElement, utc_now
from site_agent.core.synthesize.capabilities import (
    canonical_page_name,
    normalize_args_schema,
    normalize_binding_args,
    page_capabilities,
    semantic_context_name,
    semantic_read_name,
    semantic_write_name,
    shaped_args_schema,
    synthesize_capabilities,
)


def make_tool(name: str, description: str = "", *, source_type: str = "canonical_concept", confidence: float = 0.8) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=description,
        args={
            "type": "object",
            "properties": {
                "Name_1": {"type": "string", "description": "Name"},
                "Protocol_2": {"type": "string", "description": "Protocol"},
                "Lan_Host_Port_3": {"type": "string", "description": "LAN host port"},
                "StopFormAutoSubmit": {"type": "string"},
            },
            "required": ["Name_1", "Protocol_2"],
        },
        return_schema={"type": "object"},
        risk_level="low",
        evidence_ids=[f"ev_{name}"],
        confidence=confidence,
        source_type=source_type,
        reasoning_summary=description,
    )


def make_binding(tool_name: str, fields: list[dict] | None = None, **extra) -> AdapterBinding:
    return AdapterBinding(
        tool_name=tool_name,
        profile_id="profile",
        version="0.1.0",
        selector_action_bindings={
            "action": "submit",
            "page_id": "page",
            "page_label": extra.pop("page_label", ""),
            "purpose_label": extra.pop("purpose_label", ""),
            "form_classification": extra.pop("form_classification", ""),
            "fields": fields
            if fields is not None
            else [
                {"arg": "Name_1", "label": "Name"},
                {"arg": "Protocol_2", "label": "Protocol"},
                {"arg": "Lan_Host_Port_3", "label": "LAN host port"},
            ],
            **extra,
        },
    )


def test_canonical_page_names_cover_common_router_sections():
    cases = [
        ("https://example.test", [], "home_overview_get"),
        ("https://example.test/#state=home", [], "home_overview_get"),
        ("https://example.test/#state=topology", [], "topology_devices_get"),
        ("https://example.test/#state=management", ["ARP Table"], "management_arp_table_get"),
        ("https://example.test/#state=internet/wan", ["WAN Connection"], "internet_wan_get"),
        ("https://example.test/#state=local-network/wlan", ["WLAN SSID"], "local_network_wifi_get"),
        ("https://example.test/#state=internet/security", ["Port Forwarding"], "security_port_forwarding_list"),
        ("https://example.test/#state=custom/page", ["Advanced Metrics"], "custom_page_advanced_metrics_get"),
    ]

    assert [canonical_page_name(url, headings) for url, headings, _ in cases] == [expected for _, _, expected in cases]


def test_semantic_name_helpers_map_read_write_and_context_labels():
    assert semantic_read_name(make_tool("get_wan_status", "WAN status")) == "wan_connection_get"
    assert semantic_read_name(make_tool("get_software_version", "Software Version")) == "software_version_get"
    assert semantic_read_name(make_tool("get_filter", "MAC filter switch")) == "security_filtering_get"

    assert semantic_write_name(make_tool("save_settings")) == "settings_update"
    assert semantic_write_name(make_tool("submit_rule", "Port forwarding rule")) == "security_port_forwarding_create_or_update"
    assert semantic_write_name(make_tool("submit_host_name_unknown_mac_address")) == "security_mac_filter_update"

    assert semantic_context_name(make_tool("read_form"), make_binding("read_form", page_label="User Account Management"), False) == "management_accounts_get"
    assert semantic_context_name(make_tool("submit_form"), make_binding("submit_form", page_label="NTP server Time Zone"), True) == "internet_sntp_update"
    assert semantic_context_name(make_tool("submit_form"), make_binding("submit_form", page_label="DMZ LAN host"), True) == "security_dmz_update"


def test_shaped_arg_schemas_exist_for_common_write_capabilities():
    expected_properties = {
        "security_firewall_update": "level",
        "local_network_upnp_update": "enabled",
        "wifi_radios_update": "radios",
        "wifi_radio_update": "band",
        "internet_port_binding_update": "lan_ports",
        "security_filtering_update": "mac_filter_enabled",
        "security_port_forwarding_create_or_update": "lan_host",
        "lan_dhcp_reservation_update": "mac_address",
        "lan_dhcp_update": "lease_time",
        "security_mac_filter_update": "source_mac",
        "security_url_filter_update": "url",
        "wifi_ssid_update": "passphrase",
        "devices_access_update": "access_allowed",
        "internet_wan_update": "connection_name",
        "management_account_update": "new_password",
        "management_idle_timeout_update": "timeout",
        "management_network_diagnostics_run": "maximum_hops",
        "internet_ddns_update": "provider_url",
        "internet_sntp_update": "time_zone",
        "local_network_dms_update": "media_sources",
        "security_dmz_update": "lan_host",
        "local_network_dhcpv6_update": "dns_servers",
        "local_network_dns_update": "domain_name",
    }

    for semantic_name, property_name in expected_properties.items():
        schema = shaped_args_schema(semantic_name)
        assert schema is not None, semantic_name
        assert property_name in schema["properties"], semantic_name
        assert "dry_run" in schema["properties"]
        assert "confirm" in schema["properties"]
        assert schema["additionalProperties"] is False


def test_normalize_args_and_bindings_drop_noise_and_shape_fields():
    args = normalize_args_schema("security_port_forwarding_create_or_update", make_tool("submit_rule").args)

    assert set(args["properties"]) >= {"name", "protocol", "lan_host", "lan_port", "dry_run", "confirm"}
    assert args["additionalProperties"] is False

    adapter = normalize_binding_args(
        make_binding(
            "submit_rule",
            fields=[
                {"arg": "Name_1", "label": "Name"},
                {"arg": "StopFormAutoSubmit", "label": "Stop"},
                {"arg": "Lan_Host_Port_3", "label": "LAN host port"},
            ],
        ).selector_action_bindings,
        "security_port_forwarding_create_or_update",
    )

    assert [field["arg"] for field in adapter["fields"]] == ["name", "lan_port"]

    synthetic = normalize_binding_args({"fields": [{"arg": "unknown", "label": "unknown"}]}, "wifi_radios_update")
    assert {"enabled", "radios"} <= {field["arg"] for field in synthetic["fields"]}


def test_page_capabilities_collect_values_and_deduplicate_sections():
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[
            Page(id="home", url="https://example.test/#state=home", headings=["Overview"]),
            Page(id="clients", url="https://example.test/#state=local-network/status", headings=["LAN Client Status"]),
        ],
        elements=[
            UiElement(id="ui_1", page_id="home", selector_fingerprint="a", label="WAN Status", control_type="readonly_status", context={"read_value": "Connected"}, evidence_ids=["ev_1"]),
            UiElement(id="ui_2", page_id="clients", selector_fingerprint="b", label="Client Count", control_type="readonly_status", context={"read_value": "3"}, evidence_ids=["ev_2"]),
        ],
        evidence=[Evidence(id="ev_1", kind="ui", source="home", summary="WAN"), Evidence(id="ev_2", kind="ui", source="clients", summary="clients")],
    )

    pairs = page_capabilities(snapshot)
    names = {tool.name for tool, _ in pairs}

    assert {"home_overview_get", "local_network_status_get", "local_network_clients_get"} <= names
    home_binding = next(binding for tool, binding in pairs if tool.name == "home_overview_get")
    assert home_binding.selector_action_bindings["values"] == {"wan_status": "Connected"}


def test_synthesize_capabilities_collapses_adapters_and_adds_page_sections():
    read_tool = make_tool("get_firewall", "Firewall status", confidence=0.7)
    better_read_tool = make_tool("get_filter", "Firewall status", confidence=0.9)
    write_tool = make_tool("submit_rule", "Port forwarding rule", source_type="ui_form")
    generic_tool = make_tool("submit_form", "Submit Form", source_type="ui_form")
    snapshot = CrawlSnapshot(
        timestamp=utc_now(),
        profile_id="profile",
        run_id="run",
        pages=[Page(id="page", url="https://example.test/#state=internet/security", headings=["Firewall"])],
        elements=[
            UiElement(
                id="ui",
                page_id="page",
                selector_fingerprint="fp",
                label="Firewall Level",
                control_type="readonly_status",
                context={"read_value": "high"},
                evidence_ids=["ev_page"],
            )
        ],
    )

    tools, bindings, report = synthesize_capabilities(
        [read_tool, better_read_tool, write_tool, generic_tool],
        [
            make_binding("get_firewall", fields=[], action="read", page_id="page", page_url="https://example.test/#state=internet/security"),
            make_binding("get_filter", fields=[], action="read", page_id="page", page_url="https://example.test/#state=internet/security"),
            make_binding("submit_rule"),
            make_binding("submit_form", fields=[]),
        ],
        snapshot,
    )

    names = [tool.name for tool in tools]
    assert "security_firewall_get" in names
    assert "security_port_forwarding_create_or_update" in names
    assert "security_firewall_update" not in names
    assert report["collapsed_adapter_counts"]["security_firewall_get"] == 2
    assert report["discarded_adapter_count"] == 1
    assert any(binding.tool_name == "security_port_forwarding_create_or_update" for binding in bindings)
