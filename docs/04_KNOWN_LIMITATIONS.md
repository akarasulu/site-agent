# Known Limitations

This document lists current implementation, environment, validation, and
documentation risks. It should stay honest enough to support release decisions.

## Version And Packaging

| Limitation | Impact | Mitigation |
| --- | --- | --- |
| An already installed editable package may still expose stale metadata until reinstalled. | `importlib.metadata.version("site-agent")` can lag source version in externally managed Python environments. | Refresh in a virtual environment or with `pipx`; source `pyproject.toml` and `site_agent.__version__` agree at `1.9.0`. |
| Crawl4AI is pinned to `0.8.9`. | Newer Python interpreters or native dependencies may fail install or runtime checks. | Prefer Python 3.11-3.13 for Crawl4AI and run `site-agent doctor`. |
| Generated target packages are not distributed through the core PyPI package. | Operators need a separate generated workspace or bundle. | Use `site-agent package build` or separate target repositories. |

## Crawl Coverage

| Limitation | Impact | Mitigation |
| --- | --- | --- |
| Live crawl coverage depends on target UI behavior, auth state, timeouts, overlays, and JavaScript state depth. | 100 percent coverage cannot be guaranteed for arbitrary authenticated sites in one pass. | Run `crawl inventory`, `crawl collect`, `crawl plan`, targeted second passes, `crawl merge`, and `quality check`. |
| Read-only crawling avoids state-changing controls by default. | Some write-only or hidden workflows may remain unmapped. | Use fixture or explicitly approved apply-mode harnesses for write validation. |
| Browser artifacts can contain captured values. | Sharing output may leak sensitive configuration details. | Review output, use redaction patterns, and keep settings repositories private. |

## AI And Evidence

| Limitation | Impact | Mitigation |
| --- | --- | --- |
| AI-backed live discovery needs `SITE_AGENT_AI_PROVIDER=openai` and `OPENAI_API_KEY`, unless `SITE_AGENT_ALLOW_NO_AI=1` is set for offline/debug crawls. | Live autonomous learning may stop early without an AI backend. | Configure OpenAI or run fixture/deterministic workflows. |
| AI suggestions are not authoritative. | Wrong mappings could become public if review and evidence gates are bypassed. | Keep confidence gating, review queue, UI evidence, and docs evidence requirements active. |
| Documentation discovery depends on source availability and model quality. | Domain vocabulary may remain incomplete for poorly documented products. | Add profile docs manually and rerun schema review. |

## Generated Surface Maturity

| Surface | Current limitation | Mitigation |
| --- | --- | --- |
| Python API | Generated package is currently a thin semantic wrapper over tool specs and runtime metadata. | Treat it as the preferred shared execution layer, then extend adapters as capabilities mature. |
| MCP | Stdio server is local-process oriented; no hosted HTTP/SSE transport exists in core. | Use `site-agent mcp import` for local MCP clients; add transport wrappers outside core if needed. |
| Ansible | Modules should claim full idempotence only when current-value reads and write evidence both exist. | Review generated `ansible-spec.json` and run `ansible-test sanity` when available. |
| Restore apply | Apply mode is guarded and should be considered experimental outside controlled fixtures. | Use `restore-plan`, `restore-readiness`, dry-run, and fixture/live smoke tests before enabling writes. |

## Validation Gaps

| Gap | Impact | Recommended check |
| --- | --- | --- |
| Browser-dependent Playwright tests skip when Chromium is unavailable. | Local unit validation can pass while browser launch readiness is unverified. | Run `site-agent install browsers`, `site-agent doctor`, and browser-backed smoke scripts in a browser-ready environment. |
| Live router workflows are opt-in and environment-dependent. | CI cannot prove real-device behavior by default. | Run `scripts/run-router-integration.sh` only with private credentials and approved network access. |
| Browser-backed staged apply tests mutate a mock app by design. | They require Docker and local ports. | Run `scripts/run-mock-staged-actions-e2e.sh` in a controlled environment. |

## Secrets And Sensitive Values

* Credentials must be supplied through environment variables or external secret
  files, not committed profile files.
* `profiles/*/auth/`, generated `output/`, and `settings-repos/` are ignored by
  `.gitignore`, but operators still own private storage and access controls.
* Configuration snapshots preserve captured values by default. This is useful
  for restore and audit, but unsafe for public repositories.
* `site-agent-openai.key` is ignored and points to a local key file in some
  developer workspaces; do not rely on it in CI or shared environments.
