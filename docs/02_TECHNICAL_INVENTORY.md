# Technical Inventory

This inventory maps the repository's developer-facing interfaces, modules,
schemas, fixtures, scripts, generated artifacts, and validation surfaces.

## Package And Runtime

| Item | Location | Notes |
| --- | --- | --- |
| Package metadata | `pyproject.toml` | `site-agent` version `1.15.0`; console script maps to `site_agent.cli:main`. |
| Runtime version | `site_agent/__init__.py` | `__version__ = "1.15.0"`. |
| Python support | `pyproject.toml` | `>=3.11`; classifiers list 3.11, 3.12, and 3.13. |
| Optional crawl dependencies | `pyproject.toml` | `playwright>=1.49`, `crawl4ai==0.8.9`. |
| Development dependencies | `pyproject.toml` | `pytest`, `pytest-cov`, `build`, `twine`. |
| Docker runtime | `Dockerfile` | Installs `site-agent[crawl]`, Playwright Chromium, and uses `site-agent` as entrypoint. |

## CLI Command Inventory

The CLI is implemented in `site_agent/cli.py`.

| Command | Subcommands | Primary purpose |
| --- | --- | --- |
| `site-agent profile` | `init`, `import-example` | Create or import target profiles. |
| `site-agent auth` | `setup` | Store auth strategy metadata and environment-variable references. |
| `site-agent docs` | `discover`, `build` | Run AI-assisted documentation discovery and generate OpenAPI, Postman, quickstart, Python, MCP, Ansible, and API reference artifacts for a profile. |
| `site-agent crawl` | `run`, `collect`, `inventory`, `plan`, `compare`, `merge` | Crawl targets, collect rendered states, build site trees, plan follow-up crawls, compare and merge snapshots. |
| `site-agent schema` | `review`, `queue`, `approve`, `reject`, `edit` | Align UI elements to ontology and manage review decisions. |
| `site-agent api` | `build`, `serve` | Generate a typed Python API package and serve generated methods over a local HTTP bridge. |
| `site-agent mcp` | `build`, `serve`, `call`, `import`, `diff`, `refresh-adapter` | Generate, serve, call, import, compare, and refresh MCP packages; `build` also syncs the generated Python API execution layer. |
| `site-agent ansible` | `build` | Generate an Ansible collection from synthesized tools and API spec. |
| `site-agent explorer` | `build`, `serve` | Build and serve a generated API portal with Use, Automate, Audit, and Debug modes, Swagger/Postman/docs links, operation examples, and a resizable audit view. |
| `site-agent drift` | `check` | Compare latest crawl snapshots for UI drift. |
| `site-agent ai` | `analyze` | Build an AI analysis report for a profile. |
| `site-agent debug` | `report` | Explain state classification, evidence coverage, and mapping gaps. |
| `site-agent actions` | `report` | Summarize form and action candidates from a crawl snapshot. |
| `site-agent quality` | `check` | Run contract quality and quality gate checks. |
| `site-agent config` | `save`, `diff`, `restore-plan`, `restore-readiness`, `restore`, `coverage` | Snapshot settings, compare refs, plan restores, evaluate readiness, execute dry-run/apply restores, and measure config coverage. |
| `site-agent benchmark` | `run` | Run benchmark fixture profiles and compare expected metrics. |
| `site-agent package` | `build` | Build a public/private profile knowledge package and optional zip. |
| `site-agent doctor` | none | Check Python, optional dependencies, and browser readiness. |
| `site-agent install` | `browsers` | Install Playwright browser binaries. |
| `site-agent completion` | `bash`, `zsh`, `fish`, `complete` | Generate shell completion scripts. |

## CLI Option Highlights

| Command | Important options |
| --- | --- |
| `profile init` | `--name`, `--base-url` |
| `auth setup` | `--profile`, `--username-env`, `--password-env` |
| `docs discover` | `--profile`, `--product-hint`, `--max-sources` |
| `docs build` | `--profile`, `--api-bridge-url` |
| `crawl run` | `--profile`, `--url`, `--fixture-html`, `--fixture-site`, `--start-path`, `--research-product-hint`, `--refresh-ai-domain`, `--use-plan`, `--max-planned-labels`, `--probe-budget-seconds`, `--target-depth`, `--backend` |
| `crawl collect` | `--profile`, `--probe-budget-seconds`, `--target-depth`, `--max-states`, `--allow-incomplete` |
| `schema approve/reject/edit` | `--profile`, `--ui-element-id`, `--confidence`, `--note`; `edit` also requires `--canonical-name` |
| `api build` | `--profile`, `--no-action-tools`, `--no-page-tools` |
| `api serve` | `--profile`, `--host`, `--port`, `--auto-port` |
| `mcp build` | `--profile`, `--include-writes`, `--no-action-tools`, `--no-page-tools` |
| `mcp call` | `--profile`, `--tool`, `--args-json`, `--mode`, `--browser` |
| `mcp import` | `--profile`, `--target`, `--server-name`, `--project-dir`, `--python`, `--engine-dir`, `--config`, `--apply` |
| `config restore` | `--profile`, `--repo`, `--ref`, `--plan`, `--current-snapshot`, `--mode`, `--confirm`, `--verify-snapshot`, `--max-snapshot-age-minutes`, `--fail-on-error` |
| `benchmark run` | `--fixtures-root`, `--name-prefix`, `--fail-on-error` |
| `package build` | `--profile`, `--public-only`, `--no-zip` |

## Core Modules

| Module | Responsibility |
| --- | --- |
| `site_agent/core/models.py` | Dataclass contracts for evidence, ontology, UI elements, snapshots, mappings, tools, API specs, Ansible specs, and drift reports. |
| `site_agent/core/profiles.py` | Profile, auth, crawl, and risk policy dataclasses; profile init/import/load helpers. |
| `site_agent/core/storage.py` | JSON read/write helpers and latest-artifact lookup. |
| `site_agent/core/redact.py` | Redacts secrets, tokens, cookies, passwords, and configured patterns from snapshots and schema. |
| `site_agent/core/ingest/docs.py` | Loads ontology seeds, ingests profile docs, asks AI for terms, and writes ontology artifacts. |
| `site_agent/core/ai/backends.py` | AI protocol plus noop, fake, and OpenAI Responses backends. |
| `site_agent/core/ai/research.py` | Research session persistence and documentation/UI domain discovery artifacts. |
| `site_agent/core/ai/analyze.py` | AI analysis report generation. |
| `site_agent/core/crawl/playwright.py` | Playwright crawl, JS state graph discovery, form capture, flow probing, fixtures, and landing text sampling. |
| `site_agent/core/crawl/crawl4ai_backend.py` | Crawl4AI backend adapter normalized to `CrawlSnapshot`. |
| `site_agent/core/extract/html.py` | Static HTML interaction parser for forms, elements, transitions, and evidence. |
| `site_agent/core/inventory.py` | Browser site-tree inventory with ontology-weighted text signals. |
| `site_agent/core/evidence_cache.py` | Selector-independent page-family cache, template signatures, text/rendered hashes, and cache diffs. |
| `site_agent/core/page_graph.py` | Page graph, visual block grouping, repeated structure detection, and coverage-preservation label projection. |
| `site_agent/core/crawl_gain.py` | Adaptive crawl candidate scoring from missing terms, cache discoveries, changed content, preservation states, and crawl memory. |
| `site_agent/core/plan.py` | Missing-term analysis, gain-aware follow-up crawl plan generation, and research-session planning metadata. |
| `site_agent/core/merge.py` | Merge multiple crawl snapshots and write merge reports. |
| `site_agent/core/align/lexical.py` | Lexical and AI-assisted UI-to-domain alignment. |
| `site_agent/core/review.py` | Review queue, approve/reject/edit operations, and reviewed schema writing. |
| `site_agent/core/form_classify.py` | Heuristic and AI form purpose classification. |
| `site_agent/core/actions.py` | Form action inventory and risk classification. |
| `site_agent/core/synthesize/capabilities.py` | Canonical capability projection and semantic name normalization. |
| `site_agent/core/synthesize/mcp.py` | MCP tool, page tool, form tool, flow tool, and adapter binding synthesis. |
| `site_agent/core/synthesize/api.py` | Generated Python API package synthesis. |
| `site_agent/core/synthesize/ansible.py` | Generated Ansible collection synthesis. |
| `site_agent/core/synthesize/contracts.py` | MCP contract generation and breaking-change diffing. |
| `site_agent/core/synthesize/docs.py` | Generated OpenAPI, Postman, quickstart, Python, MCP, Ansible, and API reference documentation bundle synthesis. |
| `site_agent/core/synthesize/http_api.py` | Local HTTP API bridge for generated methods, OpenAPI, and Postman execution. |
| `site_agent/core/synthesize/mcp_import.py` | MCP client config rendering and Codex config block installation. |
| `site_agent/core/synthesize/runtime.py` | Generated tool runtime, browser-backed staged actions, MCP JSON-RPC handling, and stdio serving. |
| `site_agent/core/config_versioning.py` | Settings repo init, config snapshot, diff, restore plan, readiness, restore execution, and verification. |
| `site_agent/core/config_coverage.py` | Configuration coverage score and gap report. |
| `site_agent/core/drift/check.py` | Snapshot-to-snapshot selector drift report. |
| `site_agent/core/drift/reuse.py` | Adapter reuse analysis for selector changes that preserve semantics, state path, and visual position. |
| `site_agent/core/quality.py` | Contract quality, coverage comparison, crawl memory, and quality gate reports. |
| `site_agent/core/debug.py` | Debug report for states, evidence coverage, and ontology gaps. |
| `site_agent/core/explorer.py` | Static generated API portal and audit explorer data/HTML writer, including Swagger and artifact publishing. |
| `site_agent/core/package.py` | Profile knowledge package assembly, RAG chunks, checksums, and zip bundles. |
| `site_agent/core/doctor.py` | Local dependency and Playwright readiness checks. |
| `site_agent/core/completion.py` | Shell completion generation and dynamic profile-name completion. |

## Contract And Schema Files

| Path | Purpose |
| --- | --- |
| `contracts/config-versioning-design.md` | Design for settings snapshots, diffs, restore planning, and restore apply guardrails. |
| `contracts/generated-automation-surfaces.md` | Design for Python API, MCP, and Ansible synthesis from approved schema. |
| `contracts/interaction-flow-design.md` | Design for dynamic add/create/edit/delete flow discovery. |
| `contracts/research-technique-implementation-plan.md` | Sprint plan mapping crawler research threads into cache, visual graph, gain scoring, drift, and documentation mining work. |
| `contracts/schemas/crawl-snapshot.schema.json` | JSON schema for crawl snapshot artifacts. |
| `contracts/schemas/mapped-schema.schema.json` | JSON schema for mapped schema artifacts. |
| `contracts/schemas/tool-spec.schema.json` | JSON schema for generated MCP tool specs. |
| `contracts/schemas/python-api-spec.schema.json` | JSON schema for generated Python API specs. |
| `contracts/schemas/ansible-collection-spec.schema.json` | JSON schema for generated Ansible collection specs. |
| `contracts/schemas/config-snapshot.schema.json` | JSON schema for configuration snapshot artifacts. |
| `contracts/schemas/config-coverage-report.schema.json` | JSON schema for configuration coverage reports. |
| `contracts/schemas/restore-plan.schema.json` | JSON schema for restore plan artifacts. |

## Scripts

| Script | Purpose |
| --- | --- |
| `scripts/install-shell-commands.sh` | Install a user-local `site-agent` command, optional Playwright Chromium, and shell completions. |
| `scripts/run-mock-e2e.sh` | Dependency-light fixture flow through profile, auth, crawl, schema, debug, plan, merge, MCP, actions, quality, and drift. |
| `scripts/run-mock-generated-surfaces.sh` | Full generated surface smoke flow: API, MCP, Ansible, config save, coverage, quality, drift, and package. |
| `scripts/run-mock-staged-actions-e2e.sh` | Browser-backed staged action apply test against the mock app container. |
| `scripts/run-mock-container.sh` | Build and run the OpsBoard mock app container. |
| `scripts/run-openai-ai-smoke.sh` | Bounded OpenAI backend smoke test for term extraction, alignment, field/action classification, and research. |
| `scripts/run-router-integration.sh` | Opt-in live router read-only integration workflow using the ZTE example profile; builds the explorer and sanitized MCP smoke reports. |
| `scripts/run-router-port-forward-live-test.sh` | Guarded live router staged write test wrapper. |
| `scripts/router_port_forward_live_check.py` | Playwright routine for guarded port-forwarding plan/apply/debug/cleanup checks. |
| `scripts/zte-router-smoke.sh` | Curl-based ZTE router login smoke test. |
| `scripts/export-config-snapshot.py` | Legacy/standalone config snapshot export helper backed by core config versioning when available. |

## Fixtures And Examples

| Path | Purpose |
| --- | --- |
| `profiles/fixtures/mock_app/` | Product-agnostic OpsBoard app with static pages, docs, ontology seed, Dockerfile, and FastAPI runtime. |
| `profiles/fixtures/benchmark_pack/` | Four benchmark profile types: docs site, workflow dashboard, settings admin, and staged dialog. |
| `profiles/examples/zte-router/` | External validation profile for a local ZTE router UI; not core behavior. |

The current benchmark output in `output/benchmark-pack-report.json` reports all
four benchmark profiles passing their expected page, form, tool, mapping, and
contract-quality thresholds.

## CI And Distribution

| File | Purpose |
| --- | --- |
| `.github/workflows/ci.yml` | Runs tests with coverage on Python 3.11 and 3.12 and builds the Python distribution. |
| `.github/workflows/docker.yml` | Builds and publishes `ghcr.io/akarasulu/site-agent` on push/tag. |
| `.github/workflows/publish-pypi.yml` | Builds and publishes to PyPI through trusted publishing on release. |
| `Dockerfile` | Repeatable crawl/runtime image. |
| `docs/release.md` | Packaging, TestPyPI, PyPI, Docker, and generated-target delivery notes. |

## Generated Artifact Inventory

| Artifact | Producer |
| --- | --- |
| `output/<profile>/ontology/ontology.json` | `site-agent crawl run` or ontology ingestion. |
| `output/<profile>/reports/site-tree-*.json` | `site-agent crawl run` and `site-agent crawl inventory`. |
| `output/<profile>/reports/evidence-cache-*.json` | `site-agent crawl run`, `crawl collect`, `crawl compare`, and `crawl plan`. |
| `output/<profile>/crawl/snapshot-*.json` | `site-agent crawl run`, `collect`, or `merge`. |
| `output/<profile>/schema/mapped-schema-*.json` | `site-agent schema review` and review decisions. |
| `output/<profile>/mcp/tools.json` | `site-agent mcp build`. |
| `output/<profile>/mcp/adapter.bindings.json` | `site-agent mcp build` and `refresh-adapter`. |
| `output/<profile>/mcp/contract.json` | `site-agent mcp build`. |
| `output/<profile>/api/` | `site-agent mcp build` and `site-agent api build`. |
| `output/<profile>/ansible/` | `site-agent ansible build`. |
| `output/<profile>/docs/openapi.json` | `site-agent docs build`, `site-agent mcp build`, `site-agent api build`, and `site-agent ansible build`. |
| `output/<profile>/docs/python-api.md` | `site-agent docs build`, `site-agent mcp build`, `site-agent api build`, and `site-agent ansible build`. |
| `output/<profile>/postman/collection.json` | `site-agent docs build`, `site-agent mcp build`, `site-agent api build`, and `site-agent ansible build`. |
| `output/<profile>/explorer/` | `site-agent explorer build`; includes `index.html`, `swagger.html`, `explorer-data.json`, rendered artifact helpers, copied docs/Postman artifacts, and raw download links. |
| `output/<profile>/reports/*.json` | Debug, action, quality, coverage, AI, drift, collection, and package reports. |
| `output/<profile>/packages/` | `site-agent package build`. |
| `<settings-repo>/snapshots/latest.json` | `site-agent config save`. |
| `<settings-repo>/restore-plans/*.json` | `site-agent config restore-plan`. |
