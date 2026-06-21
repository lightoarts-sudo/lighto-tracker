#!/usr/bin/env python3
"""Auto-promote/demote strategies on Render based on performance."""

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path
import urllib.request
import urllib.error

BASE = Path.cwd()
if not (BASE / "crypto_bot.py").exists():
    # When run from cron via ~/.hermes/scripts/, cwd may be different
    BASE = Path(r"C:\Users\fuful\OneDrive\Desktop\LIGHTOARTS\_render_lighto_tracker")

STATE_FILE = BASE / "data" / "auto_manage_state.json"
ACTIVE_FILE = BASE / "data" / "active_strategies.json"
POOL_FILE = BASE / "data" / "strategy_pool.json"
RENDER_YAML = BASE / "render.yaml"
CRYPTO_BOT = BASE / "crypto_bot.py"

RENDER_URL = os.environ.get("RENDER_URL", "https://lighto-tracker.onrender.com")

# Thresholds
MIN_TRADES = 20
MIN_WIN_RATE = 0.45
# Live proxy for PF >= 1.2: realizedPnl must be positive
MIN_REALIZED_PNL = 0.0
DEMOTE_STREAK = 3


def fetch_performance():
    url = f"{RENDER_URL}/api/crypto/micro/performance"
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            return json.loads(r.read())
    except Exception as e:
        print(f"[ERROR] fetch_performance failed: {e}")
        return []


def load_state():
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"last_run": None, "streaks": {}, "promoted": [], "demoted": []}


def save_state(state):
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def get_active_from_file():
    if not ACTIVE_FILE.exists():
        return []
    data = json.loads(ACTIVE_FILE.read_text(encoding="utf-8"))
    return data.get("strategies", [])


def set_active_in_file(strategies):
    now = datetime.now(timezone(timedelta(hours=8))).isoformat()
    ACTIVE_FILE.write_text(
        json.dumps({"updated_at": now, "strategies": strategies}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def get_current_render_active():
    """Read CRYPTO_MICRO_ACTIVE_STRATEGIES from render.yaml."""
    content = RENDER_YAML.read_text(encoding="utf-8")
    for line in content.splitlines():
        if "CRYPTO_MICRO_ACTIVE_STRATEGIES" in line:
            if "value:" in line:
                val = line.split("value:", 1)[1].strip().strip('"')
                return [s.strip() for s in val.split(",") if s.strip()]
    # Multiline fallback
    lines = content.splitlines()
    for i, line in enumerate(lines):
        if "CRYPTO_MICRO_ACTIVE_STRATEGIES" in line and i + 1 < len(lines):
            val = lines[i + 1].split("value:", 1)[1].strip().strip('"')
            return [s.strip() for s in val.split(",") if s.strip()]
    return []


def update_render_yaml(strategies):
    content = RENDER_YAML.read_text(encoding="utf-8")
    new_val = ",".join(strategies)
    # Single-line style
    pattern = r'(- key:\s*CRYPTO_MICRO_ACTIVE_STRATEGIES\s*\n\s*value:\s*")[^"]*(")'
    replacement = r"\g<1>" + new_val + r"\2"
    new_content, count = re.subn(pattern, replacement, content)
    if count == 0:
        # Multiline style
        pattern2 = r'(- key:\s*CRYPTO_MICRO_ACTIVE_STRATEGIES\s*\n\s*value:\s*)[^\n]*'
        new_content = re.sub(pattern2, r"\g<1>" + new_val, content)
    RENDER_YAML.write_text(new_content, encoding="utf-8")


def get_config_default_string():
    content = CRYPTO_BOT.read_text(encoding="utf-8")
    m = re.search(r'"microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*"([^"]*)"\)', content)
    if not m:
        return ""
    return m.group(1)


def update_crypto_bot_config(strategies):
    """Update the default string in CONFIG and _DEFAULT_MICRO_ACTIVE tuple."""
    content = CRYPTO_BOT.read_text(encoding="utf-8")
    new_val = ",".join(strategies)

    # 1. Update CONFIG default string
    def replace_config(m):
        return f'"microActiveStrategies": _csv_env("CRYPTO_MICRO_ACTIVE_STRATEGIES", "{new_val}")'
    content = re.sub(
        r'"microActiveStrategies":\s*_csv_env\("CRYPTO_MICRO_ACTIVE_STRATEGIES",\s*"[^"]*"\)',
        replace_config,
        content,
    )

    # 2. Update _DEFAULT_MICRO_ACTIVE tuple
    tuple_start = content.find("_DEFAULT_MICRO_ACTIVE = (")
    if tuple_start != -1:
        tuple_end = content.find(")", tuple_start) + 1
        old_tuple = content[tuple_start:tuple_end]
        # Build replacement
        lines = ['_DEFAULT_MICRO_ACTIVE = (']
        for s in strategies:
            lines.append(f'    "{s},"')
        lines.append(")")
        new_tuple = "\n".join(lines)
        content = content[:tuple_start] + new_tuple + content[tuple_end:]

    CRYPTO_BOT.write_text(content, encoding="utf-8")


def append_crypto_bot_new_strategy(name, entry, exit_):
    """Append a new strategy dict entry and name to crypto_bot.py."""
    content = CRYPTO_BOT.read_text(encoding="utf-8")

    # Build dict entry
    dict_entry = f'''    "{name}": {{
        "version": "auto_{name.split('_')[1]}_4h",
        "entry_delay_bars": {entry.get('delay_bars', 3)},
        "max_rank": {entry.get('max_entry_rank', 3)},
        "min_change_1h_pct": {float(entry.get('min_entry_change', 3))},
        "max_change_1h_pct": {float(entry.get('max_entry_change', 10))},
        "min_current_change_1h_pct": 0.0,
        "require_change_reclaim": {str(entry.get('reclaim_entry_price', False)).lower()},
        "require_green_confirm": {str(entry.get('require_green_confirm', True)).lower()},
        "max_upper_wick_pct": {entry.get('max_upper_wick_pct', 1.2)},
        "min_volume_ratio": {float(entry.get('min_vol_ratio', 1.0))},
        "reclaim_entry_price": {str(entry.get('reclaim_entry_price', False)).lower()},
        "shadow_only": False,
        "stop_loss_pct": {exit_.get('sl_pct', 1.0)},
        "breakeven_after_pct": {exit_.get('breakeven_after_pct', 0.6)},
        "trailing_start_pct": {exit_.get('trail_start_pct', 0.9)},
        "trailing_giveback_pct": {exit_.get('trail_giveback_pct', 0.4)},
        "time_stop_bars": {exit_.get('time_stop_bars', 8)},
    }},'''

    # Insert before strategy4_1
    marker = '# === Strategy 4.1 (production backtest positive) ==='
    marker_idx = content.find(marker)
    if marker_idx == -1:
        # Append at end of file
        content = content.rstrip() + "\n\n" + dict_entry + "\n"
    else:
        content = content[:marker_idx] + dict_entry + "\n" + content[marker_idx:]

    # Update tuple and config
    # We'll do this via update_crypto_bot_config after all additions
    CRYPTO_BOT.write_text(content, encoding="utf-8")


def candidate_to_name(entry, exit_, index):
    """Generate strategy name from candidate entry/exit parameters."""
    delay = entry.get("delay_bars", 3)
    rank = entry.get("max_entry_rank", 3)
    min_c = entry.get("min_entry_change", 3)
    max_c = entry.get("max_entry_change", 10)
    sl = exit_.get("sl_pct", 1.0)
    be = exit_.get("breakeven_after_pct", 0.6)
    ts = exit_.get("trail_start_pct", 0.9)
    tg = exit_.get("trail_giveback_pct", 0.4)
    tstop = exit_.get("time_stop_bars", 8)

    entry_name = entry.get("name", "")
    exit_name = exit_.get("name", "")

    # Parse entry suffix
    entry_suffix = entry_name
    # Remove delay prefix
    entry_suffix = re.sub(r'^delay\d+_', '', entry_suffix)
    # Remove rank prefix  
    entry_suffix = re.sub(r'^rank\d+_', '', entry_suffix)
    # Replace chgX-Y with chg{min}-{max}
    entry_suffix = re.sub(r'chg[\d.]+-[\d.]+', f'chg{min_c}-{max_c}', entry_suffix)

    # Parse exit suffix
    exit_suffix = exit_name.replace("trail", "tr")

    return f"auto_top{index}_4h_{entry_suffix}_{exit_suffix}"


def get_pool_candidates():
    if not POOL_FILE.exists():
        return []
    pool = json.loads(POOL_FILE.read_text(encoding="utf-8"))
    cands = pool.get("candidates", [])
    good = []
    for c in cands:
        status = c.get("status", "")
        if status not in ("pending_review", "approved"):
            continue
        m = c.get("metrics", {})
        trades = m.get("trades", 0)
        win_rate = m.get("win_rate", 0) / 100.0 if m.get("win_rate", 0) > 1 else m.get("win_rate", 0)
        pf = m.get("profit_factor", 0)
        if trades >= MIN_TRADES and win_rate >= MIN_WIN_RATE and pf >= 1.2:
            good.append(c)
    return good


def build_qualified_pickle(candidates):
    """Build qualified_strategies.pkl compatible format from candidates."""
    qualified = []
    for i, c in enumerate(candidates, 1):
        name = candidate_to_name(c["entry"], c["exit"], i)
        qualified.append((i, {
            "entry": c["entry"],
            "exit": c["exit"],
            "name": name,
        }))
    return qualified


def git_commit_and_push(message):
    try:
        subprocess.run(["git", "add", "-A"], cwd=BASE, check=True, capture_output=True)
        subprocess.run(["git", "commit", "-m", message], cwd=BASE, check=True, capture_output=True)
        subprocess.run(["git", "push", "origin", "main"], cwd=BASE, check=True, capture_output=True)
        return True
    except subprocess.CalledProcessError as e:
        print(f"[ERROR] git failed: {e.stderr.decode()}")
        return False


def send_email(subject, body):
    try:
        gapi = r"C:\Users\fuful\.hermes\skills\productivity\google-workspace\scripts\google_api.py"
        script = f"""
import sys
sys.path.insert(0, r'{os.path.dirname(gapi)}')
from google_api import gmail_send
gmail_send(
    to='propc7358@gmail.com',
    subject='{subject}',
    body='''{body}'''
)
"""
        subprocess.run([sys.executable, "-c", script], cwd=BASE, check=True, capture_output=True, timeout=30)
        print(f"[email] sent: {subject}")
    except Exception as e:
        print(f"[ERROR] email send failed: {e}")


def main():
    print(f"[auto_manage] start cwd={BASE}")
    state = load_state()
    performance = fetch_performance()
    perf_map = {s["strategy"]: s for s in performance}

    current_active = get_active_from_file()
    print(f"[auto_manage] current_active={len(current_active)} strategies")
    print(f"[auto_manage] performance_fetched={len(perf_map)} strategies")

    # Evaluate existing active strategies
    keep = []
    demote = []
    new_streaks = {}
    for s in current_active:
        streak = state.get("streaks", {}).get(s, 0)
        if s in perf_map:
            p = perf_map[s]
            trades = p.get("trades", 0)
            win_rate = p.get("winRate", 0) / 100.0
            pnl = p.get("realizedPnl", 0)
            if trades < MIN_TRADES:
                print(f"  {s}: insufficient trades ({trades}), keep")
                keep.append(s)
                new_streaks[s] = 0
            elif win_rate >= MIN_WIN_RATE and pnl >= MIN_REALIZED_PNL:
                print(f"  {s}: PASS trades={trades} wr={win_rate:.1%} pnl={pnl:.2f}")
                keep.append(s)
                new_streaks[s] = 0
            else:
                streak += 1
                new_streaks[s] = streak
                if streak >= DEMOTE_STREAK:
                    print(f"  {s}: DEMOTE after {streak} failures trades={trades} wr={win_rate:.1%} pnl={pnl:.2f}")
                    demote.append(s)
                else:
                    print(f"  {s}: WARN {streak}/{DEMOTE_STREAK} failures trades={trades} wr={win_rate:.1%} pnl={pnl:.2f}")
                    keep.append(s)  # keep for now but watch
        else:
            # Not in performance data yet (maybe too new). Keep but don't reset streak.
            print(f"  {s}: no performance data yet, keep")
            keep.append(s)
            new_streaks[s] = streak

    # Check candidates
    candidates = get_pool_candidates()
    print(f"[auto_manage] pool candidates meeting criteria: {len(candidates)}")
    promote = []
    for c in candidates:
        name = candidate_to_name(c["entry"], c["exit"], len(keep) + len(promote) + 1)
        if name not in keep and name not in demote:
            promote.append((name, c["entry"], c["exit"]))
            print(f"  PROMOTE: {name}")

    # Build new active list: non-auto strategies first, then auto strategies
    non_auto = [s for s in keep if not s.startswith("auto_top")]
    auto_keep = [s for s in keep if s.startswith("auto_top")]
    new_auto_names = [n for n, _, _ in promote]
    new_active = non_auto + auto_keep + new_auto_names

    if new_active == current_active and not demote and not promote:
        print("[auto_manage] no changes needed")
        state["last_run"] = datetime.now(timezone.utc).isoformat()
        state["streaks"] = new_streaks
        save_state(state)
        return

    print(f"[auto_manage] changes: keep={len(keep)} demote={len(demote)} promote={len(promote)}")
    print(f"[auto_manage] new_active: {new_active}")

    # 1. Update active_strategies.json
    set_active_in_file(new_active)

    # 2. Update render.yaml
    update_render_yaml(new_active)

    # 3. Update crypto_bot.py
    # First, remove demoted strategies from tuple/config
    # Then add new strategies
    update_crypto_bot_config(new_active)
    for name, entry, exit_ in promote:
        append_crypto_bot_new_strategy(name, entry, exit_)

    # 4. Commit and push
    msg = f"Auto-manage strategies: +{len(promote)} -{len(demote)} active={len(new_active)}"
    if git_commit_and_push(msg):
        print(f"[auto_manage] pushed: {msg}")
    else:
        print(f"[auto_manage] WARNING: git push failed")

    # 5. Update state
    state["last_run"] = datetime.now(timezone.utc).isoformat()
    state["streaks"] = new_streaks
    state["promoted"] = state.get("promoted", []) + [{"time": state["last_run"], "names": new_auto_names}]
    state["demoted"] = state.get("demoted", []) + [{"time": state["last_run"], "names": demote}]
    save_state(state)

    # 6. Notify
    if demote or promote:
        subject = f"[LIGHTOARTS] 策略自動調整: +{len(promote)} -{len(demote)}"
        body = f"Render 策略已自動調整\n\n新增: {', '.join(new_auto_names) or '無'}\n下架: {', '.join(demote) or '無'}\n當前總數: {len(new_active)}"
        send_email(subject, body)


if __name__ == "__main__":
    main()
