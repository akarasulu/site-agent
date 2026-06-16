from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from site_agent.core.models import to_jsonable, utc_now
from site_agent.core.profiles import Profile, output_root
from site_agent.core.storage import ensure_dir, read_json, write_json
from site_agent.core.synthesize.api import build_api_spec


DEFAULT_API_BRIDGE_URL = "http://127.0.0.1:8766"
POSTMAN_COLLECTION_SCHEMA = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"

SOURCE_TYPE_TAGS = {
    "canonical_concept": "Read APIs",
    "ui_page": "Page Reads",
    "ui_form": "Form Actions",
    "ui_flow": "Staged Workflows",
}


def _as_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    return to_jsonable(value)


def _public_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [tool for tool in tools if tool.get("exposure_level") != "internal_disabled"]


def _load_api_spec(profile_name: str, root: Path, tools: list[dict[str, Any]]) -> dict[str, Any]:
    api_spec_path = root / "api" / "api-spec.json"
    if api_spec_path.exists():
        return read_json(api_spec_path)
    return to_jsonable(build_api_spec(profile_name, tools))


def _tool_by_method(method: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    tools_by_name = {tool.get("name"): tool for tool in tools}
    backing_tool = method.get("backing_tool") or method.get("name")
    if backing_tool in tools_by_name:
        return tools_by_name[backing_tool]
    for tool in tools:
        if backing_tool in (tool.get("compatibility_aliases") or []):
            return tool
    return {}


def _operation_tag(method: dict[str, Any], tool: dict[str, Any]) -> str:
    if method.get("risk_level") == "high" or tool.get("risk_level") == "high":
        return "High Risk"
    if tool.get("exposure_level") == "review_required":
        return "Review Required"
    return SOURCE_TYPE_TAGS.get(str(tool.get("source_type") or "canonical_concept"), "Generated API")


def _schema_or_object(schema: dict[str, Any] | None) -> dict[str, Any]:
    if not schema:
        return {"type": "object", "properties": {}, "additionalProperties": False}
    result = dict(schema)
    result.setdefault("type", "object")
    result.setdefault("properties", {})
    return result


def _example_value(schema: dict[str, Any]) -> Any:
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    schema_type = schema.get("type")
    if schema_type == "boolean":
        return False
    if schema_type in {"integer", "number"}:
        return 0
    if schema_type == "array":
        return []
    if schema_type == "object":
        return {}
    return "string"


def _example_args(args_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        name: _example_value(schema if isinstance(schema, dict) else {})
        for name, schema in (args_schema.get("properties") or {}).items()
        if name not in {"dry_run", "confirm"}
    }


def _call_request_schema(args_schema: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "object",
        "additionalProperties": False,
        "properties": {
            "args": _schema_or_object(args_schema),
            "mode": {
                "type": "string",
                "enum": ["dry-run", "apply"],
                "default": "dry-run",
                "description": "Execution mode. Write-like operations should be tried in dry-run before apply.",
            },
            "browser": {
                "type": "boolean",
                "default": False,
                "description": "Use the browser-backed runtime for staged UI flow apply calls.",
            },
        },
    }


def _operation_description(method: dict[str, Any], tool: dict[str, Any]) -> str:
    evidence = ", ".join(method.get("evidence_ids") or tool.get("evidence_ids") or []) or "none"
    details = [
        method.get("description") or tool.get("description") or "Generated site-agent API operation.",
        "",
        f"Risk level: `{method.get('risk_level') or tool.get('risk_level', 'low')}`.",
        f"Backing MCP tool: `{method.get('backing_tool') or method.get('name')}`.",
        f"Evidence IDs: `{evidence}`.",
    ]
    if tool.get("requires_confirmation"):
        details.append("Apply mode requires explicit confirmation in the request arguments.")
    return "\n".join(details)


def build_openapi_spec(
    profile: Profile,
    tools: list[dict[str, Any]],
    api_spec: dict[str, Any],
    api_bridge_url: str = DEFAULT_API_BRIDGE_URL,
) -> dict[str, Any]:
    """Builds an OpenAPI description for the generated profile API bridge."""
    public_tools = _public_tools(tools)
    methods = api_spec.get("methods", [])
    paths: dict[str, Any] = {}
    tags: dict[str, dict[str, str]] = {}
    for method in methods:
        tool = _tool_by_method(method, public_tools)
        tag = _operation_tag(method, tool)
        tags.setdefault(tag, {"name": tag})
        method_name = str(method.get("name"))
        args_schema = _schema_or_object(method.get("args") or tool.get("args"))
        request_example = {
            "mode": "dry-run",
            "browser": False,
            "args": _example_args(args_schema),
        }
        paths[f"/methods/{method_name}"] = {
            "post": {
                "operationId": method_name,
                "summary": method.get("description") or tool.get("description") or method_name,
                "description": _operation_description(method, tool),
                "tags": [tag],
                "requestBody": {
                    "required": False,
                    "content": {
                        "application/json": {
                            "schema": _call_request_schema(args_schema),
                            "example": request_example,
                        }
                    },
                },
                "responses": {
                    "200": {
                        "description": "Generated tool result.",
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ToolResult"}
                            }
                        },
                    },
                    "400": {"description": "Invalid JSON request or rejected tool call."},
                    "404": {"description": "Unknown generated API method."},
                },
                "x-site-agent": {
                    "profile": profile.name,
                    "method_name": method_name,
                    "backing_tool": method.get("backing_tool") or method_name,
                    "mcp_tool": tool.get("name") or method.get("backing_tool") or method_name,
                    "risk_level": method.get("risk_level") or tool.get("risk_level", "low"),
                    "dry_run_supported": method.get("dry_run_supported", tool.get("dry_run_supported", True)),
                    "source_type": tool.get("source_type"),
                    "exposure_level": tool.get("exposure_level", "ready_public"),
                    "evidence_ids": method.get("evidence_ids") or tool.get("evidence_ids", []),
                },
            }
        }
    return {
        "openapi": "3.1.0",
        "info": {
            "title": f"{profile.name} Generated Site API",
            "version": api_spec.get("version", "0.1.0"),
            "description": (
                "Generated OpenAPI contract for the profile-specific site-agent API bridge. "
                "The bridge delegates to the generated Python API/MCP execution layer; raw UI selectors stay private."
            ),
        },
        "servers": [
            {
                "url": api_bridge_url.rstrip("/"),
                "description": "Local site-agent API bridge.",
            }
        ],
        "tags": list(tags.values()),
        "paths": paths,
        "components": {
            "schemas": {
                "ToolResult": {
                    "type": "object",
                    "additionalProperties": True,
                    "description": "Raw structured result from the generated site-agent runtime.",
                }
            }
        },
        "x-site-agent": {
            "profile_id": profile.id,
            "profile_name": profile.name,
            "base_url": profile.base_url,
            "package_name": api_spec.get("package_name"),
            "generated_at": utc_now(),
            "selector_free_public_contract": True,
        },
    }


def _postman_uuid(profile_name: str, suffix: str) -> str:
    return str(uuid5(NAMESPACE_URL, f"site-agent:{profile_name}:{suffix}"))


def build_postman_environment(
    profile: Profile,
    api_bridge_url: str = DEFAULT_API_BRIDGE_URL,
) -> dict[str, Any]:
    return {
        "id": _postman_uuid(profile.name, "environment"),
        "name": f"{profile.name} Generated API",
        "values": [
            {
                "key": "baseUrl",
                "value": api_bridge_url.rstrip("/"),
                "type": "default",
                "enabled": True,
            },
            {
                "key": "profile",
                "value": profile.name,
                "type": "default",
                "enabled": True,
            },
        ],
        "_postman_variable_scope": "environment",
        "_postman_exported_using": "site-agent",
    }


def _postman_request(method: dict[str, Any], tool: dict[str, Any]) -> dict[str, Any]:
    method_name = str(method.get("name"))
    args_schema = _schema_or_object(method.get("args") or tool.get("args"))
    body = {
        "mode": "dry-run",
        "browser": False,
        "args": _example_args(args_schema),
    }
    return {
        "name": method_name,
        "request": {
            "method": "POST",
            "header": [{"key": "Content-Type", "value": "application/json"}],
            "body": {
                "mode": "raw",
                "raw": json.dumps(body, indent=2, sort_keys=True),
                "options": {"raw": {"language": "json"}},
            },
            "url": {
                "raw": f"{{{{baseUrl}}}}/methods/{method_name}",
                "host": ["{{baseUrl}}"],
                "path": ["methods", method_name],
            },
            "description": _operation_description(method, tool),
        },
    }


def build_postman_collection(
    profile: Profile,
    tools: list[dict[str, Any]],
    api_spec: dict[str, Any],
) -> dict[str, Any]:
    public_tools = _public_tools(tools)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for method in api_spec.get("methods", []):
        tool = _tool_by_method(method, public_tools)
        grouped[_operation_tag(method, tool)].append(_postman_request(method, tool))
    items = [
        {"name": name, "item": sorted(requests, key=lambda item: item["name"])}
        for name, requests in sorted(grouped.items())
    ]
    return {
        "info": {
            "_postman_id": _postman_uuid(profile.name, "collection"),
            "name": f"{profile.name} Generated Site API",
            "description": (
                "Generated Postman collection for the site-agent local API bridge. "
                "Requests default to dry-run mode."
            ),
            "schema": POSTMAN_COLLECTION_SCHEMA,
        },
        "item": items,
        "variable": [{"key": "baseUrl", "value": DEFAULT_API_BRIDGE_URL}],
    }


def _operation_rows(api_spec: dict[str, Any], tools: list[dict[str, Any]]) -> list[str]:
    public_tools = _public_tools(tools)
    rows = [
        "| Method | Risk | Backing MCP tool | Evidence |",
        "| --- | --- | --- | --- |",
    ]
    for method in sorted(api_spec.get("methods", []), key=lambda item: item.get("name", "")):
        tool = _tool_by_method(method, public_tools)
        evidence = ", ".join(method.get("evidence_ids") or tool.get("evidence_ids") or [])
        rows.append(
            "| `{}` | `{}` | `{}` | {} |".format(
                method.get("name"),
                method.get("risk_level") or tool.get("risk_level", "low"),
                method.get("backing_tool") or method.get("name"),
                evidence or "none",
            )
        )
    return rows


def build_api_reference_markdown(
    profile: Profile,
    tools: list[dict[str, Any]],
    api_spec: dict[str, Any],
) -> str:
    rows = "\n".join(_operation_rows(api_spec, tools))
    return (
        f"# {profile.name} Generated API Reference\n\n"
        "This generated documentation describes the selector-free automation "
        "contract for the target profile. Raw selectors and browser bindings "
        "remain private in adapter artifacts.\n\n"
        "## Artifacts\n\n"
        "* `openapi.json`: OpenAPI 3.1 contract for the local API bridge.\n"
        "* `openapi.yaml`: YAML-compatible copy of the OpenAPI contract.\n"
        "* `../postman/collection.json`: Postman collection for generated methods.\n"
        "* `../postman/environment.json`: Postman environment with `baseUrl`.\n\n"
        "## Run The Local API Bridge\n\n"
        "```bash\n"
        f"site-agent api serve --profile {profile.name}\n"
        "```\n\n"
        "Requests default to `dry-run`. Use `apply` only when the profile risk "
        "policy, operation metadata, and confirmation rules allow it.\n\n"
        "## Operations\n\n"
        f"{rows}\n"
    )


def write_json_yaml(path: Path, data: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_api_documentation_bundle(
    workspace: Path,
    profile: Profile,
    api_bridge_url: str = DEFAULT_API_BRIDGE_URL,
) -> dict[str, Path]:
    """Writes OpenAPI, Postman, and API reference docs for a profile."""
    root = output_root(workspace, profile.name)
    tools_path = root / "mcp" / "tools.json"
    if not tools_path.exists():
        raise FileNotFoundError(f"No generated tools found. Run: site-agent mcp build --profile {profile.name}")
    tools = read_json(tools_path).get("tools", [])
    api_spec = _load_api_spec(profile.name, root, tools)
    openapi = build_openapi_spec(profile, tools, api_spec, api_bridge_url)
    collection = build_postman_collection(profile, tools, api_spec)
    environment = build_postman_environment(profile, api_bridge_url)
    docs_dir = ensure_dir(root / "docs")
    postman_dir = ensure_dir(root / "postman")
    write_json(docs_dir / "openapi.json", openapi)
    write_json_yaml(docs_dir / "openapi.yaml", openapi)
    write_json(postman_dir / "collection.json", collection)
    write_json(postman_dir / "environment.json", environment)
    (docs_dir / "api-reference.md").write_text(
        build_api_reference_markdown(profile, tools, api_spec),
        encoding="utf-8",
    )
    return {
        "openapi_json": docs_dir / "openapi.json",
        "openapi_yaml": docs_dir / "openapi.yaml",
        "api_reference": docs_dir / "api-reference.md",
        "postman_collection": postman_dir / "collection.json",
        "postman_environment": postman_dir / "environment.json",
    }
