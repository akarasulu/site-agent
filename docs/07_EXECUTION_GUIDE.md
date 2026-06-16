# Execution Guide

This guide lists the commands, environment variables, and expected workflows
needed to run and validate `site-agent`.

## Install From A Checkout

```bash
python -m pip install -e ".[crawl,dev]"
site-agent install browsers
site-agent doctor
```

Expected outcome:

```text
site-agent doctor reports Python, optional module, and browser readiness.
```

## Install A User-Local Command

```bash
scripts/install-shell-commands.sh
```

Useful options:

```bash
scripts/install-shell-commands.sh --bin-dir ~/.local/bin
scripts/install-shell-commands.sh --venv-dir ~/.local/share/site-agent/venv
scripts/install-shell-commands.sh --no-playwright
scripts/install-shell-commands.sh --no-completion
```

## Shell Completion

```bash
site-agent completion bash > ~/.local/share/bash-completion/completions/site-agent
site-agent completion zsh > ~/.zfunc/_site-agent
site-agent completion fish > ~/.config/fish/completions/site-agent.fish
```

For one shell session:

```bash
source <(site-agent completion bash)
```

## Core Environment Variables

| Variable | Used by | Purpose |
| --- | --- | --- |
| `SITE_AGENT_AI_PROVIDER` | AI backend | `none`, `fake`, or `openai`. |
| `OPENAI_API_KEY` | OpenAI backend | API key for live AI-assisted discovery and mapping. |
| `SITE_AGENT_AI_MODEL` | OpenAI backend | Model name; README currently documents default `gpt-5-mini`. |
| `SITE_AGENT_AI_TIMEOUT` | OpenAI smoke/router scripts | Request timeout override. |
| `SITE_AGENT_AI_ALIGNMENT_BUDGET` | OpenAI backend | Maximum AI alignment calls per backend instance; defaults to `8`. |
| `SITE_AGENT_AI_TOOL_DESCRIPTION_BUDGET` | OpenAI backend | Optional generated tool-description calls; defaults to `0`. |
| `SITE_AGENT_AI_FORM_CLASSIFICATION_BUDGET` | OpenAI backend | Optional form-purpose classification calls; defaults to `0`. |
| `SITE_AGENT_ALLOW_NO_AI` | Live crawl | Allows explicit offline/debug live crawl without AI when set to a truthy value. |
| `PYTHONPATH` | Scripts | Lets temporary workspaces import the checkout package. |
| `SITE_AGENT_BIN_DIR` | Installer | User-local binary directory override. |
| `SITE_AGENT_INSTALL_VENV` | Installer | Installer venv path override. |
| `SITE_AGENT_INSTALL_EXTRAS` | Installer | Extras installed by shell installer; defaults to `crawl`. |
| `SITE_AGENT_INSTALL_PLAYWRIGHT` | Installer | Set to `0` to skip browser install. |
| `SITE_AGENT_INSTALL_COMPLETION` | Installer | Set to `0` to skip completion files. |

## Router Validation Environment Variables

| Variable | Purpose |
| --- | --- |
| `SITE_AGENT_ROUTER_URL` | Router base URL for documented workflow examples. |
| `SITE_AGENT_ROUTER_BASE_URL` | Base URL used by live port-forward check script. |
| `SITE_AGENT_ROUTER_USER` | Router username; defaults to `admin` in scripts. |
| `SITE_AGENT_ROUTER_PASSWORD` | Router password; never commit this value. |
| `SITE_AGENT_RUN_ROUTER_TESTS` | Enables opt-in pytest router tests. |
| `SITE_AGENT_ROUTER_WORKDIR` | Workspace for router integration script. |
| `SITE_AGENT_ROUTER_PLANNED_SECOND_PASS` | Enables or disables planned second pass in router script. |
| `SITE_AGENT_ROUTER_MAX_PLANNED_LABELS` | Planned second-pass label cap for router integration script. |
| `SITE_AGENT_ROUTER_PROBE_SECONDS` | Planned second-pass probe budget for router integration script. |
| `SITE_AGENT_DISCOVER_DOCS` | Set to `0` to skip router documentation discovery in the integration script. |
| `SITE_AGENT_BIN` | Override the `site-agent` executable used by router scripts. |
| `PYTHON_BIN` | Override the Python executable used by router scripts. |
| `SITE_AGENT_CONFIRM_LIVE_ROUTER_WRITE` | Must equal `create-activate-delete-port-forward` for live write apply mode. |

## Mock Fixture Workflow

```bash
scripts/run-mock-e2e.sh
```

Expected outcome:

```text
Mock E2E artifacts written to <tempdir>/output/opsboard
```

Run all generated surfaces:

```bash
scripts/run-mock-generated-surfaces.sh
```

Expected output includes counts and paths for MCP tools, Python API methods,
Ansible modules, settings repo, and knowledge package.

## Manual Profile Workflow

```bash
site-agent profile init --name my-site --base-url https://example.com
site-agent auth setup --profile my-site \
  --username-env MY_SITE_USER \
  --password-env MY_SITE_PASSWORD
site-agent docs discover --profile my-site --product-hint "my site admin guide"
site-agent crawl run --profile my-site
site-agent schema review --profile my-site
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent docs build --profile my-site
site-agent api serve --profile my-site
site-agent ansible build --profile my-site
site-agent explorer serve --profile my-site
site-agent quality check --profile my-site
```

Use fixture HTML instead of a live browser:

```bash
site-agent crawl run --profile my-site \
  --fixture-site profiles/fixtures/mock_app/site
```

## Crawl Planning And Merge Workflow

```bash
site-agent crawl inventory --profile my-site
site-agent crawl plan --profile my-site
site-agent crawl run --profile my-site --use-plan latest
site-agent crawl merge --profile my-site
site-agent crawl compare --profile my-site
site-agent quality check --profile my-site
```

Use `crawl collect` for a broader rendered-state capture:

```bash
site-agent crawl collect --profile my-site \
  --probe-budget-seconds 600 \
  --target-depth 8 \
  --max-states 500
```

## MCP Runtime Commands

```bash
site-agent mcp build --profile my-site
site-agent mcp serve --profile my-site
site-agent mcp serve --profile my-site --once
site-agent mcp call --profile my-site --tool get_status
site-agent mcp import --profile my-site --target json
site-agent mcp import --profile my-site --target codex --apply
site-agent mcp diff --profile my-site --baseline output/my-site/mcp/contract.json
site-agent mcp refresh-adapter --profile my-site
```

## Generated API Documentation

```bash
site-agent docs build --profile my-site
```

The command writes:

```text
output/my-site/docs/openapi.json
output/my-site/docs/openapi.yaml
output/my-site/docs/api-reference.md
output/my-site/docs/quickstart.md
output/my-site/docs/python-api.md
output/my-site/docs/mcp-tools.md
output/my-site/docs/ansible-collection.md
output/my-site/postman/collection.json
output/my-site/postman/environment.json
output/my-site/explorer/index.html
output/my-site/explorer/swagger.html
```

Use `--api-bridge-url` when the local API bridge will be served on a different
host or port:

```bash
site-agent docs build --profile my-site --api-bridge-url http://127.0.0.1:9000
```

Serve the generated API bridge:

```bash
site-agent api serve --profile my-site
```

Build or serve the explorer portal for Swagger, Postman, Python, MCP, Ansible,
and audit links:

```bash
site-agent explorer build --profile my-site
site-agent explorer serve --profile my-site
```

The bridge exposes:

* `GET /health`,
* `GET /openapi.json`,
* `POST /methods/<generated_method>`.

Write-like tool calls default to dry-run:

```bash
site-agent mcp call --profile my-site \
  --tool save_settings \
  --args-json args.json \
  --mode dry-run
```

## Configuration Versioning

```bash
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent config diff --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore --profile my-site --repo ../my-site-settings --ref v1 --mode dry-run
```

Apply mode requires explicit confirmation and profile risk policy support:

```bash
site-agent config restore --profile my-site \
  --repo ../my-site-settings \
  --ref v1 \
  --mode apply \
  --confirm
```

## Benchmark Pack

```bash
site-agent benchmark run
```

Fail the command if any fixture misses its expected thresholds:

```bash
site-agent benchmark run --fail-on-error
```

## Test And Coverage

```bash
python -m pytest -q --cov=site_agent --cov-branch \
  --cov-report=term-missing:skip-covered \
  --cov-report=xml
```

Run selected smoke checks:

```bash
python -m site_agent --help
scripts/run-mock-e2e.sh
scripts/run-mock-generated-surfaces.sh
```

## Build And Release

```bash
python -m pip install -e ".[release]"
python -m build
python -m twine check dist/*
```

Docker:

```bash
docker build -t site-agent .
docker run --rm -v "$PWD:/workspace" site-agent --help
```

See [Release And Packaging](release.md) for TestPyPI, PyPI, Docker, and
generated-target delivery notes.
