# ZTE Router Validation Profile

This is an external validation profile for a local ZTE H3600-class router UI. It is not core product logic.

Secrets policy:

- Do not store router passwords in this directory.
- Use `SITE_AGENT_ROUTER_PASSWORD` or stdin for scripts.
- Browser storage state belongs under `profiles/zte-router/auth/` in a temporary workspace, not in this example profile.

Run a read-only smoke login from WSL:

```bash
SITE_AGENT_ROUTER_PASSWORD='...' scripts/zte-router-smoke.sh
```

Run the opt-in pytest integration:

```bash
SITE_AGENT_RUN_ROUTER_TESTS=1 SITE_AGENT_ROUTER_PASSWORD='...' .venv/bin/python -m pytest tests/integration_router
```
