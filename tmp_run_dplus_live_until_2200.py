from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

REPO = Path(__file__).resolve().parent
DATA = REPO / "data"
STRATEGY = "top5dplus_score95_chg2_5_sl1_tr06x03_t6"
STATE = DATA / "okx_dplus_live_pilot_state.json"
LOG = DATA / "okx_dplus_live_pilot_log.jsonl"
LOCK = DATA / "okx_dplus_live_pilot.lock"
PAUSE = DATA / "okx_dplus_live_pilot_paused.flag"
STDOUT = DATA / "okx_dplus_live_pilot_stdout.log"
SUPERVISOR = DATA / "okx_dplus_live_supervisor.json"
SUMMARY = DATA / "okx_dplus_live_until_2200_summary.json"


def taipei_now():
    return datetime.now(ZoneInfo("Asia/Taipei"))


def stop_time():
    now = taipei_now()
    stop = now.replace(hour=22, minute=0, second=0, microsecond=0)
    if now >= stop:
        raise SystemExit(f"already past Taipei 22:00: {now.isoformat()}")
    return stop


def read_jsonl(path: Path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except Exception:
            rows.append({"raw": line})
    return rows


def build_summary(reason: str, proc_code: int | None):
    rows = read_jsonl(LOG)
    buys = [r for r in rows if r.get("event") == "BUY"]
    sells = [r for r in rows if r.get("event") == "SELL"]
    skips = [r for r in rows if r.get("event") == "skip_entry_guard"]
    hard_stop_failures = [r for r in rows if r.get("event") == "HARD_STOP_FAILED_EMERGENCY_CLOSE"]
    buy_slippages = [float(r.get("slippagePct") or 0) for r in buys]
    sell_slippages = [float(r.get("slippagePct") or 0) for r in sells]
    realized = [float(r.get("realizedPnl") or 0) for r in sells]
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
        except Exception as exc:
            state = {"stateReadError": str(exc)}
    summary = {
        "reason": reason,
        "procReturnCode": proc_code,
        "generatedAtTaipei": taipei_now().isoformat(),
        "strategy": STRATEGY,
        "statePath": str(STATE),
        "logPath": str(LOG),
        "stdoutPath": str(STDOUT),
        "entriesPlacedState": state.get("entriesPlaced"),
        "openPositionsState": list((state.get("positions") or {}).keys()) if isinstance(state.get("positions"), dict) else [],
        "buyCount": len(buys),
        "sellCount": len(sells),
        "skipGuardCount": len(skips),
        "hardStopFailureCount": len(hard_stop_failures),
        "buySlippagePctAvg": sum(buy_slippages) / len(buy_slippages) if buy_slippages else 0,
        "buySlippagePctMin": min(buy_slippages) if buy_slippages else 0,
        "buySlippagePctMax": max(buy_slippages) if buy_slippages else 0,
        "sellSlippagePctAvg": sum(sell_slippages) / len(sell_slippages) if sell_slippages else 0,
        "realizedPnlUSDT": sum(realized),
        "buyRows": buys,
        "sellRows": sells,
        "lastEvents": rows[-20:],
    }
    SUMMARY.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    PAUSE.unlink(missing_ok=True)
    # Do not delete STATE/LOG: preserving the full pilot evidence is useful.
    # If the state is already completed from an older D+ run, reset only the completion flag.
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text(encoding="utf-8"))
            state["completed"] = False
            state.setdefault("positions", {})
            state.setdefault("entriesPlaced", 0)
            STATE.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass
    stop = stop_time()
    seconds = max(1, int((stop - taipei_now()).total_seconds()))
    env = os.environ.copy()
    env.update({
        "OKX_TOP10_PILOT_STRATEGY": STRATEGY,
        "OKX_TOP10_PILOT_STATE": str(STATE),
        "OKX_TOP10_PILOT_LOG": str(LOG),
        "OKX_TOP10_PILOT_LOCK": str(LOCK),
        "OKX_TOP10_PILOT_PAUSE_FILE": str(PAUSE),
        "OKX_TOP10_PILOT_LIVE": "1",
    })
    cmd = [
        sys.executable,
        "okx_strategy22_live_pilot.py",
        "--max-entries", "0",
        "--allow-unlimited-live",
        "--margin-usdt", "3",
        "--leverage", "5",
        "--hard-stop-pct", "1.0",
        "--poll-seconds", "300",
        "--scan-pause", "0.35",
        "--min-pct1h", "2.0",
        "--min-pct15", "0.0",
        "--min-volume-ratio", "0.0",
        "--daily-loss-limit-usdt", "-1.0",
        "--consecutive-loss-limit", "5",
        "--i-understand-live-trading",
    ]
    creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
    with STDOUT.open("a", encoding="utf-8") as out:
        out.write(f"\n=== supervisor start {taipei_now().isoformat()} stop {stop.isoformat()} seconds {seconds} ===\n")
        out.flush()
        proc = subprocess.Popen(cmd, cwd=str(REPO), env=env, stdout=out, stderr=subprocess.STDOUT, creationflags=creationflags)
    SUPERVISOR.write_text(json.dumps({
        "startedAtTaipei": taipei_now().isoformat(),
        "stopAtTaipei": stop.isoformat(),
        "secondsUntilStop": seconds,
        "pid": proc.pid,
        "cmd": cmd,
        "strategy": STRATEGY,
        "marginUSDT": 3,
        "leverage": 5,
        "hardStopPct": 1.0,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"D+ OKX live runner started pid={proc.pid} stopAtTaipei={stop.isoformat()} state={STATE} log={LOG}", flush=True)
    deadline = time.time() + seconds
    reason = "time_stop_2200"
    while time.time() < deadline:
        code = proc.poll()
        if code is not None:
            reason = "runner_exited_before_2200"
            summary = build_summary(reason, code)
            print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
            return code
        time.sleep(min(30, max(1, deadline - time.time())))
    if proc.poll() is None:
        print("22:00 reached; terminating D+ runner", flush=True)
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.terminate()
            proc.wait(timeout=20)
        except Exception:
            proc.kill()
            proc.wait(timeout=20)
    summary = build_summary(reason, proc.returncode)
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
