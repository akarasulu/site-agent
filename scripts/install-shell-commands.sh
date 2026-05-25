#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BIN_DIR="${SITE_AGENT_BIN_DIR:-$HOME/.local/bin}"
VENV_DIR="${SITE_AGENT_INSTALL_VENV:-$HOME/.local/share/site-agent/venv}"
INSTALL_EXTRAS="${SITE_AGENT_INSTALL_EXTRAS:-crawl}"
INSTALL_PLAYWRIGHT="${SITE_AGENT_INSTALL_PLAYWRIGHT:-1}"

usage() {
  cat <<'EOF'
Usage: scripts/install-shell-commands.sh [--bin-dir DIR] [--venv-dir DIR] [--no-playwright]

Installs the site-agent shell command for the current user without sudo:

  ~/.local/bin/site-agent -> ~/.local/share/site-agent/venv/bin/site-agent

Environment overrides:
  SITE_AGENT_BIN_DIR
  SITE_AGENT_INSTALL_VENV
  SITE_AGENT_INSTALL_EXTRAS
  SITE_AGENT_INSTALL_PLAYWRIGHT=0
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --bin-dir)
      BIN_DIR="$2"
      shift 2
      ;;
    --venv-dir)
      VENV_DIR="$2"
      shift 2
      ;;
    --no-playwright)
      INSTALL_PLAYWRIGHT=0
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

mkdir -p "$BIN_DIR" "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"
"$VENV_DIR/bin/python" -m pip install --upgrade pip
if [[ -n "$INSTALL_EXTRAS" ]]; then
  "$VENV_DIR/bin/python" -m pip install -e "$ROOT[$INSTALL_EXTRAS]"
else
  "$VENV_DIR/bin/python" -m pip install -e "$ROOT"
fi
if [[ "$INSTALL_PLAYWRIGHT" == "1" ]]; then
  "$VENV_DIR/bin/python" -m playwright install chromium
fi

ln -sfn "$VENV_DIR/bin/site-agent" "$BIN_DIR/site-agent"

echo "Installed: $BIN_DIR/site-agent"
if [[ ":$PATH:" != *":$BIN_DIR:"* ]]; then
  echo "Add this to your shell profile if needed:"
  echo "  export PATH=\"$BIN_DIR:\$PATH\""
fi
echo "Try: site-agent --help"

