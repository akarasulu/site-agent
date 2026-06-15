from site_agent.core.models import AdapterBinding, CrawlSnapshot, Evidence, Page, ToolSpec, UiElement, utc_now
from site_agent.core.synthesize.capabilities import (
    canonical_page_name,
    choose_better,
    normalize_args_schema,
    normalize_binding_args,
    page_capabilities,
    page_description,
    provenance_missing_read_adapter,
    semantic_context_name,
    semantic_arg_name,
    semantic_read_name,
    semantic_write_name,
    shaped_args_schema,
    state_path,
    strip_numbered_suffix,
    suspicious_semantic_name,
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


def test_capability_naming_matrix_covers_router_sections_and_helper_edges():
    page_cases = [
        ("https://example.test", ["Software Version"], "home_system_status_get"),
        ("https://example.test/#state=status", ["Call Log"], "voip_status_get"),
        ("https://example.test/#state=management", ["User Account"], "management_accounts_get"),
        ("https://example.test/#state=management", ["MAC Table"], "management_mac_table_get"),
        ("https://example.test/#state=management", ["Network Diagnosis Ping"], "management_network_diagnostics_get"),
        ("https://example.test/#state=management", ["Factory Reset"], "management_system_get"),
        ("https://example.test/#state=internet/security", ["Filter Criteria"], "security_filtering_get"),
        ("https://example.test/#state=internet/security", ["DMZ"], "security_dmz_get"),
        ("https://example.test/#state=internet/security", ["Firewall"], "security_firewall_get"),
        ("https://example.test/#state=internet", ["Parental Controls"], "internet_parental_controls_get"),
        ("https://example.test/#state=internet", ["DDNS"], "internet_ddns_get"),
        ("https://example.test/#state=internet", ["SNTP"], "internet_sntp_get"),
        ("https://example.test/#state=internet/port-binding", [], "internet_port_binding_get"),
        ("https://example.test/#state=internet/3g-4g", [], "internet_mobile_network_get"),
        ("https://example.test/#state=internet", ["DSLite"], "internet_dslite_get"),
        ("https://example.test/#state=internet", ["6RD"], "internet_6rd_get"),
        ("https://example.test/#state=internet/status", ["Ethernet"], "internet_status_get"),
        ("https://example.test/#state=local-network/status", ["LAN Status"], "local_network_status_get"),
        ("https://example.test/#state=wifi", ["Access Control"], "wifi_access_control_get"),
        ("https://example.test/#state=wifi", ["WLAN Radar"], "wifi_radar_get"),
        ("https://example.test/#state=lan/dhcp", ["DHCP"], "local_network_lan_get"),
        ("https://example.test/#state=ftp", ["FTP"], "local_network_ftp_get"),
        ("https://example.test/#state=dns", ["Domain Name"], "local_network_dns_get"),
        ("https://example.test/#state=dms", ["DMS"], "local_network_dms_get"),
        ("https://example.test/#state=upnp", ["UPnP"], "local_network_upnp_get"),
        ("https://example.test/#state=lan", [], "local_network_status_get"),
        ("https://example.test/#state=internet", [], "internet_status_get"),
    ]

    assert [canonical_page_name(url, headings) for url, headings, _ in page_cases] == [expected for _, _, expected in page_cases]
    assert state_path("https://example.test/#state=internet/security&tab=rules") == ["internet", "security"]
    assert strip_numbered_suffix("name_1_2") == "name"
    assert page_description("security_firewall_get", ["Firewall", "Level"]) == "Read security firewall: Firewall, Level."
    assert suspicious_semantic_name(None)
    assert suspicious_semantic_name("home_get")
    assert provenance_missing_read_adapter({"action": "read"})
    assert not provenance_missing_read_adapter({"action": "read", "page_url": "https://example.test"})

    base = make_tool("get_status", confidence=0.7)
    assert choose_better(base, make_tool("get_status_new", confidence=0.8))
    assert choose_better(make_tool("get_status", source_type="ui_page"), make_tool("get_status", source_type="canonical_concept"))
    richer = make_tool("get_status", confidence=0.8)
    richer.evidence_ids.append("ev_more")
    assert choose_better(make_tool("get_status", confidence=0.8), richer)


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


def test_semantic_name_helpers_cover_read_write_context_matrix():
    read_cases = [
        (make_tool("get_mobile_network", "Mobile network"), "internet_mobile_network_get"),
        (make_tool("get_dslite", "DSLite"), "internet_dslite_get"),
        (make_tool("get_6rd", "6RD"), "internet_6rd_get"),
        (make_tool("get_access_control", "Access control"), "wifi_access_control_get"),
        (make_tool("get_port_forwarding", "Port Forwarding"), "security_port_forwarding_list"),
        (make_tool("get_dhcp", "Allocated address DHCP"), "lan_dhcp_get"),
        (make_tool("get_devices", "Access devices"), None),
        (make_tool("get_wlan", "WLAN status"), "wifi_radios_get"),
        (make_tool("get_ssid", "SSID Name"), "wifi_ssids_get"),
        (make_tool("get_channel", "WLAN Channel"), "wifi_channel_get"),
        (make_tool("get_encryption", "Encryption Type"), "wifi_security_get"),
        (make_tool("get_power", "Transmitting Power"), "wifi_radio_power_get"),
        (make_tool("get_upnp", "UPnP"), "local_network_upnp_get"),
        (make_tool("get_port_binding", "Port Binding"), "internet_port_binding_get"),
        (make_tool("get_custom_metric", "Custom Metric"), "custom_metric_get"),
        (make_tool("get_ip_address", "IP Address"), None),
    ]
    write_cases = [
        (make_tool("submit_access", "Access control"), "wifi_access_control_update"),
        (make_tool("submit_binding", "Port binding"), "internet_port_binding_update"),
        (make_tool("submit_firewall", "Firewall"), "security_firewall_update"),
        (make_tool("submit_mode", "Mode"), "security_filtering_update"),
        (make_tool("submit_wan", "WAN Connection"), "internet_wan_update"),
        (make_tool("submit_dhcp", "Lease time DHCP"), "lan_dhcp_update"),
        (make_tool("submit_ip_address", "IP Address"), "lan_dhcp_reservation_update"),
        (make_tool("submit_wlan_on_off", "WLAN on off"), "wifi_radios_update"),
        (make_tool("submit_ssid", "SSID WPA Passphrase"), "wifi_ssid_update"),
        (make_tool("submit_channel", "WLAN Channel"), "wifi_radio_update"),
        (make_tool("submit_upnp", "UPnP"), "local_network_upnp_update"),
        (make_tool("submit_devices", "Access devices"), None),
        (make_tool("submit_url", "URL"), "security_url_filter_update"),
        (make_tool("submit_ftp", "FTP server"), "local_network_ftp_update"),
        (make_tool("apply_filters", "Apply filters"), "incident_filters_apply"),
        (make_tool("send_invite", "Send invite"), "users_invite_send"),
        (make_tool("export_report", "Export report"), "reports_export"),
        (make_tool("sign_in", "Sign in"), "session_sign_in"),
        (make_tool("create_item", "Create item"), "create_item"),
        (make_tool("submit_clean", "Clean"), "clean_update"),
        (make_tool("submit_name_2", "Name"), None),
    ]
    context_cases = [
        (make_tool("read"), make_binding("read", page_label="Idle Timeout"), False, "management_idle_timeout_get"),
        (make_tool("read"), make_binding("read", page_label="Network Diagnosis"), False, "management_network_diagnostics_get"),
        (make_tool("read"), make_binding("read", page_label="MAC Table"), False, "management_mac_table_get"),
        (make_tool("read"), make_binding("read", page_label="Device Information"), False, "management_device_information_get"),
        (make_tool("read"), make_binding("read", page_label="Topology Access Devices"), False, "topology_devices_get"),
        (make_tool("read"), make_binding("read", page_label="VOIP Status"), False, "voip_status_get"),
        (make_tool("read"), make_binding("read", page_label="Local Network"), False, "local_network_status_get"),
        (make_tool("submit"), make_binding("submit", page_label="Old Password Confirmed Password"), True, "management_account_update"),
        (make_tool("submit"), make_binding("submit", page_label="Access Control"), True, "wifi_access_control_update"),
        (make_tool("submit"), make_binding("submit", page_label="Maximum Hops Egress"), True, "management_network_diagnostics_run"),
        (make_tool("submit"), make_binding("submit", page_label="Provider URL Domain Information Hash"), True, "internet_ddns_update"),
        (make_tool("submit"), make_binding("submit", page_label="Media Source"), True, "local_network_dms_update"),
        (make_tool("submit"), make_binding("submit", page_label="UPnP", fields=[{"arg": "enabled", "label": "UPnP"}]), True, "local_network_upnp_update"),
        (make_tool("submit"), make_binding("submit", page_label="FTP", fields=[{"arg": "server", "label": "Server"}]), True, "local_network_ftp_update"),
        (make_tool("submit"), make_binding("submit", fields=[], page_label="Prefix Delegate LAN IPv6"), True, "local_network_dhcpv6_update"),
        (make_tool("submit"), make_binding("submit", fields=[], page_label="Show Password SSID Name"), True, "wifi_ssid_update"),
    ]

    assert [semantic_read_name(tool) for tool, _ in read_cases] == [expected for _, expected in read_cases]
    assert [semantic_write_name(tool) for tool, _ in write_cases] == [expected for _, expected in write_cases]
    assert [semantic_context_name(tool, binding, is_write) for tool, binding, is_write, _ in context_cases] == [
        expected for _, _, _, expected in context_cases
    ]
    assert semantic_arg_name("security_port_forwarding_create_or_update", "Protocol_2", "Protocol") == "protocol"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "Lan_Host_Port_3", "LAN host port") == "lan_port"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "Wan_Port_4", "WAN port") == "wan_port"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "lan_host", "LAN host") == "lan_host"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "wan_host", "WAN host") == "wan_host"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "On", "Enable") == "enabled"
    assert semantic_arg_name("security_port_forwarding_create_or_update", "StopFormAutoSubmit", "Stop") is None
    assert semantic_arg_name("custom_update", "confirmok", "Confirm") is None


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


def test_synthesize_capabilities_preserves_collapsed_form_provenance():
    first = make_tool("submit_rule", "Port forwarding rule", source_type="ui_form")
    second = make_tool("submit_rule_duplicate", "Port forwarding rule", source_type="ui_form")

    tools, bindings, report = synthesize_capabilities(
        [first, second],
        [
            make_binding("submit_rule", form_id="form_1", fields=[{"arg": "Name_1", "label": "Name", "ui_element_id": "field_1"}]),
            make_binding("submit_rule_duplicate", form_id="form_2", fields=[{"arg": "Name_1", "label": "Name", "ui_element_id": "field_2"}]),
        ],
    )

    assert report["collapsed_adapter_counts"]["security_port_forwarding_create_or_update"] == 2
    tool = next(tool for tool in tools if tool.name == "security_port_forwarding_create_or_update")
    binding = next(binding for binding in bindings if binding.tool_name == "security_port_forwarding_create_or_update")
    assert {"ev_submit_rule", "ev_submit_rule_duplicate"} <= set(tool.evidence_ids)
    assert binding.selector_action_bindings["source_form_ids"] == ["form_1", "form_2"]
    assert binding.selector_action_bindings["source_field_ids"] == ["field_1", "field_2"]
