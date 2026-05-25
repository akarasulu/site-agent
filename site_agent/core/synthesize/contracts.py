from __future__ import annotations

from pathlib import Path

from site_agent.core.storage import read_json, write_json


def contract_from_tools(tools: list[dict]) -> dict:
    return {
        "version": "0.1.0",
        "tools": [
            {
                "name": tool["name"],
                "args": tool["args"],
                "risk_level": tool["risk_level"],
                "return_schema": tool["return_schema"],
            }
            for tool in sorted(tools, key=lambda item: item["name"])
        ]
    }


def write_contract(package_dir: Path) -> Path:
    tools = read_json(package_dir / "tools.json")["tools"]
    path = package_dir / "contract.json"
    write_json(path, contract_from_tools(tools))
    return path


def _major(version: str | None) -> int:
    try:
        return int((version or "0").split(".", 1)[0])
    except ValueError:
        return 0


def _signature(tool: dict) -> tuple:
    return (
        tool.get("risk_level"),
        tool.get("args"),
        tool.get("return_schema"),
    )


def diff_contracts(old: dict, new: dict) -> dict:
    old_tools = {tool["name"]: tool for tool in old.get("tools", [])}
    new_tools = {tool["name"]: tool for tool in new.get("tools", [])}
    removed = sorted(set(old_tools) - set(new_tools))
    added = sorted(set(new_tools) - set(old_tools))
    renamed = []
    unmatched_added = set(added)
    for old_name in removed:
        old_signature = _signature(old_tools[old_name])
        for new_name in sorted(unmatched_added):
            if _signature(new_tools[new_name]) == old_signature:
                renamed.append({"from": old_name, "to": new_name})
                unmatched_added.remove(new_name)
                break
    changed = []
    for name in sorted(set(old_tools) & set(new_tools)):
        if old_tools[name].get("args") != new_tools[name].get("args") or old_tools[name].get("return_schema") != new_tools[name].get("return_schema"):
            changed.append(name)
    breaking = bool(removed or changed or renamed)
    old_version = old.get("version", "0.1.0")
    new_version = new.get("version", "0.1.0")
    version_ok = not breaking or _major(new_version) > _major(old_version)
    return {
        "breaking": breaking,
        "semver_required": "major" if breaking else "minor" if added else "patch",
        "version_ok": version_ok,
        "old_version": old_version,
        "new_version": new_version,
        "removed": removed,
        "added": added,
        "renamed": renamed,
        "changed": changed,
    }
