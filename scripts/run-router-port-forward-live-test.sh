#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$ROOT/.venv/bin/python}"
ROUTER_USER="${SITE_AGENT_ROUTER_USER:-admin}"
ROUTER_PASSWORD="${SITE_AGENT_ROUTER_PASSWORD:-}"
MODE="${1:-plan}"

if [[ "$MODE" != "plan" && "$MODE" != "apply" && "$MODE" != "debug-fill" && "$MODE" != "cleanup" ]]; then
  echo "Usage: $0 [plan|apply|debug-fill|cleanup]" >&2
  exit 2
fi

if [[ "$MODE" == "apply" && "${SITE_AGENT_CONFIRM_LIVE_ROUTER_WRITE:-}" != "create-activate-delete-port-forward" ]]; then
  echo "Refusing live write. Set SITE_AGENT_CONFIRM_LIVE_ROUTER_WRITE=create-activate-delete-port-forward to run apply mode." >&2
  exit 2
fi

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

SITE_AGENT_ROUTER_USER="$ROUTER_USER" \
SITE_AGENT_ROUTER_PASSWORD="$ROUTER_PASSWORD" \
SITE_AGENT_ROUTER_LIVE_MODE="$MODE" \
SITE_AGENT_ROUTER_TEST_NAME="${SITE_AGENT_ROUTER_TEST_NAME:-SA12121}" \
SITE_AGENT_ROUTER_TEST_IP="${SITE_AGENT_ROUTER_TEST_IP:-192.168.1.254}" \
SITE_AGENT_ROUTER_TEST_PORT="${SITE_AGENT_ROUTER_TEST_PORT:-12121}" \
SITE_AGENT_ROUTER_TEST_PROTOCOL="${SITE_AGENT_ROUTER_TEST_PROTOCOL:-TCP}" \
"$PYTHON_BIN" "$ROOT/scripts/router_port_forward_live_check.py"
