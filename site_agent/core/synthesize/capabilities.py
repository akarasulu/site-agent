from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from site_agent.core.models import AdapterBinding, CrawlSnapshot, ToolSpec


NUMBERED_SUFFIX_RE = re.compile(r"_\d+$")
GENERIC_TOOL_RE = re.compile(r"^(get_ip_address(?:_\d+)?|submit_wlan_status(?:_\d+)?|submit_form(?:_\d+)?|submit_off(?:_\d+)?)$")
GENERIC_SEMANTIC_RE = re.compile(
    r"^(home|internet|local_network|topology|voip|h3600_v9|ddns|sntp|ftp|dms|dmz|parental_controls|domain_name|"
    r"device_information|ethernet_interface_information|arp_table|mac_table|network_diagnosis|"
    r"management_diagnosis|reboot_management|idle_timeout|user_account_management)_(get|update)$|"
    r"^(password|confirmed_password|show_password|hash|protocol|dscp|egress|timeout|"
    r"media_source1|prefix|prefix_delegate_type|lan_ipv6_address|lan_host)_update$"
)


def words(value: str) -> set[str]:
    return set(re.findall(r"[a-z0-9]+", value.lower()))


def strip_numbered_suffix(value: str) -> str:
    previous = value
    while True:
        current = NUMBERED_SUFFIX_RE.sub("", previous)
        if current == previous:
            return current
        previous = current


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def state_path(url: str) -> list[str]:
    if "#state=" not in url:
        return []
    state = url.split("#state=", 1)[1].split("&", 1)[0]
    return [part for part in re.split(r"/+", state.strip("/")) if part]


def canonical_page_name(url: str, headings: list[str]) -> str:
    state = state_path(url)
    text = " ".join([*state, *headings]).lower()
    if not state and not headings:
        return "home_overview_get"
    if state and state[0] == "home":
        return "home_overview_get"
    if not state:
        if "sip" in text or "cpu" in text or "software" in text:
            return "home_system_status_get"
        return "home_overview_get"
    if state[0] == "topology":
        return "topology_devices_get"
    if state[0] in {"voip", "status"} or "voip status" in text:
        if "call log" in text:
            return "voip_status_get"
        return "voip_status_get"
    if state[0] in {"management", "diagnosis", "management-diagnosis"} or "device information" in text:
        if "account" in text:
            return "management_accounts_get"
        if "arp" in text:
            return "management_arp_table_get"
        if "mac table" in text:
            return "management_mac_table_get"
        if "diagnosis" in text or "ping" in text or "traceroute" in text:
            return "management_network_diagnostics_get"
        if "reboot" in text or "factory reset" in text:
            return "management_system_get"
        return "management_device_information_get"
    if "port forwarding" in text:
        return "security_port_forwarding_list"
    if "filter" in text:
        return "security_filtering_get"
    if "dmz" in text:
        return "security_dmz_get"
    if "firewall" in text:
        return "security_firewall_get"
    if "parental" in text:
        return "internet_parental_controls_get"
    if "ddns" in text:
        return "internet_ddns_get"
    if "sntp" in text:
        return "internet_sntp_get"
    if "port binding" in text or "port-binding" in text:
        return "internet_port_binding_get"
    if "wan connection" in text or (state[:2] == ["internet", "wan"]):
        return "internet_wan_get"
    if "mobile network" in text or state[:2] == ["internet", "3g-4g"]:
        return "internet_mobile_network_get"
    if "dslite" in text:
        return "internet_dslite_get"
    if "6rd" in text:
        return "internet_6rd_get"
    if "ethernet" in text or state[:2] == ["internet", "status"] or state == ["internet"]:
        return "internet_status_get"
    if "wlan status" in text or "lan status" in text or state[:2] == ["local-network", "status"] or state == ["local-network"]:
        return "local_network_status_get"
    if "access control" in text:
        return "wifi_access_control_get"
    if "wlan radar" in text:
        return "wifi_radar_get"
    if "dhcp" in text or "port control" in text:
        return "local_network_lan_get"
    if "wlan on/off" in text or "wlan global" in text or "wlan ssid" in text:
        return "local_network_wifi_get"
    if "ftp" in text:
        return "local_network_ftp_get"
    if "domain name" in text or "host name" in text or "dns" in text:
        return "local_network_dns_get"
    if re.search(r"\bdms\b", text):
        return "local_network_dms_get"
    if "upnp" in text:
        return "local_network_upnp_get"
    if state[:2] == ["local-network", "wlan"]:
        return "local_network_wifi_get"
    if state[0] in {"local-network", "lan", "ftp", "dns", "dms"}:
        return "local_network_status_get"
    if state[0] == "internet":
        return "internet_status_get"
    return f"{slug(' '.join([*state, *(headings[:1] or [])]))}_get"


def page_description(name: str, headings: list[str]) -> str:
    label = name.removesuffix("_get").replace("_", " ")
    heading_text = ", ".join(headings[:4])
    if heading_text:
        return f"Read {label}: {heading_text}."
    return f"Read {label}."


def semantic_read_name(tool: ToolSpec) -> str | None:
    text = f"{tool.name} {tool.description} {tool.reasoning_summary}".lower()
    name = tool.name
    if GENERIC_TOOL_RE.match(name):
        return None
    if "port_forwarding" in name:
        return "security_port_forwarding_list"
    if "mobile_network" in name or "mobile network" in text:
        return "internet_mobile_network_get"
    if "dslite" in name or "dslite" in text:
        return "internet_dslite_get"
    if "6rd" in name or "6rd" in text:
        return "internet_6rd_get"
    if "access_control" in name or "access control" in text:
        return "wifi_access_control_get"
    if "wlan_radar" in name or "wlan radar" in text:
        return "wifi_radar_get"
    if "wan connection" in text or "wan status" in text:
        return "wan_connection_get"
    if "software version" in text:
        return "software_version_get"
    if "port forwarding" in text:
        return "security_port_forwarding_list"
    if "firewall" in text:
        return "security_firewall_get"
    if "filter switch" in text or "mac filter" in text or "url filter" in text:
        return "security_filtering_get"
    if "allocated address" in text or "dhcp" in text:
        return "lan_dhcp_get"
    if "access devices" in text:
        return None
    if "wlan_on_off" in name or "wlan on off" in text or "wlan status" in text:
        return "wifi_radios_get"
    if "ssid name" in text:
        return "wifi_ssids_get"
    if "wlan channel" in text:
        return "wifi_channel_get"
    if "encryption type" in text:
        return "wifi_security_get"
    if "transmitting power" in text:
        return "wifi_radio_power_get"
    if "upnp" in text:
        return "local_network_upnp_get"
    if "port binding" in text:
        return "internet_port_binding_get"
    if name.startswith("get_") and not NUMBERED_SUFFIX_RE.search(name):
        concept = name.removeprefix("get_")
        if concept and concept != "page":
            return f"{concept}_get"
    return None


def semantic_context_name(tool: ToolSpec, binding: AdapterBinding | None, is_write: bool) -> str | None:
    adapter = binding.selector_action_bindings if binding else {}
    labels = " ".join(
        [
            str(adapter.get("page_label", "")),
            str(adapter.get("purpose_label", "")),
            str(adapter.get("form_classification", "")),
            " ".join(str(field.get("label", "")) for field in adapter.get("fields", []) if isinstance(field, dict)),
            tool.description,
            tool.reasoning_summary,
            tool.name,
        ]
    ).lower()
    if not is_write:
        if "user account" in labels or "account management" in labels:
            return "management_accounts_get"
        if "idle timeout" in labels:
            return "management_idle_timeout_get"
        if "network diagnosis" in labels:
            return "management_network_diagnostics_get"
        if "arp table" in labels:
            return "management_arp_table_get"
        if "mac table" in labels:
            return "management_mac_table_get"
        if "device information" in labels:
            return "management_device_information_get"
        if "reboot" in labels:
            return "management_system_get"
        if "management diagnosis" in labels:
            return "management_device_information_get"
        if "ethernet" in labels:
            return "internet_status_get"
        if "dmz" in labels:
            return "security_dmz_get"
        if "parental" in labels:
            return "internet_parental_controls_get"
        if "ddns" in labels:
            return "internet_ddns_get"
        if "sntp" in labels:
            return "internet_sntp_get"
        if "ftp" in labels:
            return "local_network_ftp_get"
        if "dms" in labels:
            return "local_network_dms_get"
        if "domain name" in labels or "host name" in labels or "dns" in labels:
            return "local_network_dns_get"
        if "topology" in labels or "access devices" in labels:
            return "topology_devices_get"
        if "voip" in labels:
            return "voip_status_get"
        if "home" in labels or "h3600" in labels:
            return "home_overview_get"
        if "internet" in labels:
            return "internet_status_get"
        if "local network" in labels:
            return "local_network_status_get"
        return None
    if "user account" in labels or "confirmed password" in labels or "old password" in labels:
        return "management_account_update"
    if "access control" in labels:
        return "wifi_access_control_update"
    if "idle timeout" in labels or "timeout" in labels:
        return "management_idle_timeout_update"
    if "network diagnosis" in labels or "diagnosis result" in labels or "maximum hops" in labels or "egress" in labels:
        return "management_network_diagnostics_run"
    if "ddns" in labels or "provider url" in labels or "domain information" in labels or "hash" in labels:
        return "internet_ddns_update"
    if "sntp" in labels or "ntp server" in labels or "time zone" in labels:
        return "internet_sntp_update"
    if "dms" in labels or "media source" in labels:
        return "local_network_dms_update"
    if "dmz" in labels or "lan host" in labels:
        return "security_dmz_update"
    if "dhcpv6" in labels or "prefix delegate" in labels or "lan ipv6" in labels:
        return "local_network_dhcpv6_update"
    if "domain name" in labels or "host name" in labels or "dns" in labels:
        return "local_network_dns_update"
    if "show password" in labels or "wpa passphrase" in labels or "ssid name" in labels:
        return "wifi_ssid_update"
    return None


def semantic_write_name(tool: ToolSpec) -> str | None:
    text = f"{tool.name} {tool.description} {tool.reasoning_summary}".lower()
    name = tool.name
    if GENERIC_TOOL_RE.match(name):
        return None
    if "port_forwarding" in name:
        return "security_port_forwarding_create_or_update"
    if "access_control" in name or "access control" in text:
        return "wifi_access_control_update"
    if "port binding" in text:
        return "internet_port_binding_update"
    if "port forwarding" in text:
        return "security_port_forwarding_create_or_update"
    if "firewall" in text:
        return "security_firewall_update"
    if name == "submit_mode" or "filter switch" in text or "mac filter" in text or "url filter" in text:
        return "security_filtering_update"
    if "wan connection" in text:
        return "internet_wan_update"
    if "allocated address" in text or "dhcp" in text or "lease time" in text:
        return "lan_dhcp_update"
    if name == "submit_ip_address" or ("ip address" in text and "mac address" in text):
        return "lan_dhcp_reservation_update"
    if "wlan_on_off" in name or "wlan on off" in text:
        return "wifi_radios_update"
    if "ssid" in text or "wpa passphrase" in text or "encryption type" in text:
        return "wifi_ssid_update"
    if "transmitting power" in text or "channel" in text:
        return "wifi_radio_update"
    if "upnp" in text:
        return "local_network_upnp_update"
    if "access devices" in text:
        return None
    if "url" in text:
        return "security_url_filter_update"
    if "host_name_unknown_mac_address" in name or "host name unknown mac address" in text:
        return "security_mac_filter_update"
    if name == "save_settings":
        return "settings_update"
    if name == "apply_filters":
        return "incident_filters_apply"
    if name == "send_invite":
        return "users_invite_send"
    if name == "export_report":
        return "reports_export"
    if name == "sign_in":
        return "session_sign_in"
    if name in {"create_item", "activate_item", "deactivate_item", "delete_item"}:
        return name
    if name.startswith(("submit_", "save_", "apply_", "send_", "export_")) and not NUMBERED_SUFFIX_RE.search(name):
        base = re.sub(r"^(submit|save|apply|send|export)_", "", name)
        return f"{base}_update" if base else None
    return None


def semantic_arg_name(semantic_name: str, arg: str, label: str = "") -> str | None:
    text = f"{arg} {label}".lower()
    if arg in {"dry_run", "confirm"}:
        return arg
    if semantic_name == "security_port_forwarding_create_or_update":
        if "name" in text and "host" not in text:
            return "name"
        if "protocol" in text:
            return "protocol"
        if "lan_host_port" in arg or "lan host port" in text:
            return "lan_port"
        if "wan_port" in arg or "wan port" in text:
            return "wan_port"
        if arg == "lan_host" or "lan host" in text:
            return "lan_host"
        if "wan_host" in arg or "wan host" in text:
            return "wan_host"
        if "enable" in text or arg == "on":
            return "enabled"
        return None
    clean = strip_numbered_suffix(arg)
    if clean in {"stopformautosubmit", "confirmok", "confirmcancel", "confirmstop", "datahasbeengot", "totaltabwidth"}:
        return None
    return clean


def normalize_args_schema(semantic_name: str, args: dict[str, Any]) -> dict[str, Any]:
    shaped = shaped_args_schema(semantic_name)
    if shaped is not None:
        return shaped
    properties = args.get("properties", {})
    normalized: dict[str, Any] = {}
    for arg, schema in properties.items():
        semantic_arg = semantic_arg_name(semantic_name, arg, str(schema.get("description", "")) if isinstance(schema, dict) else "")
        if not semantic_arg or semantic_arg in normalized:
            continue
        normalized[semantic_arg] = schema
    required = []
    for arg in args.get("required", []) or []:
        semantic_arg = semantic_arg_name(semantic_name, arg)
        if semantic_arg and semantic_arg in normalized and semantic_arg not in required:
            required.append(semantic_arg)
    return {"type": "object", "properties": normalized, "required": required, "additionalProperties": False}


def shaped_args_schema(semantic_name: str) -> dict[str, Any] | None:
    flags = {
        "dry_run": {"type": "boolean", "default": True},
        "confirm": {"type": "boolean", "default": False, "description": "Required for apply mode when this tool requires confirmation."},
    }
    if semantic_name == "security_firewall_update":
        return {
            "type": "object",
            "properties": {
                "level": {"type": "string", "enum": ["low", "middle", "high"], "description": "Firewall protection level."},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name in {"security_upnp_update", "local_network_upnp_update"}:
        return {
            "type": "object",
            "properties": {"enabled": {"type": "boolean", "description": "Whether UPnP is enabled."}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "wifi_radios_update":
        return {
            "type": "object",
            "properties": {
                "radios": {
                    "type": "object",
                    "description": "Per-band radio enablement.",
                    "properties": {"2_4ghz": {"type": "boolean"}, "5ghz": {"type": "boolean"}},
                    "additionalProperties": False,
                },
                "enabled": {"type": "boolean", "description": "Set all Wi-Fi radios on or off."},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "wifi_radio_update":
        return {
            "type": "object",
            "properties": {
                "band": {"type": "string", "enum": ["2_4ghz", "5ghz"], "description": "Radio band to configure."},
                "channel": {"type": "string"},
                "band_width": {"type": "string"},
                "mode": {"type": "string"},
                "transmit_power": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name in {"lan_port_binding_update", "internet_port_binding_update"}:
        return {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "lan_ports": {"type": "array", "items": {"type": "string"}, "description": "LAN ports included in the binding."},
                "ssids": {"type": "array", "items": {"type": "string"}, "description": "SSID names or indexes included in the binding."},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "security_filtering_update":
        return {
            "type": "object",
            "properties": {
                "mac_filter_enabled": {"type": "boolean"},
                "url_filter_enabled": {"type": "boolean"},
                "mode": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "security_port_forwarding_create_or_update":
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "protocol": {"type": "string", "enum": ["TCP", "UDP", "TCP/UDP"]},
                "lan_host": {"type": "string"},
                "lan_port": {"type": "string"},
                "wan_port": {"type": "string"},
                "wan_host": {"type": "string"},
                "enabled": {"type": "boolean"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "lan_dhcp_reservation_update":
        return {
            "type": "object",
            "properties": {"name": {"type": "string"}, "ip_address": {"type": "string"}, "mac_address": {"type": "string"}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "lan_dhcp_update":
        return {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "lan_ip": {"type": "string"},
                "subnet_mask": {"type": "string"},
                "start_ip": {"type": "string"},
                "end_ip": {"type": "string"},
                "lease_time": {"type": "string"},
                "primary_dns": {"type": "string"},
                "secondary_dns": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "security_mac_filter_update":
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "host_name": {"type": "string"},
                "source_mac": {"type": "string"},
                "destination_mac": {"type": "string"},
                "protocol": {"type": "string"},
                "action": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "security_url_filter_update":
        return {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "url": {"type": "string"},
                "enabled": {"type": "boolean"},
                "schedule": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "wifi_ssid_update":
        return {
            "type": "object",
            "properties": {
                "ssid": {"type": "string"},
                "band": {"type": "string", "enum": ["2_4ghz", "5ghz"]},
                "enabled": {"type": "boolean"},
                "hidden": {"type": "boolean"},
                "encryption_type": {"type": "string"},
                "passphrase": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "devices_access_update":
        return {
            "type": "object",
            "properties": {"host_name": {"type": "string"}, "mac_address": {"type": "string"}, "access_allowed": {"type": "boolean"}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name in {"wan_connection_update", "internet_wan_update"}:
        return {
            "type": "object",
            "properties": {
                "connection_name": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "management_account_update":
        return {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "old_password": {"type": "string"},
                "new_password": {"type": "string"},
                "confirmed_password": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "management_idle_timeout_update":
        return {
            "type": "object",
            "properties": {"timeout": {"type": "string"}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "management_network_diagnostics_run":
        return {
            "type": "object",
            "properties": {
                "host": {"type": "string"},
                "egress": {"type": "string"},
                "protocol": {"type": "string"},
                "maximum_hops": {"type": "string"},
                "wait_time": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "internet_ddns_update":
        return {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "provider": {"type": "string"},
                "provider_url": {"type": "string"},
                "username": {"type": "string"},
                "password": {"type": "string"},
                "host_name": {"type": "string"},
                "service_type": {"type": "string"},
                "domain": {"type": "string"},
                "hash": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "internet_sntp_update":
        return {
            "type": "object",
            "properties": {
                "current_datetime": {"type": "string"},
                "time_zone": {"type": "string"},
                "ntp_server": {"type": "string"},
                "poll_interval": {"type": "string"},
                "daylight_saving": {"type": "boolean"},
                "dscp": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "local_network_dms_update":
        return {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "name": {"type": "string"},
                "library_rescan_method": {"type": "string"},
                "rescan_cycle": {"type": "string"},
                "media_sources": {"type": "array", "items": {"type": "string"}},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "security_dmz_update":
        return {
            "type": "object",
            "properties": {"enabled": {"type": "boolean"}, "lan_host": {"type": "string"}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "local_network_dhcpv6_update":
        return {
            "type": "object",
            "properties": {
                "enabled": {"type": "boolean"},
                "lan_ipv6_address": {"type": "string"},
                "prefix": {"type": "string"},
                "prefix_delegate_type": {"type": "string"},
                "dns_delegate_type": {"type": "string"},
                "dns_servers": {"type": "array", "items": {"type": "string"}},
                "dns_refresh_time": {"type": "string"},
                **flags,
            },
            "required": [],
            "additionalProperties": False,
        }
    if semantic_name == "local_network_dns_update":
        return {
            "type": "object",
            "properties": {"domain_name": {"type": "string"}, "host_name": {"type": "string"}, **flags},
            "required": [],
            "additionalProperties": False,
        }
    return None


def normalize_capability_tool(tool: ToolSpec, semantic_name: str) -> ToolSpec:
    operation = "Read" if semantic_name.endswith(("_get", "_list")) else "Configure"
    description = f"{operation} {semantic_name.replace('_', ' ')}."
    return replace(
        tool,
        name=semantic_name,
        description=description,
        args=normalize_args_schema(semantic_name, tool.args),
        compatibility_aliases=[],
        source_type="canonical_concept",
        reasoning_summary=f"Semantic capability generated from evidence-backed UI adapter {tool.name}.",
    )


def normalize_binding_args(adapter: dict[str, Any], semantic_name: str) -> dict[str, Any]:
    if "fields" not in adapter:
        return adapter
    normalized_fields = []
    seen: set[str] = set()
    shaped_args = set((shaped_args_schema(semantic_name) or {}).get("properties", {}))
    for field in adapter.get("fields", []):
        semantic_arg = semantic_arg_name(semantic_name, str(field.get("arg", "")), str(field.get("label", "")))
        if not semantic_arg or semantic_arg in seen:
            continue
        if shaped_args and semantic_arg not in shaped_args:
            continue
        updated = dict(field)
        updated["arg"] = semantic_arg
        normalized_fields.append(updated)
        seen.add(semantic_arg)
    updated_adapter = dict(adapter)
    if shaped_args and not normalized_fields:
        normalized_fields = [
            {"arg": arg, "label": arg.replace("_", " "), "control_type": "semantic"}
            for arg in sorted(shaped_args)
            if arg not in {"dry_run", "confirm"}
        ]
    updated_adapter["fields"] = normalized_fields
    return updated_adapter


def remap_binding(binding: AdapterBinding, semantic_name: str) -> AdapterBinding:
    return replace(binding, tool_name=semantic_name, selector_action_bindings=normalize_binding_args(binding.selector_action_bindings, semantic_name))


def choose_better(existing: ToolSpec, candidate: ToolSpec) -> bool:
    if candidate.confidence != existing.confidence:
        return candidate.confidence > existing.confidence
    if candidate.source_type != existing.source_type:
        return candidate.source_type == "canonical_concept"
    return len(candidate.evidence_ids) > len(existing.evidence_ids)


def suspicious_semantic_name(name: str | None) -> bool:
    return not name or bool(GENERIC_SEMANTIC_RE.match(name))


def page_capabilities(snapshot: CrawlSnapshot) -> list[tuple[ToolSpec, AdapterBinding]]:
    elements_by_page: dict[str, list[Any]] = {}
    for element in snapshot.elements:
        elements_by_page.setdefault(element.page_id, []).append(element)
    best: dict[str, tuple[ToolSpec, AdapterBinding, int]] = {}
    for page in snapshot.pages:
        semantic_names = [canonical_page_name(page.url, page.headings)]
        heading_text = " ".join(page.headings).lower()
        if "lan client status" in heading_text:
            semantic_names.append("local_network_clients_get")
        page_elements = elements_by_page.get(page.id, [])
        values: dict[str, Any] = {}
        evidence_ids: list[str] = []
        seen_value_keys: set[str] = set()
        for element in page_elements:
            evidence_ids.extend(element.evidence_ids)
            if element.control_type == "hidden":
                continue
            read_value = element.context.get("read_value") if isinstance(element.context, dict) else None
            if read_value in (None, ""):
                continue
            key_base = slug(element.label or str(read_value)) or "value"
            key = key_base
            counter = 2
            while key in seen_value_keys:
                key = f"{key_base}_{counter}"
                counter += 1
            seen_value_keys.add(key)
            values[key] = read_value
            if len(values) >= 200:
                break
        evidence_ids = sorted(dict.fromkeys(evidence_ids))
        score = len(values) + (10 if page.headings else 0) + len(evidence_ids)
        for semantic_name in semantic_names:
            tool = ToolSpec(
                name=semantic_name,
                description=page_description(semantic_name, page.headings),
                args={"type": "object", "properties": {}, "required": [], "additionalProperties": False},
                return_schema={
                    "type": "object",
                    "properties": {
                        "values": {"type": "object"},
                        "headings": {"type": "array", "items": {"type": "string"}},
                        "evidence_ids": {"type": "array", "items": {"type": "string"}},
                    },
                },
                risk_level="low",
                evidence_ids=evidence_ids,
                confidence=0.8 if values else 0.65,
                source_type="canonical_concept",
                reasoning_summary=f"Semantic section capability generated from crawled page headings and state URL {page.url}.",
            )
            binding = AdapterBinding(
                tool_name=semantic_name,
                profile_id=snapshot.profile_id,
                version="0.1.0",
                selector_action_bindings={
                    "action": "read_page",
                    "page_id": page.id,
                    "page_url": page.url,
                    "headings": page.headings,
                    "element_ids": [element.id for element in page_elements[:300]],
                    "values": values,
                },
            )
            if semantic_name not in best or score > best[semantic_name][2]:
                best[semantic_name] = (tool, binding, score)
    return [(tool, binding) for tool, binding, _ in best.values()]


def provenance_missing_read_adapter(adapter: dict[str, Any]) -> bool:
    if adapter.get("action") != "read":
        return False
    return not adapter.get("page_id") and not adapter.get("page_url")


def synthesize_capabilities(
    tools: list[ToolSpec],
    bindings: list[AdapterBinding],
    snapshot: CrawlSnapshot | None = None,
) -> tuple[list[ToolSpec], list[AdapterBinding], dict[str, Any]]:
    binding_by_tool = {binding.tool_name: binding for binding in bindings}
    selected: dict[str, tuple[ToolSpec, AdapterBinding]] = {}
    skipped = 0
    collapsed: dict[str, int] = {}
    page_capability_pairs = page_capabilities(snapshot) if snapshot is not None else []
    page_section_names = {tool.name for tool, _ in page_capability_pairs}
    for tool in tools:
        is_write = tool.name.startswith(("submit_", "create_", "delete_", "update_", "save_", "apply_", "enable_", "disable_", "activate_", "deactivate_")) or tool.source_type in {
            "ui_form",
            "ui_flow",
        }
        binding = binding_by_tool.get(tool.name)
        if not binding:
            skipped += 1
            continue
        semantic_name = semantic_write_name(tool) if is_write else semantic_read_name(tool)
        context_name = semantic_context_name(tool, binding, is_write)
        if context_name and suspicious_semantic_name(semantic_name):
            semantic_name = context_name
        if snapshot is not None and len(snapshot.pages) > 1 and semantic_name == "wan_connection_get":
            semantic_name = "internet_wan_get"
        if not semantic_name or suspicious_semantic_name(semantic_name):
            skipped += 1
            continue
        adapter = binding.selector_action_bindings
        visual_collection = (
            snapshot is not None
            and len(snapshot.pages) > 1
            and any(page.html_snapshot for page in snapshot.pages)
            and any("#state=" in page.url for page in snapshot.pages)
        )
        if visual_collection and not is_write and provenance_missing_read_adapter(adapter):
            skipped += 1
            continue
        capability_tool = normalize_capability_tool(tool, semantic_name)
        meaningful_args = set(capability_tool.args.get("properties", {})) - {"dry_run", "confirm"}
        if is_write and not meaningful_args:
            skipped += 1
            continue
        if capability_tool.exposure_level == "internal_disabled":
            capability_tool = replace(capability_tool, exposure_level="review_required")
        capability_binding = remap_binding(binding, semantic_name)
        collapsed[semantic_name] = collapsed.get(semantic_name, 0) + 1
        if semantic_name not in selected or choose_better(selected[semantic_name][0], tool):
            selected[semantic_name] = (capability_tool, capability_binding)

    section_names: list[str] = []
    if snapshot is not None:
        for capability_tool, capability_binding in page_capability_pairs:
            section_names.append(capability_tool.name)
            existing = selected.get(capability_tool.name)
            existing_adapter = existing[1].selector_action_bindings if existing else {}
            existing_value_count = len(existing_adapter.get("values") or {}) if existing else 0
            candidate_value_count = len(capability_binding.selector_action_bindings.get("values") or {})
            if existing is None or (
                capability_binding.selector_action_bindings.get("values")
                and (existing_adapter.get("action") != "read_page" or candidate_value_count > existing_value_count)
                and capability_tool.name in {
                    *page_section_names,
                    "home_overview_get",
                    "internet_status_get",
                    "local_network_status_get",
                    "topology_devices_get",
                    "voip_status_get",
                    "management_device_information_get",
                }
            ):
                selected[capability_tool.name] = (capability_tool, capability_binding)

    capability_tools = [pair[0] for _, pair in sorted(selected.items())]
    capability_bindings = [pair[1] for _, pair in sorted(selected.items())]
    report = {
        "capabilities": len(capability_tools),
        "discarded_adapter_count": skipped,
        "collapsed_adapter_counts": {name: count for name, count in sorted(collapsed.items()) if count > 1},
        "ui_sections": {
            "discovered": len(set(section_names)),
            "capability_names": sorted(set(section_names)),
        },
        "quality": {
            "numbered_args": {
                tool.name: sorted(arg for arg in tool.args.get("properties", {}) if NUMBERED_SUFFIX_RE.search(arg))
                for tool in capability_tools
                if any(NUMBERED_SUFFIX_RE.search(arg) for arg in tool.args.get("properties", {}))
            },
            "numbered_public_names": [tool.name for tool in capability_tools if NUMBERED_SUFFIX_RE.search(tool.name)],
            "generic_public_names": [tool.name for tool in capability_tools if GENERIC_TOOL_RE.match(tool.name)],
        },
    }
    return capability_tools, capability_bindings, report
