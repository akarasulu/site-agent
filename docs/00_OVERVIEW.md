# Overview

`site-agent` is a generic, evidence-backed website interaction mapper. It
creates target profiles, crawls authenticated browser applications, extracts
pages, forms, fields, actions, and navigation paths, maps UI evidence to
domain concepts, and generates stable automation surfaces.

The reusable engine lives in `site_agent/`. Target-specific knowledge belongs
in profile directories, generated adapters, and user-owned output artifacts.

## Project Identity

| Item | Current value |
| --- | --- |
| Python package | `site-agent` |
| Console script | `site-agent` |
| Package metadata version | `1.10.0` in `pyproject.toml` |
| Runtime package version | `1.10.0` in `site_agent/__init__.py` |
| Supported Python | `>=3.11` |
| Default browser runtime | Playwright Chromium |
| Optional crawl backend | Crawl4AI `0.8.9` |

Versioned local checkpoints from `v1.2.0` through `v1.8.0` add the
research-backed crawl cache, page graph, adaptive gain scoring, drift reuse,
workflow hardening, and documentation constraint-mining layers.
Checkpoint `v1.9.0` refreshes the developer documentation and research report
index around those implementation threads.
Checkpoint `v1.10.0` makes generated MCP builds synchronize the Python API
execution layer by default.

## Product Goal

The project is designed to help developers and operators automate web UIs
without exposing raw selectors as public contracts. A successful profile run
should produce:

* a crawl snapshot of reachable pages, forms, fields, transitions, and dynamic
  interaction flows,
* an ontology and mapped schema backed by UI and documentation evidence,
* generated Python API methods with typed arguments and risk metadata,
* generated MCP tools with stable semantic names and adapter bindings,
* generated Ansible modules when read/write evidence supports idempotence,
* deterministic configuration snapshots and restore plans for user-owned
  settings repositories,
* validation, drift, debug, quality, and packaging reports.

## Non-Goals

The core package must not become a target-specific automation client.

* Do not hardcode product-specific labels or workflows in reusable modules.
* Do not commit generated target API, MCP, or Ansible packages as core logic.
* Do not expose Playwright selectors, cookies, storage state, or credentials in
  public API surfaces.
* Do not treat AI output as authoritative without captured evidence.
* Do not apply high-risk or destructive UI changes without explicit policy and
  confirmation gates.

## Primary Workflow

```bash
site-agent profile init --name my-site --base-url https://example.com
site-agent auth setup --profile my-site
site-agent crawl run --profile my-site
site-agent schema review --profile my-site
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent mcp serve --profile my-site
site-agent ansible build --profile my-site
site-agent config save --profile my-site --repo ../my-site-settings
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent quality check --profile my-site
site-agent package build --profile my-site
```

Every command should print the next useful command. Destructive operations
remain dry-run or review-gated unless profile risk policy and CLI flags allow
apply mode.

## Documentation Suite

This documentation suite is the engineering map for the repository:

| Document | Purpose |
| --- | --- |
| [Architecture](01_ARCHITECTURE.md) | System design, data flow, and component boundaries. |
| [Technical Inventory](02_TECHNICAL_INVENTORY.md) | CLI, modules, schemas, scripts, fixtures, workflows, and artifacts. |
| [Development Log](03_DEVELOPMENT_LOG.md) | Chronological architectural decisions, sprint checkpoints, and validation evidence. |
| [Known Limitations](04_KNOWN_LIMITATIONS.md) | Current issues, constraints, and residual risks. |
| [Roadmap](05_ROADMAP.md) | Completed work, planned phases, and future milestones. |
| [Learning Guide](06_LEARNING_GUIDE.md) | Developer learning path from first run to advanced integration. |
| [Execution Guide](07_EXECUTION_GUIDE.md) | Installation, environment variables, run commands, and validation. |
| [Troubleshooting](08_TROUBLESHOOTING.md) | Common failures and actionable fixes. |
| [Validation Checklist](09_VALIDATION_CHECKLIST.md) | Manual and automated checks for project readiness. |
| [Final Report](10_FINAL_REPORT.md) | Current state summary, evidence, metrics, and remaining risks. |
| [Research Reports](research/README.md) | Paper-by-paper crawler technique summaries and implementation mapping. |

Additional design notes live under `contracts/`, and release-specific packaging
notes live in [Release And Packaging](release.md).
