# Learning Guide

This guide helps a developer move from first checkout to advanced generated
automation workflows.

## 1. Understand The Mental Model

`site-agent` separates four things:

| Layer | What it contains |
| --- | --- |
| Core engine | Generic crawl, extraction, alignment, synthesis, config versioning, quality, and packaging modules. |
| Profile | Target base URL, host allowlist, auth references, crawl policy, ontology seed, docs, risk policy, and aliases. |
| Generated output | Profile-specific schema, tools, adapters, API package, MCP package, Ansible collection, reports, and knowledge bundle. |
| Settings repository | User-owned, versionable snapshots and restore plans for captured UI configuration. |

Public automation contracts use canonical concepts and evidence. Private
adapter files hold selectors and browser action bindings.

## 2. Install For Local Development

```bash
python -m pip install -e ".[crawl,dev]"
site-agent install browsers
site-agent doctor
```

For a user-local command without activating a checkout venv:

```bash
scripts/install-shell-commands.sh
```

## 3. Run The Fast Fixture Flow

The quickest way to learn the workflow without external credentials is the
mock fixture script:

```bash
scripts/run-mock-e2e.sh
```

This creates a temporary workspace, initializes a profile, crawls static fixture
HTML, reviews schema, creates debug reports, plans a second crawl, merges
snapshots, builds MCP tools, and runs quality and drift checks.

## 4. Generate All Automation Surfaces

Use the generated-surface smoke flow:

```bash
scripts/run-mock-generated-surfaces.sh
```

It creates:

* `output/opsboard/api/`,
* `output/opsboard/mcp/`,
* `output/opsboard/ansible/`,
* an `opsboard-settings` repository,
* quality and drift reports,
* a profile knowledge package.

Review the printed output paths and inspect `tools.json`, `api-spec.json`, and
`ansible-spec.json`.

## 5. Learn The Manual Workflow

For a new target profile:

```bash
site-agent profile init --name my-site --base-url https://example.com
site-agent auth setup --profile my-site \
  --username-env MY_SITE_USER \
  --password-env MY_SITE_PASSWORD
site-agent docs discover --profile my-site --product-hint "my site admin guide"
site-agent crawl run --profile my-site
site-agent schema review --profile my-site
site-agent schema queue --profile my-site
```

Approve or edit low-confidence mappings:

```bash
site-agent schema approve --profile my-site --ui-element-id ui_abc --confidence 0.9
site-agent schema edit --profile my-site --ui-element-id ui_def \
  --canonical-name "alert email" \
  --confidence 0.88
```

Then generate automation surfaces:

```bash
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent docs build --profile my-site
site-agent api serve --profile my-site
site-agent ansible build --profile my-site
site-agent explorer build --profile my-site
```

## 6. Connect MCP To Agent Clients

Emit standard MCP JSON:

```bash
site-agent mcp import --profile my-site --target json
```

Install a marked Codex block:

```bash
site-agent mcp import --profile my-site --target codex --apply
```

The generated MCP server is a local stdio process. It uses standard
`Content-Length` framing and can also support newline-delimited JSON probes.

## 7. Work With Configuration Snapshots

Create a user-owned settings repository:

```bash
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
```

Compare and plan restore:

```bash
site-agent config diff --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore --profile my-site --repo ../my-site-settings --ref v1 --mode dry-run
```

Only use apply mode after readiness checks pass and profile risk policy allows
write operations.

## 8. Learn The Codebase

Start with these files:

| File | Why it matters |
| --- | --- |
| `site_agent/cli.py` | Shows the end-to-end command orchestration. |
| `site_agent/core/models.py` | Defines the core data contracts. |
| `site_agent/core/profiles.py` | Defines profile, auth, crawl, and risk policy shape. |
| `site_agent/core/crawl/playwright.py` | Contains the primary browser crawl engine. |
| `site_agent/core/align/lexical.py` | Shows mapping confidence and AI-assisted alignment. |
| `site_agent/core/synthesize/capabilities.py` | Shows semantic tool normalization and capability projection. |
| `site_agent/core/synthesize/runtime.py` | Shows generated MCP runtime and apply-mode behavior. |
| `site_agent/core/config_versioning.py` | Shows settings snapshot, diff, restore plan, readiness, and restore execution. |

## 9. Use A Real Authenticated Site Carefully

For live sites:

* keep credentials in environment variables,
* verify host allowlists,
* start with read-only crawl and dry-run restore,
* review output before sharing,
* keep settings repositories private,
* run `quality check` and `config coverage` before trusting generated
  automation.

The ZTE router profile under `profiles/examples/zte-router/` is an external
validation profile. It is not core product logic and requires private network
access and credentials.
