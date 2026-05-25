# site-agent

`site-agent` is a generic, domain-aware website interaction mapper. It creates target profiles, crawls browser applications, extracts forms and actions, aligns UI evidence to domain terms, and generates stable automation surfaces: a Python API, an MCP server, and an Ansible collection.

The project core is product-agnostic. Target-specific behavior belongs in profiles and adapters.

## Documentation

- [Release and packaging](docs/release.md): PyPI, pipx, Docker, and generated-target delivery.
- [Config versioning design](contracts/config-versioning-design.md): save, diff, restore-plan, and restore guardrails.
- [Generated automation surfaces](contracts/generated-automation-surfaces.md): Python API, MCP, and Ansible generation contracts.
- [Interaction flow design](contracts/interaction-flow-design.md): staged add/edit/delete flow discovery.

## Quick Start

```bash
site-agent profile init --name my-site --base-url https://example.com
site-agent auth setup --profile my-site
site-agent crawl run --profile my-site
site-agent schema review --profile my-site
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent mcp serve --profile my-site
site-agent ansible build --profile my-site
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent drift check --profile my-site
```

That primary workflow is intentionally short:

1. Create or import a profile.
2. Add authentication and crawl scope.
3. Gather documentation when the target has manuals, support pages, or guides.
4. Crawl the UI and extract pages, forms, fields, actions, and dynamic flows.
5. Review AI-assisted mappings and approve low-confidence items.
6. Generate the Python API, MCP server, and Ansible collection from the approved model.
7. Snapshot configuration into a dedicated settings repository when desired.
8. Build a package containing evidence, schema, generated contracts, reports, and RAG chunks.
9. Re-run drift and quality checks when the UI changes.

Install from PyPI with `pipx`:

```bash
pipx install "site-agent[crawl]"
site-agent install browsers
site-agent doctor
```

Install from a checkout with:

```bash
pip install -e ".[crawl]"
site-agent install browsers
site-agent doctor
```

Install the shell command for the current user with:

```bash
scripts/install-shell-commands.sh
```

That creates an isolated venv under `~/.local/share/site-agent/venv` and links `site-agent` into `~/.local/bin`. Make sure `~/.local/bin` is on `PATH`, then run:

```bash
site-agent --help
```

The installer does not require sudo. It is meant for developer workstations and generated target projects that need a stable `site-agent` command on `PATH`.

Installer options:

```bash
scripts/install-shell-commands.sh --bin-dir ~/.local/bin
scripts/install-shell-commands.sh --venv-dir ~/.local/share/site-agent/venv
scripts/install-shell-commands.sh --no-playwright
```

Enable shell completion with:

```bash
site-agent completion bash > ~/.local/share/bash-completion/completions/site-agent
site-agent completion zsh > ~/.zfunc/_site-agent
site-agent completion fish > ~/.config/fish/completions/site-agent.fish
```

For one-off use:

```bash
source <(site-agent completion bash)
```

## Mock App Harness

The repository includes an OpsBoard fixture under `profiles/fixtures/mock_app` for fast, product-agnostic iteration.

Run the dependency-light fixture flow:

```bash
scripts/run-mock-e2e.sh
```

Run the fuller generated-output smoke flow:

```bash
scripts/run-mock-generated-surfaces.sh
```

That script creates an isolated temporary workspace, crawls the mock app fixture, generates the Python API, MCP package, Ansible collection, configuration snapshot, quality report, and profile knowledge package. It prints the final output paths so you can inspect a complete non-device example without touching a real site.

Run the mock website in Docker:

```bash
scripts/run-mock-container.sh
```

## Router Validation

Router validation is opt-in and uses an external profile under `profiles/examples/zte-router`.

```bash
scripts/run-router-integration.sh
```

The script reads `SITE_AGENT_ROUTER_PASSWORD` or prompts silently, stores browser session state only in the temporary run workspace, and removes that session state after the crawl. Router-facing commands may need a network grant when run from a sandboxed agent environment.

### Example: ZTE Modem/Router Profile

The ZTE profile is an example validation target, not core product logic. Keep credentials outside the repository:

```bash
export SITE_AGENT_ROUTER_URL=https://192.168.1.1
export SITE_AGENT_ROUTER_USER=admin
read -rsp "Router password: " SITE_AGENT_ROUTER_PASSWORD
export SITE_AGENT_ROUTER_PASSWORD
```

Then run the normal workflow against a private workspace/profile:

```bash
site-agent profile import-example profiles/examples/zte-router --name zte-router
site-agent auth setup --profile zte-router \
  --username-env SITE_AGENT_ROUTER_USER \
  --password-env SITE_AGENT_ROUTER_PASSWORD
site-agent docs discover --profile zte-router --product-hint "ZTE router web UI user guide"
site-agent crawl run --profile zte-router --research-product-hint "ZTE router web UI user guide"
site-agent schema review --profile zte-router
site-agent api build --profile zte-router
site-agent mcp build --profile zte-router
site-agent ansible build --profile zte-router
site-agent config save --profile zte-router --repo ../zte-router-settings --commit --tag v1
site-agent config coverage --profile zte-router --settings-repo ../zte-router-settings
site-agent package build --profile zte-router
```

For restores, start with planning and readiness checks. Apply mode is disabled unless the profile risk policy explicitly opts in.

```bash
site-agent config diff --profile zte-router --repo ../zte-router-settings --ref v1
site-agent config restore-plan --profile zte-router --repo ../zte-router-settings --ref v1
site-agent config restore-readiness --profile zte-router --repo ../zte-router-settings --ref v1 --apply --confirm
site-agent config restore --profile zte-router --repo ../zte-router-settings --ref v1 --mode dry-run
```

Use private storage, filesystem permissions, `git-crypt`, `sops`, or equivalent controls for settings repositories. Captured configuration values are preserved as-is.

## AI Backends

AI is optional. The default path is deterministic and evidence-gated.

```bash
SITE_AGENT_AI_PROVIDER=fake site-agent schema review --profile demo
SITE_AGENT_AI_PROVIDER=openai OPENAI_API_KEY=... site-agent schema review --profile demo
```

Supported providers:

- `none` or unset: deterministic ontology plus lexical alignment
- `fake`: deterministic test backend for CI
- `openai`: OpenAI Responses API backend using structured JSON outputs

OpenAI settings:

- `OPENAI_API_KEY`
- `SITE_AGENT_AI_MODEL`, default `gpt-5-mini`

AI outputs are never accepted as the sole source of truth. Public mappings still require evidence IDs and confidence gating.

Run a bounded live OpenAI smoke test:

```bash
scripts/run-openai-ai-smoke.sh
```

Generated write tools are opt-in and dry-run by default:

```bash
site-agent mcp build --profile my-site --include-writes
site-agent mcp call --profile my-site --tool save_settings --args-json args.json
site-agent mcp call --profile my-site --tool save_settings --args-json args.json --mode apply
```

Contract stability helpers:

```bash
site-agent mcp diff --profile my-site --baseline output/my-site/mcp/contract.json
site-agent mcp refresh-adapter --profile my-site
```

## Generated Automation Surfaces

The approved model is the source of truth. After crawl, documentation ingestion, AI-assisted semantic alignment, and human review, `site-agent` should be able to generate three complementary automation outputs.

### Python API

The generated Python API is intended to be the shared execution layer:

```bash
site-agent api build --profile my-site
```

Expected output:

```text
output/my-site/api/
  pyproject.toml
  my_site_client/
    __init__.py
    client.py
    models.py
    runtime.py
    evidence.json
```

The public Python API should expose typed, selector-free methods such as:

```python
from my_site_client import MySiteClient

client = MySiteClient.from_profile("profiles/my-site")
status = client.get_wan_status()
plan = client.set_alert_email("ops@example.test", dry_run=True)
```

Selectors, Playwright locators, and profile-specific adapter details stay private inside the generated runtime/adapter files. Methods include docstrings, constraints, risk metadata, and evidence IDs.

### MCP Server

MCP remains the agent-facing surface:

```bash
site-agent mcp build --profile my-site
site-agent mcp serve --profile my-site
```

Where practical, generated MCP tools should call the generated Python API rather than duplicating browser/action logic. This keeps agent tooling stable while the Python API owns execution, dry-run, confirmation, and adapter behavior.

Install or export client configuration with:

```bash
site-agent mcp import --profile my-site --target json
site-agent mcp import --profile my-site --target codex --apply
site-agent mcp import --profile my-site --target kimi-code
```

`json` emits a standard `mcpServers` block for clients that accept MCP JSON. `codex --apply` updates `~/.codex/config.toml` with a marked block that can be safely refreshed. Other AI coding tools can reuse the same command, args, cwd, and env values even when their config wrapper differs.

Useful options:

```bash
site-agent mcp import --profile my-site --server-name my_site
site-agent mcp import --profile my-site --project-dir /path/to/target-project
site-agent mcp import --profile my-site --python /path/to/target-project/.venv/bin/python
site-agent mcp import --profile my-site --engine-dir /path/to/site-agent
site-agent mcp import --profile my-site --target codex --config ~/.codex/config.toml --apply
```

The generated server is currently a local stdio MCP server. Multiple AI coding tools can share the same generated project and command, but each client usually starts its own MCP process. A centralized one-process MCP service would require an HTTP/SSE transport wrapper.

### Ansible Collection

The generated Ansible collection is the operator-facing surface:

```bash
site-agent ansible build --profile my-site
```

Expected output:

```text
output/my-site/ansible/ansible_collections/site_agent/my_site/
  galaxy.yml
  plugins/
    module_utils/client.py
    modules/
      my_site_facts.py
      my_site_alert_email.py
  playbooks/
    backup.yml
    restore_plan.yml
```

Ansible modules should be thin wrappers around the generated Python API. Modules may claim idempotence only when the model has both current-value read evidence and an approved write/restore path. Write-capable modules must support check mode by using the Python API dry-run path.

Example playbook shape:

```yaml
- hosts: localhost
  gather_facts: false
  tasks:
    - name: Read web UI facts
      site_agent.my_site.my_site_facts:
        profile_path: profiles/my-site

    - name: Set alert email
      site_agent.my_site.my_site_alert_email:
        profile_path: profiles/my-site
        value: ops@example.test
      check_mode: true
```

## Configuration Versioning

`site-agent` is designed to snapshot web UI settings into a small dedicated git repository, then diff or restore those settings later through approved UI tools.

Workflow:

```bash
site-agent config save --profile my-site --repo ../my-site-settings --commit --tag v1
site-agent config coverage --profile my-site --settings-repo ../my-site-settings
site-agent config diff --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-plan --profile my-site --repo ../my-site-settings --ref v1
site-agent config restore-readiness --profile my-site --repo ../my-site-settings --ref v1 --apply --confirm
site-agent config restore --profile my-site --repo ../my-site-settings --ref v1 --mode dry-run
```

Snapshots are deterministic and evidence-backed. Restore planning maps changed settings to generated MCP write or staged-action tools, groups settings by shared forms where possible, and records non-restorable settings explicitly.

Apply mode is guarded:

- the profile must set `risk.write_mode` to `apply`
- `--confirm` is required
- the settings repository must be clean
- the current snapshot must be fresh and match the latest crawl/save cycle
- rollback/current snapshot IDs must exist
- post-restore verification should compare a fresh snapshot against the target ref

Run controlled apply tests against mock or fixture targets before using apply on a real site.

Detailed design: `contracts/config-versioning-design.md`.

## Packaging for Agents

Build a reusable knowledge package after crawl, schema review, MCP generation, and optional config coverage:

```bash
site-agent package build --profile my-site
```

The package includes public schema/tool metadata, interaction graph, ontology, reports, and RAG chunks. Private adapter bindings and profile data are separated under `private/` when included.

As Python API and Ansible generation land, packages should include those generated artifacts or manifests pointing to them, so agents and operators can choose the right surface for the task.

## Distribution

The reusable engine is packaged as the `site-agent` Python distribution. Target-specific generated projects are not bundled into the core package.

Supported delivery paths:

- PyPI package for the `site-agent` CLI and Python modules.
- `pipx` install for developer workstations.
- Docker image for repeatable crawl environments.
- `site-agent package build` zip bundles for generated profile knowledge packages.
- Separate target projects, such as `zte-agent`, for generated MCP/API/Ansible artifacts and settings repos.

Release notes and commands are in [docs/release.md](docs/release.md).
