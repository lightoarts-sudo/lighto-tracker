#!/usr/bin/env bash
# Helper: write deploy marker after a successful Render deploy.
# Call this from deploy job 06e36790d96b.
set -euo pipefail

REPO="C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker"
MARKER="${REPO}/data/render_deploy_marker.json"

STARTED_AT="${1:-$(date -u +%Y-%m-%dT%H:%M:%SZ)}"
EXIT_CODE="${2:-0}"

mkdir -p "$(dirname "${MARKER}")"

NOW=$(date +%s)
NOW_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)

python3 - <<PY
import json, sys
marker = {
    "exit_code": ${EXIT_CODE},
    "finished_at": "${NOW_ISO}",
    "started_at": "${STARTED_AT}",
    "cron_job_id": "06e36790d96b",
    "service": "lighto-tracker"
}
print(json.dumps(marker, indent=2))
PY > "${MARKER}"

echo "Wrote deploy marker to ${MARKER} (exit_code=${EXIT_CODE})"
