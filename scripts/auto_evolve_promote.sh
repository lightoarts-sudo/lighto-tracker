#!/usr/bin/env bash
set -euo pipefail
cd 'C:\Users\fuful\OneDrive\Desktop\LIGHTOARTS\_render_lighto_tracker'
mkdir -p data/logs
LOG=data/logs/auto_evolve_promote_$(date +%Y%m%d_%H%M%S).log
{
  echo "=== AUTOEVOLVE ==="
  if ! python autoevolve.py; then
    echo "autoevolve failed"
    exit 1
  fi
  echo "=== AUTOPROMOTE ==="
  if ! python autopromote.py; then
    echo "autopromote failed"
    exit 1
  fi
  echo "=== DONE ==="
} > "$LOG" 2>&1
