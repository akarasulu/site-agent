#!/usr/bin/env bash
set -euo pipefail

BASE_URL="${SITE_AGENT_ROUTER_URL:-https://192.168.1.1}"
USERNAME="${SITE_AGENT_ROUTER_USER:-admin}"
PASSWORD_ENV="${SITE_AGENT_ROUTER_PASSWORD_ENV:-SITE_AGENT_ROUTER_PASSWORD}"
OUT_DIR="${SITE_AGENT_ROUTER_OUT_DIR:-$(mktemp -d /tmp/site-agent-zte-XXXXXX)}"

mkdir -p "$OUT_DIR"

PASSWORD="${!PASSWORD_ENV:-}"
if [[ -z "$PASSWORD" ]]; then
  if [[ -t 0 ]]; then
    IFS= read -r -s PASSWORD
    printf "\n" >&2
  else
    IFS= read -r PASSWORD
  fi
fi
if [[ -z "$PASSWORD" ]]; then
  echo "Router password was not provided on stdin or in $PASSWORD_ENV." >&2
  exit 2
fi

COOKIE_JAR="$OUT_DIR/cookies.txt"
LOGIN_PAGE="$OUT_DIR/login-page.html"
LOGIN_ENTRY="$OUT_DIR/login-entry.json"
LOGIN_TOKEN="$OUT_DIR/login-token.xml"
LOGIN_RESPONSE="$OUT_DIR/login-response.json"
HOME_PAGE="$OUT_DIR/post-login-home.html"
SUMMARY="$OUT_DIR/summary.json"

curl -k -sS --max-time 10 -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/" -o "$LOGIN_PAGE"
curl -k -sS --max-time 10 -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/?_type=loginData&_tag=login_entry" -o "$LOGIN_ENTRY"
curl -k -sS --max-time 10 -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/?_type=loginData&_tag=login_token" -o "$LOGIN_TOKEN"

SESSION_TOKEN="$(python3 - "$LOGIN_ENTRY" <<'PY'
import json
import sys

print(json.load(open(sys.argv[1], encoding="utf-8")).get("sess_token", ""))
PY
)"
if [[ -z "$SESSION_TOKEN" ]]; then
  echo "Could not read sess_token from login_entry response." >&2
  exit 3
fi

SALT="$(python3 - "$LOGIN_TOKEN" <<'PY'
import re
import sys

text = open(sys.argv[1], encoding="utf-8", errors="replace").read()
match = re.search(r">([^<>]+)<", text)
print(match.group(1) if match else "")
PY
)"
if [[ -z "$SALT" ]]; then
  echo "Could not read login token XML body." >&2
  exit 4
fi

HASH="$(PASSWORD="$PASSWORD" SALT="$SALT" python3 - <<'PY'
import hashlib
import os

print(hashlib.sha256((os.environ["PASSWORD"] + os.environ["SALT"]).encode("utf-8")).hexdigest())
PY
)"
unset PASSWORD

curl -k -sS --max-time 10 \
  -c "$COOKIE_JAR" -b "$COOKIE_JAR" \
  -X POST \
  --data-urlencode "Username=$USERNAME" \
  --data-urlencode "Password=$HASH" \
  --data-urlencode "_sessionTOKEN=$SESSION_TOKEN" \
  --data-urlencode "action=login" \
  "$BASE_URL/?_type=loginData&_tag=login_entry" \
  -o "$LOGIN_RESPONSE"

STATUS="$(python3 - "$LOGIN_RESPONSE" <<'PY'
import json
import sys

data = json.load(open(sys.argv[1], encoding="utf-8"))
print("authenticated" if data.get("login_need_refresh") is True else "not_authenticated")
PY
)"

if [[ "$STATUS" == "authenticated" ]]; then
  curl -k -sS --max-time 10 -c "$COOKIE_JAR" -b "$COOKIE_JAR" "$BASE_URL/" -o "$HOME_PAGE"
else
  : > "$HOME_PAGE"
fi

python3 - "$BASE_URL" "$USERNAME" "$STATUS" "$LOGIN_PAGE" "$HOME_PAGE" "$OUT_DIR" "$SUMMARY" <<'PY'
import html
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

base_url, username, status, login_page, home_page, out_dir, summary = sys.argv[1:]
login_html = Path(login_page).read_text(encoding="utf-8", errors="replace")
home_html = Path(home_page).read_text(encoding="utf-8", errors="replace")
title_match = re.search(r"<title>(.*?)</title>", login_html, re.I | re.S)
title = html.unescape(title_match.group(1).strip()) if title_match else ""
result = {
    "base_url": base_url,
    "username": username,
    "status": status,
    "product_title": title,
    "login_inputs": len(re.findall(r"<input\b", login_html, re.I)),
    "post_login_bytes": len(home_html),
    "artifacts_dir": out_dir,
    "generated_at": datetime.now(timezone.utc).isoformat(),
}
Path(summary).write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(result, indent=2, sort_keys=True))
PY
