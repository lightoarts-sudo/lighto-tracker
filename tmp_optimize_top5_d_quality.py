from __future__ import annotations
import json, os, sqlite3
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date
from itertools import product

REPO = Path('C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker')
os.chdir(REPO)
DB = REPO / 'data/okx_micro_5m_tracking.sqlite'
OUT = REPO / 'data' / 'top5_d_quality_optimized_latest.json'
COST = 0.18


def parse_ts(s: str) -> datetime:
    return datetime.fromisoformat(s.replace('Z', '+00:00'))


def load():
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    snaps = []
    for sid, ts in con.execute('select id,captured_at from snapshots order by id'):
        ranks = [dict(r) for r in con.execute('select * from rankings where snapshot_id=? order by rank_1h', (sid,))]
        snaps.append({'id': sid, 'ts': ts, 'dt': parse_ts(ts), 'ranks': ranks})
    candles = defaultdict(list)
    for r in con.execute('select inst_id, ts_iso, ts_ms, open, high, low, close, vol, vol_ccy from candles_5m order by inst_id, ts_ms'):
        candles[r['inst_id']].append(dict(r))
    return snaps, candles


def first_idx(bars, dt):
    target = dt.timestamp() * 1000
    lo, hi = 0, len(bars)
    while lo < hi:
        mid = (lo + hi) // 2
        if int(bars[mid]['ts_ms']) < target:
            lo = mid + 1
        else:
            hi = mid
    return lo if lo < len(bars) else None


def make_events(snaps):
    events = []
    prev = set()
    sess_counter = 0
    session_id = {}
    for snap in snaps:
        cur = set()
        for r in snap['ranks']:
            rank = int(r['rank_1h'])
            inst = r['inst_id']
            if 1 <= rank <= 5:
                cur.add(inst)
                if inst not in prev:
                    sess_counter += 1
                    session_id[inst] = sess_counter
                    events.append({
                        'ts': snap['ts'], 'dt': snap['dt'], 'inst_id': inst, 'rank': rank,
                        'chg': float(r['change_1h_pct'] or 0),
                        'vol_ratio': float(r['vol_ratio_5m'] or 0),
                        'atr': float(r['atr_pct_5m'] or 0),
                        'ema9': float(r['ema9_5m'] or 0),
                        'ema21': float(r['ema21_5m'] or 0),
                        'high12': float(r['high12_5m'] or 0),
                        'low12': float(r['low12_5m'] or 0),
                        'session_id': session_id[inst],
                    })
        prev = cur
    return events


def score_event(e, bars, idx, cfg):
    b = bars[idx]
    close = float(b['close'])
    open_ = float(b['open'])
    high = float(b['high'])
    low = float(b['low'])
    rng = max(high - low, close * 0.0001)
    upper = (high - close) / rng
    body = abs(close - open_) / rng
    pos = (close - low) / rng
    score = 0.0
    score += max(0, 6 - int(e['rank'])) * cfg['rank_w']
    score += max(0, cfg['chg_peak_score'] - abs(e['chg'] - cfg['chg_peak']) * cfg['chg_penalty'])
    score += min(cfg['vol_cap_score'], max(0, e['vol_ratio']) * cfg['vol_w'])
    if e['ema9'] and e['ema21'] and e['ema9'] > e['ema21']:
        score += cfg['ema_bonus']
    if close > open_:
        score += cfg['green_bonus']
    if upper <= cfg['upper_max']:
        score += cfg['upper_bonus']
    if pos >= cfg['close_pos_min']:
        score += cfg['close_pos_bonus']
    if body >= cfg['body_min']:
        score += cfg['body_bonus']
    if e['atr'] and e['atr'] <= cfg['atr_max']:
        score += cfg['atr_bonus']
    return score, {'upper': upper, 'body': body, 'close_pos': pos}


def exit_trade(bars, idx, cfg):
    entry = float(bars[idx]['close'])
    if entry <= 0:
        return None
    stop = entry * (1 - cfg['stop_pct'] / 100)
    peak = entry
    exit_px = None
    reason = None
    exit_i = idx
    end = min(len(bars) - 1, idx + cfg['hold_bars'])
    for i in range(idx + 1, end + 1):
        b = bars[i]
        high = float(b['high'])
        low = float(b['low'])
        peak = max(peak, high)
        if low <= stop:
            exit_px = stop
            reason = 'hard_stop'
            exit_i = i
            break
        runup = (peak / entry - 1) * 100
        if runup >= cfg['trail_start']:
            trail = peak * (1 - cfg['trail_giveback'] / 100)
            if low <= trail:
                exit_px = trail
                reason = 'trail'
                exit_i = i
                break
    if exit_px is None:
        exit_px = float(bars[end]['close'])
        reason = 'time_stop'
        exit_i = end
    raw = (exit_px / entry - 1) * 100
    return entry, exit_px, raw, raw - COST, reason, exit_i


def make_trade(e, bars_by_inst, cfg):
    if not (cfg['chg_min'] <= e['chg'] <= cfg['chg_max']):
        return None
    if e['vol_ratio'] < cfg['vol_min']:
        return None
    if cfg['require_ema'] and not (e['ema9'] and e['ema21'] and e['ema9'] > e['ema21']):
        return None
    if cfg['atr_hard_max'] and e['atr'] and e['atr'] > cfg['atr_hard_max']:
        return None
    bars = bars_by_inst.get(e['inst_id']) or []
    idx = first_idx(bars, e['dt'])
    if idx is None or idx + 1 >= len(bars):
        return None
    sc, diag = score_event(e, bars, idx, cfg)
    if sc < cfg['score_thr']:
        return None
    ex = exit_trade(bars, idx, cfg)
    if not ex:
        return None
    entry, exit_px, raw, net, reason, exit_i = ex
    return {
        **e, 'score': sc, **diag,
        'entry_ts': bars[idx]['ts_iso'], 'exit_ts': bars[exit_i]['ts_iso'],
        'entry': entry, 'exit': exit_px, 'raw': raw, 'net': net, 'reason': reason,
        'bars_held': exit_i - idx,
    }


def apply_guards(trades, loss_cooldown_min=180, max_inst_12h=1):
    # No daily cap. Same coin de-dup only.
    trades = sorted(trades, key=lambda x: x['entry_ts'])
    out = []
    seen_session = set()
    inst_entries = defaultdict(list)
    last_loss = {}
    for t in trades:
        dt = parse_ts(t['entry_ts'])
        inst = t['inst_id']
        skey = (inst, t['session_id'])
        if skey in seen_session:
            continue
        if inst in last_loss and (dt - last_loss[inst]).total_seconds() < loss_cooldown_min * 60:
            continue
        cutoff = dt - timedelta(hours=12)
        inst_entries[inst] = [x for x in inst_entries[inst] if x >= cutoff]
        if len(inst_entries[inst]) >= max_inst_12h:
            continue
        out.append(t)
        seen_session.add(skey)
        inst_entries[inst].append(dt)
        if t['net'] <= 0:
            last_loss[inst] = dt
    return out


def summarize(cfg, trades, all_days):
    vals = [t['net'] for t in trades]
    if not vals:
        return None
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    byday = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
    reasons = Counter(t['reason'] for t in trades)
    inst = defaultdict(float)
    for t in trades:
        d = t['entry_ts'][:10]
        byday[d]['pnl'] += t['net']
        byday[d]['trades'] += 1
        if t['net'] > 0:
            byday[d]['wins'] += 1
        else:
            byday[d]['losses'] += 1
        inst[t['inst_id']] += t['net']
    cum = 0.0
    daily = []
    for d in all_days:
        pnl = byday[d]['pnl']
        cum += pnl
        daily.append({'date': d, 'trades': byday[d]['trades'], 'wins': byday[d]['wins'], 'losses': byday[d]['losses'], 'daily_pct': round(pnl, 3), 'cum_pct': round(cum, 3)})
    day_vals = [byday[d]['pnl'] for d in all_days]
    return {
        'config': cfg,
        'trades': len(vals), 'wins': len(wins), 'losses': len(losses),
        'win_rate': len(wins) / len(vals) * 100,
        'net_sum': sum(vals), 'net_avg': sum(vals) / len(vals),
        'pf': sum(wins) / abs(sum(losses)) if losses else 999,
        'max_loss': min(vals), 'max_win': max(vals),
        'avg_calendar_day': sum(day_vals) / len(all_days),
        'pos_days': sum(1 for x in day_vals if x > 0),
        'day_win_rate': sum(1 for x in day_vals if x > 0) / len(all_days) * 100,
        'worst_day': min(day_vals), 'best_day': max(day_vals),
        'days_ge_1pct': sum(1 for x in day_vals if x >= 1),
        'days_le_neg1pct': sum(1 for x in day_vals if x <= -1),
        'avg_entries_day': len(vals) / len(all_days),
        'reasons': dict(reasons),
        'worst_instruments': sorted(inst.items(), key=lambda kv: kv[1])[:5],
        'best_instruments': sorted(inst.items(), key=lambda kv: kv[1], reverse=True)[:5],
        'daily': daily,
    }


def grid():
    base_score = {
        'rank_w': 8, 'chg_peak': 5, 'chg_peak_score': 25, 'chg_penalty': 7,
        'vol_w': 8, 'vol_cap_score': 20,
        'ema_bonus': 12, 'green_bonus': 8,
        'upper_bonus': 8, 'close_pos_bonus': 6, 'body_bonus': 5, 'atr_bonus': 5,
    }
    score_variants = [
        dict(base_score, upper_max=0.35, close_pos_min=0.55, body_min=0.20, atr_max=2.0),
        dict(base_score, upper_max=0.25, close_pos_min=0.60, body_min=0.25, atr_max=1.8),
        dict(base_score, upper_max=0.45, close_pos_min=0.50, body_min=0.15, atr_max=2.5),
    ]
    for chg_min, chg_max in [(2, 5), (3, 6), (3, 8), (4, 7), (4, 9), (5, 10)]:
      for vol_min in [0, 0.5, 1.0, 1.5]:
       for score_thr in [70, 75, 80, 85, 90, 95]:
        for require_ema in [False, True]:
         for atr_hard_max in [0, 1.5, 2.0, 3.0]:
          for stop_pct in [0.8, 1.0, 1.2]:
           for trail_start, trail_giveback in [(0.6, 0.3), (0.8, 0.4), (1.0, 0.5), (1.2, 0.6)]:
            for hold_bars in [3, 6, 9, 12]:
             for sv in score_variants:
                cfg = {
                    'chg_min': chg_min, 'chg_max': chg_max, 'vol_min': vol_min,
                    'score_thr': score_thr, 'require_ema': require_ema, 'atr_hard_max': atr_hard_max,
                    'stop_pct': stop_pct, 'trail_start': trail_start, 'trail_giveback': trail_giveback,
                    'hold_bars': hold_bars, **sv,
                }
                yield cfg


def main():
    snaps, candles = load()
    events = make_events(snaps)
    start = date.fromisoformat(snaps[0]['ts'][:10])
    end = date.fromisoformat(snaps[-1]['ts'][:10])
    all_days = []
    d = start
    while d <= end:
        all_days.append(d.isoformat())
        d += timedelta(days=1)

    results = []
    count = 0
    for cfg in grid():
        count += 1
        raw = []
        for e in events:
            t = make_trade(e, candles, cfg)
            if t:
                raw.append(t)
        trades = apply_guards(raw)
        if len(trades) < 25:
            continue
        s = summarize(cfg, trades, all_days)
        if not s:
            continue
        # Keep broad candidates; final sort below.
        results.append(s)

    def robust_key(s):
        # Prefer positive net/PF, enough trades, daily stability. Penalize large worst day.
        return (
            s['net_sum'] > 0,
            s['pf'],
            s['net_sum'],
            s['day_win_rate'],
            -abs(min(0, s['worst_day'])),
            s['trades'],
        )

    results.sort(key=robust_key, reverse=True)
    report = {
        'db': str(DB), 'range': [all_days[0], all_days[-1]], 'cost_pct': COST,
        'base': 'Top5 quality-score D variants, no daily cap, same-coin session dedup + 12h max1 + 180m loss cooldown',
        'grid_count': count, 'result_count': len(results),
        'top': results[:50],
    }
    OUT.write_text(json.dumps(report, indent=2), encoding='utf-8')
    print('saved', OUT)
    print('grid_count', count, 'result_count', len(results))
    for i, s in enumerate(results[:20], 1):
        c = s['config']
        print('\n#', i,
              'trades', s['trades'], 'win', round(s['win_rate'], 2), 'net', round(s['net_sum'], 3),
              'avgD', round(s['avg_calendar_day'], 3), 'PF', round(s['pf'], 3),
              'worstD', round(s['worst_day'], 3), 'posD', f"{s['pos_days']}/16",
              'ge1', s['days_ge_1pct'], 'le-1', s['days_le_neg1pct'])
        print(' cfg', {k: c[k] for k in ['chg_min','chg_max','vol_min','score_thr','require_ema','atr_hard_max','stop_pct','trail_start','trail_giveback','hold_bars','upper_max','close_pos_min','body_min','atr_max']})

if __name__ == '__main__':
    main()
