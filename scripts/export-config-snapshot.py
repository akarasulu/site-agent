#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def latest(path: Path, pattern: str) -> Path:
    matches = sorted(path.glob(pattern), key=lambda item: item.stat().st_mtime, reverse=True)
    if not matches:
        raise FileNotFoundError(f"No {pattern} artifact found in {path}")
    return matches[0]


def slug(value: str) -> str:
    import re

    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "setting"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def init_repo(repo: Path, profile_name: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", str(repo)], check=True, text=True)
    readme = repo / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {profile_name} settings\n\n"
            "This repository stores deterministic web UI configuration snapshots exported by site-agent.\n"
            "Snapshots preserve captured values. Protect this repository appropriately, for example with git-crypt or private storage.\n",
            encoding="utf-8",
        )


def schema_mappings(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["ui_element_id"]: item for item in schema.get("mappings", []) if item.get("status") in {"ready", "review"}}


def setting_from_element(element: dict[str, Any], mapping: dict[str, Any] | None, tool_by_element: dict[str, str]) -> dict[str, Any] | None:
    context = element.get("context", {})
    if "read_value" not in context:
        return None
    label = str(element.get("label") or "setting")
    canonical = str((mapping or {}).get("canonical_name") or label)
    value = context.get("read_value")
    path = [str(item) for item in context.get("headings", [])[:3] if item]
    if not path:
        path = [str(context.get("page_title") or element.get("page_id") or "page")]
    path.append(canonical)
    return {
        "id": f"cfg_{slug('/'.join(path))}",
        "canonical_name": canonical,
        "path": path,
        "value": value,
        "value_type": "string",
        "source_tool": tool_by_element.get(element["id"]),
        "restore_tool": None,
        "evidence_ids": sorted(set(element.get("evidence_ids", []) + (mapping or {}).get("evidence_ids", []))),
        "confidence": float((mapping or {}).get("confidence", 0.8)),
        "sensitivity": "operator_managed",
        "restorable": False,
    }


def build_tool_lookup(bindings: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for binding in bindings.get("bindings", []):
        adapter = binding.get("selector_action_bindings", {})
        element_id = adapter.get("ui_element_id")
        if element_id and adapter.get("action") == "read":
            lookup[element_id] = binding.get("tool_name")
    return lookup


def build_snapshot(
    profile_name: str,
    profile_id: str,
    source_run_id: str,
    snapshot: dict[str, Any],
    schema: dict[str, Any],
    bindings: dict[str, Any],
    tools: dict[str, Any] | None = None,
) -> dict[str, Any]:
    mappings = schema_mappings(schema)
    tool_by_element = build_tool_lookup(bindings)
    settings = []
    seen_ids = set()
    for element in snapshot.get("elements", []):
        setting = setting_from_element(element, mappings.get(element.get("id")), tool_by_element)
        if not setting or setting["id"] in seen_ids:
            continue
        seen_ids.add(setting["id"])
        settings.append(setting)
    settings.sort(key=lambda item: (item["path"], item["canonical_name"]))
    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return {
        "schema_version": "0.1.0",
        "id": f"cfgsnap_{source_run_id}",
        "timestamp": now,
        "profile_id": profile_id,
        "profile_name": profile_name,
        "source_run_id": source_run_id,
        "settings": settings,
        "value_policy": "preserve-captured-values",
    }


def write_snapshot(repo: Path, snapshot: dict[str, Any]) -> None:
    safe_timestamp = snapshot["timestamp"].replace(":", "-")
    write_json(repo / "site-agent-settings.json", {"schema_version": "0.1.0", "profile_name": snapshot["profile_name"]})
    write_json(repo / "snapshots" / "latest.json", snapshot)
    write_json(repo / "snapshots" / f"{safe_timestamp}-{snapshot['source_run_id']}.json", snapshot)
    normalized = {
        "schema_version": snapshot["schema_version"],
        "profile_name": snapshot["profile_name"],
        "settings": [
            {
                "canonical_name": item["canonical_name"],
                "path": item["path"],
                "value": item["value"],
                "sensitivity": item["sensitivity"],
                "restorable": item["restorable"],
            }
            for item in snapshot["settings"]
        ],
    }
    write_json(repo / "normalized" / "settings.json", normalized)
    write_json(
        repo / "reports" / f"snapshot-{snapshot['source_run_id']}.json",
        {
            "snapshot_id": snapshot["id"],
            "settings": len(snapshot["settings"]),
            "source_run_id": snapshot["source_run_id"],
            "generated_at": snapshot["timestamp"],
        },
    )


def commit_and_tag(repo: Path, tag: str | None) -> None:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, text=True)
    status = git(repo, "status", "--porcelain")
    if status:
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "Save configuration snapshot"], check=True, text=True)
    if tag:
        existing = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if existing.returncode == 0:
            raise RuntimeError(f"Tag already exists in settings repo: {tag}")
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True, text=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a configuration snapshot from site-agent artifacts into a settings git repository.")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--output-root", required=True, type=Path)
    parser.add_argument("--repo", required=True, type=Path)
    parser.add_argument("--commit", action="store_true")
    parser.add_argument("--tag")
    args = parser.parse_args()

    output_root = args.output_root
    snapshot_path = latest(output_root / "crawl", "snapshot-*.json")
    schema_path = latest(output_root / "schema", "mapped-schema-*.json")
    bindings_path = output_root / "mcp" / "adapter.bindings.json"
    tools_path = output_root / "mcp" / "tools.json"
    snapshot = read_json(snapshot_path)
    schema = read_json(schema_path)
    bindings = read_json(bindings_path) if bindings_path.exists() else {"bindings": []}
    tools = read_json(tools_path) if tools_path.exists() else {"tools": []}
    try:
        from site_agent.core.config_versioning import build_config_snapshot

        config_snapshot = build_config_snapshot(args.profile, snapshot["profile_id"], snapshot["run_id"], snapshot, schema, bindings, tools)
    except Exception:
        config_snapshot = build_snapshot(args.profile, snapshot["profile_id"], snapshot["run_id"], snapshot, schema, bindings, tools)

    init_repo(args.repo, args.profile)
    write_snapshot(args.repo, config_snapshot)
    if args.commit or args.tag:
        commit_and_tag(args.repo, args.tag)
    print(json.dumps({"repo": str(args.repo), "settings": len(config_snapshot["settings"]), "snapshot_id": config_snapshot["id"], "tag": args.tag}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
