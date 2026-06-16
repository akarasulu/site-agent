# Changelog

All notable repository checkpoints are recorded here. Tags use semantic
versioning and sprint records under `docs/sprints/` capture validation evidence.

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
