# Changelog

All notable repository checkpoints are recorded here. Tags use semantic
versioning and sprint records under `docs/sprints/` capture validation evidence.

## 1.16.0 - 2026-06-16

### Added

* Added per-operation `Try in Swagger` links from the explorer selected
  operation panel into the generated Swagger UI operation anchor.
* Added a native explorer `Try Operation` panel with editable request JSON,
  bridge URL configuration, bridge health check, dry-run execution, guarded
  apply execution, and response rendering.
* Added OpenAPI operation metadata and API bridge URL metadata to
  `explorer-data.json`.
* Added CORS and `OPTIONS` handling to the local API bridge so Swagger UI and
  the explorer can execute generated methods from browser origins.

### Validation

* `python -m pytest tests/unit/test_explorer.py tests/unit/test_http_api_bridge.py`
* `python -m py_compile site_agent/core/explorer.py site_agent/core/synthesize/http_api.py`
* Extracted explorer template JavaScript and checked it with `node --check`.
* Browser smoke against the regenerated ZTE explorer and live API bridge
  confirmed bridge health, Swagger operation links, dry-run execution, response
  rendering, and no browser console errors.

## 1.15.0 - 2026-06-16

### Added

* Added explorer role modes for Use, Automate, Audit, and Debug workflows.
* Added schema-backed examples for selected generated operations, including
  HTTP request bodies, curl, Python, MCP, Ansible, and Postman guidance.
* Added selectable operation rows so users can pivot from method lists to
  concrete examples without entering the dense audit browser.
* Added a Debug view for summary, artifact routing, and capability projection
  inspection.
* Added Postman Web and official import-documentation links to the explorer and
  generated Postman artifact helper pages.

### Validation

* `python -m pytest tests/unit/test_explorer.py tests/unit/test_cli_flow.py::test_cli_fixture_flow`
* `python -m py_compile site_agent/core/explorer.py site_agent/cli.py`
* Extracted explorer template JavaScript and checked it with `node --check`.
* Browser smoke against the regenerated ZTE explorer confirmed role modes,
  mode-aware tabs, examples, Postman links, Debug view, collapsed Audit
  evidence, and mobile layout without horizontal overflow.

## 1.14.1 - 2026-06-16

### Fixed

* Render generated Markdown and Postman artifacts as human-readable explorer
  pages for browser requests while preserving raw downloads for tools.
* Collapse evidence by default in generated artifact tables, MCP tool rows, and
  the Audit detail panel.
* Redirect browser requests for raw artifact paths to rendered helper pages,
  while allowing raw access with `?raw=1`.
* Reuse the explorer serve socket address so quick restarts stay on the
  requested port.

### Validation

* `python -m pytest tests/unit/test_explorer.py tests/unit/test_cli_flow.py::test_cli_fixture_flow`
* `python -m py_compile site_agent/core/explorer.py site_agent/cli.py`
* `git diff --check`
* Browser smoke against the regenerated ZTE explorer confirmed collapsed
  evidence in the MCP tab and Audit detail panel.

## 1.14.0 - 2026-06-16

### Added

* Reworked the generated explorer into a consumer-first API portal with
  Overview, API, Python, MCP, Ansible, Postman, and Audit tabs.
* Added generated Swagger UI entry point and local explorer artifact copies for
  OpenAPI, Markdown docs, and Postman imports.
* Generated quickstart, Python API, MCP, and Ansible Markdown docs alongside
  the API reference.
* Included generated docs and Postman files in profile knowledge packages.

### Validation

* `python -m pytest tests/unit/test_generated_specs.py tests/unit/test_explorer.py tests/unit/test_http_api_bridge.py tests/unit/test_cli_flow.py::test_cli_fixture_flow`
* `python -m pytest tests/unit/test_contracts_and_writes.py::test_package_build_creates_rag_bundle_with_private_boundary`
* `python -m py_compile site_agent/cli.py site_agent/core/synthesize/docs.py site_agent/core/synthesize/http_api.py site_agent/core/explorer.py site_agent/core/package.py`

## 1.13.0 - 2026-06-16

### Added

* Added `site-agent api serve` for a local HTTP bridge over generated API
  methods.
* Added `GET /health`, `GET /openapi.json`, and
  `POST /methods/<generated_method>` bridge routes.
* Delegated bridge execution to the same generated runtime used by MCP calls.

### Validation

* `python -m pytest tests/unit/test_http_api_bridge.py tests/unit/test_generated_specs.py`
* `python -m py_compile site_agent/cli.py site_agent/core/synthesize/http_api.py site_agent/core/synthesize/docs.py`

## 1.12.0 - 2026-06-16

### Added

* Generated OpenAPI 3.1 contracts for profile API bridge methods.
* Generated Postman collection and environment artifacts for profile methods.
* Added `site-agent docs build` for OpenAPI, Postman, and generated API
  reference output.
* Wired OpenAPI/Postman generation into `site-agent mcp build`,
  `site-agent api build`, and `site-agent ansible build`.

### Validation

* `python -m pytest tests/unit/test_generated_specs.py`
* `python -m pytest tests/unit/test_cli_flow.py::test_cli_fixture_flow tests/unit/test_explorer.py::test_build_and_write_explorer_data`
