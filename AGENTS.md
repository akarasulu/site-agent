# AGENTS.md

## Mission
Build a generic, domain-aware website interaction mapper that:
- Crawls authenticated web applications.
- Maps pages, forms, fields, actions, and navigation paths.
- Uses AI plus retrieved domain documentation to produce coherent, jargon-correct schema.
- Generates stable MCP server interfaces from canonical concepts, not fragile UI selectors.
- Generates a typed Python API package from the approved model so developers can automate the target web UI directly.
- Generates an Ansible collection from the approved model so operators can manage the target web UI declaratively.
- Captures current web UI configuration state into versionable artifacts so users can diff, audit, and restore settings through approved UI actions.

This project must remain product-agnostic.

## Non-Goals
- Do not hardcode target-specific product logic in core.
- Do not ship target-specific MCP tools as part of core.
- Do not ship target-specific Python API clients or Ansible modules as part of core.
- Do not expose raw selectors as public API.
- Do not rely on LLM guesses without evidence.

## Scope Boundary
Core project provides reusable engine only.
Target systems are external profiles.

- Core:
  - Document ingestion and retrieval.
  - Authenticated crawler and interaction extraction.
  - Semantic alignment and ontology mapping.
  - Generated Python API synthesis.
  - MCP tool synthesis.
  - Ansible collection synthesis.
  - Configuration state snapshot, diff, and restore planning.
  - Drift detection and validation.
- Profiles (external fixtures/config packs):
  - Domain ontology seed.
  - Site auth flow strategy.
  - Host allowlist and crawl policy.
  - Risk policy and confirmation rules.

Example test targets are allowed only as validation profiles, not as core behavior.

## Simple User Experience
This is a developer tool. The default workflow must be clear, short, and consistent.

Primary user flow:
1. Create a profile for a target website.
2. Configure authentication and crawl scope.
3. Run crawl + extraction.
4. Review AI mappings and approve low-confidence items.
5. Generate automation surfaces from approved schema: Python API, MCP server, and optionally an Ansible collection.
6. Connect MCP server to an agent client, import the Python API, or run Ansible modules/tasks.
7. Optionally snapshot current settings into a dedicated git repository.
8. Re-run sync when website UI changes.

Recommended CLI shape (or equivalent UI actions):
- `site-agent profile init`
- `site-agent auth setup`
- `site-agent crawl run`
- `site-agent schema review`
- `site-agent api build`
- `site-agent mcp build`
- `site-agent mcp serve`
- `site-agent mcp import`
- `site-agent ansible build`
- `site-agent config save`
- `site-agent config coverage`
- `site-agent config diff`
- `site-agent config restore-plan`
- `site-agent config restore-readiness`
- `site-agent config restore`
- `site-agent drift check`

UX requirements:
- Every command prints next-step guidance.
- Destructive or high-risk actions require explicit confirmation.
- Errors must include actionable fixes, not just stack traces.
- Low-confidence mappings are shown in a review queue.
- Generated MCP tools include human-readable descriptions and evidence references.
- Generated MCP packages can emit or install client configuration with a reusable import command instead of target-specific setup instructions.
- Generated Python API methods include typed arguments, docstrings, constraints, risk metadata, and evidence references.
- Generated Ansible modules expose idempotent check-mode friendly operations where the model has enough read/write evidence.
- Configuration snapshots produce deterministic, reviewable files suitable for a small dedicated git repository.
- Restores default to plan/dry-run and require explicit confirmation before applying any setting changes.

## Quick Start (5 Minutes)
Use this flow to go from zero to generated automation surfaces quickly.

1. Initialize a target profile.
```bash
site-agent profile init --name my-site --base-url https://example.com
```
Expected outcome:
- Creates profile config files.
- Prints next step: authentication setup.

2. Configure authentication.
```bash
site-agent auth setup --profile my-site
```
Expected outcome:
- Stores session/auth strategy for the profile.
- Verifies login success before continuing.

3. Run crawl and extraction.
```bash
site-agent crawl run --profile my-site
```
Expected outcome:
- Produces page map, forms, fields, and transitions.
- Saves crawl snapshot artifact.

4. Review schema mappings.
```bash
site-agent schema review --profile my-site
```
Expected outcome:
- Shows high-confidence mappings as ready.
- Queues low-confidence mappings for approval.

5. Build the Python API, then build and serve MCP.
```bash
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent mcp serve --profile my-site
```
Expected outcome:
- Generates a typed Python API package from approved schema and profile adapters.
- Generates MCP tools from approved schema, preferably backed by the generated Python API execution layer.
- Starts MCP server for agent client connection.

6. Emit or install MCP client configuration.
```bash
site-agent mcp import --profile my-site --target json
site-agent mcp import --profile my-site --target codex --apply
site-agent mcp import --profile my-site --target kimi-code
```
Expected outcome:
- Emits a standard MCP client config block or updates a supported client config.
- Keeps target setup reusable across Codex, Kimi Code, and other clients that can launch local MCP stdio servers.

7. Optionally build an Ansible collection.
```bash
site-agent ansible build --profile my-site
```
Expected outcome:
- Generates Ansible modules, module_utils, documentation fragments, and task examples for model-backed read/update operations.
- Modules support check mode for write-capable operations when the generated Python API supports dry-run.

8. Check drift after UI updates.
```bash
site-agent drift check --profile my-site
```
Expected outcome:
- Reports changes and proposed remaps.
- Preserves stable tool contracts when semantics are unchanged.

9. Snapshot settings into a dedicated git repository.
```bash
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
```
Expected outcome:
- Reads current UI-backed settings through approved read/snapshot tools.
- Writes deterministic JSON/YAML artifacts into the settings repo.
- Commits the snapshot with run metadata and evidence references.

10. Compare or restore settings from a branch, tag, or commit.
```bash
site-agent config diff --profile my-site --repo ../my-site-settings --ref v2026-05-25-good
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref v2026-05-25-good
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref v2026-05-25-good --apply --confirm
site-agent config restore --profile my-site --repo ../my-site-settings --ref v2026-05-25-good --mode dry-run
```
Expected outcome:
- Produces a setting-level diff against current UI state.
- Builds a restore plan using generated MCP write/staged-action tools.
- Applies only reviewed, reversible changes allowed by profile risk policy when `--mode apply` is explicitly enabled and readiness checks pass.

## Acceleration with Existing Tools
Use proven open-source building blocks where practical instead of re-implementing core browser automation and crawl primitives.

Recommended baseline stack:
- Browser automation runtime: Playwright (embedded Chromium execution required for JavaScript-heavy websites).
- Agent browser control reference: Playwright MCP patterns for accessibility snapshot + deterministic tool flow.
- Authenticated crawl orchestration: Crawlee-style session/crawl patterns or Crawl4AI-style hook-based auth integration.
- Optional high-fidelity crawl reference: Browsertrix-style browser-driven crawl patterns for complex dynamic pages.

How these are used in this project:
- Core crawl engine uses Playwright runtime directly for page execution, interaction, and extraction.
- MCP synthesis remains project-owned and schema-driven; do not proxy raw browser tools as the final API.
- Existing projects are used as implementation references and reusable components, while keeping canonical contract logic in core.

Selection policy:
- Prefer stable, actively maintained libraries.
- Avoid vendor lock-in in core abstractions.
- Wrap third-party dependencies behind internal interfaces so they can be swapped without contract breakage.

## System Architecture
Implement in this layered order.

1. Domain Intelligence Layer
- Ingest official docs, manuals, KBs, changelogs, and trusted forums.
- For product/device website targets, prioritize owner guides, admin manuals, quick-start guides, and vendor support articles as required sources.
- Build domain lexicon with:
  - canonical term
  - aliases
  - units
  - constraints
  - source evidence
- Output: ontology plus confidence-scored dictionary.

2. Authenticated Crawl and Extraction Layer
- Execute login-aware crawl with session persistence.
- Use embedded Chromium automation (Playwright/Puppeteer class runtime) so JavaScript-driven UI behavior is executed and observable during crawl.
- Extract:
  - pages and hierarchy
  - forms and sections
  - fields and control types
  - labels, help text, validation text
  - action triggers and navigation transitions
- Include context features:
  - page title
  - headings
  - breadcrumbs/tabs/cards
- Output: raw interaction graph and candidate schema elements.

3. AI Semantic Alignment Layer
- Map raw UI elements to ontology terms.
- For every mapped concept, store:
  - canonical name
  - aliases seen in UI
  - evidence links to UI and docs
  - confidence
- Never invent mappings when confidence is low.
- Output: coherent, domain-grounded schema.

4. Generated Python API Layer
- Generate a target-specific Python package from canonical concepts, approved schema, and profile adapter bindings.
- Treat the generated Python API as the shared execution layer for higher-level automation surfaces when practical.
- Expose stable, typed methods for:
  - read/status operations
  - low/medium-risk configuration updates
  - staged create/update/delete flows
  - configuration snapshot/diff/restore-plan helpers
- Include generated dataclasses or Pydantic-style models for arguments and returns when dependencies allow; otherwise use typed standard-library dataclasses.
- Preserve dry-run support for all write operations.
- Keep selectors and browser details private inside adapter/runtime modules, not public method signatures.
- Output: generated Python client package plus adapter/runtime metadata.

5. MCP Synthesis Layer
- Generate MCP tools from canonical intents.
- Keep external API stable and readable.
- Prefer calling the generated Python API rather than duplicating browser/action execution logic.
- Internally map to selector adapters per profile and version through the Python API/runtime layer.
- Provide a reusable MCP import/install command that emits standard `mcpServers` JSON and supported client config blocks.
- Keep target-specific MCP client setup in generated projects as thin wrappers around the reusable import command.
- Emit metadata for each tool:
  - description in domain language
  - arguments and types
  - constraints and side effects
  - evidence summary
  - risk level

6. Ansible Collection Synthesis Layer
- Generate an Ansible collection from approved schema and generated Python API capabilities.
- Prefer implementing Ansible modules as thin wrappers around the generated Python API.
- Generate:
  - modules for read/status facts where read evidence exists
  - modules for configuration updates where restore/write tools and current-value reads exist
  - module_utils client wrapper for shared auth/session/runtime behavior
  - examples/playbooks and argument documentation
- Support Ansible check mode using Python API dry-run behavior.
- Expose idempotent semantics only when current-value reads and write/restore paths are both evidenced.
- Mark non-idempotent or low-confidence actions as documentation-only or review-required, not normal modules.
- Output: generated Ansible collection package.

7. Validation and Drift Layer
- Re-run crawl after UI change or schedule.
- Detect label/selector/layout drift.
- Attempt semantic remapping using ontology and evidence.
- Mark uncertain remaps for review.

8. Configuration State Versioning Layer
- Read all approved setting/status values that are in scope for configuration backup.
- Normalize values into deterministic artifacts keyed by canonical concept and stable collection path, not raw selectors.
- Store snapshots in a user-provided git repository dedicated to the target's settings.
- Compare current UI state against any branch, tag, or commit in that repository.
- Generate restore plans from versioned snapshots using approved MCP write/staged-action tools.
- Keep restore execution separate from snapshot/diff and gated by dry-run, confirmation, risk policy, and rollback metadata.
- Output: settings snapshot, settings diff, restore plan, restore execution report.

## Acceptance Metrics
- Site coverage target: 100 percent of in-scope reachable pages and interaction paths discovered for the configured profile.
- Extraction quality target: >= 0.95 precision on form/input extraction for benchmark profiles.
- Mapping quality target: >= 0.90 precision on stable (>= 0.85 confidence) concept mappings.
- Contract stability target: no breaking MCP tool signature changes without version bump.
- Python API stability target: no breaking method signature changes without version bump.
- Ansible collection stability target: no breaking module argument changes without version bump.
- Drift remap target: >= 0.85 automatic remap success on non-semantic UI changes.
- Configuration snapshot determinism target: identical UI state produces byte-stable snapshot artifacts .
- Restore planning target: 100 percent of changed settings either map to an approved write/staged-action tool or are reported as non-restorable with evidence.

## AI Integration Rules
Use AI for these tasks only:
- Document summarization and term extraction.
- Field typing and semantic classification.
- Action intent normalization.
- Constraint extraction and conflict detection.
- Crawl planning prioritization by expected missing concepts.
- Configuration grouping and restore-plan explanation when backed by UI/tool evidence.
- Python API and Ansible naming/description generation when backed by approved schema evidence.

Do not use AI as single source of truth.
All public schema and MCP decisions require evidence artifacts.

## Evidence-First Contract
Every canonical concept and generated tool must include evidence.
Minimum evidence policy:
- At least one UI artifact (label/help/validation/context).
- Prefer at least one documentation artifact for domain terms.
- Confidence score in [0, 1].

Confidence gating:
- >= 0.85: stable
- 0.60 to 0.84: experimental
- < 0.60: internal only, no public exposure

## Safety and Risk Controls
Classify operations by risk:
- low: read-only status and diagnostics
- medium: reversible configuration updates
- high: destructive or connectivity-impacting actions

Requirements:
- High-risk operations need explicit confirmation policy.
- Store rollback instructions where possible.
- Enforce host allowlists.
- Do not print credential values in command output; saved configuration repositories may contain sensitive settings and must be protected by the operator.

Execution safety modes:
- Read-only mode: allows navigation, extraction, and diagnostics only.
- Dry-run mode for write operations: required for create/update/delete actions to preview intended steps without applying changes.
- Apply mode for write operations: requires explicit user confirmation and policy checks.

Configuration versioning safety:
- Snapshot and diff are read-only operations.
- Restore plan is dry-run by default and may not mutate the target.
- Restore apply requires explicit `--mode apply --confirm`, host allowlist checks, approved write/staged-action tools, fresh snapshot/readiness checks, and profile risk policy compliance.
- High-risk or connectivity-impacting settings must remain pending review unless a profile-specific confirmation policy allows them.
- Before restore apply, capture a pre-restore snapshot and store rollback instructions in the settings repository.

## Secrets and Configuration Policy
- Never log secrets, auth tokens, cookies, or credential values.
- Load secrets from environment variables or external secret file references located outside the generated project tree.
- Configuration snapshots preserve captured values by default. Operators are responsible for storing settings repositories in private storage or using tools such as git-crypt when sensitive values are present.

## Human Review Policy
- Human reviewer is the final authority for approving, editing, or rejecting mappings and tool exposure.
- Keep review workflow simple: approve, reject, or edit.
- Require review only for low-confidence mappings and high-risk write tools.

## Versioning Policy
- Use semantic versioning for generated Python API, MCP contracts, and Ansible collections.
- Patch: non-breaking metadata or internal adapter fixes.
- Minor: additive tool/argument changes that are backward compatible.
- Major: breaking renames, argument removals, or semantic behavior changes.
- Version adapters independently from canonical API/MCP/Ansible contracts when only UI bindings drift.

## Observability and Debugging
- Every run must emit a unique run_id.
- Every mapping/tool decision must include evidence IDs and reasoning summary.
- Persist structured logs for crawl events, extraction events, mapping decisions, and synthesis actions.
- Provide a debug view that answers: what was found, why it was mapped, and what evidence supports it.
- Observability artifacts may contain captured values; operators should review before sharing or embedding them.

## Plugin Interfaces
Core must expose stable extension points for:
- Auth strategy plugins.
- Crawl strategy plugins.
- Document ingestion/retrieval providers.
- Ontology provider plugins.
- Semantic alignment backends.
- Python API synthesis backends.
- MCP synthesis backends.
- Ansible collection synthesis backends.

Plugin requirements:
- Well-defined interface contracts.
- Version compatibility checks.
- Safe defaults when plugins are missing.

## Data Model Requirements
At minimum persist:
- DomainTerm
  - id, canonical_name, aliases, units, constraints, sources
- UiElement
  - id, page_id, selector_fingerprint, label, control_type, context
- ConceptMapping
  - ui_element_id, domain_term_id, confidence, evidence_ids
- ToolSpec
  - name, description, args, return_schema, risk_level, evidence_ids
- AdapterBinding
  - tool_name, profile_id, version, selector/action bindings
- CrawlSnapshot
  - timestamp, profile_id, pages, forms, transitions
- ConfigSnapshot
  - id, timestamp, profile_id, source_run_id, settings, evidence_ids, value_policy
- ConfigSetting
  - id, canonical_name, path, value, value_type, source_tool, evidence_ids, confidence, sensitivity
- ConfigDiff
  - baseline_ref, current_snapshot_id, added, removed, changed, unchanged, non_restorable
- RestorePlan
  - id, target_ref, current_snapshot_id, steps, risk_summary, rollback_snapshot_id, requires_review
- RestoreStep
  - setting_id, tool_name, args, previous_value, desired_value, risk_level, evidence_ids, status
- PythonApiSpec
  - package_name, version, methods, models, evidence_ids, adapter_version
- PythonApiMethod
  - name, description, args, return_schema, risk_level, dry_run_supported, evidence_ids, backing_tool_or_concept
- AnsibleCollectionSpec
  - namespace, name, version, modules, module_utils, evidence_ids, python_api_dependency
- AnsibleModuleSpec
  - name, description, options, supports_check_mode, idempotence_level, risk_level, evidence_ids, backing_python_method

## Implementation Phases
Phase 1: Foundations
- Project scaffolding.
- Core schemas and storage.
- Basic authenticated crawl.
- Raw form extraction.

Phase 2: Domain Grounding
- Doc ingestion and retrieval index.
- Ontology builder.
- Evidence model.

Phase 3: Semantic Layer
- AI mapping pipeline.
- Confidence scoring and gating.
- Human-review hooks.

Phase 4: Automation Surface Generation
- Python API synthesis from canonical concepts.
- MCP tool synthesis, preferably backed by the generated Python API.
- Ansible collection synthesis for evidenced read/update operations.
- Profile adapters.
- Structured metadata and docs output.

Phase 5: Drift and Quality
- Change detection.
- Auto-remap with confidence thresholds.
- Regression checks and benchmark suite.

Phase 6: Configuration Versioning
- Dedicated settings repository initialization.
- Read-only configuration snapshot generation.
- Git-backed snapshot commit, branch, and tag workflows.
- Current-vs-ref diffing.
- Dry-run restore plans using approved MCP write/staged-action tools.
- Apply restore with confirmation, rollback snapshot, and execution report.

## Quality Gates
A build is acceptable only if:
- No product-specific hardcoding in core.
- >= 90 percent of exposed tools have dual evidence (UI + docs) or approved exception.
- All high-risk tools require confirmation metadata.
- Generated tool names are canonical and domain coherent.
- Generated Python API methods are canonical, typed, documented, and selector-free.
- Generated Ansible modules use Ansible-style names/options, support check mode where possible, and do not claim idempotence without read/write evidence.
- Drift tests pass for at least one synthetic target profile.
- Configuration snapshots are deterministic and restorable only through approved tools.

## Testing Strategy
- Unit tests:
  - parsers, type inference, confidence logic, tool synthesis.
- Integration tests:
  - authenticated crawl against controlled demo apps.
- Golden tests:
  - stable expected schema for known fixtures.
- Configuration versioning tests:
  - deterministic snapshot generation for fixture settings.
  - git repo init/commit/diff against fixture snapshots.
  - restore plan generation from a tag/branch/commit.
  - restore apply against controlled mock app only.
- Generated API tests:
  - Python API package imports and calls dry-run/read operations against fixtures.
  - API method signatures remain stable across adapter-only drift.
- Generated Ansible tests:
  - collection skeleton validates with `ansible-test sanity` when available.
  - modules support check mode for write-capable fixture operations.
  - generated modules call the Python API layer rather than duplicating selector logic.
- Benchmark pack tests:
  - run standard benchmark profiles and compare coverage, extraction precision, mapping quality, and contract stability.
- Manual acceptance:
  - optional profile run against a real authenticated website, outside core CI.

## Benchmark Pack
Maintain a benchmark pack with at least 3 to 5 profile types:
- content-heavy documentation site
- workflow-heavy dashboard app
- settings-heavy admin interface

Each benchmark profile must define:
- expected reachable page set
- expected key forms and fields
- expected canonical concepts
- acceptable metric thresholds

## Deliverables
Ship these outputs:
- Canonical ontology JSON.
- Interaction graph JSON.
- Mapped schema JSON with evidence and confidence.
- Generated Python API package.
- Generated MCP server package.
- Generated Ansible collection package.
- Profile adapter package.
- Validation report with drift and risk summary.
- Versioned configuration snapshot package.
- Restore plan and restore execution report when requested.

## Repository Layout Guidance
Use this structure once code is added:
- core/
  - ingest/
  - crawl/
  - extract/
  - align/
  - synthesize/
  - drift/
  - config/
  - api/
  - ansible/
- contracts/
  - schemas/
- profiles/
  - examples/
  - fixtures/
- output/
  - ontology/
  - schema/
  - mcp/
  - api/
  - ansible/
  - reports/
  - config/
- tests/
  - unit/
  - integration/
  - golden/

## Agent Workflow
For any new target profile:
1. Gather docs and build domain lexicon.
2. Configure auth and crawl policy.
3. Run crawl and extract forms/inputs/actions.
4. Run semantic alignment with evidence capture.
5. Generate Python API, MCP tools, Ansible collection, and adapters.
6. Optionally run configuration snapshot into a dedicated settings repository.
7. Run quality gates and risk checks.
8. Publish artifacts and report confidence.

## MVP Scope Lock
Phase 1 MVP includes only:
- authenticated crawl with embedded Chromium JavaScript execution
- form/input extraction with context capture
- evidence-backed semantic mapping
- Python API generation for read-only and low-risk write operations
- MCP generation for read-only and low-risk write operations
- Ansible collection generation for evidenced read-only and low-risk idempotent operations
- dry-run support for all write operations
- read-only configuration snapshots and restore-plan dry-runs for approved low/medium-risk settings

Phase 1 MVP excludes:
- autonomous high-risk writes without confirmation
- cross-profile ontology federation
- hosted multi-tenant control plane
- non-browser protocol automation outside website interaction
- assuming configuration repositories are safe to publish without operator review

## Change Management
When UI changes:
- Produce drift report.
- Recompute mappings.
- Keep stable tool names if semantic identity is unchanged.
- Version bump adapters, not canonical contract, unless semantic break is real.

## Definition of Done
Done means:
- Core remains generic.
- Schema is domain-coherent and evidence-backed.
- Generated Python API is stable, typed, selector-free, and used as the preferred shared execution layer.
- MCP interface is stable, readable, and safe.
- Generated Ansible collection is evidence-backed, check-mode aware, and uses the generated Python API where practical.
- Target-specific behavior exists only in profiles/adapters.
