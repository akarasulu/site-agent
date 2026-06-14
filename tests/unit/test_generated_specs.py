from site_agent.core.synthesize.ansible import build_ansible_spec, option_spec_from_tool
from site_agent.core.synthesize.api import build_api_spec


def tool(
    name: str,
    *,
    exposure_level: str = "ready_public",
    risk_level: str = "low",
    dry_run_supported: bool = True,
    aliases: list[str] | None = None,
):
    return {
        "name": name,
        "description": f"{name} description",
        "args": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "payload": {"type": "object"},
                "dry_run": {"type": "boolean"},
                "confirm": {"type": "boolean"},
            },
            "required": ["name", "payload"],
        },
        "return_schema": {"type": "object"},
        "risk_level": risk_level,
        "dry_run_supported": dry_run_supported,
        "evidence_ids": [f"ev_{name}"],
        "exposure_level": exposure_level,
        "compatibility_aliases": aliases or [],
    }


def test_api_spec_filters_internal_tools_and_adds_compatibility_aliases():
    spec = build_api_spec(
        "Demo Site",
        [
            tool("get_status", aliases=["read_status", "get_status"]),
            tool("internal_probe", exposure_level="internal_disabled"),
        ],
    )

    assert spec.package_name == "demo_site_client"
    assert [method.name for method in spec.methods] == ["get_status", "read_status"]
    assert spec.methods[1].backing_tool == "read_status"
    assert spec.evidence_ids == ["ev_get_status"]


def test_ansible_option_spec_filters_runtime_flags_and_preserves_raw_objects():
    options = option_spec_from_tool(tool("update_settings"))

    assert options["profile_path"]["type"] == "str"
    assert options["package_dir"]["type"] == "str"
    assert options["mode"]["choices"] == ["dry-run", "apply"]
    assert options["name"] == {"type": "str", "required": True}
    assert options["payload"] == {"type": "raw", "required": True}
    assert "dry_run" not in options
    assert "confirm" not in options


def test_ansible_spec_uses_python_api_and_marks_non_dry_run_high_risk_non_idempotent():
    spec = build_ansible_spec(
        "Demo Site",
        [
            tool("get_status"),
            tool("factory_reset", risk_level="high", dry_run_supported=False),
            tool("internal_probe", exposure_level="internal_disabled"),
        ],
    )

    assert spec.namespace == "site_agent"
    assert spec.name == "demosite"
    assert spec.python_api_dependency == "demo_site_client"
    assert [module.name for module in spec.modules] == ["demosite_get_status", "demosite_factory_reset"]
    assert spec.modules[0].supports_check_mode is True
    assert spec.modules[0].idempotence_level == "full"
    assert spec.modules[1].supports_check_mode is False
    assert spec.modules[1].idempotence_level == "none"
    assert spec.evidence_ids == ["ev_factory_reset", "ev_get_status"]
