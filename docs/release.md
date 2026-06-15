# Release And Packaging

`site-agent` is the reusable engine package. Target-specific generated projects, such as `zte-agent`, are delivered separately as private repos, zip bundles, internal packages, or operator workspaces.

## Release Notes

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
