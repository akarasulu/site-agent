# Configuration Versioning Design

## Goal

Provide a generic way to snapshot, diff, and restore settings exposed through a web UI.
The feature must work for routers, dashboards, admin panels, SaaS tools, and other authenticated web applications without hardcoding product-specific logic in core.

## User Workflow

```bash
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent config diff --profile my-site --repo ../my-site-settings --ref main
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref known-good
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref known-good --apply --confirm
site-agent config restore --profile my-site --repo ../my-site-settings --ref known-good --mode dry-run
```

Save, coverage, diff, and restore planning are read-only. Restore is dry-run by default.

## Settings Repository Layout

The settings repository is a separate git repository owned by the user, not part of `site-agent`.

```text
my-site-settings/
  README.md
  site-agent-settings.json
  snapshots/
    latest.json
    2026-05-25T12-30-00Z-run_abcd1234.json
  normalized/
    settings.json
    settings.yaml
  restore-plans/
    restore-known-good-to-current-plan.json
  reports/
    snapshot-run_abcd1234.json
    diff-known-good-to-current.json
    restore-run_efgh5678.json
```

`normalized/settings.json` is byte-stable for identical UI state, so normal git diffs are useful.
Timestamped files keep immutable audit history.

## Snapshot Model

`ConfigSnapshot`:

```json
{
  "schema_version": "0.1.0",
  "id": "cfgsnap_...",
  "timestamp": "2026-05-25T12:30:00Z",
  "profile_id": "profile_...",
  "profile_name": "my-site",
  "source_run_id": "run_...",
  "settings": [
    {
      "id": "cfg_...",
      "canonical_name": "alert email",
      "path": ["workspace settings", "notification policy", "alert email"],
      "value": "ops@example.test",
      "value_type": "string",
      "source_tool": "get_alert_email",
      "restore_tool": "save_settings",
      "restore_arg": "alert_email",
      "restore_binding": {
        "tool_name": "save_settings",
        "arg_name": "alert_email",
        "risk_level": "medium",
        "confidence": 0.91
      },
      "evidence_ids": ["ev_ui", "ev_doc"],
      "confidence": 0.91,
      "sensitivity": "operator_managed",
      "restorable": true
    }
  ],
  "value_policy": "preserve-captured-values"
}
```

The stable identity of a setting is:

```text
profile_id + normalized path + canonical_name
```

Raw selectors are private adapter details and must not be used as public setting identities.

## Snapshot Sources

Settings can be collected from:

- `get_*` canonical read tools.
- `ui_page` read tools for discovered read-only/status values.
- Form fields whose current values are observable after navigation.
- Staged item/list workflows when rows are readable and item identity fields are known.

Each setting must have at least UI evidence.
Documentation evidence improves confidence but is not required for UI-backed settings.

## Value Preservation

Configuration snapshots preserve captured values by default. The operator owns sensitivity handling for the settings repository and should use private remotes, filesystem permissions, git-crypt, sops, or an equivalent control when saved values are sensitive. Site-agent should avoid printing credential values in routine command output, but it should not rewrite configuration snapshot values.

## Diff

`site-agent config diff` compares current UI state to a branch, tag, or commit.

Diff categories:

- `added`: present now, absent in ref.
- `removed`: present in ref, absent now.
- `changed`: same setting identity, different normalized value.
- `unchanged`: same setting identity and value.
- `non_restorable`: changed but no approved restore tool or safe action path exists.

The diff output must include evidence IDs and confidence for each changed setting.

## Restore Planning

Restore planning maps changed settings from a target ref to MCP write/staged-action tools.

Planning rules:

- Use canonical setting identity, not selectors.
- Prefer specific approved tools over generic form submits.
- Preserve tool contracts across UI drift when semantic identity is unchanged.
- Group settings by shared restore tool when the UI naturally saves them together.
- Mark missing tools, low-confidence mappings, high-risk changes, and high-risk values as review-required.
- Produce a plan even when some settings are non-restorable; do not silently drop them.

`RestorePlan`:

```json
{
  "id": "restore_...",
  "target_ref": "known-good",
  "current_snapshot_id": "cfgsnap_current",
  "rollback_snapshot_id": "cfgsnap_before_restore",
  "risk_summary": {"low": 3, "medium": 2, "high": 1},
  "requires_review": true,
  "steps": [
    {
      "setting_id": "cfg_alert_email",
      "setting_ids": ["cfg_alert_email", "cfg_retention_days"],
      "tool_name": "save_settings",
      "args": {"alert_email": "ops@example.test", "retention_days": "30", "dry_run": true, "confirm": false},
      "restore_args": {"cfg_alert_email": "alert_email", "cfg_retention_days": "retention_days"},
      "previous_value": {"cfg_alert_email": "alerts@example.test", "cfg_retention_days": "60"},
      "desired_value": {"cfg_alert_email": "ops@example.test", "cfg_retention_days": "30"},
      "risk_level": "medium",
      "evidence_ids": ["ev_ui", "ev_doc"],
      "status": "planned"
    }
  ]
}
```

## Restore Apply

Restore apply executes only after:

- a fresh pre-restore snapshot is written and committed;
- host allowlists pass;
- every step has an approved tool binding;
- risk policy allows the operation;
- caller passes `--mode apply --confirm`;
- restore readiness checks pass, including clean settings repository and fresh current snapshot;
- high-risk steps have profile-specific approval or remain skipped.

Apply writes `reports/restore-<run_id>.json` with:

- attempted steps;
- applied steps;
- skipped steps;
- failures;
- post-restore verification;
- rollback snapshot ref.
- recovery metadata showing executed and skipped setting IDs when a grouped step fails.

## Git Semantics

Supported refs:

- branch names;
- tags;
- commit SHAs;
- any valid `git rev-parse` target inside the settings repository.

Core commands should use non-interactive git commands only:

- `git init`
- `git status --porcelain`
- `git add`
- `git commit`
- `git rev-parse`
- `git show <ref>:normalized/settings.json`
- `git diff -- normalized/settings.json`

The settings repository may be remote-backed, but push/pull is user-controlled.

## MCP Exposure

Generated MCP packages may expose:

- `get_configuration_snapshot`
- `compare_configuration_snapshot`
- `plan_configuration_restore`

Actual restore apply is high-impact and should remain confirmation-gated.
Agent clients may request a restore plan, but apply must respect the same profile risk policy as direct CLI restore.

## Product-Agnostic Boundary

The core knows only:

- pages;
- canonical concepts;
- settings;
- tools;
- evidence;
- risk.

Target-specific grouping, naming hints, and risk exceptions belong in profiles.
Router backup/restore is one validation profile, not core behavior.
