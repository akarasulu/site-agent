# Release And Packaging

`site-agent` is the reusable engine package. Target-specific generated projects, such as `zte-agent`, are delivered separately as private repos, zip bundles, internal packages, or operator workspaces.

## Release Notes

### 1.9.0

- Refresh the numbered developer documentation suite for the current
  research-backed crawler implementation state.
- Add a research report index that links the paper-by-paper summaries and the
  research technique implementation plan.
- Link the research implementation plan and report index from the repository
  README.

### 1.8.0

- Extract deterministic documentation clues from local manuals: ranges,
  allowed values, defaults, required/read-only hints, operation verbs, and
  common units.
- Attach section-local documentation constraints and units to ontology terms
  during document ingestion.
- Add tests covering direct clue extraction and end-to-end profile document
  ingestion.

### 1.7.0

- Add drift-aware adapter reuse analysis for selector changes that preserve
  labels, control types, state paths, and visual position.
- Extend `drift check` reports with adapter reuse summaries for stable,
  reuse-candidate, review-required, and broken bindings.
- Keep existing selector drift findings intact while adding richer
  contract-preservation evidence.

### 1.6.0

- Bound optional OpenAI build-time enrichment behind explicit description and
  form-classification budgets.
- Preserve collapsed form provenance across generated capabilities and MCP form
  tool deduplication.
- Improve configuration coverage with adapter bindings and internal sentinel
  field filtering.
- Capture rendered form geometry, accessibility, and style metadata during
  browser reconciliation, and bound planned branch crawl time.

### 1.5.0

- Wire evidence-cache artifacts into crawl runs and fast collection runs.
- Add evidence-cache diffs to crawl comparison reports and crawl memory
  workflows.
- Feed cache/gain signals into crawl planning so plans explain page-family
  discoveries, changed content, preservation states, and memory effects.

### 1.4.0

- Add adaptive crawl gain scoring that combines missing ontology terms,
  observed UI labels, evidence-cache discoveries, changed page content,
  coverage preservation states, and crawl memory promotions/demotions.
- Add gain summaries so future crawl plans can explain which signals drove the
  top labels.
- Keep the scorer independent from planner wiring so existing crawl planning
  work can adopt it without losing current behavior.

### 1.3.0

- Add visual-block extraction to page graphs, grouping rendered elements by
  geometry and semantic role without depending on raw selectors.
- Mark repeated visual block patterns so settings rows, cards, and table-like
  regions can be reused by later mapping and drift logic.
- Attach visual block IDs to element node features while preserving the
  existing page/form/element graph shape.

### 1.2.0

- Add a reusable evidence cache for crawl snapshots with selector-independent
  page-family keys, template signatures, rendered/text hashes, evidence
  density, and cache diffs.
- Add a research-technique implementation plan that sequences evidence caching,
  visual block extraction, adaptive crawl planning, documentation mining, and
  drift-aware wrapper reuse.
- Align runtime `site_agent.__version__` with package metadata for the `1.2.0`
  sprint tag.

### 0.3.1

- Fix generated MCP stdio servers to speak standard `Content-Length` framed JSON-RPC, which lets Codex and other MCP clients complete initialize and `tools/list` handshakes.
- Ignore MCP notifications, including `notifications/initialized`, instead of sending invalid notification responses.
- Keep newline-delimited JSON support for local smoke tests and direct probes.

## Local Install

For normal developer use:

```bash
pipx install "site-agent[crawl]"
site-agent install browsers
site-agent doctor
```

From a checkout:

```bash
pipx install -e ".[crawl]"
site-agent install browsers
site-agent doctor
```

Without `pipx`:

```bash
python -m pip install "site-agent[crawl]"
site-agent install browsers
```

## Shell Command Installer

The checkout helper installs a dedicated user venv and links `site-agent` into `~/.local/bin`:

```bash
scripts/install-shell-commands.sh
```

It also installs bash and fish completion by default. Use `--no-completion` or `--no-playwright` to skip those steps.

## Build

```bash
python -m pip install -e ".[release]"
python -m build
python -m twine check dist/*
```

## TestPyPI

```bash
python -m twine upload --repository testpypi dist/*
pipx install --index-url https://test.pypi.org/simple/ --pip-args="--extra-index-url https://pypi.org/simple" "site-agent[crawl]"
```

## PyPI

Preferred deployment is GitHub Actions trusted publishing:

1. Create the `site-agent` project on PyPI.
2. Configure PyPI trusted publisher for `akarasulu/site-agent`, workflow `publish-pypi.yml`, environment `pypi`.
3. Create a GitHub release from a matching signed tag.
4. The publish workflow builds and uploads the package.

Manual fallback:

```bash
python -m twine upload dist/*
```

## Docker

Build locally:

```bash
docker build -t site-agent .
docker run --rm -v "$PWD:/workspace" site-agent --help
```

GitHub Actions publishes images to:

```text
ghcr.io/akarasulu/site-agent
```

## Generated Target Packages

Generated profile projects should not be shipped in the core PyPI package.

Target projects can be delivered as:

- a private git repository
- a zip bundle from `site-agent package build`
- an internal PyPI package
- a Docker image containing the target workspace
- an operator workspace copied next to a `site-agent` install

Use:

```bash
site-agent package build --profile my-site
```

to create a knowledge bundle containing schema, MCP metadata, API/Ansible manifests, reports, and RAG chunks. Private adapter/profile artifacts remain separated under `private/` unless `--public-only` is used.
