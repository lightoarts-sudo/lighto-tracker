import csv
import json
import math
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path

DB = Path('data/okx_micro_5m_tracking.sqlite')
OUT_JSON = Path('data/top10_training_strategy_scan_latest.json')
OUT_CSV = Path('data/top10_training_strategy_scan_latest.csv')

FEE_SLIP_PCT = 0.18  # round-trip conservative friction: fees + average adverse fill/stop slippage
MIN_TRADES = 80

@dataclass(frozen=True)
class Params:
    name: str
    delay_bars: int
    max_entry_rank: int
    min_entry_change: float
    max_entry_change: float
    min_current_change: float
    require_change_reclaim: bool
    min_vol_ratio: float
    stop_pct: float
    trail_start_pct: float
    trail_giveback: float
    time_stop_bars: int
    exit_on_leave_top10: bool


def load_sessions():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        """
        SELECT session_id, inst_id, entered_at, exited_at, is_active, bar_index_from_entry,
               ts_ms, ts_iso, open, high, low, close, vol, vol_ccy, rank_1h, change_1h_pct,
               entry_rank_1h, entry_change_1h_pct, entry_price, last_rank_1h, last_change_1h_pct,
               max_change_1h_pct, min_rank_1h
        FROM top10_1h_training_dataset
        WHERE close > 0 AND open > 0 AND high > 0 AND low > 0
        ORDER BY session_id, bar_index_from_entry, ts_ms
        """
    ).fetchall()
    sessions = defaultdict(list)
    for r in rows:
        sessions[r['session_id']].append(dict(r))
    return dict(sessions)


def vol_ratio_at(bars, idx, lookback=6):
    if idx <= 0:
        return 1.0
    start = max(0, idx - lookback)
    prev = [float(b['vol_ccy'] or b['vol'] or 0) for b in bars[start:idx]]
    cur = float(bars[idx]['vol_ccy'] or bars[idx]['vol'] or 0)
    avg = sum(prev) / len(prev) if prev else cur
    if avg <= 0:
        return 1.0
    return cur / avg


def run_trade(bars, p: Params):
    if len(bars) <= p.delay_bars:
        return None
    entry_bar = bars[p.delay_bars]
    if int(entry_bar['entry_rank_1h']) > p.max_entry_rank:
        return None
    entry_change = float(entry_bar['entry_change_1h_pct'] or 0)
    cur_change = float(entry_bar['change_1h_pct'] or entry_change)
    if not (p.min_entry_change <= entry_change <= p.max_entry_change):
        return None
    if cur_change < p.min_current_change:
        return None
    if p.require_change_reclaim and cur_change < entry_change - 1.0:
        return None
    if vol_ratio_at(bars, p.delay_bars) < p.min_vol_ratio:
        return None

    entry = float(entry_bar['close'])
    if entry <= 0:
        return None
    stop = entry * (1 - p.stop_pct / 100)
    peak = entry
    exit_px = None
    exit_reason = None
    exit_i = None
    max_runup = 0.0
    max_drawdown = 0.0
    end_i = min(len(bars) - 1, p.delay_bars + p.time_stop_bars)

    for i in range(p.delay_bars + 1, end_i + 1):
        b = bars[i]
        high = float(b['high']); low = float(b['low']); close = float(b['close'])
        peak = max(peak, high)
        runup = (peak / entry - 1) * 100
        drawdown = (low / entry - 1) * 100
        max_runup = max(max_runup, runup)
        max_drawdown = min(max_drawdown, drawdown)
        if low <= stop:
            exit_px = stop
            exit_reason = 'stop'
            exit_i = i
            break
        if runup >= p.trail_start_pct:
            trail = peak * (1 - p.trail_giveback / 100)
            if low <= trail:
                exit_px = trail
                exit_reason = 'trail'
                exit_i = i
                break
        if p.exit_on_leave_top10 and (b.get('rank_1h') is None or int(b['rank_1h']) > 10):
            exit_px = close
            exit_reason = 'left_top10'
            exit_i = i
            break
    if exit_px is None:
        last = bars[end_i]
        exit_px = float(last['close'])
        exit_reason = 'time_stop' if end_i < len(bars) - 1 else 'session_end'
        exit_i = end_i
    raw_ret = (exit_px / entry - 1) * 100
    net_ret = raw_ret - FEE_SLIP_PCT
    return {
        'session_id': bars[0]['session_id'],
        'inst_id': bars[0]['inst_id'],
        'entry_ts': entry_bar['ts_iso'],
        'exit_ts': bars[exit_i]['ts_iso'],
        'entry': entry,
        'exit': exit_px,
        'raw_ret_pct': raw_ret,
        'net_ret_pct': net_ret,
        'exit_reason': exit_reason,
        'bars_held': exit_i - p.delay_bars,
        'max_runup_pct': max_runup,
        'max_drawdown_pct': max_drawdown,
        'entry_rank': int(entry_bar['entry_rank_1h']),
        'entry_change': entry_change,
        'cur_change': cur_change,
        'vol_ratio': vol_ratio_at(bars, p.delay_bars),
    }


def summarize(params, trades):
    vals = [t['net_ret_pct'] for t in trades]
    wins = [x for x in vals if x > 0]
    losses = [x for x in vals if x <= 0]
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    by_day = defaultdict(list)
    for t in trades:
        day = t['entry_ts'][:10]
        by_day[day].append(t['net_ret_pct'])
    day_sums = [sum(v) for v in by_day.values()]
    inst = defaultdict(list)
    for t in trades:
        inst[t['inst_id']].append(t['net_ret_pct'])
    worst_inst = sorted(((k, len(v), sum(v)) for k, v in inst.items()), key=lambda x: x[2])[:5]
    reasons = defaultdict(int)
    for t in trades:
        reasons[t['exit_reason']] += 1
    return {
        **asdict(params),
        'trades': len(trades),
        'win_rate': len(wins) / len(vals) * 100 if vals else 0,
        'net_avg_pct': sum(vals) / len(vals) if vals else 0,
        'net_sum_pct': sum(vals),
        'profit_factor': gross_profit / gross_loss if gross_loss > 0 else 999,
        'avg_win_pct': sum(wins) / len(wins) if wins else 0,
        'avg_loss_pct': sum(losses) / len(losses) if losses else 0,
        'max_loss_pct': min(vals) if vals else 0,
        'max_win_pct': max(vals) if vals else 0,
        'avg_bars_held': sum(t['bars_held'] for t in trades) / len(trades) if trades else 0,
        'days': len(by_day),
        'positive_days': sum(1 for x in day_sums if x > 0),
        'day_win_rate': sum(1 for x in day_sums if x > 0) / len(day_sums) * 100 if day_sums else 0,
        'worst_day_pct': min(day_sums) if day_sums else 0,
        'best_day_pct': max(day_sums) if day_sums else 0,
        'exit_reasons': dict(reasons),
        'worst_instruments': worst_inst,
    }


def candidate_params():
    out = []
    idx = 1
    # Bounded grid: targeted candidates after live Top10v1 showed chase-entry weakness.
    for delay in [1, 2]:
      for max_rank in [3, 5]:
       for min_chg in [1.0, 2.0, 3.0]:
        for max_chg in [8.0, 12.0]:
         if max_chg <= min_chg: continue
         for min_cur in [1.0, 2.0]:
          for reclaim in [True]:
           for min_vol in [0.0, 1.2]:
            for stop in [0.8, 1.0]:
             for trail_start in [1.0, 1.5]:
              for giveback in [0.5, 0.8]:
               for tstop in [6, 12]:
                name = f'top10scan_d{delay}_r{max_rank}_chg{min_chg:g}-{max_chg:g}_cur{min_cur:g}_vol{min_vol:g}_sl{stop:g}_tr{trail_start:g}x{giveback:g}_t{tstop}'
                out.append(Params(name, delay, max_rank, min_chg, max_chg, min_cur, reclaim, min_vol, stop, trail_start, giveback, tstop, True))
                idx += 1
    return out


def main():
    sessions = load_sessions()
    coverage = {
        'sessions': len(sessions),
        'bars': sum(len(v) for v in sessions.values()),
        'min_ts': min((b['ts_iso'] for bars in sessions.values() for b in bars), default=None),
        'max_ts': max((b['ts_iso'] for bars in sessions.values() for b in bars), default=None),
        'insts': len({bars[0]['inst_id'] for bars in sessions.values() if bars}),
    }
    results = []
    best_trades = {}
    params_list = candidate_params()
    for n, p in enumerate(params_list, 1):
        trades = []
        seen_inst_recent_losses = defaultdict(int)
        for sid, bars in sessions.items():
            tr = run_trade(bars, p)
            if tr:
                trades.append(tr)
        if len(trades) < MIN_TRADES:
            continue
        s = summarize(p, trades)
        # robustness gate: avoid tiny PF / one-day dependency / uncontrolled tail
        if s['profit_factor'] < 1.05:
            continue
        if s['max_loss_pct'] < -2.3:
            continue
        if s['day_win_rate'] < 50:
            continue
        results.append(s)
        if len(best_trades) < 20:
            best_trades[p.name] = trades[:200]
    results.sort(key=lambda r: (r['net_avg_pct'], r['profit_factor'], r['trades'], r['day_win_rate']), reverse=True)
    payload = {
        'generated_at': datetime.now(timezone.utc).isoformat(),
        'coverage': coverage,
        'fee_slip_pct': FEE_SLIP_PCT,
        'params_scanned': len(params_list),
        'qualified': len(results),
        'top': results[:50],
    }
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
    if results:
        with OUT_CSV.open('w', newline='', encoding='utf-8') as f:
            fields = [k for k in results[0].keys() if k not in ('exit_reasons','worst_instruments')]
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for r in results[:500]:
                w.writerow({k: r.get(k) for k in fields})
    print(json.dumps({**payload, 'top': results[:10]}, ensure_ascii=False, indent=2))

if __name__ == '__main__':
    main()
