# Roadmap

The roadmap follows the layered implementation model in `AGENTS.md` and the
current repository state.

## Completed Or Present

| Area | Current status |
| --- | --- |
| Project scaffolding | Python package, CLI entry point, Dockerfile, CI, PyPI publishing workflow, shell installer, and completion support exist. |
| Profile model | Profiles include base URL, host allowlist, auth references, crawl policy, risk policy, ontology seed path, docs path, and tool aliases. |
| Crawl and extraction | Playwright crawl, fixture crawl, Crawl4AI backend, static HTML extraction, JS state exploration, dynamic flow probing, and read-only fact extraction exist. |
| Domain grounding | Ontology seed loading, profile doc ingestion, AI-assisted term extraction, and research session artifacts exist. |
| Semantic alignment | Lexical plus AI-assisted alignment, confidence bands, review queue, approve/reject/edit, and reviewed schema writing exist. |
| Generated surfaces | MCP, Python API, local API bridge, Ansible collection, OpenAPI/Postman docs, generated surface docs, role-based explorer portal with native Try execution, MCP import, contract diff, adapter refresh commands, and MCP-build Python API synchronization exist. |
| Configuration versioning | Settings repo init, snapshots, commit/tag, diff, restore plan, readiness, restore dry-run/apply path, verification, and coverage exist. |
| Quality and drift | Drift reports, adapter reuse analysis, quality gates, coverage comparison, crawl memory, page graph support, and benchmark pack exist. |
| Research-backed crawl intelligence | Evidence cache, visual block grouping, adaptive crawl gain scoring, cache/gain workflow wiring, and documentation clue mining exist. |
| Packaging | Profile knowledge package builder, RAG chunks, public/private artifact split, zip bundles, Docker, PyPI, and GHCR workflows exist. |
| Documentation | Full `docs/00_` through `docs/10_` engineering suite now exists. |

## Near-Term Priorities

1.  Add stricter generated contract regression tests for API, MCP, and Ansible
    signature stability.
2.  Expand configuration coverage checks for staged list workflows and grouped
    restore steps.
3.  Add benchmark trend history across releases.
4.  Improve documentation link and artifact validation automation.
5.  Expand live-browser integration coverage for cache/gain/drift workflows.

## Phase Plan

### Phase 1: Foundations

Status: implemented enough for local and fixture workflows.

* Package metadata and CLI are present.
* Profiles, auth references, crawl policies, and output paths are present.
* Basic and dynamic crawl paths are present.
* Form and UI element extraction is present.

### Phase 2: Domain Grounding

Status: implemented with deterministic and AI-assisted paths.

* Ontology seeds are loaded from profile files.
* Profile docs are ingested.
* AI-assisted product documentation discovery and term extraction exist.
* Research sessions are persisted under `output/<profile>/reports/`.

### Phase 3: Semantic Layer

Status: implemented with review workflow.

* Lexical and AI alignment exist.
* Confidence scoring and exposure bands exist.
* Human review queue and review decisions exist.
* Debug reports explain mapping gaps and evidence coverage.

### Phase 4: Automation Surface Generation

Status: implemented, with maturity work remaining.

* MCP tools and adapter bindings are generated.
* Python API package and API spec are generated.
* The local API bridge serves generated methods for Swagger/Postman execution.
* OpenAPI 3.1, Postman collection, Postman environment, quickstart, Python,
  MCP, Ansible, and API reference docs are generated from the approved
  tools/API spec.
* Ansible collection and Ansible spec are generated.
* MCP import, diff, serve, call, and refresh commands exist.
* The generated explorer defaults to a role-based consumer API portal with
  generated operation examples, Swagger links, native dry-run Try execution,
  and keeps the dense evidence browser under Audit.

Future work:

* Extend Python API delegation deeper into generated apply-mode adapters where
  practical.
* Add stronger generated surface compatibility tests.

### Phase 5: Drift And Quality

Status: implemented for fixture and artifact workflows.

* Drift reports compare crawl snapshots.
* Adapter reuse analysis identifies semantic selector drift.
* Contract quality and quality gate reports exist.
* Benchmark pack validates multiple profile types.
* Crawl planning uses missing terms, page graphs, evidence cache, gain scoring,
  and coverage preservation.

Future work:

* Add more drift scenarios for non-semantic UI changes.
* Record benchmark trend history across releases.

### Phase 6: Configuration Versioning

Status: implemented with cautious apply mode.

* Save, coverage, diff, restore-plan, restore-readiness, and restore commands
  exist.
* Snapshots are deterministic and git-backed.
* Restore apply is gated by risk policy, confirmation, readiness, and
  verification hooks.

Future work:

* Expand grouped restore planning.
* Improve rollback metadata and post-restore verification ergonomics.
* Add more fixture tests for non-restorable and high-risk settings.

## Release Readiness Gates

Before a stable release:

* verify package and runtime versions agree,
* run full unit and integration tests,
* run benchmark pack,
* run generated surface smoke tests,
* run documentation validation,
* verify no raw credentials or sensitive values are committed,
* inspect generated contract diffs for breaking changes,
* update `docs/release.md` if packaging or publishing changes.
