#!/usr/bin/env python3
"""
Parameter sweep for 1H Top10 strategies with session tracking.
目標：找出 win_rate > 50% 且 PF > 1.5 的參數組合。
使用 tmp_top10_training_optimizer.py 的入場邏輯（含 reclaim_entry_price, green_confirm, upper_wick）
但套用生產環境的 session tracking 限制。
"""
from __future__ import annotations
import json, sqlite3, math
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

DB = Path("data/okx_micro_5m_tracking.sqlite")
OUT = Path("data/param_sweep_results.json")
COST_PCT = 0.16  # production round-trip cost

@dataclass(frozen=True)
class EntryRule:
    delay_bars: int          # 1, 2, 3
    max_entry_rank: int      # 3, 5
    min_entry_change: float  # 1, 2, 3
    max_entry_change: float  # 8, 10, 12
    require_green_confirm: bool
    max_upper_wick_pct: float  # 0.8, 1.2, None
    reclaim_entry_price: bool

    @property
    def name(self):
        parts = [
            f"d{self.delay_bars}",
            f"r{self.max_entry_rank}",
            f"chg{self.min_entry_change:g}-{self.max_entry_change:g}",
        ]
        if self.require_green_confirm:
            parts.append("green")
        if self.max_upper_wick_pct is not None:
            parts.append(f"uw{self.max_upper_wick_pct:g}")
        if self.reclaim_entry_price:
            parts.append("reclaim")
        return "_".join(parts)

@dataclass(frozen=True)
class ExitRule:
    sl_pct: float
    tp_pct: float | None
    time_stop_bars: int      # 6, 8, 12, 18
    breakeven_after_pct: float | None  # None = disabled, or 0.6, 0.8
    trail_start_pct: float
    trail_giveback_pct: float

    @property
    def name(self):
        parts = [f"sl{self.sl_pct:g}"]
        if self.breakeven_after_pct:
            parts.append(f"be{self.breakeven_after_pct:g}")
        parts.append(f"tr{self.trail_start_pct:g}x{self.trail_giveback_pct:g}")
        parts.append(f"t{self.time_stop_bars}")
        return "_".join(parts)

def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z', '+00:00'))

def load_data():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    snaps = []
    for sid, ts in con.execute('SELECT id, captured_at FROM snapshots ORDER BY id'):
        ranks = [dict(r) for r in con.execute(
            'SELECT * FROM rankings WHERE snapshot_id=? ORDER BY rank_1h', (sid,))]
        snaps.append({'id': sid, 'ts': ts, 'dt': parse_ts(ts), 'ranks': ranks})
    candles = defaultdict(list)
    for r in con.execute('SELECT inst_id, ts_iso, ts_ms, open, high, low, close FROM candles_5m ORDER BY inst_id, ts_ms'):
        candles[r['inst_id']].append(dict(r))
    return snaps, candles

def first_candle_at_or_after(bars, dt):
    target = dt.timestamp() * 1000
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(bars[mid]['ts_ms']) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(bars) else None

def make_events(snaps, rmin, rmax):
    events = []
    prev_in = set()
    for snap in snaps:
        cur = set()
        for r in snap['ranks']:
            rank = int(r['rank_1h'])
            inst = r['inst_id']
            if rmin <= rank <= rmax:
                cur.add(inst)
                if inst not in prev_in:
                    events.append({
                        'ts': snap['ts'], 'dt': snap['dt'], 'inst_id': inst, 'rank': rank,
                        'chg': float(r['change_1h_pct'] or 0),
                        'vol_ratio': float(r['vol_ratio_5m'] or 0),
                        'price': float(r['last'] or 0)
                    })
        prev_in = cur
    return events

def check_entry_conditions(e, rule, entry_price):
    """檢查進場條件（含 reclaim_entry_price 邏輯）"""
    if not (rule.min_entry_change <= e['chg'] <= rule.max_entry_change):
        return False
    if rule.max_upper_wick_pct is not None:
        # 需要當根 K 線數據，這裡簡化：在 trade_for_event 中用實際 K 線檢查
        pass
    return True

def trade_for_event(e, entry_rule: EntryRule, exit_rule: ExitRule, candles):
    """單筆交易模擬，含 reclaim_entry_price 邏輯"""
    if not (entry_rule.min_entry_change <= e['chg'] <= entry_rule.max_entry_change):
        return None
    if e['rank'] > entry_rule.max_entry_rank:
        return None
    
    bars = candles.get(e['inst_id']) or []
    idx = first_candle_at_or_after(bars, e['dt'])
    if idx is None or idx >= len(bars):
        return None
    
    entry_bar = bars[idx]
    entry_price = float(entry_bar['close'] or e['price'])
    if entry_price <= 0:
        return None
    
    # 檢查 green confirm
    if entry_rule.require_green_confirm:
        if float(entry_bar['close'] or 0) < float(entry_bar['open'] or 0):
            return None
    
    # 檢查 upper wick
    if entry_rule.max_upper_wick_pct is not None:
        high = float(entry_bar['high'] or 0)
        low = float(entry_bar['low'] or 0)
        close = float(entry_bar['close'] or 0)
        open_ = float(entry_bar['open'] or 0)
        if high > 0 and high != low:
            upper_wick = high - max(close, open_)
            upper_wick_pct = (upper_wick / (high - low)) * 100
            if upper_wick_pct > entry_rule.max_upper_wick_pct:
                return None
    
    # reclaim_entry_price: 等價格回踩並反彈回 entry_price 才真正進場
    # 在優化器邏輯中：breakout -> pullback -> close >= entry_price -> enter
    # 這裡簡化：從 idx+1 開始找第一根 close >= entry_price 的 K 線
    actual_entry_idx = idx
    actual_entry_price = entry_price
    
    if entry_rule.reclaim_entry_price:
        for i in range(idx + 1, min(len(bars), idx + entry_rule.delay_bars * 4 + 20)):
            b = bars[i]
            c = float(b['close'] or 0)
            o = float(b['open'] or 0)
            if c >= entry_price and c >= o:  # 綠 K 且收回 entry_price
                actual_entry_idx = i
                actual_entry_price = c
                break
        else:
            return None  # 未回踩確認，放棄
    else:
        # 標準邏輯：delay_bars 後按 close 進場
        if idx + entry_rule.delay_bars < len(bars):
            actual_entry_idx = idx + entry_rule.delay_bars
            actual_entry_price = float(bars[actual_entry_idx]['close'] or 0)
        else:
            return None
    
    if actual_entry_price <= 0:
        return None
    
    # 出場模擬
    stop_price = actual_entry_price * (1 - exit_rule.sl_pct / 100.0)
    peak = actual_entry_price
    exit_px = None
    reason = None
    exit_i = actual_entry_idx
    
    breakeven_activated = False
    trail_activated = False
    
    for i in range(actual_entry_idx + 1, min(len(bars), actual_entry_idx + exit_rule.time_stop_bars + 1)):
        b = bars[i]
        high = float(b['high'] or 0)
        low = float(b['low'] or 0)
        close = float(b['close'] or 0)
        
        if high > peak:
            peak = high
        
        # hard stop
        if low <= stop_price:
            exit_px = stop_price
            reason = 'hard_stop'
            exit_i = i
            break
        
        runup = (peak / actual_entry_price - 1) * 100
        
        # breakeven
        if exit_rule.breakeven_after_pct and runup >= exit_rule.breakeven_after_pct and not breakeven_activated:
            stop_price = max(stop_price, actual_entry_price)
            breakeven_activated = True
        
        # trailing
        if runup >= exit_rule.trail_start_pct and not trail_activated:
            trail_activated = True
        
        if trail_activated:
            trail_price = peak * (1 - exit_rule.trail_giveback_pct / 100.0)
            if low <= trail_price:
                exit_px = trail_price
                reason = 'trail'
                exit_i = i
                break
            stop_price = max(stop_price, trail_price)
        
        # time stop check at end of loop
        if i == min(len(bars), actual_entry_idx + exit_rule.time_stop_bars) - 1:
            if exit_px is None:
                exit_px = close
                reason = 'time_stop'
                exit_i = i
                break
    
    if exit_px is None:
        exit_i = min(len(bars) - 1, actual_entry_idx + exit_rule.time_stop_bars)
        exit_px = float(bars[exit_i]['close'])
        reason = 'session_end'
    
    raw = (exit_px / actual_entry_price - 1) * 100
    net = raw - COST_PCT
    
    return {
        **e, 'entry_idx': actual_entry_idx, 'exit_idx': exit_i,
        'entry_price': actual_entry_price, 'exit_price': exit_px,
        'raw': raw, 'net': net, 'reason': reason,
        'bars_held': exit_i - actual_entry_idx,
        'entry_ts': bars[actual_entry_idx]['ts_iso'],
        'exit_ts': bars[exit_i]['ts_iso']
    }

def apply_guards(trades, entry_rule):
    """生產環境 guards：cooldown, 1/12h per inst, daily cap"""
    trades = sorted(trades, key=lambda x: x['entry_ts'])
    out = []
    last_loss_dt = {}
    inst_entries_12h = defaultdict(list)
    daily_count = defaultdict(int)
    max_daily = 999  # 不限制每日次數
    
    for t in trades:
        dt = parse_ts(t['entry_ts'])
        day = t['entry_ts'][:10]
        inst = t['inst_id']
        
        if daily_count[day] >= max_daily:
            continue
        
        if inst in last_loss_dt and (dt - last_loss_dt[inst]).total_seconds() < 180 * 60:
            continue
        
        cutoff = dt - timedelta(hours=12)
        inst_entries_12h[inst] = [x for x in inst_entries_12h[inst] if x >= cutoff]
        if len(inst_entries_12h[inst]) >= 1:
            continue
        
        out.append(t)
        daily_count[day] += 1
        inst_entries_12h[inst].append(dt)
        if t['net'] <= 0:
            last_loss_dt[inst] = dt
    return out

def summarize(trades, entry_rule, exit_rule):
    if not trades:
        return None
    vals = [t['net'] for t in trades]
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    days = defaultdict(float)
    inst = defaultdict(float)
    for t in trades:
        d = t['entry_ts'][:10]
        days[d] += t['net']
        inst[t['inst_id']] += t['net']
    day_vals = list(days.values())
    reas = Counter(t['reason'] for t in trades)
    
    return {
        'entry': asdict(entry_rule),
        'exit': asdict(exit_rule),
        'strategy_name': f"{entry_rule.name}_{exit_rule.name}",
        'trades': len(vals),
        'wins': len(wins),
        'losses': len(losses),
        'win_rate': len(wins) / len(vals) * 100,
        'net_avg': sum(vals) / len(vals),
        'net_sum': sum(vals),
        'avg_raw': max(vals) if vals else 0,
        'profit_factor': sum(wins) / abs(sum(losses)) if losses else 999,
        'max_loss': min(vals) if vals else 0,
        'max_win': max(vals) if vals else 0,
        'day_win_rate': sum(1 for x in day_vals if x > 0) / len(day_vals) * 100 if day_vals else 0,
        'avg_day': sum(day_vals) / len(day_vals) if day_vals else 0,
        'worst_day': min(day_vals) if day_vals else 0,
        'best_day': max(day_vals) if day_vals else 0,
        'exit_reasons': dict(reas),
        'worst_inst': sorted(inst.items(), key=lambda x: x[1])[:3],
        'best_inst': sorted(inst.items(), key=lambda x: x[1], reverse=True)[:3],
    }

def main():
    snaps, candles = load_data()
    
    # ===== 參數網格 =====
    entry_grid = [
        EntryRule(d, r, cmin, cmax, green, uw, reclaim)
        for d in [1, 2, 3]
        for r in [3, 5]
        for cmin, cmax in [(1, 8), (1, 10), (1, 12), (2, 8), (3, 10), (3, 12)]
        for green in [True, False]
        for uw in [0.8, 1.2, None]
        for reclaim in [True, False]
        # 篩選：reclaim=True 時需要 green=True 且 uw<=0.8
        if not (reclaim and (not green or (uw is not None and uw > 1.0)))
    ]
    
    exit_grid = [
        ExitRule(sl, None, t, be, ts, tg)
        for sl in [1.0, 1.2, 1.5, 2.0]
        for t in [6, 8, 12, 18]
        for be in [None, 0.6, 0.8]  # None = disabled
        for ts, tg in [(0.8, 0.4), (0.9, 0.4), (1.0, 0.5), (1.5, 0.5)]
    ]
    
    print(f"Total combos: {len(entry_grid)} x {len(exit_grid)} = {len(entry_grid) * len(exit_grid)}")
    
    results = []
    best_by_wr = []
    
    for entry_rule in entry_grid:
        # 預計算所有符合基本條件的事件
        events = make_events(snaps, 1, entry_rule.max_entry_rank)
        print(f"Testing entry: {entry_rule.name} | events={len(events)}")
        
        for exit_rule in exit_grid:
            raw_trades = []
            for e in events:
                tr = trade_for_event(e, entry_rule, exit_rule, candles)
                if tr:
                    raw_trades.append(tr)
            
            if len(raw_trades) < 30:
                continue
            
            guarded = apply_guards(raw_trades, entry_rule)
            if len(guarded) < 30:
                continue
            
            s = summarize(guarded, entry_rule, exit_rule)
            if s:
                results.append(s)
                if s['win_rate'] >= 50 and s['profit_factor'] >= 1.5:
                    best_by_wr.append(s)
                    print(f"  ✅ FOUND: {s['strategy_name']} WR={s['win_rate']:.1f}% PF={s['profit_factor']:.2f} NetAvg={s['net_avg']:.3f}% trades={s['trades']}")
    
    results.sort(key=lambda x: (x['win_rate'], x['profit_factor'], x['net_avg']), reverse=True)
    
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({
        'total_tested': len(results),
        'top_50': results[:50],
        'meet_criteria': best_by_wr
    }, indent=2, ensure_ascii=False))
    
    print(f"\n=== Top 20 ===")
    for r in results[:20]:
        print(f"{r['strategy_name']}: WR={r['win_rate']:.1f}% PF={r['profit_factor']:.2f} NetAvg={r['net_avg']:.3f}% Trades={r['trades']}")
    
    if best_by_wr:
        print(f"\n=== MEETS >50% WR & PF>1.5: {len(best_by_wr)} strategies ===")
        for r in best_by_wr:
            print(f"  {r['strategy_name']}: WR={r['win_rate']:.1f}% PF={r['profit_factor']:.2f} NetAvg={r['net_avg']:.3f}%")

if __name__ == '__main__':
    main()