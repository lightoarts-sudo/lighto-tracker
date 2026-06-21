#!/usr/bin/env bash
# cron runner: executes the 5-minute-wait verify only when
# data/render_deploy_marker.json exists and was modified within the last 10 minutes.
set -euo pipefail

REPO="C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker"
MARKER="${REPO}/data/render_deploy_marker.json"
VERIFIER="${REPO}/scripts/render_verify_5m_wait.sh"
MAX_AGE_SECONDS="${MAX_AGE_SECONDS:-600}"  # 10 minutes

if [[ ! -f "${MARKER}" ]]; then
    exit 0
fi

NOW=$(date +%s)
FILE_MTIME=$(stat -c %Y "${MARKER}" 2>/dev/null || stat -f %m "${MARKER}")
AGE=$(( NOW - FILE_MTIME ))

if (( AGE > MAX_AGE_SECONDS )); then
    exit 0
fi

exec bash "${VERIFIER}" "${MARKER}"
