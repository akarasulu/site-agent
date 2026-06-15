# Troubleshooting

This guide maps common failures to the most direct checks and fixes.

## Installation

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `site-agent: command not found` | The package is not installed or `~/.local/bin` is not on `PATH`. | Run `python -m pip install -e ".[crawl]"` or `scripts/install-shell-commands.sh`, then add the printed `PATH` export if needed. |
| `No module named playwright` | The `crawl` extra was not installed. | Run `python -m pip install -e ".[crawl]"`. |
| Browser launch fails | Playwright browser binaries are missing. | Run `site-agent install browsers` or `python -m playwright install chromium`. |
| Crawl4AI import fails | Native or Python-version dependency mismatch. | Use Python 3.11-3.13 for Crawl4AI workflows or use the default Playwright backend. |

## Profile And Auth

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `Profile '<name>' does not exist` | Profile was not initialized in the current workspace. | Run `site-agent profile init --name <name> --base-url https://example.com`. |
| Live target redirects to login | Auth setup only stores references; browser storage state may be missing or stale. | Recreate login/session state for the profile and rerun `site-agent auth setup`. |
| Credentials appear in output | A profile, script, or target returned sensitive text. | Stop sharing artifacts, add redaction patterns to the profile, and keep `output/` and settings repositories private. |

## Crawl

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Live crawl refuses to run without AI | Live discovery requires an AI backend unless explicitly overridden. | Set `SITE_AGENT_AI_PROVIDER=openai` and `OPENAI_API_KEY`, or set `SITE_AGENT_ALLOW_NO_AI=1` for an offline/debug crawl. |
| URL rejected by crawler | Host is outside the profile allowlist. | Check `profiles/<name>/profile.json` and adjust host allowlist deliberately. |
| Crawl finds too few pages | JavaScript state depth, time budget, overlays, or navigation labels limited discovery. | Run `crawl inventory`, `crawl plan`, `crawl run --use-plan latest`, `crawl collect`, and `crawl merge`. |
| `crawl collect` exits non-zero for incomplete coverage | Queued or failed paths remain. | Increase `--probe-budget-seconds`, `--target-depth`, or `--max-states`, or use `--allow-incomplete` for exploratory output. |
| Browser clicks risky controls | Navigation safety filtering is too permissive for the target. | Add profile `click_deny_patterns` and keep `read_only` enabled. |

## Schema And Mapping

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Many mappings stay in review | Ontology terms or documentation evidence are incomplete. | Add profile docs or ontology seed terms, run `docs discover`, then `schema review`. |
| Generated names are too generic | UI labels lack domain context or docs. | Add better domain docs and use `schema edit` for important mappings. |
| AI mapping seems wrong | AI suggestion exceeded lexical match but evidence is weak. | Reject or edit the mapping; AI is advisory only. |

## Generated MCP

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| MCP client cannot initialize | Client config points to wrong Python, project dir, or package dir. | Regenerate config with `site-agent mcp import --profile <name> --target json` and verify `cwd`, command, and args. |
| MCP `tools/list` hangs | Client/server stdio framing mismatch or stale generated package. | Rebuild with `site-agent mcp build --profile <name>` and confirm generated runtime supports `Content-Length` framing. |
| Tool call returns dry-run output | Write-like calls default to dry-run. | Pass `--mode apply --confirm` only when profile policy and readiness checks allow it. |
| Tool name changed after drift | Semantic identity may have changed or capability normalization changed. | Use `site-agent mcp diff --baseline ...` and `mcp refresh-adapter`; bump versions for real breaking changes. |

## Generated Python API And Ansible

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Generated API package import fails | Output package path is not on `PYTHONPATH` or package was not generated. | Run `site-agent mcp build --profile <name>` or `site-agent api build --profile <name>` and install/import from `output/<name>/api/`. |
| Ansible module claims are too weak | Idempotence evidence is incomplete. | Add current-value read coverage and write/restore evidence, then rebuild. |
| `ansible-test` is unavailable | Ansible tooling is not installed in the current environment. | Install Ansible test tooling or validate generated modules with a narrower local smoke check. |

## Configuration Versioning

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| `config save` writes few settings | Snapshot lacks readable values or schema mappings. | Improve crawl coverage and run `schema review`, then rerun `config coverage`. |
| Changed setting is non-restorable | No approved write/staged-action tool maps to the setting. | Review generated action tools, add evidence, or keep the setting manual. |
| Restore readiness fails | Dirty settings repo, stale snapshot, missing plan, risk policy block, or confirmation missing. | Read the readiness report and rerun with a fresh snapshot, clean repo, and explicit `--confirm` when appropriate. |
| Apply restore skips high-risk steps | Profile policy or confirmation does not permit high-risk changes. | Keep high-risk changes manual unless the profile explicitly approves them. |

## Router Validation

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| Router scripts fail immediately | `SITE_AGENT_ROUTER_PASSWORD` is not set and stdin is unavailable. | Export the password in a private shell or run interactively. |
| Router page cannot be reached | Private network or TLS issue. | Verify routing, base URL, and `ignore_https_errors` settings. |
| Live write test refuses to run | Confirmation guard is missing. | Set `SITE_AGENT_CONFIRM_LIVE_ROUTER_WRITE=create-activate-delete-port-forward` only in a controlled test. |

## Validation

Run these when the project behaves unexpectedly:

```bash
site-agent doctor
python -m site_agent --help
git diff --check
python -m pytest -q
site-agent benchmark run --fail-on-error
```

If a failure appears after a source change, rerun the narrow failing command
first, then expand to adjacent tests only if the fix touches shared behavior.
