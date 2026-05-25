#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKDIR="${SITE_AGENT_STAGED_E2E_DIR:-$(mktemp -d)}"
IMAGE="${SITE_AGENT_MOCK_IMAGE:-site-agent-opsboard}"
PORT="${SITE_AGENT_MOCK_PORT:-18080}"
DOCKER="${DOCKER:-sudo docker}"
PYTHON="${SITE_AGENT_PYTHON:-$ROOT/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="python3"
fi
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"

$DOCKER build -t "$IMAGE" "$ROOT/profiles/fixtures/mock_app"
CONTAINER="$($DOCKER run -d --rm -p "127.0.0.1:${PORT}:8080" "$IMAGE")"
cleanup() {
  $DOCKER rm -f "$CONTAINER" >/dev/null 2>&1 || true
}
trap cleanup EXIT

"$PYTHON" - "$PORT" <<'PY'
import sys
import time
from urllib.request import urlopen

port = sys.argv[1]
deadline = time.monotonic() + 20
while time.monotonic() < deadline:
    try:
        with urlopen(f"http://127.0.0.1:{port}/items.html", timeout=1) as response:
            if response.status == 200:
                raise SystemExit(0)
    except Exception:
        time.sleep(0.2)
raise SystemExit("mock container did not become ready")
PY

cd "$WORKDIR"
"$PYTHON" -m site_agent profile init --name opsboard --base-url "http://127.0.0.1:${PORT}/index.html"
cp "$ROOT/profiles/fixtures/mock_app/ontology.seed.json" "$WORKDIR/profiles/opsboard/ontology.seed.json"
cp "$ROOT/profiles/fixtures/mock_app/docs/opsboard-admin-guide.md" "$WORKDIR/profiles/opsboard/docs/opsboard-admin-guide.md"
"$PYTHON" -m site_agent auth setup --profile opsboard --username-env OPSBOARD_USER --password-env OPSBOARD_PASSWORD
"$PYTHON" -m site_agent crawl run --profile opsboard --probe-budget-seconds 30
"$PYTHON" -m site_agent schema review --profile opsboard
"$PYTHON" -m site_agent mcp build --profile opsboard --include-writes

cat > create.json <<'JSON'
{"item_name":"SA12121","service_port":"12121","enabled":false,"dry_run":false,"confirm":true}
JSON
cat > match.json <<'JSON'
{"item_match":{"item_name":"SA12121"},"dry_run":false,"confirm":true}
JSON

"$PYTHON" -m site_agent mcp call --profile opsboard --tool create_item --args-json create.json --mode apply --browser
"$PYTHON" - "$PORT" false <<'PY'
import json
import sys
from urllib.request import urlopen

port, expected = sys.argv[1], sys.argv[2].lower() == "true"
items = json.loads(urlopen(f"http://127.0.0.1:{port}/api/items", timeout=3).read().decode())["items"]
assert items == [{"item_name": "SA12121", "service_port": "12121", "enabled": expected}], items
PY

"$PYTHON" -m site_agent mcp call --profile opsboard --tool activate_item --args-json match.json --mode apply --browser
"$PYTHON" - "$PORT" true <<'PY'
import json
import sys
from urllib.request import urlopen

port, expected = sys.argv[1], sys.argv[2].lower() == "true"
items = json.loads(urlopen(f"http://127.0.0.1:{port}/api/items", timeout=3).read().decode())["items"]
assert items[0]["enabled"] is expected, items
PY

"$PYTHON" -m site_agent mcp call --profile opsboard --tool deactivate_item --args-json match.json --mode apply --browser
"$PYTHON" - "$PORT" false <<'PY'
import json
import sys
from urllib.request import urlopen

port, expected = sys.argv[1], sys.argv[2].lower() == "true"
items = json.loads(urlopen(f"http://127.0.0.1:{port}/api/items", timeout=3).read().decode())["items"]
assert items[0]["enabled"] is expected, items
PY

"$PYTHON" -m site_agent mcp call --profile opsboard --tool delete_item --args-json match.json --mode apply --browser
"$PYTHON" - "$PORT" <<'PY'
import json
import sys
from urllib.request import urlopen

items = json.loads(urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/items", timeout=3).read().decode())["items"]
assert items == [], items
PY

echo "Staged action E2E artifacts written to $WORKDIR/output/opsboard"
