#!/usr/bin/env python3
"""Auto-demote underperforming active strategies from Render production.

Policy:
- Must have >= 30 closed trades (avoid premature demotion).
- Demote if realizedPnl < 0 (net negative).
- Or demote if WR < 35% and realizedPnl < 0.

On demotion:
- Remove from data/active_strategies.json
- Update render.yaml CRYPTO_MICRO_ACTIVE_STRATEGIES
- Update crypto_bot.py _DEFAULT_MICRO_ACTIVE and CONFIG["microActiveStrategies"]
- Update strategy_pool.json status -> demoted
- Send email notification
- Git commit + push
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

try:
    import requests
except ImportError:
    requests = None

ROOT = Path.cwd()
RENDER_URL = os.environ.get("LIGHTO_RENDER_URL", "https://lighto-tracker.onrender.com")
RENDER_PERF = f"{RENDER_URL}/api/crypto/micro/performance"

ACTIVE_FILE = ROOT / "data" / "active_strategies.json"
POOL_FILE = ROOT / "data" / "strategy_pool.json"
RENDER_YAML = ROOT / "render.yaml"
CRYPTO_BOT = ROOT / "crypto_bot.py"
GAPI = Path(r"C:\Users\fuful\.hermes\skills\productivity\google-workspace\scripts\google_api.py")

STATE_FILE = ROOT / "data" / "auto_demote_state.json"

MIN_CLOSED_TRADES = 30
MIN_WR_PCT = 35.0
MAX_PNL = 0.0

HTML_TEMPLATE = """
<h2>LIGHTOARTS 策略自動下架通知</h2>
<p>時間：{now}</p>
<p>共下架 <b>{count}</b> 支表現不佳策略：</p>
<ul>
{items}
</ul>
<p>剩餘 active 策略：<b>{remaining}</b></p>
"""


def load_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
        f.write("\n")


def fetch_performance() -> list[dict[str, Any]]:
    if requests:
        r = requests.get(RENDER_PERF, timeout=30)
        r.raise_for_status()
        return r.json()
    else:
        import urllib.request
        with urllib.request.urlopen(RENDER_PERF, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))


def send_email(subject: str, html: str) -> None:
    if not GAPI.exists():
        print("[auto_demote] google_api.py not found, skip email")
        return
    cmd = [
        sys.executable,
        str(GAPI),
        "--to",
        "propc7358@gmail.com",
        "--subject",
        subject,
        "--html",
        html,
    ]
    env = os.environ.copy()
    env["HERMES_EMAIL_SKIP_TELEGRAM"] = "1"
    p = subprocess.run(cmd, capture_output=True, text=True, env=env)
    if p.returncode != 0:
        print(f"[auto_demote] email send failed: {p.stderr.strip()}")
    else:
        print(f"[auto_demote] email sent: {p.stdout.strip()}")


def read_active_ids() -> list[str]:
    data = load_json(ACTIVE_FILE)
    return list(data.get("strategies", []))


def write_active_ids(ids: list[str]) -> None:
    data = load_json(ACTIVE_FILE)
    data["strategies"] = ids
    save_json(ACTIVE_FILE, data)


def find_deployed_pool_ids(pool: dict, ids: set[str]) -> set[str]:
    found = set()
    for c in pool.get("candidates", []):
        sid = c.get("id") or c.get("strategy_id") or c.get("name")
        if sid in ids:
            found.add(sid)
    return found


def update_render_yaml(ids: list[str]) -> None:
    text = RENDER_YAML.read_text(encoding="utf-8")
    new_env = f'CRYPTO_MICRO_ACTIVE_STRATEGIES: "{",".join(ids)}"'
    # replace the env var line
    import re
    pattern = r'CRYPTO_MICRO_ACTIVE_STRATEGIES: "[^"]*"'
    if re.search(pattern, text):
        text = re.sub(pattern, new_env, text)
    else:
        # fallback append under env
        text = text.replace("env:", "env:\n  " + new_env + "\n  ", 1)
    RENDER_YAML.write_text(text, encoding="utf-8")


def update_crypto_bot(ids: list[str]) -> None:
    text = CRYPTO_BOT.read_text(encoding="utf-8")
    csv = ",".join(ids)
    # 1) _DEFAULT_MICRO_ACTIVE tuple
    import re
    pattern_default = r'"_DEFAULT_MICRO_ACTIVE":\s*\[\s*"[^"]*"(?:\s*,\s*"[^"]*")*\s*\]'
    repl_default = f'"_DEFAULT_MICRO_ACTIVE": [\n        "{csv}"\n    ]'
    if re.search(pattern_default, text):
        text = re.sub(pattern_default, repl_default, text, count=1)
    # 2) CONFIG["microActiveStrategies"] default list
    pattern_config = r'"microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*"[^"]*"\)'
    repl_config = f'"microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", "{csv}")'
    if re.search(pattern_config, text):
        text = re.sub(pattern_config, repl_config, text, count=1)
    CRYPTO_BOT.write_text(text, encoding="utf-8")


def update_pool_demoted(ids: set[str], reason_map: dict[str, str]) -> None:
    pool = load_json(POOL_FILE)
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    for c in pool.get("candidates", []):
        sid = c.get("id") or c.get("strategy_id") or c.get("name")
        if sid in ids:
            c["status"] = "demoted"
            c["demoted_at"] = now
            c["demote_reason"] = reason_map.get(sid, "underperform")
    save_json(POOL_FILE, pool)


def git_commit_push(message: str) -> None:
    subprocess.run(["git", "add", "-A"], cwd=ROOT, check=False)
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=False)
    subprocess.run(["git", "push", "origin", "main"], cwd=ROOT, check=False)


def main() -> int:
    print("[auto_demote] start")
    active_ids = read_active_ids()
    if not active_ids:
        print("[auto_demote] no active strategies")
        return 0

    try:
        perf = fetch_performance()
    except Exception as e:
        print(f"[auto_demote] fetch performance failed: {e}")
        return 1

    perf_map = {row["strategy"]: row for row in perf}
    PERF_NAME_ALIASES = {
        "strategy4_1_breakout_confirmation": "strategy4_breakout_confirmation",
    }

    def perf_for(sid: str) -> dict | None:
        row = perf_map.get(sid)
        if row is None and sid in PERF_NAME_ALIASES:
            row = perf_map.get(PERF_NAME_ALIASES[sid])
        return row

    keep = []
    demote = []
    reasons: dict[str, str] = {}

    for sid in active_ids:
        row = perf_for(sid)
        if row is None:
            # New strategy not yet showing trades; keep it.
            print(f"[auto_demote] {sid}: no performance data yet, keep")
            keep.append(sid)
            continue
        trades = row.get("trades", 0)
        closed = row.get("closedTrades", 0)
        pnl = float(row.get("realizedPnl", 0.0))
        wr = float(row.get("winRate", 0.0))

        if closed < MIN_CLOSED_TRADES:
            print(f"[auto_demote] {sid}: closed={closed} < {MIN_CLOSED_TRADES}, keep")
            keep.append(sid)
            continue

        if pnl < MAX_PNL or wr < MIN_WR_PCT:
            demote.append(sid)
            reason = []
            if pnl < MAX_PNL:
                reason.append(f"pnl={pnl:.2f}")
            if wr < MIN_WR_PCT:
                reason.append(f"WR={wr:.1f}%")
            reasons[sid] = ", ".join(reason)
            print(f"[auto_demote] DEMOTE {sid}: {reasons[sid]}")
        else:
            keep.append(sid)
            print(f"[auto_demote] KEEP {sid}: closed={closed}, WR={wr:.1f}%, pnl={pnl:.2f}")

    if not demote:
        print("[auto_demote] nothing to demote")
        return 0

    # update files
    remaining = [sid for sid in active_ids if sid not in set(demote)]
    write_active_ids(remaining)
    update_render_yaml(remaining)
    update_crypto_bot(remaining)
    update_pool_demoted(set(demote), reasons)

    now_str = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S")
    items = "\n".join(f"<li>{sid} ({reasons.get(sid, '')})</li>" for sid in demote)
    html = HTML_TEMPLATE.format(
        now=now_str,
        count=len(demote),
        items=items,
        remaining=len(remaining),
    )
    send_email("[LIGHTOARTS] 策略自動下架通知", html)

    msg = f"Auto-demote strategies: -{len(demote)} +0 (demote: {', '.join(demote)})"
    try:
        git_commit_push(msg)
    except Exception as e:
        print(f"[auto_demote] git failed: {e}")

    print(f"[auto_demote] done, remaining={len(remaining)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
