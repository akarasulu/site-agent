from __future__ import annotations

import re
import subprocess
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from site_agent.core.storage import read_json, write_json


def slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_") or "setting"


def git(repo: Path, *args: str) -> str:
    result = subprocess.run(["git", "-C", str(repo), *args], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return result.stdout.strip()


def init_settings_repo(repo: Path, profile_name: str) -> None:
    repo.mkdir(parents=True, exist_ok=True)
    if not (repo / ".git").exists():
        subprocess.run(["git", "init", str(repo)], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        subprocess.run(["git", "-C", str(repo), "config", "user.email", "site-agent@example.invalid"], check=True, text=True)
        subprocess.run(["git", "-C", str(repo), "config", "user.name", "site-agent"], check=True, text=True)
    readme = repo / "README.md"
    if not readme.exists():
        readme.write_text(
            f"# {profile_name} settings\n\n"
            "This repository stores deterministic web UI configuration snapshots exported by site-agent.\n"
            "Snapshots preserve captured values. Protect this repository appropriately with private storage, git-crypt, sops, or equivalent controls.\n",
            encoding="utf-8",
        )


def schema_mappings(schema: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {item["ui_element_id"]: item for item in schema.get("mappings", []) if item.get("status") in {"ready", "review"}}


def build_tool_lookup(bindings: dict[str, Any]) -> dict[str, str]:
    lookup: dict[str, str] = {}
    for binding in bindings.get("bindings", []):
        adapter = binding.get("selector_action_bindings", {})
        element_id = adapter.get("ui_element_id")
        if element_id and adapter.get("action") == "read":
            lookup[element_id] = binding.get("tool_name")
    return lookup


def normalized_words(value: str) -> set[str]:
    return {part for part in re.split(r"[^a-z0-9]+", value.lower()) if part}


def arg_matches_setting(arg: str, label: str, canonical: str, path: list[str]) -> bool:
    arg_words = normalized_words(arg)
    haystack = normalized_words(" ".join([label, canonical, *path]))
    return bool(arg_words and (arg_words <= haystack or haystack <= arg_words or arg_words & haystack))


def restore_binding_for_element(
    element: dict[str, Any],
    canonical: str,
    path: list[str],
    tools: list[dict[str, Any]],
    bindings: dict[str, Any],
) -> dict[str, Any] | None:
    element_evidence = set(element.get("evidence_ids", []))
    label = str(element.get("label") or canonical)
    tool_by_name = {tool.get("name"): tool for tool in tools if tool.get("name")}
    candidates = []
    for binding in bindings.get("bindings", []):
        tool_name = binding.get("tool_name")
        tool = tool_by_name.get(tool_name)
        if not tool or tool.get("source_type") not in {"canonical_concept", "ui_form", "ui_flow"}:
            continue
        adapter = binding.get("selector_action_bindings", {})
        tool_evidence = set(tool.get("evidence_ids", []))
        if element_evidence and not (element_evidence & tool_evidence):
            continue
        for field in adapter.get("fields", []):
            arg = field.get("arg")
            if not arg:
                continue
            score = 0
            if field.get("ui_element_id") == element.get("id"):
                score += 5
            if arg_matches_setting(str(arg), label, canonical, path):
                score += 3
            if element_evidence & tool_evidence:
                score += 2
            if score:
                candidates.append(
                    {
                        "tool_name": tool_name,
                        "arg_name": str(arg),
                        "risk_level": tool.get("risk_level", "medium"),
                        "confidence": min(0.95, 0.55 + score * 0.08),
                        "reasoning_summary": "Matched setting to generated write tool by UI evidence and field/argument labels.",
                        "score": score,
                    }
                )
    if not candidates:
        return None
    candidates.sort(key=lambda item: (item["score"], item["confidence"]), reverse=True)
    selected = dict(candidates[0])
    selected.pop("score", None)
    return selected


def setting_from_element(
    element: dict[str, Any],
    mapping: dict[str, Any] | None,
    tool_by_element: dict[str, str],
    tools: list[dict[str, Any]],
    bindings: dict[str, Any],
) -> dict[str, Any] | None:
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
    restore_binding = restore_binding_for_element(element, canonical, path, tools, bindings)
    return {
        "id": f"cfg_{slug('/'.join(path))}",
        "canonical_name": canonical,
        "path": path,
        "value": value,
        "value_type": "string",
        "source_tool": tool_by_element.get(element["id"]),
        "restore_tool": (restore_binding or {}).get("tool_name"),
        "restore_arg": (restore_binding or {}).get("arg_name"),
        "restore_binding": restore_binding,
        "evidence_ids": sorted(set(element.get("evidence_ids", []) + (mapping or {}).get("evidence_ids", []))),
        "confidence": float((mapping or {}).get("confidence", 0.8)),
        "sensitivity": "operator_managed",
        "restorable": bool(restore_binding),
    }


def build_config_snapshot(
    profile_name: str,
    profile_id: str,
    source_run_id: str,
    snapshot: dict[str, Any],
    schema: dict[str, Any],
    bindings: dict[str, Any],
    tools: dict[str, Any] | list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    mappings = schema_mappings(schema)
    tool_by_element = build_tool_lookup(bindings)
    tool_items = tools.get("tools", []) if isinstance(tools, dict) else tools or []
    settings = []
    seen_ids = set()
    for element in snapshot.get("elements", []):
        setting = setting_from_element(element, mappings.get(element.get("id")), tool_by_element, tool_items, bindings)
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


def write_config_snapshot(repo: Path, snapshot: dict[str, Any]) -> None:
    safe_timestamp = snapshot["timestamp"].replace(":", "-")
    write_json(repo / "site-agent-settings.json", {"schema_version": "0.1.0", "profile_name": snapshot["profile_name"]})
    write_json(repo / "snapshots" / "latest.json", snapshot)
    write_json(repo / "snapshots" / f"{safe_timestamp}-{snapshot['source_run_id']}.json", snapshot)
    write_json(
        repo / "normalized" / "settings.json",
        {
            "schema_version": snapshot["schema_version"],
            "profile_name": snapshot["profile_name"],
            "settings": [
                {
                    "canonical_name": item["canonical_name"],
                    "path": item["path"],
                    "value": item["value"],
                    "sensitivity": item["sensitivity"],
                    "restorable": item["restorable"],
                    "restore_tool": item.get("restore_tool"),
                    "restore_arg": item.get("restore_arg"),
                }
                for item in snapshot["settings"]
            ],
        },
    )
    write_json(
        repo / "reports" / f"snapshot-{snapshot['source_run_id']}.json",
        {
            "snapshot_id": snapshot["id"],
            "settings": len(snapshot["settings"]),
            "source_run_id": snapshot["source_run_id"],
            "generated_at": snapshot["timestamp"],
        },
    )


def commit_and_tag(repo: Path, tag: str | None = None) -> bool:
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    status = git(repo, "status", "--porcelain")
    committed = False
    if status:
        subprocess.run(["git", "-C", str(repo), "commit", "-m", "Save configuration snapshot"], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        committed = True
    if tag:
        existing = subprocess.run(["git", "-C", str(repo), "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if existing.returncode == 0:
            raise RuntimeError(f"Tag already exists in settings repo: {tag}")
        subprocess.run(["git", "-C", str(repo), "tag", tag], check=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    return committed


def load_snapshot_at_ref(repo: Path, ref: str) -> dict[str, Any]:
    if ref in {"current", "latest", "worktree"}:
        return read_json(repo / "snapshots" / "latest.json")
    result = subprocess.run(
        ["git", "-C", str(repo), "show", f"{ref}:snapshots/latest.json"],
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    import json

    return json.loads(result.stdout)


def settings_by_key(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    keyed = {}
    for setting in snapshot.get("settings", []):
        key = str(setting.get("id") or "/".join(str(part) for part in setting.get("path", [])))
        keyed[key] = setting
    return keyed


def diff_config_snapshots(profile_name: str, baseline: dict[str, Any], current: dict[str, Any], baseline_ref: str = "baseline") -> dict[str, Any]:
    before = settings_by_key(baseline)
    after = settings_by_key(current)
    added = sorted(set(after) - set(before))
    removed = sorted(set(before) - set(after))
    changed = sorted(key for key in set(before) & set(after) if before[key].get("value") != after[key].get("value"))
    return {
        "schema_version": "0.1.0",
        "profile_name": profile_name,
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "baseline_ref": baseline_ref,
        "baseline_snapshot_id": baseline.get("id"),
        "current_snapshot_id": current.get("id"),
        "summary": {
            "added": len(added),
            "removed": len(removed),
            "changed": len(changed),
            "unchanged": len(set(before) & set(after)) - len(changed),
        },
        "added": [after[key] for key in added],
        "removed": [before[key] for key in removed],
        "changed": [{"setting_id": key, "before": before[key], "after": after[key]} for key in changed],
    }


def tool_by_name(tools: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {tool.get("name"): tool for tool in tools if tool.get("name")}


def build_restore_plan(profile_name: str, target_ref: str, target: dict[str, Any], current: dict[str, Any], tools: list[dict[str, Any]]) -> dict[str, Any]:
    desired = settings_by_key(target)
    actual = settings_by_key(current)
    tool_lookup = tool_by_name(tools)
    risk_counts = Counter({"low": 0, "medium": 0, "high": 0})
    grouped: dict[str, dict[str, Any]] = {}
    non_restorable = []
    changed_keys = sorted(key for key in set(desired) & set(actual) if desired[key].get("value") != actual[key].get("value"))
    for key in changed_keys:
        target_setting = desired[key]
        current_setting = actual[key]
        tool_name = target_setting.get("restore_tool") or current_setting.get("restore_tool")
        tool = tool_lookup.get(tool_name)
        if not tool_name or not tool:
            non_restorable.append(
                {
                    "setting_id": key,
                    "current_value": current_setting.get("value"),
                    "desired_value": target_setting.get("value"),
                    "reason": "No approved restore_tool is recorded for this setting.",
                    "evidence_ids": sorted(set(current_setting.get("evidence_ids", []) + target_setting.get("evidence_ids", []))),
                }
            )
            continue
        arg_name = str(target_setting.get("restore_arg") or current_setting.get("restore_arg") or slug(str(target_setting.get("canonical_name") or target_setting.get("path", ["value"])[-1])))
        group_key = tool_name
        group = grouped.setdefault(
            group_key,
            {
                "setting_id": key,
                "setting_ids": [],
                "tool_name": tool_name,
                "args": {"dry_run": True, "confirm": False},
                "previous_value": {},
                "desired_value": {},
                "risk_level": tool.get("risk_level", "medium"),
                "evidence_ids": [],
                "status": "review_required" if tool.get("risk_level", "medium") in {"medium", "high"} else "planned",
                "restore_args": {},
            },
        )
        group["setting_ids"].append(key)
        group["args"][arg_name] = target_setting.get("value")
        group["previous_value"][key] = current_setting.get("value")
        group["desired_value"][key] = target_setting.get("value")
        group["restore_args"][key] = arg_name
        group["evidence_ids"] = sorted(set(group["evidence_ids"] + current_setting.get("evidence_ids", []) + target_setting.get("evidence_ids", []) + tool.get("evidence_ids", [])))
    steps = list(grouped.values())
    for step in steps:
        risk_counts[step["risk_level"]] += 1
    return {
        "schema_version": "0.1.0",
        "id": f"restore_{slug(profile_name)}_{slug(target_ref)}_{datetime.now(UTC).strftime('%Y%m%d%H%M%S')}",
        "target_ref": target_ref,
        "current_snapshot_id": current.get("id"),
        "rollback_snapshot_id": current.get("id"),
        "desired_snapshot_id": target.get("id"),
        "steps": steps,
        "non_restorable": non_restorable,
        "risk_summary": {level: risk_counts[level] for level in ("low", "medium", "high")},
        "requires_review": bool(non_restorable or any(step["risk_level"] in {"medium", "high"} for step in steps)),
        "mode": "dry-run-plan-only",
    }


def parse_timestamp(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def build_restore_readiness_report(
    profile_name: str,
    plan: dict[str, Any],
    settings_repo: Path | None = None,
    current_snapshot: dict[str, Any] | None = None,
    latest_run_id: str | None = None,
    max_snapshot_age_minutes: int = 30,
    apply_requested: bool = False,
    profile_write_mode: str = "dry-run",
    confirm: bool = False,
) -> dict[str, Any]:
    checks = []

    def add_check(name: str, passed: bool, severity: str, summary: str) -> None:
        checks.append({"name": name, "passed": passed, "severity": severity, "summary": summary})

    repo_clean = True
    if settings_repo:
        repo_clean = not bool(git(settings_repo, "status", "--porcelain"))
        add_check("settings_repo_clean", repo_clean, "error", "Settings repository is clean." if repo_clean else "Settings repository has uncommitted changes.")
    else:
        add_check("settings_repo_clean", not apply_requested, "error", "Settings repository was not supplied; apply mode requires it.")

    target_ref_exists = bool(plan.get("target_ref"))
    add_check("target_ref_exists", target_ref_exists, "error", "Restore plan includes a target ref." if target_ref_exists else "Restore plan is missing target_ref.")

    steps = plan.get("steps", [])
    grouped_steps = sum(1 for step in steps if len(step.get("setting_ids", [])) > 1)
    add_check("steps_available", bool(steps), "warning", f"Restore plan has {len(steps)} executable step(s).")
    add_check("grouped_steps_reported", True, "info", f"Restore plan has {grouped_steps} grouped multi-setting step(s).")
    add_check(
        "non_restorable_review",
        not plan.get("non_restorable"),
        "warning",
        f"{len(plan.get('non_restorable', []))} setting(s) are non-restorable and require manual handling.",
    )

    risk_summary = plan.get("risk_summary", {})
    high_risk = int(risk_summary.get("high", 0) or 0)
    add_check("high_risk_block", high_risk == 0, "error", f"High-risk restore steps: {high_risk}.")
    add_check("confirmation", (not apply_requested) or confirm, "error", "Confirmation supplied." if confirm else "Apply mode requires explicit confirmation.")
    add_check(
        "profile_write_mode",
        (not apply_requested) or profile_write_mode == "apply",
        "error",
        f"Profile write mode is {profile_write_mode}; apply requires apply.",
    )
    add_check("rollback_snapshot", bool(plan.get("rollback_snapshot_id")), "error", "Rollback snapshot is recorded." if plan.get("rollback_snapshot_id") else "Rollback snapshot is missing.")

    freshness_passed = True
    if current_snapshot:
        timestamp = parse_timestamp(current_snapshot.get("timestamp"))
        age_minutes = None
        if timestamp:
            age_minutes = (datetime.now(UTC) - timestamp.astimezone(UTC)).total_seconds() / 60
            freshness_passed = age_minutes <= max_snapshot_age_minutes
        if latest_run_id and current_snapshot.get("source_run_id") != latest_run_id:
            freshness_passed = False
        age_text = f"{age_minutes:.1f} minute(s)" if age_minutes is not None else "unknown age"
        add_check(
            "fresh_current_snapshot",
            freshness_passed,
            "error",
            f"Current config snapshot is {age_text}; source_run_id={current_snapshot.get('source_run_id')}.",
        )
    else:
        add_check("fresh_current_snapshot", not apply_requested, "error", "Current config snapshot was not supplied; apply mode requires freshness checks.")

    errors = [check for check in checks if check["severity"] == "error" and not check["passed"]]
    warnings = [check for check in checks if check["severity"] == "warning" and not check["passed"]]
    return {
        "schema_version": "0.1.0",
        "profile_name": profile_name,
        "restore_plan_id": plan.get("id"),
        "target_ref": plan.get("target_ref"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "ready_for_apply": not errors,
        "checks": checks,
        "risk_summary": risk_summary,
        "steps": len(steps),
        "grouped_steps": grouped_steps,
        "non_restorable": len(plan.get("non_restorable", [])),
        "errors": errors,
        "warnings": warnings,
        "verification_plan": {
            "required_after_apply": True,
            "expected_target_snapshot_id": plan.get("desired_snapshot_id"),
            "compare_after_snapshot_to_target_ref": plan.get("target_ref"),
        },
    }


def execute_restore_plan(package_dir: Path, plan: dict[str, Any], mode: str = "dry-run", confirm: bool = False) -> dict[str, Any]:
    from site_agent.core.synthesize.runtime import RuntimeErrorForTool, call_tool

    if mode not in {"dry-run", "apply"}:
        raise RuntimeError("Restore execution mode must be dry-run or apply.")
    results = []
    executed_steps = []
    skipped_steps = []
    for step in plan.get("steps", []):
        args = dict(step.get("args", {}))
        args["dry_run"] = mode != "apply"
        args["confirm"] = bool(confirm)
        try:
            response = call_tool(package_dir, step["tool_name"], args, mode=mode)
            results.append(
                {
                    "setting_id": step.get("setting_id"),
                    "setting_ids": step.get("setting_ids", [step.get("setting_id")]),
                    "tool_name": step.get("tool_name"),
                    "status": "dry_run" if mode != "apply" else response.get("status", "applied"),
                    "response": response,
                    "risk_level": step.get("risk_level"),
                }
            )
            executed_steps.append(step.get("setting_id"))
        except RuntimeErrorForTool as exc:
            results.append(
                {
                    "setting_id": step.get("setting_id"),
                    "setting_ids": step.get("setting_ids", [step.get("setting_id")]),
                    "tool_name": step.get("tool_name"),
                    "status": "failed",
                    "error": str(exc),
                    "risk_level": step.get("risk_level"),
                }
            )
            skipped_steps.extend(item.get("setting_id") for item in plan.get("steps", [])[len(results) :] if item.get("setting_id"))
            break
    failed = sum(1 for result in results if result["status"] == "failed")
    return {
        "schema_version": "0.1.0",
        "restore_plan_id": plan.get("id"),
        "target_ref": plan.get("target_ref"),
        "generated_at": datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "mode": mode,
        "summary": {
            "steps": len(results),
            "dry_run": sum(1 for result in results if result["status"] == "dry_run"),
            "applied": sum(1 for result in results if result["status"] == "applied"),
            "failed": failed,
            "non_restorable": len(plan.get("non_restorable", [])),
        },
        "results": results,
        "non_restorable": plan.get("non_restorable", []),
        "recovery": {
            "rollback_snapshot_id": plan.get("rollback_snapshot_id"),
            "target_ref": plan.get("target_ref"),
            "executed_setting_ids": [item for item in executed_steps if item],
            "skipped_setting_ids": [item for item in skipped_steps if item],
            "resume_recommendation": "Review failed step, refresh a configuration snapshot, then rebuild the restore plan before retrying.",
        },
    }


def verify_restore_snapshot(target: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    diff = diff_config_snapshots(str(target.get("profile_name") or after.get("profile_name") or "profile"), target, after, "restore-target")
    return {
        "verified": diff["summary"]["changed"] == 0 and diff["summary"]["removed"] == 0,
        "target_snapshot_id": target.get("id"),
        "after_snapshot_id": after.get("id"),
        "diff_summary": diff["summary"],
        "changed": diff["changed"],
        "removed": diff["removed"],
    }
