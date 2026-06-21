#!/usr/bin/env python3
"""Monitor LIGHTOARTS promotion / OKX live status and send email alerts."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path.cwd()
STATE_FILE = ROOT / "data" / "monitor_notify_state.json"
GAPI = (
    r"C:\Users\fuful\.hermes\skills\productivity\google-workspace\scripts\google_api.py"
)
EMAIL_TO = "propc7358@gmail.com"
EMAIL_FROM = '"LIGHTOARTS Monitor" <propc7358@gmail.com>'


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def save_json(path: Path, payload) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def ts() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def send_email(subject: str, body: str) -> None:
    cmd = [
        sys.executable,
        GAPI,
        "gmail",
        "send",
        "--to",
        EMAIL_TO,
        "--from",
        EMAIL_FROM,
        "--subject",
        subject,
        "--body",
        body,
    ]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True)
        if p.returncode != 0:
            print(f"[monitor] email send failed: {p.stderr.strip()}", file=sys.stderr)
        else:
            print(f"[monitor] sent email: {subject}")
    except Exception as e:
        print(f"[monitor] email exception: {e}", file=sys.stderr)


def is_live(name: str, state: dict) -> bool:
    if state.get("completed", True):
        return False
    if state.get("pausedReason"):
        return False
    if state.get("pausedAt"):
        return False
    if (ROOT / "data" / f"{name}_live_pilot_paused.flag").exists():
        return False
    return True


def load_live_pilot_states() -> dict[str, dict]:
    states = {}
    data_dir = ROOT / "data"
    if not data_dir.is_dir():
        return states
    for path in sorted(data_dir.glob("*_live_pilot_state.json")):
        name = path.stem.replace("_live_pilot_state", "")
        states[name] = load_json(path, {"completed": True})
    return states


def main() -> int:
    state_exists = STATE_FILE.exists()
    previous = load_json(STATE_FILE, {
        "active_strategy_count": 0,
        "live_pilots": {},
        "notified_promote": False,
        "notified_okx_live_by_pilot": {},
    })

    active = load_json(ROOT / "data" / "active_strategies.json", {"updated_at": "", "strategies": []})
    current_live_pilots = load_live_pilot_states()

    current = {
        "active_strategy_count": len(active.get("strategies", []) if isinstance(active.get("strategies"), list) else []),
        "live_pilots": {name: is_live(name, s) for name, s in current_live_pilots.items()},
        "notified_promote": previous.get("notified_promote", False),
        "notified_okx_live_by_pilot": previous.get("notified_okx_live_by_pilot", {}),
    }

    # Bootstrap: if no prior state file existed, just persist current state without emailing
    if not state_exists:
        save_json(STATE_FILE, current)
        now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        live_names = [p for p, v in current["live_pilots"].items() if v]
        print(
            f"[monitor] init active={current['active_strategy_count']} "
            f"live={','.join(live_names) if live_names else 'none'}; "
            "suppress initial alert."
        )
        return 0

    now_label = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    changed = False

    # Condition 1: new strategy promoted to active (Render)
    if current["active_strategy_count"] > previous.get("active_strategy_count", 0):
        if not previous.get("notified_promote"):
            new_count = current["active_strategy_count"]
            render_promo = active.get("updated_at", "N/A")
            body = (
                f"LIGHTOARTS 新策略已推上 Render / Active\n\n"
                f"時間：{now_label}\n"
                f"active_strategies.json updated_at：{render_promo}\n"
                f"目前 active 策略數量：{new_count}\n\n"
                f"請手動確認 Render dashboard：https://lighto-tracker.onrender.com\n\n"
                f"--\nLIGHTOARTS Monitor"
            )
            send_email("[LIGHTOARTS] 新策略已推上 Render", body)
            current["notified_promote"] = True
            changed = True

    # Condition 2: any OKX pilot transitioned to live
    prev_live = previous.get("live_pilots", {})
    for pilot, live in current["live_pilots"].items():
        prev_live_flag = bool(prev_live.get(pilot, False))
        if live and not prev_live_flag:
            if not previous.get("notified_okx_live_by_pilot", {}).get(pilot):
                state = current_live_pilots[pilot]
                started = state.get("startedAt", "N/A")
                entries = state.get("entriesPlaced", "N/A")
                body = (
                    f"LIGHTOARTS OKX 實際交易已啟動\n\n"
                    f"時間：{now_label}\n"
                    f"Pilot：{pilot}\n"
                    f"startedAt：{started}\n"
                    f"entriesPlaced：{entries}\n"
                    f"狀態：實盤交易中\n\n"
                    f"--\nLIGHTOARTS Monitor"
                )
                send_email(f"[LIGHTOARTS] OKX 實際交易啟動 ({pilot})", body)
                current.setdefault("notified_okx_live_by_pilot", {})[pilot] = True
                changed = True

    # Reset flags if conditions revert so next occurrence triggers again
    if current["active_strategy_count"] == 0 and previous.get("notified_promote"):
        current["notified_promote"] = False
        changed = True

    for pilot in list(current.get("notified_okx_live_by_pilot", {}).keys()):
        live_now = current["live_pilots"].get(pilot, False)
        if not live_now:
            current["notified_okx_live_by_pilot"][pilot] = False
            changed = True

    if changed:
        save_json(STATE_FILE, current)

    live_names = [p for p, v in current["live_pilots"].items() if v]
    print(
        f"[monitor] active={current['active_strategy_count']} "
        f"live={','.join(live_names) if live_names else 'none'} "
        f"notified_promote={current['notified_promote']} "
        f"notified_okx={current['notified_okx_live_by_pilot']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
