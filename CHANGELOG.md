# Changelog

All notable repository checkpoints are recorded here. Tags use semantic
versioning and sprint records under `docs/sprints/` capture validation evidence.

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
