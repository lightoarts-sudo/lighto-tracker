import json
import subprocess
import sys
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

SHEET_ID = "1It3yl9mbRPMqn3QMhUbwyL4b0OATPnGuDq7MEvgRtEA"
TAB_NAME = "strategy_performance_12h"
SHEET_RANGE_KEYS = f"{TAB_NAME}!A:A"
SHEET_HEADER_RANGE = f"{TAB_NAME}!A1:R1"
SHEET_APPEND_RANGE = f"{TAB_NAME}!A:R"
GOOGLE_API = r"C:/Users/fuful/.hermes/skills/productivity/google-workspace/scripts/google_api.py"
GOOGLE_API_DIR = str(Path(GOOGLE_API).resolve().parent)
TRADE_RECORDS_URL = "https://lighto-tracker.onrender.com/api/crypto/micro/trade-records"
PERFORMANCE_URL = "https://lighto-tracker.onrender.com/api/crypto/micro/performance"
PERFORMANCE_12H_URL = "https://lighto-tracker.onrender.com/api/crypto/micro/performance12h"
MICRO_URL = "https://lighto-tracker.onrender.com/micro"
TAIPEI = ZoneInfo("Asia/Taipei")
STATE_PATH = Path("data/micro_strategy_performance_sheet_sync_state.json")
HEADERS = [
    "key",
    "snapshot_ts_utc",
    "snapshot_ts_taipei",
    "snapshot_slot_taipei",
    "window_start_utc",
    "window_end_utc",
    "window_start_taipei",
    "window_end_taipei",
    "strategy",
    "entries",
    "closed_trades",
    "wins",
    "losses",
    "open_trades",
    "realized_pnl_usdt",
    "avg_pnl_roe_pct",
    "win_rate_pct",
    "source_url",
]


def fetch_json(url):
    req = urllib.request.Request(url, headers={"User-Agent": "lighto-strategy-performance-sheet-sync/1.0"})
    with urllib.request.urlopen(req, timeout=90) as resp:
        return json.loads(resp.read().decode("utf-8"))


def run_google_api(args):
    proc = subprocess.run([sys.executable, GOOGLE_API, *args], text=True, capture_output=True, timeout=120)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr or proc.stdout)
    return json.loads(proc.stdout or "null")


def sheets_service():
    sys.path.insert(0, GOOGLE_API_DIR)
    from google_api import build_service
    return build_service("sheets", "v4")


def ensure_tab_and_header():
    service = sheets_service()
    meta = service.spreadsheets().get(spreadsheetId=SHEET_ID).execute()
    titles = {s.get("properties", {}).get("title") for s in meta.get("sheets", [])}
    if TAB_NAME not in titles:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SHEET_ID,
            body={"requests": [{"addSheet": {"properties": {"title": TAB_NAME}}}]},
        ).execute()
    try:
        existing = run_google_api(["sheets", "get", SHEET_ID, SHEET_HEADER_RANGE]) or []
    except Exception:
        existing = []
    if not existing or not existing[0] or existing[0][0] != "key":
        run_google_api(["sheets", "update", SHEET_ID, SHEET_HEADER_RANGE, "--values", json.dumps([HEADERS], ensure_ascii=False)])


def parse_dt(value):
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def slot_dt_taipei(now_tpe):
    """Return the intended 09:00/21:00 Taipei reporting slot for this run."""
    slot_hour = 9 if now_tpe.hour < 15 else 21
    return now_tpe.replace(hour=slot_hour, minute=0, second=0, microsecond=0)


def slot_label(now_tpe):
    return slot_dt_taipei(now_tpe).isoformat(timespec="minutes")


def normalize_iso(value):
    return parse_dt(value).isoformat(timespec="seconds")


def metric_rows_from_performance12h(perf12h, now_utc):
    window = perf12h.get("current") or {}
    rows = window.get("rows") or []
    window_start = parse_dt(window.get("windowStart"))
    window_end = parse_dt(window.get("windowEnd"))
    if not window_start or not window_end:
        return None
    slot = window.get("snapshotSlotTaipei") or window_end.astimezone(TAIPEI).isoformat(timespec="minutes")
    now_tpe = now_utc.astimezone(TAIPEI)
    window_start_tpe = window.get("windowStartTaipei") or window_start.astimezone(TAIPEI).isoformat(timespec="minutes")
    window_end_tpe = window.get("windowEndTaipei") or window_end.astimezone(TAIPEI).isoformat(timespec="minutes")
    out = []
    for group in sorted(rows, key=lambda r: r.get("strategy") or ""):
        strategy = group.get("strategy")
        if not strategy:
            continue
        key = f"{slot}|{window_start.isoformat(timespec='seconds')}|{window_end.isoformat(timespec='seconds')}|{strategy}"
        out.append([
            key,
            now_utc.isoformat(timespec="seconds"),
            now_tpe.isoformat(timespec="seconds"),
            slot,
            window_start.isoformat(timespec="seconds"),
            window_end.isoformat(timespec="seconds"),
            window_start_tpe,
            window_end_tpe,
            strategy,
            int(group.get("entries") or 0),
            int(group.get("closedTrades") or 0),
            int(group.get("wins") or 0),
            int(group.get("losses") or 0),
            int(group.get("openTrades") or 0),
            round(float(group.get("realizedPnl") or 0), 4),
            round(float(group.get("avgPnlRoePct") or 0), 4),
            round(float(group.get("winRate") or 0), 4),
            MICRO_URL,
        ])
    return window_start, window_end, out


def load_existing_key_rows():
    rows = run_google_api(["sheets", "get", SHEET_ID, SHEET_RANGE_KEYS]) or []
    key_rows = {}
    for idx, row in enumerate(rows[1:], start=2):
        if row:
            key_rows[str(row[0])] = idx
    return key_rows


def summarize(records, performance_rows, now_utc):
    now_tpe = now_utc.astimezone(TAIPEI)
    scheduled_end_tpe = slot_dt_taipei(now_tpe)
    window_end = scheduled_end_tpe.astimezone(timezone.utc)
    window_start = window_end - timedelta(hours=12)
    strategies = {row.get("strategy") for row in performance_rows if row.get("strategy")}
    strategies.update(row.get("strategy") for row in records if row.get("strategy"))
    groups = {
        strategy: {
            "strategy": strategy,
            "entries": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "open_trades": 0,
            "realized_pnl": 0.0,
            "roe_values": [],
        }
        for strategy in sorted(strategies)
    }
    for row in records:
        strategy = row.get("strategy")
        if not strategy:
            continue
        entry_time = parse_dt(row.get("entry_time"))
        if not entry_time or entry_time < window_start or entry_time > window_end:
            continue
        g = groups.setdefault(strategy, {
            "strategy": strategy,
            "entries": 0,
            "closed_trades": 0,
            "wins": 0,
            "losses": 0,
            "open_trades": 0,
            "realized_pnl": 0.0,
            "roe_values": [],
        })
        g["entries"] += 1
        status = (row.get("status") or "").lower()
        if status == "open" or not row.get("exit_time"):
            g["open_trades"] += 1
            continue
        g["closed_trades"] += 1
        pnl = row.get("pnl")
        try:
            pnl = float(pnl or 0)
        except Exception:
            pnl = 0.0
        g["realized_pnl"] += pnl
        if pnl > 0:
            g["wins"] += 1
        elif pnl < 0:
            g["losses"] += 1
        roe = row.get("pnl_roe_pct")
        if roe is not None:
            try:
                g["roe_values"].append(float(roe))
            except Exception:
                pass
    return window_start, window_end, [groups[k] for k in sorted(groups)]


def to_row(group, now_utc, window_start, window_end):
    now_tpe = now_utc.astimezone(TAIPEI)
    window_start_tpe = window_start.astimezone(TAIPEI)
    window_end_tpe = window_end.astimezone(TAIPEI)
    slot = slot_label(now_tpe)
    strategy = group["strategy"]
    closed = int(group["closed_trades"])
    wins = int(group["wins"])
    losses = int(group["losses"])
    win_rate = round((wins / closed * 100), 4) if closed else 0.0
    avg_roe = round(sum(group["roe_values"]) / len(group["roe_values"]), 4) if group["roe_values"] else 0.0
    key = f"{slot}|{window_start.isoformat(timespec='seconds')}|{window_end.isoformat(timespec='seconds')}|{strategy}"
    return [
        key,
        now_utc.isoformat(timespec="seconds"),
        now_tpe.isoformat(timespec="seconds"),
        slot,
        window_start.isoformat(timespec="seconds"),
        window_end.isoformat(timespec="seconds"),
        window_start_tpe.isoformat(timespec="seconds"),
        window_end_tpe.isoformat(timespec="seconds"),
        strategy,
        int(group["entries"]),
        closed,
        wins,
        losses,
        int(group["open_trades"]),
        round(float(group["realized_pnl"]), 4),
        avg_roe,
        win_rate,
        MICRO_URL,
    ]


def main():
    ensure_tab_and_header()
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    perf12h = fetch_json(PERFORMANCE_12H_URL)
    from_api = metric_rows_from_performance12h(perf12h, now_utc)
    if from_api:
        window_start, window_end, rows = from_api
    else:
        records = fetch_json(TRADE_RECORDS_URL)
        performance = fetch_json(PERFORMANCE_URL)
        window_start, window_end, groups = summarize(records, performance, now_utc)
        rows = [to_row(group, now_utc, window_start, window_end) for group in groups]
    existing = load_existing_key_rows()
    update_count = 0
    append_rows = []
    for row in rows:
        existing_row = existing.get(row[0])
        if existing_row:
            run_google_api(["sheets", "update", SHEET_ID, f"{TAB_NAME}!A{existing_row}:R{existing_row}", "--values", json.dumps([row], ensure_ascii=False)])
            update_count += 1
        else:
            append_rows.append(row)
    if append_rows:
        run_google_api(["sheets", "append", SHEET_ID, SHEET_APPEND_RANGE, "--values", json.dumps(append_rows, ensure_ascii=False)])
    state = {
        "lastRunAt": now_utc.isoformat(timespec="seconds"),
        "sheetId": SHEET_ID,
        "tab": TAB_NAME,
        "windowStart": window_start.isoformat(timespec="seconds"),
        "windowEnd": window_end.isoformat(timespec="seconds"),
        "strategies": [row[8] for row in rows],
        "updatedRows": update_count,
        "appendedRows": len(append_rows),
        "sheetUrl": f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit#gid=809326833",
    }
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(state, ensure_ascii=False))


if __name__ == "__main__":
    main()
