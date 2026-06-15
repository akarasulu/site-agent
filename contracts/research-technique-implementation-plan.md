# Research Technique Implementation Plan

This plan turns the crawler research reports into project-native work. The
goal is not to transplant papers wholesale. The goal is to keep the useful
threads and attach them to the existing `site-agent` contracts: evidence-backed
snapshots, page graphs, crawl memory, generated Python API, generated MCP,
generated Ansible, risk policy, and drift reports.

## Technique Threads To Preserve

| Thread | Applied Interpretation |
| --- | --- |
| Multi-pass crawling | Allow several cheap passes, but cache page evidence so repeat work is measurable and skippable. |
| Page-family detection | Compare structural signatures and state paths before selector details. |
| Visual and accessibility cues | Use rendered geometry, roles, names, headings, and proximity as extraction evidence. |
| Wrapper induction | Learn stable page templates from repeated structures, then reuse them with drift checks. |
| Adaptive crawl ordering | Prioritize missing ontology concepts and high-value preserved states instead of blindly clicking everything. |
| API/documentation mining | Treat docs as evidence for canonical names, constraints, and generated method descriptions. |
| Human-in-the-loop review | Keep low-confidence mappings and high-risk tools behind review gates. |

## Conservation Rules

* Keep core product-agnostic. Site-specific behavior stays in profiles and
  adapters.
* Keep public contracts selector-free. Selectors remain adapter/runtime
  details.
* Preserve the existing crawl snapshot, mapped schema, page graph, quality, and
  config versioning surfaces.
* Add evidence IDs and reasoning summaries when generated public surfaces use a
  new signal.
* Prefer cacheable multi-pass crawling over one large irreversible crawl.
* Do not use AI as the single source of truth. AI output must be backed by UI,
  documentation, or review evidence.

## Sprint Series

### Sprint 1: Evidence Cache And Page Families

Implemented first because it is the foundation for safe multi-pass crawls.

Deliverables:

* Build a reusable evidence cache from `CrawlSnapshot`.
* Store page-family keys from URL family, state path, and template signature,
  not raw selectors.
* Hash rendered HTML and normalized text separately.
* Record tag histograms, link/control labels, evidence density, and template
  groups.
* Diff two caches to identify added, removed, unchanged, and changed-content
  page families.

Validation:

* Unit tests cover query-value redaction from cache identity, selector
  fingerprint independence, and content-change detection.
* Version bump to `1.2.0` and tag `v1.2.0`.

### Sprint 2: Visual Block And Repeated Structure Extraction

Build on the existing `page_graph` work.

Status: implemented in `1.3.0`.

Deliverables:

* Cluster rendered elements into visual blocks using bounding boxes, role,
  y-band, and heading context.
* Emit repeated block candidates for tables, cards, settings rows, and menu
  regions.
* Attach block IDs to page graph node features so mapping and synthesis can use
  surrounding structure.
* Preserve current extraction paths as fallback when geometry is unavailable.

Validation:

* Synthetic page-graph tests for rows, cards, and settings sections.
* Fixture crawl comparison showing no loss of existing forms/elements.
* Minor version bump and tag `v1.3.0`.

### Sprint 3: Adaptive Multi-Pass Crawl Planning

Use cache and page graph signals to reduce duplicate work.

Status: implemented as a reusable scorer in `1.4.0`; planner wiring remains a
follow-on integration task so current in-flight planner changes are preserved.

Deliverables:

* Rank next crawl labels by expected gain: missing terms, new template families,
  high-value preserved states, and previous reward.
* Penalize repeated no-gain labels using crawl memory.
* Emit a plan explanation that shows why each path is selected.
* Keep destructive/action labels blocked by existing risk policy.

Validation:

* Unit tests for gain scoring and memory penalties.
* Existing navigation planning tests continue to pass.
* Minor version bump and tag `v1.4.0`.

### Sprint 4: Crawl Workflow Cache/Gain Wiring

Status: implemented in `1.5.0`.

Deliverables:

* Write evidence-cache artifacts after crawl and fast collection passes.
* Compare caches during `crawl compare`.
* Feed cache/gain signals into `crawl plan` without replacing existing
  ontology, observed UI, AI directional, or preservation signals.

Validation:

* CLI flow tests for emitted cache artifacts and cache diff reporting.
* Crawl-plan tests for cache-driven gain signals.
* Minor version bump and tag `v1.5.0`.

### Sprint 5: Workflow Hardening And Provenance Preservation

Deliverables:

* Capture visual/accessibility browser metadata for reconciled forms.
* Bound optional AI enrichment calls with explicit budgets.
* Preserve source form/field provenance when generated capabilities collapse
  duplicate semantic forms.
* Improve configuration coverage with adapter bindings and internal sentinel
  field filtering.

Validation:

* Targeted unit tests for AI budgets, config coverage, capability provenance,
  and navigation planning.
* Minor version bump and tag `v1.6.0`.

### Sprint 6: Drift-Aware Wrapper Reuse

Use learned templates to keep contracts stable through UI changes.

Deliverables:

* Compare new crawl caches against previous template groups.
* Rebind adapter candidates when semantics match but selectors change.
* Escalate changed labels, changed risk cues, or missing evidence to review.

Validation:

* Drift fixture with selector/layout churn and stable semantics.
* Contract diff confirms no public breaking changes for adapter-only drift.
* Minor version bump and tag `v1.7.0`.

### Sprint 7: Documentation And API Constraint Mining

Turn the API/documentation extraction papers into domain grounding.

Deliverables:

* Extract constraints, aliases, units, and operation verbs from local docs.
* Tie generated Python API, MCP, and Ansible descriptions to evidence IDs.
* Mark sparse or conflicting documentation as review-required.

Validation:

* Golden tests for term/constraint extraction from sample manuals.
* Generated surface tests confirm doc evidence is present.
* Minor version bump and tag `v1.8.0`.

## Cache Strategy

The cache key is intentionally conservative:

* URL family includes scheme, host, path, query key names, and state path.
* Query values are excluded to avoid cache churn and secret leakage.
* Template signature uses structural tags, form counts, element role families,
  and transition counts.
* Raw selectors and selector fingerprints are excluded from public cache keys.
* HTML and text hashes stay separate so rendering/template drift and content
  drift can be diagnosed independently.

The cache should eventually be written after every crawl pass as:

```text
output/<profile>/reports/evidence-cache-<run_id>.json
```

Sprint 4 wires this artifact into crawl commands and comparison reports.
