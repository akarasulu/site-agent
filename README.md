# site-agent

`site-agent` is a generic, domain-aware website interaction mapper. It creates target profiles, crawls browser applications, extracts forms and actions, aligns UI evidence to domain terms, and generates stable automation surfaces: a Python API, an MCP server, an Ansible collection, OpenAPI/Postman docs, and an explorer portal.

The project core is product-agnostic. Target-specific behavior belongs in profiles and adapters.

## Documentation

- [Overview](docs/00_OVERVIEW.md): project identity, goals, workflow, and
  documentation map.
- [Architecture](docs/01_ARCHITECTURE.md): system design, data flow,
  boundaries, runtime safety, and observability.
- [Technical inventory](docs/02_TECHNICAL_INVENTORY.md): CLI, modules,
  schemas, scripts, fixtures, workflows, and artifacts.
- [Development log](docs/03_DEVELOPMENT_LOG.md): architecture-relevant
  decisions, sprint checkpoints, and validation evidence.
- [Known limitations](docs/04_KNOWN_LIMITATIONS.md): implementation,
  environment, validation, and safety risks.
- [Roadmap](docs/05_ROADMAP.md): completed work, phase status, and near-term
  priorities.
- [Learning guide](docs/06_LEARNING_GUIDE.md): path from local setup to
  advanced generated automation.
- [Execution guide](docs/07_EXECUTION_GUIDE.md): install, environment,
  workflow, validation, and release commands.
- [Troubleshooting](docs/08_TROUBLESHOOTING.md): common failures and fixes.
- [Validation checklist](docs/09_VALIDATION_CHECKLIST.md): checks for docs,
  runtime, coverage, generated surfaces, config versioning, and release.
- [Final report](docs/10_FINAL_REPORT.md): current state, metrics, risks, and
  release-readiness summary.
- [Research reports](docs/research/README.md): paper-by-paper crawler
  technique summaries and implementation mapping.
- [Release and packaging](docs/release.md): PyPI, pipx, Docker, and
  generated-target delivery.
- [Config versioning design](contracts/config-versioning-design.md): save,
  diff, restore-plan, and restore guardrails.
- [Generated automation surfaces](contracts/generated-automation-surfaces.md):
  Python API, MCP, and Ansible generation contracts.
- [Interaction flow design](contracts/interaction-flow-design.md): staged
  add/edit/delete flow discovery.
- [Research technique implementation plan](contracts/research-technique-implementation-plan.md):
  implementation sprints from crawler research threads.

## Quick Start

```bash
site-agent profile init --name my-site --base-url https://example.com
site-agent auth setup --profile my-site
site-agent crawl run --profile my-site
site-agent schema review --profile my-site
site-agent api build --profile my-site
site-agent mcp build --profile my-site
site-agent docs build --profile my-site
site-agent api serve --profile my-site
site-agent explorer serve --profile my-site
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
6. Generate the Python API, MCP server, OpenAPI/Postman docs, explorer portal,
   and Ansible collection from the approved model.
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

The `crawl` extra installs the default Playwright runtime and the pinned
Crawl4AI backend. Crawl4AI is optional at runtime and is selected explicitly for
live crawls:

```bash
site-agent crawl run --profile my-site --backend crawl4ai
```

Use the default `playwright` backend when you need `site-agent`'s deeper
JS-state probing and dynamic form-flow inspection. Use `crawl4ai` for a
rendered HTML collection pass that benefits from Crawl4AI's session-aware
browser orchestration while still preserving `site-agent`'s canonical evidence,
schema, API, MCP, and Ansible contracts. Crawl4AI 0.8.9 currently works best on
Python 3.11-3.13; if `site-agent doctor` reports native dependency failures on a
newer interpreter, create the project venv with a supported Python version.

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

Run the unit suite with branch coverage:

```bash
python -m pytest -q --cov=site_agent --cov-branch --cov-report=term-missing:skip-covered --cov-report=xml
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

Router validation is opt-in and uses an external profile under
`profiles/examples/zte-router`.

```bash
scripts/run-router-integration.sh
```

The script reads `SITE_AGENT_ROUTER_PASSWORD` or prompts silently, stores
browser session state only in the temporary run workspace, builds the semantic
explorer, writes MCP smoke artifacts under `output/zte-router/reports/`, and
removes session state after the crawl. Router-facing commands may need a
network grant when run from a sandboxed agent environment.

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
site-agent explorer build --profile zte-router
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

AI is required for autonomous live learning unless `SITE_AGENT_ALLOW_NO_AI=1` is set for an explicit offline/debug crawl. Fixture crawls and deterministic tests can still run without AI. The default path remains evidence-gated: AI may propose domain concepts, navigation targets, mappings, and descriptions, but public mappings still require evidence IDs and confidence gating.

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

Live crawl learning uses a persistent research session at `output/<profile>/reports/research-session.json`. The intended loop is:

- Infer the site/product domain from entry-page or dashboard text.
- Research domain terminology from official docs first, then standards or Wikipedia-style catalogs, vendor/ISP support pages, and lower-confidence forum usage hints.
- Extract a domain dictionary and ontology before the first navigation pass.
- Crawl once using that ontology as nomenclature.
- Analyze weak or vague model areas, such as ontology terms with no mapped UI evidence or forms whose purpose is unclear.
- Produce directional crawl targets that name specific UI branches and labels to probe next, rather than doing a full broad recrawl.
- Feed those targets into `site-agent crawl plan` and then `site-agent crawl run --use-plan latest`.

For a residential router, the research session should converge on home-gateway/networking concepts such as WAN, LAN, Wi-Fi, DHCP, DNS, NAT, port forwarding, virtual server, firewall, DMZ, UPnP, DDNS, diagnostics, logs, firmware, and account management. Later passes should focus attention where the model is weakest, for example `Internet > Security` with labels like NAT, Virtual Server, Port Forwarding, Port Binding, and UPnP when port-forwarding concepts are missing.

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

Generate consumer-facing API docs for a profile:

```bash
site-agent docs build --profile my-site
```

That writes OpenAPI 3.1, a Postman collection, a Postman environment, and a
generated API reference plus quickstart, Python, MCP, and Ansible docs under
`output/my-site/docs/` and `output/my-site/postman/`. The OpenAPI contract
describes the selector-free site-agent API bridge, not raw website selectors.

Serve the generated local HTTP bridge when you want Swagger UI or Postman to
try requests:

```bash
site-agent api serve --profile my-site
```

Build or serve the generated explorer portal when you want Swagger, Postman,
Python, MCP, Ansible, and audit links in one browser view:

```bash
site-agent explorer build --profile my-site
site-agent explorer serve --profile my-site
```

The bridge exposes `GET /health`, `GET /openapi.json`, and
`POST /methods/<generated_method>`. Request bodies use this shape:

```json
{
  "args": {},
  "browser": false,
  "mode": "dry-run"
}
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
site-agent api serve --profile my-site
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

OpenAPI and Postman artifacts are generated beside the Python API and MCP
package:

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

Use `site-agent api serve --profile my-site` to run the local bridge behind
those docs, and `site-agent explorer serve --profile my-site` to open the
consumer-facing portal.

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

The generated server is currently a local stdio MCP server. It supports standard MCP `Content-Length` message framing and ignores notifications such as `notifications/initialized`, so clients can complete the initialize and tool-list handshake reliably. Multiple AI coding tools can share the same generated project and command, but each client usually starts its own MCP process. A centralized one-process MCP service would require an HTTP/SSE transport wrapper.

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
