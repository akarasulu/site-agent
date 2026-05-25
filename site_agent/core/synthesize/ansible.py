from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from site_agent.core.models import AnsibleCollectionSpec, AnsibleModuleSpec, PythonApiSpec
from site_agent.core.storage import write_json
from site_agent.core.synthesize.api import api_package_name, build_api_spec, class_name, method_name, slug


def collection_name(profile_name: str) -> str:
    return slug(profile_name).replace("_", "")


def option_spec_from_tool(tool: dict[str, Any]) -> dict[str, Any]:
    options = {
        "profile_path": {"type": "str", "required": False},
        "package_dir": {"type": "str", "required": False},
        "mode": {"type": "str", "required": False, "default": "dry-run", "choices": ["dry-run", "apply"]},
    }
    properties = tool.get("args", {}).get("properties", {})
    required = set(tool.get("args", {}).get("required", []))
    for name, schema in properties.items():
        if name in {"dry_run", "confirm"}:
            continue
        options[name] = {
            "type": "raw" if schema.get("type") == "object" else "str",
            "required": name in required,
        }
    return options


def build_ansible_spec(profile_name: str, tools: list[dict[str, Any]], api_spec: PythonApiSpec | None = None) -> AnsibleCollectionSpec:
    api_spec = api_spec or build_api_spec(profile_name, tools)
    modules = []
    prefix = collection_name(profile_name)
    for tool in tools:
        if tool.get("exposure_level") == "internal_disabled":
            continue
        supports_check = bool(tool.get("dry_run_supported", True))
        risk = tool.get("risk_level", "low")
        idempotence = "full" if risk in {"low", "medium"} and supports_check else "none"
        modules.append(
            AnsibleModuleSpec(
                name=f"{prefix}_{method_name(str(tool.get('name', 'tool')))}",
                description=str(tool.get("description", "")),
                options=option_spec_from_tool(tool),
                supports_check_mode=supports_check,
                idempotence_level=idempotence,
                risk_level=risk,
                evidence_ids=list(tool.get("evidence_ids", [])),
                backing_python_method=method_name(str(tool.get("name", ""))),
            )
        )
    evidence_ids = sorted({evidence_id for module in modules for evidence_id in module.evidence_ids})
    return AnsibleCollectionSpec(
        namespace="site_agent",
        name=collection_name(profile_name),
        version="0.1.0",
        modules=modules,
        evidence_ids=evidence_ids,
        python_api_dependency=api_spec.package_name,
    )


def module_source(module: AnsibleModuleSpec, client_class: str, api_package: str) -> str:
    option_spec = repr(module.options)
    argument_names = [name for name in module.options if name not in {"profile_path", "package_dir", "mode"}]
    args_expr = "{" + ", ".join(f"{name!r}: module.params.get({name!r})" for name in argument_names) + "}"
    return (
        "#!/usr/bin/python\n"
        "from __future__ import annotations\n\n"
        "DOCUMENTATION = r'''\n"
        "---\n"
        f"module: {module.name}\n"
        f"short_description: {module.description[:120]}\n"
        "description:\n"
        f"  - {module.description}\n"
        "options: {}\n"
        "'''\n\n"
        "EXAMPLES = r'''\n"
        f"- {module.name}:\n"
        "    package_dir: output/my-site/mcp\n"
        "  check_mode: true\n"
        "'''\n\n"
        "RETURN = r'''\n"
        "result:\n"
        "  description: Raw result returned by the generated Python API.\n"
        "  returned: always\n"
        "  type: dict\n"
        "'''\n\n"
        "from ansible.module_utils.basic import AnsibleModule\n"
        f"from ansible_collections.site_agent.{collection_name_from_module(module.name)}.plugins.module_utils.client import load_client\n\n\n"
        "def main():\n"
        f"    module = AnsibleModule(argument_spec={option_spec}, supports_check_mode={module.supports_check_mode!r})\n"
        "    client = load_client(module.params.get('package_dir'), module.params.get('profile_path'))\n"
        f"    args = {args_expr}\n"
        "    args = {key: value for key, value in args.items() if value is not None}\n"
        "    mode = 'dry-run' if module.check_mode else module.params.get('mode')\n"
        f"    result = client.{module.backing_python_method}(mode=mode, **args)\n"
        "    changed = bool(result.get('status') == 'applied')\n"
        "    module.exit_json(changed=changed, result=result, evidence_ids=result.get('evidence_ids', []))\n\n\n"
        "if __name__ == '__main__':\n"
        "    main()\n"
    )


def collection_name_from_module(module_name: str) -> str:
    parts = module_name.split("_")
    return parts[0] if parts else "target"


def write_ansible_collection(workspace: Path, profile_name: str, tools: list[dict[str, Any]], api_spec: PythonApiSpec | None = None) -> tuple[Path, AnsibleCollectionSpec]:
    api_spec = api_spec or build_api_spec(profile_name, tools)
    spec = build_ansible_spec(profile_name, tools, api_spec)
    root = workspace / "output" / profile_name / "ansible" / "ansible_collections" / spec.namespace / spec.name
    modules_dir = root / "plugins" / "modules"
    module_utils_dir = root / "plugins" / "module_utils"
    playbooks_dir = root / "playbooks"
    modules_dir.mkdir(parents=True, exist_ok=True)
    module_utils_dir.mkdir(parents=True, exist_ok=True)
    playbooks_dir.mkdir(parents=True, exist_ok=True)
    write_json(workspace / "output" / profile_name / "ansible" / "ansible-spec.json", spec)
    (root / "galaxy.yml").write_text(
        f"namespace: {spec.namespace}\n"
        f"name: {spec.name}\n"
        f"version: {spec.version}\n"
        "readme: README.md\n"
        "authors:\n"
        "  - site-agent\n",
        encoding="utf-8",
    )
    (root / "README.md").write_text(
        f"# site_agent.{spec.name}\n\nGenerated Ansible collection for `{profile_name}`. Modules wrap the generated `{api_spec.package_name}` Python API.\n",
        encoding="utf-8",
    )
    client_cls = class_name(profile_name)
    (module_utils_dir / "client.py").write_text(
        "from __future__ import annotations\n\n"
        "from pathlib import Path\n"
        "import sys\n\n\n"
        "def load_client(package_dir=None, profile_path=None):\n"
        f"    api_root = Path(__file__).resolve().parents[6] / 'api'\n"
        "    if api_root.exists() and str(api_root) not in sys.path:\n"
        "        sys.path.insert(0, str(api_root))\n"
        f"    from {api_spec.package_name} import {client_cls}\n"
        "    if package_dir:\n"
        f"        return {client_cls}.from_package_dir(package_dir)\n"
        "    if profile_path:\n"
        f"        return {client_cls}.from_profile(profile_path)\n"
        f"    return {client_cls}.from_package_dir(Path(__file__).resolve().parents[6] / 'mcp')\n",
        encoding="utf-8",
    )
    for module in spec.modules:
        (modules_dir / f"{module.name}.py").write_text(module_source(module, client_cls, api_spec.package_name), encoding="utf-8")
    (playbooks_dir / "backup.yml").write_text(
        "- hosts: localhost\n"
        "  gather_facts: false\n"
        "  tasks:\n"
        f"    - name: Read generated facts\n      site_agent.{spec.name}.{spec.modules[0].name if spec.modules else spec.name + '_facts'}:\n        package_dir: output/{profile_name}/mcp\n      check_mode: true\n",
        encoding="utf-8",
    )
    return root, spec
