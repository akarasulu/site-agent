#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${SITE_AGENT_E2E_DIR:-$(mktemp -d)}"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

cd "$WORKDIR"
python3 -m site_agent profile init --name opsboard --base-url https://opsboard.local
cp "$ROOT/profiles/fixtures/mock_app/ontology.seed.json" "$WORKDIR/profiles/opsboard/ontology.seed.json"
cp "$ROOT/profiles/fixtures/mock_app/docs/opsboard-admin-guide.md" "$WORKDIR/profiles/opsboard/docs/opsboard-admin-guide.md"
python3 -m site_agent auth setup --profile opsboard --username-env OPSBOARD_USER --password-env OPSBOARD_PASSWORD
python3 -m site_agent crawl run --profile opsboard --fixture-site "$ROOT/profiles/fixtures/mock_app/site"
python3 -m site_agent schema review --profile opsboard
python3 -m site_agent debug report --profile opsboard
python3 -m site_agent crawl plan --profile opsboard
python3 -m site_agent crawl run --profile opsboard --fixture-site "$ROOT/profiles/fixtures/mock_app/site" --use-plan latest --max-planned-labels 25 --probe-budget-seconds 120 --target-depth 3
python3 -m site_agent crawl merge --profile opsboard
python3 -m site_agent schema review --profile opsboard
python3 -m site_agent debug report --profile opsboard
python3 -m site_agent crawl compare --profile opsboard
python3 -m site_agent ai analyze --profile opsboard --max-elements 12
python3 -m site_agent mcp build --profile opsboard
python3 -m site_agent actions report --profile opsboard
python3 -m site_agent quality check --profile opsboard
python3 -m site_agent drift check --profile opsboard

echo "Mock E2E artifacts written to $WORKDIR/output/opsboard"
