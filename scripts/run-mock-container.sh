#!/usr/bin/env bash
set -euo pipefail

IMAGE="${SITE_AGENT_MOCK_IMAGE:-site-agent-opsboard}"
PORT="${SITE_AGENT_MOCK_PORT:-8080}"
DOCKER="${DOCKER:-sudo docker}"

$DOCKER build -t "$IMAGE" profiles/fixtures/mock_app
$DOCKER run --rm -p "$PORT:8080" "$IMAGE"
