# Development Log

This log records architecture-relevant project decisions visible from the
current repository state. It is not a full git history.

## Chronological Decisions

| Period | Decision or change | Evidence |
| --- | --- | --- |
| Foundation | Package the engine as `site-agent` with a `site-agent` console script and generic profile/output layout. | `pyproject.toml`, `site_agent/cli.py`, `site_agent/core/profiles.py` |
| Foundation | Model core artifacts as dataclasses before writing JSON outputs. | `site_agent/core/models.py`, `contracts/schemas/` |
| Crawl layer | Use Playwright as the primary browser runtime for JavaScript-heavy UIs and fixture crawls for deterministic tests. | `site_agent/core/crawl/playwright.py`, `scripts/run-mock-e2e.sh` |
| Crawl layer | Add optional Crawl4AI backend behind the same `CrawlSnapshot` contract. | `site_agent/core/crawl/crawl4ai_backend.py`, `README.md` |
| Domain grounding | Use profile ontology seeds and docs as first-class inputs; allow AI-assisted term extraction but keep evidence gates. | `site_agent/core/ingest/docs.py`, `site_agent/core/ai/backends.py` |
| Semantic layer | Split ready, review, and internal mappings by confidence band. | `site_agent/core/models.py`, `site_agent/core/align/lexical.py`, `site_agent/core/review.py` |
| Generated surfaces | Generate MCP tools, Python API package, and Ansible collection from shared `ToolSpec`-based capabilities. | `site_agent/core/synthesize/` |
| MCP runtime | Support standard MCP `Content-Length` framing and ignore notifications so clients can complete initialize and `tools/list`. | `site_agent/core/synthesize/runtime.py`, `docs/release.md` |
| Dynamic flows | Model add/create/new-item flows as `InteractionFlow` records and synthesize staged action tools. | `contracts/interaction-flow-design.md`, `site_agent/core/crawl/playwright.py`, `site_agent/core/synthesize/mcp.py` |
| Configuration versioning | Add deterministic settings snapshots, git-backed save/tag, diff, restore-plan, readiness, restore, and coverage commands. | `site_agent/core/config_versioning.py`, `site_agent/core/config_coverage.py` |
| Quality and drift | Add contract quality, coverage comparison, crawl memory, page graph, drift reports, and benchmark fixtures. | `site_agent/core/quality.py`, `site_agent/core/page_graph.py`, `site_agent/core/drift/reuse.py`, `profiles/fixtures/benchmark_pack/` |
| Packaging | Add Docker, PyPI workflow, shell command installer, and profile knowledge package builder. | `Dockerfile`, `.github/workflows/`, `scripts/install-shell-commands.sh`, `site_agent/core/package.py` |
| Research implementation | Add evidence cache, visual page graph, adaptive crawl gain scoring, cache/gain workflow wiring, workflow hardening, drift-aware adapter reuse, and documentation constraint mining. | `site_agent/core/evidence_cache.py`, `site_agent/core/page_graph.py`, `site_agent/core/crawl_gain.py`, `site_agent/core/drift/reuse.py`, `site_agent/core/ingest/docs.py`, `contracts/research-technique-implementation-plan.md` |
| Documentation | Refresh the full `docs/00_` through `docs/10_` engineering documentation suite and add research report discovery. | `docs/00_OVERVIEW.md` through `docs/10_FINAL_REPORT.md`, `docs/research/README.md` |
| Explorer and router validation | Restore generated explorer splitters for resizable/collapsible regions and refresh the live router integration harness around explorer builds and sanitized MCP smoke reports. | `site_agent/core/explorer.py`, `tests/unit/test_explorer.py`, `scripts/run-router-integration.sh` |
| Generated API docs | Generate OpenAPI 3.1, Postman collection/environment, and API reference artifacts from approved profile tools and API specs. | `site_agent/core/synthesize/docs.py`, `tests/unit/test_generated_specs.py` |
| Local API bridge | Serve generated API methods over local HTTP for Swagger UI and Postman while delegating to the generated runtime. | `site_agent/core/synthesize/http_api.py`, `tests/unit/test_http_api_bridge.py` |
| Explorer API portal | Make the generated explorer default to consumer docs, Swagger, Postman, Python, MCP, and Ansible paths while keeping the dense audit view for reviewers. | `site_agent/core/explorer.py`, `site_agent/core/synthesize/docs.py`, `tests/unit/test_explorer.py` |

## Recent Sprint Checkpoints

| Tag | Focus |
| --- | --- |
| `v1.2.0` | Research-backed evidence cache and page-family signatures. |
| `v1.3.0` | Visual page structure graphing and repeated block detection. |
| `v1.4.0` | Adaptive crawl gain scoring as a reusable primitive. |
| `v1.5.0` | Cache/gain wiring into crawl, compare, and plan workflows. |
| `v1.6.0` | Crawl workflow provenance hardening and bounded optional AI enrichment. |
| `v1.7.0` | Drift-aware adapter reuse analysis. |
| `v1.8.0` | Documentation constraint, unit, and operation mining into ontology ingestion. |
| `v1.9.0` | Developer documentation and research report refresh. |
| `v1.10.0` | MCP build synchronizes the generated Python API execution layer. |
| `v1.11.0` | Generated explorer splitters and router validation harness refresh. |
| `v1.12.0` | Generated OpenAPI/Postman/API reference documentation bundle. |
| `v1.13.0` | Local HTTP API bridge for generated method execution. |
| `v1.14.0` | Consumer-facing generated API explorer portal and packaged docs/Postman artifacts. |

## Recent Validation Evidence

Existing generated output under `output/` includes a benchmark pack report with
four passing fixture profiles:

| Fixture | Pages | Forms | Tools | Ready mappings | Contract quality |
| --- | ---: | ---: | ---: | ---: | --- |
| `docs_site` | 3 | 1 | 3 | 2 | passed |
| `workflow_dashboard` | 3 | 3 | 6 | 3 | passed |
| `settings_admin` | 3 | 3 | 6 | 3 | passed |
| `staged_dialog` | 3 | 2 | 5 | 3 | passed |

The report was generated on June 14, 2026 according to contract-quality
artifacts under `output/benchmark-*/reports/`.

## Documentation Refresh Scope

This pass refreshes the full developer documentation suite:

* overview,
* architecture,
* technical inventory,
* development log,
* limitations,
* roadmap,
* learning path,
* execution guide,
* troubleshooting,
* validation checklist,
* final report.

The pass also updated the README documentation index so the full suite is
discoverable from the repository entry point.
