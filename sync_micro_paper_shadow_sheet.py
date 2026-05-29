import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SHEET_ID = "1It3yl9mbRPMqn3QMhUbwyL4b0OATPnGuDq7MEvgRtEA"
SHEET_RANGE_IDS = "trades!A:A"
SHEET_APPEND_RANGE = "trades!A:U"
GOOGLE_API = r"C:/Users/fuful/.hermes/skills/productivity/google-workspace/scripts/google_api.py"
MICRO_TRADES_URL = "https://lighto-tracker.onrender.com/api/crypto/micro/trades"
MICRO_RUN_ONCE_URL = "https://lighto-tracker.onrender.com/api/crypto/micro/run-once"
STRATEGIES = {
    "strategy21_multi_tf_intersection_ema9_bounce",
    "strategy22_2h_strength_breakout_retest",
    "strategy23_top1h_clean_early_breakout",
}
STATE_PATH = Path("data/micro_paper_shadow_sheet_sync_state.json")
TAIPEI = ZoneInfo("Asia/Taipei")


def fetch_json(url, method="GET"):
    req = urllib.request.Request(url, method=method, headers={"User-Agent": "lighto-sheet-sync/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_google_api(args):
    proc = subprocess.run([sys.executable, GOOGLE_API, *args], text=True, capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout or "null")


def load_existing_ids():
    rows = run_google_api(["sheets", "get", SHEET_ID, SHEET_RANGE_IDS]) or []
    ids = set()
    for row in rows[1:]:
        if row:
            ids.add(str(row[0]))
    return ids


def trade_url(trade_id):
    return f"https://lighto-tracker.onrender.com/micro#trade-{trade_id}"


def to_row(trade):
    ts_utc = trade.get("ts") or ""
    ts_tpe = ""
    if ts_utc:
        dt = datetime.fromisoformat(ts_utc.replace("Z", "+00:00"))
        ts_tpe = dt.astimezone(TAIPEI).isoformat(timespec="seconds")
    return [
        str(trade.get("id", "")),
        ts_utc,
        ts_tpe,
        trade.get("strategy", ""),
        trade.get("inst_id", ""),
        trade.get("side", ""),
        trade.get("price", ""),
        trade.get("quantity", ""),
        trade.get("quote_amount", ""),
        trade.get("reason", ""),
        trade.get("pnl", ""),
        trade.get("pnlPct", ""),
        trade.get("ma60", ""),
        trade.get("volume_ratio", ""),
        trade.get("pct5", ""),
        trade.get("pct15", ""),
        datetime.now(timezone.utc).isoformat(timespec="seconds"),
        MICRO_TRADES_URL,
        "paper/shadow strategy21-23",
        trade_url(trade.get("id", "")),
        json.dumps(trade, ensure_ascii=False, separators=(",", ":")),
    ]


def main():
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    try:
        fetch_json(MICRO_RUN_ONCE_URL, method="POST")
    except Exception as exc:
        print(f"WARN run-once failed: {exc}", file=sys.stderr)
    trades = fetch_json(MICRO_TRADES_URL)
    existing = load_existing_ids()
    selected = [t for t in trades if t.get("strategy") in STRATEGIES and str(t.get("id")) not in existing]
    selected.sort(key=lambda t: int(t.get("id") or 0))
    if selected:
        run_google_api(["sheets", "append", SHEET_ID, SHEET_APPEND_RANGE, "--values", json.dumps([to_row(t) for t in selected], ensure_ascii=False)])
    state = {
        "lastRunAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sheetId": SHEET_ID,
        "sheetUrl": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit",
        "fetchedTrades": len(trades),
        "appendedTrades": len(selected),
        "strategies": sorted(STRATEGIES),
        "latestSeenId": max([int(t.get("id") or 0) for t in trades], default=0),
    }
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
