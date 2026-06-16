from site_agent.core.synthesize.ansible import build_ansible_spec, option_spec_from_tool
from site_agent.core.synthesize.api import build_api_spec
from site_agent.core.synthesize.docs import build_openapi_spec, build_postman_collection, write_api_documentation_bundle
from site_agent.core.models import utc_now
from site_agent.core.profiles import Profile
from site_agent.core.storage import read_json, write_json


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


def test_openapi_and_postman_docs_describe_public_generated_methods(tmp_path):
    profile = Profile(
        id="profile_demo",
        name="Demo Site",
        base_url="https://demo.example",
        host_allowlist=["demo.example"],
        created_at=utc_now(),
    )
    tools = [
        tool("get_status"),
        tool("update_settings", risk_level="medium"),
        tool("internal_probe", exposure_level="internal_disabled"),
    ]
    api_spec = build_api_spec(profile.name, tools).__dict__
    api_spec["methods"] = [method.__dict__ for method in api_spec["methods"]]

    openapi = build_openapi_spec(profile, tools, api_spec)
    collection = build_postman_collection(profile, tools, api_spec)

    assert openapi["openapi"] == "3.1.0"
    assert "/methods/get_status" in openapi["paths"]
    assert "/methods/update_settings" in openapi["paths"]
    assert "/methods/internal_probe" not in openapi["paths"]
    operation = openapi["paths"]["/methods/update_settings"]["post"]
    assert operation["x-site-agent"]["risk_level"] == "medium"
    assert operation["requestBody"]["content"]["application/json"]["schema"]["properties"]["mode"]["enum"] == ["dry-run", "apply"]
    assert collection["info"]["schema"].endswith("/collection/v2.1.0/collection.json")
    assert any(group["name"] == "Read APIs" for group in collection["item"])

    root = tmp_path / "output" / profile.name
    write_json(root / "mcp" / "tools.json", {"tools": tools})
    write_json(root / "api" / "api-spec.json", api_spec)
    paths = write_api_documentation_bundle(tmp_path, profile)

    assert read_json(paths["openapi_json"])["paths"]["/methods/get_status"]["post"]["operationId"] == "get_status"
    assert read_json(paths["postman_environment"])["values"][0]["key"] == "baseUrl"
    assert paths["api_reference"].read_text(encoding="utf-8").startswith("# Demo Site Generated API Reference")
