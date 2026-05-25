from __future__ import annotations

import keyword
import re
from pathlib import Path
from typing import Any

from site_agent.core.models import PythonApiMethod, PythonApiSpec
from site_agent.core.storage import read_json, write_json


def slug(value: str, fallback: str = "site") -> str:
    result = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return result or fallback


def class_name(value: str) -> str:
    return "".join(part.capitalize() for part in slug(value).split("_")) + "Client"


def method_name(value: str) -> str:
    name = slug(value, "call_tool")
    if keyword.iskeyword(name):
        name = f"{name}_"
    return name


def api_package_name(profile_name: str) -> str:
    return f"{slug(profile_name)}_client"


def api_methods_from_tools(tools: list[dict[str, Any]]) -> list[PythonApiMethod]:
    methods = []
    for tool in tools:
        if tool.get("exposure_level") == "internal_disabled":
            continue
        methods.append(
            PythonApiMethod(
                name=method_name(str(tool.get("name", ""))),
                description=str(tool.get("description", "")),
                args=tool.get("args", {}),
                return_schema=tool.get("return_schema", {}),
                risk_level=tool.get("risk_level", "low"),
                dry_run_supported=bool(tool.get("dry_run_supported", True)),
                evidence_ids=list(tool.get("evidence_ids", [])),
                backing_tool=str(tool.get("name", "")),
            )
        )
    return methods


def build_api_spec(profile_name: str, tools: list[dict[str, Any]]) -> PythonApiSpec:
    methods = api_methods_from_tools(tools)
    evidence_ids = sorted({evidence_id for method in methods for evidence_id in method.evidence_ids})
    return PythonApiSpec(
        package_name=api_package_name(profile_name),
        version="0.1.0",
        methods=methods,
        evidence_ids=evidence_ids,
    )


def python_repr(value: Any) -> str:
    return repr(value)


def method_source(method: PythonApiMethod) -> str:
    return (
        f"    def {method.name}(self, mode: str = \"dry-run\", browser: bool = False, **kwargs: Any) -> dict[str, Any]:\n"
        f"        \"\"\"{method.description.replace(chr(10), ' ')}\n\n"
        f"        Backing tool: {method.backing_tool}. Risk: {method.risk_level}. Evidence: {', '.join(method.evidence_ids) or 'none'}.\n"
        f"        \"\"\"\n"
        f"        return self.call_tool({method.backing_tool!r}, kwargs, mode=mode, browser=browser)\n"
    )


def write_api_package(workspace: Path, profile_name: str, tools: list[dict[str, Any]] | None = None) -> tuple[Path, PythonApiSpec]:
    root = workspace / "output" / profile_name
    mcp_dir = root / "mcp"
    tools = tools if tools is not None else read_json(mcp_dir / "tools.json").get("tools", [])
    spec = build_api_spec(profile_name, tools)
    api_dir = root / "api"
    package_dir = api_dir / spec.package_name
    client_class = class_name(profile_name)
    methods = "\n".join(method_source(method) for method in spec.methods) or "    pass\n"
    write_json(api_dir / "api-spec.json", spec)
    write_json(
        api_dir / "evidence.json",
        {
            "package_name": spec.package_name,
            "evidence_ids": spec.evidence_ids,
            "methods": [
                {
                    "name": method.name,
                    "backing_tool": method.backing_tool,
                    "evidence_ids": method.evidence_ids,
                    "risk_level": method.risk_level,
                }
                for method in spec.methods
            ],
        },
    )
    (api_dir / "pyproject.toml").parent.mkdir(parents=True, exist_ok=True)
    (api_dir / "pyproject.toml").write_text(
        "[project]\n"
        f"name = \"{spec.package_name.replace('_', '-')}\"\n"
        f"version = \"{spec.version}\"\n"
        "requires-python = \">=3.11\"\n"
        "dependencies = []\n",
        encoding="utf-8",
    )
    package_dir.mkdir(parents=True, exist_ok=True)
    (package_dir / "__init__.py").write_text(
        f"from .client import {client_class}\n\n__all__ = [{client_class!r}]\n",
        encoding="utf-8",
    )
    (package_dir / "models.py").write_text(
        "from __future__ import annotations\n\n"
        "from dataclasses import dataclass, field\n"
        "from typing import Any\n\n\n"
        "@dataclass\n"
        "class ToolResult:\n"
        "    status: str | None = None\n"
        "    value: Any = None\n"
        "    values: dict[str, Any] = field(default_factory=dict)\n"
        "    evidence_ids: list[str] = field(default_factory=list)\n"
        "    raw: dict[str, Any] = field(default_factory=dict)\n",
        encoding="utf-8",
    )
    (package_dir / "runtime.py").write_text(
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n"
        "from typing import Any\n\n"
        "from site_agent.core.synthesize.runtime import call_tool as _call_tool\n\n\n"
        "class Runtime:\n"
        "    def __init__(self, package_dir: str | Path):\n"
        "        self.package_dir = Path(package_dir)\n\n"
        "    def call_tool(self, tool_name: str, args: dict[str, Any] | None = None, mode: str = \"dry-run\", browser: bool = False) -> dict[str, Any]:\n"
        "        return _call_tool(self.package_dir, tool_name, args or {}, mode=mode, browser=browser, use_python_api=False)\n",
        encoding="utf-8",
    )
    (package_dir / "client.py").write_text(
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n"
        "from typing import Any\n\n"
        "from .runtime import Runtime\n\n\n"
        f"class {client_class}:\n"
        f"    \"\"\"Generated Python API client for profile {profile_name}.\"\"\"\n\n"
        "    def __init__(self, package_dir: str | Path):\n"
        "        self.runtime = Runtime(package_dir)\n\n"
        "    @classmethod\n"
        "    def from_package_dir(cls, package_dir: str | Path):\n"
        "        return cls(package_dir)\n\n"
        "    @classmethod\n"
        "    def from_profile(cls, profile_path: str | Path):\n"
        "        profile_path = Path(profile_path)\n"
        "        workspace = profile_path.parent.parent\n"
        "        return cls(workspace / \"output\" / profile_path.name / \"mcp\")\n\n"
        "    def call_tool(self, tool_name: str, args: dict[str, Any] | None = None, mode: str = \"dry-run\", browser: bool = False) -> dict[str, Any]:\n"
        "        return self.runtime.call_tool(tool_name, args or {}, mode=mode, browser=browser)\n\n"
        f"{methods}",
        encoding="utf-8",
    )
    server_path = mcp_dir / "server.json"
    if server_path.exists():
        server = read_json(server_path)
        server["python_api"] = {
            "package_name": spec.package_name,
            "client_class": client_class,
            "path": "../api",
            "version": spec.version,
        }
        write_json(server_path, server)
    return api_dir, spec
