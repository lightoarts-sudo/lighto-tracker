#!/usr/bin/env bash
set -euo pipefail

# --- Configuration ---
MARKER_PATH="${1:-data/render_deploy_marker.json}"
MAX_FILE_AGE_SECONDS="${2:-600}"
ALLOWED_TIME_SECONDS=840
LOG_PREFIX="[verify_5m]"

info() { echo "${LOG_PREFIX} [INFO]  $(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { echo "${LOG_PREFIX} [FAIL]  $(date '+%Y-%m-%d %H:%M:%S') $*"; }

# 1) Wait for Render to finish deploying
info "Waiting 5 minutes before verification..."
sleep 300
info "Resuming verification."

# 2) Check marker file existence
if [[ ! -f "${MARKER_PATH}" ]]; then
    fail "Deploy marker not found: ${MARKER_PATH}"
    exit 1
fi
info "Deploy marker found: ${MARKER_PATH}"

# 3) Verify marker recency
NOW=$(date +%s)
FILE_MTIME=$(stat -c %Y "${MARKER_PATH}" 2>/dev/null || stat -f %m "${MARKER_PATH}")
AGE=$(( NOW - FILE_MTIME ))

if (( AGE > MAX_FILE_AGE_SECONDS )); then
    fail "Marker too old: ${AGE}s > ${MAX_FILE_AGE_SECONDS}s"
    exit 1
fi
info "Marker age=${AGE}s (within ${MAX_FILE_AGE_SECONDS}s)."

# 4) Verify deployer process exited 0 within allowed time.
#    Expected marker JSON:
#    {
#      "exit_code": 0,
#      "finished_at": "<ISO-8601 timestamp>",
#      "started_at": "<ISO-8601 timestamp>",
#      "cron_job_id": "06e36790d96b",
#      "service": "lighto-tracker"
#    }
CURRENT_EPOCH=$(date +%s)
EXIT_CODE=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1]))['exit_code'])" "${MARKER_PATH}" 2>/dev/null || echo "")

if [[ -z "${EXIT_CODE}" ]]; then
    fail "Marker missing exit_code."
    exit 1
fi

if (( EXIT_CODE != 0 )); then
    fail "Deploy exited with code ${EXIT_CODE}."
    exit 1
fi

# Check that the deploy finished within the allowed window
FINISHED_AT=$(python3 -c "import json,sys; print(json.load(open(sys.argv[1])).get('finished_at',''))" "${MARKER_PATH}" 2>/dev/null || echo "")

if [[ -n "${FINISHED_AT}" ]]; then
    NOW=$(date +%s)
    FINISHED_EPOCH=$(date -d "${FINISHED_AT}" +%s 2>/dev/null \
                    || date -j -f "%Y-%m-%dT%H:%M:%SZ" "${FINISHED_AT}" +%s 2>/dev/null \
                    || echo "")

    if [[ -n "${FINISHED_EPOCH}" ]]; then
        ELAPSED=$(( NOW - FINISHED_EPOCH ))
        if (( ELAPSED > ALLOWED_TIME_SECONDS )); then
            fail "Deploy finished too long ago: ${ELAPSED}s > ${ALLOWED_TIME_SECONDS}s"
            exit 1
        fi
        info "Deploy completed at ${FINISHED_AT} (${ELAPSED}s ago), within allowed window ${ALLOWED_TIME_SECONDS}s."
    else
        info "WARNING: Could not parse finished_at timestamp '${FINISHED_AT}'; skipping time-window check."
    fi
else
    info "WARNING: Marker missing finished_at; only exit_code is verified."
fi

info "Deploy verified successfully. Exiting 0."
exit 0
