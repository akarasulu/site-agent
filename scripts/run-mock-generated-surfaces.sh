#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${SITE_AGENT_GENERATED_SURFACES_DIR:-$(mktemp -d)}"
SETTINGS_REPO="$WORKDIR/opsboard-settings"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$WORKDIR"

python3 -m site_agent profile init --name opsboard --base-url https://opsboard.local
cp "$ROOT/profiles/fixtures/mock_app/ontology.seed.json" "$WORKDIR/profiles/opsboard/ontology.seed.json"
cp "$ROOT/profiles/fixtures/mock_app/docs/opsboard-admin-guide.md" "$WORKDIR/profiles/opsboard/docs/opsboard-admin-guide.md"

python3 -m site_agent crawl run --profile opsboard --fixture-site "$ROOT/profiles/fixtures/mock_app/site"
python3 -m site_agent schema review --profile opsboard
python3 -m site_agent api build --profile opsboard
python3 -m site_agent mcp build --profile opsboard
python3 -m site_agent ansible build --profile opsboard
python3 -m site_agent config save --profile opsboard --repo "$SETTINGS_REPO" --commit --tag v1
python3 -m site_agent config coverage --profile opsboard --settings-repo "$SETTINGS_REPO"
python3 -m site_agent quality check --profile opsboard
python3 -m site_agent drift check --profile opsboard
python3 -m site_agent package build --profile opsboard

python3 - <<'PY'
from pathlib import Path
from site_agent.core.storage import read_json

root = Path.cwd()
tools = read_json(root / "output/opsboard/mcp/tools.json")["tools"]
api = read_json(root / "output/opsboard/api/api-spec.json")
ansible = read_json(root / "output/opsboard/ansible/ansible-spec.json")
packages = sorted((root / "output/opsboard/packages").glob("opsboard-*"))
package_dirs = [path for path in packages if path.is_dir()]

print("")
print("Generated surface smoke complete")
print(f"Workspace: {root}")
print(f"MCP tools: {len(tools)} -> {root / 'output/opsboard/mcp/tools.json'}")
print(f"Python API methods: {len(api['methods'])} -> {root / 'output/opsboard/api'}")
print(f"Ansible modules: {len(ansible['modules'])} -> {root / 'output/opsboard/ansible'}")
print(f"Settings repo: {root / 'opsboard-settings'}")
if package_dirs:
    print(f"Knowledge package: {package_dirs[-1]}")
PY
