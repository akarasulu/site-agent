# Validation Checklist

Use this checklist before claiming a change is complete, before releasing, or
after modifying generated contract behavior.

## Documentation Validation

| Check | Command or method | Required for docs-only changes |
| --- | --- | --- |
| Markdown whitespace | `git diff --check` | Yes |
| Documentation index freshness | Review `README.md` documentation links | Yes |
| Local Markdown links | Inspect or script-check links in `docs/` and `README.md` | Yes |
| Secret scan | `rg -n "OPENAI_API_KEY=|SITE_AGENT_ROUTER_PASSWORD=|password:|token:" docs README.md` | Yes |
| Architecture freshness | Compare docs to `site_agent/cli.py`, `site_agent/core/`, `contracts/`, `scripts/`, and workflows | Yes |

## Fast Runtime Checks

```bash
python -m site_agent --help
site-agent doctor --no-playwright
```

Use `site-agent doctor` without `--no-playwright` when browser readiness matters.

## Unit And Coverage Checks

```bash
python -m pytest -q --cov=site_agent --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-report=xml
```

The coverage configuration in `pyproject.toml` sets `fail_under = 80`.

## Fixture Workflow Checks

Dependency-light flow:

```bash
scripts/run-mock-e2e.sh
```

Generated surface flow:

```bash
scripts/run-mock-generated-surfaces.sh
```

Browser-backed staged action flow:

```bash
scripts/run-mock-staged-actions-e2e.sh
```

The staged action flow uses Docker and mutates only the controlled mock app.

## Benchmark Checks

```bash
site-agent benchmark run --fail-on-error
```

Expected benchmark profile types:

* `docs_site`,
* `workflow_dashboard`,
* `settings_admin`,
* `staged_dialog`.

The existing `output/benchmark-pack-report.json` shows all four benchmarks
passing their configured thresholds.

## Generated Contract Checks

For MCP:

```bash
site-agent mcp build --profile my-site
site-agent mcp diff --profile my-site \
  --baseline output/my-site/mcp/contract.json \
  --fail-on-breaking
site-agent mcp serve --profile my-site --once
```

For Python API and Ansible:

```bash
site-agent api build --profile my-site
site-agent docs build --profile my-site
site-agent ansible build --profile my-site
python -m py_compile output/my-site/api/*/*.py
```

Generated docs should include `output/my-site/docs/openapi.json`,
`output/my-site/postman/collection.json`, and
`output/my-site/postman/environment.json`.

When Ansible tooling is installed, run the generated collection through
`ansible-test sanity`.

## Configuration Versioning Checks

```bash
site-agent config save --profile my-site --repo ../my-site-settings
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent config diff --profile my-site --repo ../my-site-settings --ref HEAD
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref HEAD
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref HEAD
site-agent config restore --profile my-site --repo ../my-site-settings --ref HEAD --mode dry-run
```

Apply-mode checks require:

* clean settings repository,
* fresh current snapshot,
* profile risk policy allowing apply mode,
* explicit `--confirm`,
* approved tools for every applying step,
* post-restore verification when available.

## CI And Release Checks

Before release:

```bash
python -m pip install -e ".[release]"
python -m build
python -m twine check dist/*
docker build -t site-agent .
```

Verify:

* `pyproject.toml` version and `site_agent/__init__.py` version agree,
* changelog or release notes describe user-visible changes,
* full documentation suite exists,
* benchmark and generated surface smoke checks pass,
* no generated private adapters, auth state, settings repo, or secrets are
  committed,
* GitHub release tag matches `v<pyproject version>`.

## Live Router Checks

Live router checks are optional and must stay outside default CI:

```bash
SITE_AGENT_RUN_ROUTER_TESTS=1 \
SITE_AGENT_ROUTER_PASSWORD=your_private_password \
python -m pytest tests/integration_router
```

Read-only integration:

```bash
scripts/run-router-integration.sh
```

Live write testing requires a private network and the explicit confirmation
environment variable documented in [Execution Guide](07_EXECUTION_GUIDE.md).
