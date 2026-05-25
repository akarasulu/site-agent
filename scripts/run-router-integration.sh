#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${SITE_AGENT_ROUTER_WORKDIR:-$(mktemp -d /tmp/site-agent-router-XXXXXX)}"
SITE_AGENT_BIN="${SITE_AGENT_BIN:-$ROOT/.venv/bin/site-agent}"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
ROUTER_USER="${SITE_AGENT_ROUTER_USER:-admin}"
ROUTER_PASSWORD="${SITE_AGENT_ROUTER_PASSWORD:-}"

if [[ -z "$ROUTER_PASSWORD" ]]; then
  if [[ -t 0 ]]; then
    IFS= read -r -s -p "Router password: " ROUTER_PASSWORD
    printf "\n" >&2
  else
    IFS= read -r ROUTER_PASSWORD
  fi
fi
if [[ -z "$ROUTER_PASSWORD" ]]; then
  echo "Router password was not provided on stdin or in SITE_AGENT_ROUTER_PASSWORD." >&2
  exit 2
fi

export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
AI_PROVIDER_VALUE="${SITE_AGENT_AI_PROVIDER:-none}"

cd "$WORKDIR"
"$SITE_AGENT_BIN" profile import-example "$ROOT/profiles/examples/zte-router"
if [[ "${SITE_AGENT_DISCOVER_DOCS:-1}" == "1" ]]; then
  KEY_FILE="${OPENAI_API_KEY_FILE:-$ROOT/site-agent-openai.key}"
  if [[ -n "${OPENAI_API_KEY:-}" || -s "$KEY_FILE" ]]; then
    if [[ -z "${OPENAI_API_KEY:-}" ]]; then
      export OPENAI_API_KEY="$(tr -d '\r\n' < "$KEY_FILE")"
    fi
    AI_PROVIDER_VALUE="${SITE_AGENT_AI_PROVIDER:-openai}"
    SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" docs discover --profile zte-router --product-hint "ZTE H3600 V9 router web UI user guide manual" --max-sources 3
  fi
fi
mkdir -p profiles/zte-router/auth

login_router() {
SITE_AGENT_ROUTER_USER="$ROUTER_USER" SITE_AGENT_ROUTER_PASSWORD="$ROUTER_PASSWORD" "$PYTHON_BIN" - <<'PY'
import os
from pathlib import Path
from playwright.sync_api import sync_playwright

base_url = "https://192.168.1.1"
state_path = Path("profiles/zte-router/auth/storage-state.json")
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    context = browser.new_context(ignore_https_errors=True)
    page = context.new_page()
    page.goto(base_url, wait_until="domcontentloaded", timeout=15000)
    page.fill("#Frm_Username", os.environ.get("SITE_AGENT_ROUTER_USER", "admin"))
    page.fill("#Frm_Password", os.environ["SITE_AGENT_ROUTER_PASSWORD"])
    page.click("#LoginId")
    page.wait_for_timeout(3000)
    context.storage_state(path=str(state_path))
    browser.close()
PY
}

login_router

SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" crawl run --profile zte-router
SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" schema review --profile zte-router
"$SITE_AGENT_BIN" debug report --profile zte-router --limit 8
SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" crawl plan --profile zte-router --limit 8
if [[ "${SITE_AGENT_ROUTER_PLANNED_SECOND_PASS:-1}" == "1" ]]; then
  login_router
  SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" crawl run --profile zte-router --use-plan latest --max-planned-labels "${SITE_AGENT_ROUTER_MAX_PLANNED_LABELS:-25}" --probe-budget-seconds "${SITE_AGENT_ROUTER_PROBE_SECONDS:-180}" --target-depth "${SITE_AGENT_ROUTER_TARGET_DEPTH:-3}"
  "$SITE_AGENT_BIN" crawl merge --profile zte-router
  SITE_AGENT_AI_PROVIDER="$AI_PROVIDER_VALUE" SITE_AGENT_AI_TIMEOUT="${SITE_AGENT_AI_TIMEOUT:-120}" "$SITE_AGENT_BIN" schema review --profile zte-router
  "$SITE_AGENT_BIN" debug report --profile zte-router --limit 8
  "$SITE_AGENT_BIN" crawl compare --profile zte-router
fi
"$SITE_AGENT_BIN" mcp build --profile zte-router
"$SITE_AGENT_BIN" actions report --profile zte-router
"$SITE_AGENT_BIN" quality check --profile zte-router --fail-on-error
"$SITE_AGENT_BIN" mcp call --profile zte-router --tool get_wan_status
"$SITE_AGENT_BIN" mcp call --profile zte-router --tool get_software_version
unset ROUTER_PASSWORD

rm -f profiles/zte-router/auth/storage-state.json
echo "Router integration artifacts written to $WORKDIR/output/zte-router"
