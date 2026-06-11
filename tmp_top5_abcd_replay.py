import sqlite3, json, os
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timedelta, date

repo = Path('C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker')
os.chdir(repo)
DB = repo / 'data/okx_micro_5m_tracking.sqlite'
COST = 0.18


def parse_ts(s):
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
    session_id = {}
    sess_counter = 0
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
                        'chg': float(r['change_1h_pct'] or 0), 'vol_ratio': float(r['vol_ratio_5m'] or 0),
                        'atr': float(r['atr_pct_5m'] or 0), 'ema9': float(r['ema9_5m'] or 0),
                        'ema21': float(r['ema21_5m'] or 0), 'high12': float(r['high12_5m'] or 0),
                        'low12': float(r['low12_5m'] or 0), 'structure': r.get('structure'),
                        'session_id': session_id[inst],
                    })
        prev = cur
    return events


def exit_from(bars, entry_i, stop_pct=1.0, trail_start=0.8, trail_giveback=0.4, hold=6):
    entry = float(bars[entry_i]['close'])
    if entry <= 0:
        return None
    stop = entry * (1 - stop_pct / 100)
    peak = entry
    exit_px = None
    reason = None
    exit_i = entry_i
    end = min(len(bars) - 1, entry_i + hold)
    for i in range(entry_i + 1, end + 1):
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
        if runup >= trail_start:
            trail = peak * (1 - trail_giveback / 100)
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
    net = raw - COST
    return entry, exit_px, raw, net, reason, exit_i


def recent_ema(bars, idx, n):
    alpha = 2 / (n + 1)
    start = max(0, idx - 60)
    ema = float(bars[start]['close'])
    for j in range(start + 1, idx + 1):
        ema = alpha * float(bars[j]['close']) + (1 - alpha) * ema
    return ema


def make_trade(e, candles, variant):
    if not (3 <= e['chg'] <= 8):
        return None
    bars = candles.get(e['inst_id']) or []
    idx = first_idx(bars, e['dt'])
    if idx is None or idx + 1 >= len(bars):
        return None
    entry_i = None
    note = ''

    if variant == 'A_session_dedup':
        entry_i = idx
        note = 'immediate'
    elif variant == 'B_5m_continuation':
        b0, b1 = bars[idx], bars[idx + 1]
        if float(b1['close']) > float(b0['close']) and float(b1['close']) > float(b1['open']):
            entry_i = idx + 1
            note = 'next_green_close_gt_signal'
        else:
            return None
    elif variant == 'C_pullback_reclaim':
        ema = e['ema9'] or recent_ema(bars, idx, 9)
        for j in range(idx + 1, min(len(bars), idx + 4)):
            b = bars[j]
            if float(b['low']) <= ema * 1.003 and float(b['close']) > ema and float(b['close']) > float(b['open']):
                entry_i = j
                note = 'ema9_reclaim'
                break
        if entry_i is None:
            return None
    elif variant == 'D_quality_score':
        b0 = bars[idx]
        close = float(b0['close'])
        open_ = float(b0['open'])
        high = float(b0['high'])
        low = float(b0['low'])
        rng = max(high - low, close * 0.0001)
        upper = (high - close) / rng
        score = 0
        score += max(0, 6 - int(e['rank'])) * 8
        score += max(0, 25 - abs(e['chg'] - 5) * 7)
        vr = e['vol_ratio']
        score += min(20, max(0, vr) * 8)
        if e['ema9'] and e['ema21'] and e['ema9'] > e['ema21']:
            score += 12
        if close > open_:
            score += 8
        if upper < 0.35:
            score += 8
        if e['atr'] and e['atr'] <= 2.0:
            score += 5
        if score >= 70:
            entry_i = idx
            note = f'score_{score:.1f}'
        else:
            return None
    else:
        raise ValueError(variant)

    ex = exit_from(bars, entry_i)
    if not ex:
        return None
    entry, exit_px, raw, net, reason, exit_i = ex
    return {
        **e, 'variant': variant, 'entry_ts': bars[entry_i]['ts_iso'], 'exit_ts': bars[exit_i]['ts_iso'],
        'entry': entry, 'exit': exit_px, 'raw': raw, 'net': net, 'reason': reason,
        'bars_held': exit_i - entry_i, 'note': note,
    }


def apply_same_coin_guards(trades):
    trades = sorted(trades, key=lambda x: x['entry_ts'])
    out = []
    inst_entries = defaultdict(list)
    last_loss = {}
    seen_session = set()
    for t in trades:
        dt = parse_ts(t['entry_ts'])
        inst = t['inst_id']
        key = (inst, t['session_id'])
        if key in seen_session:
            continue
        if inst in last_loss and (dt - last_loss[inst]).total_seconds() < 180 * 60:
            continue
        cutoff = dt - timedelta(hours=12)
        inst_entries[inst] = [x for x in inst_entries[inst] if x >= cutoff]
        if len(inst_entries[inst]) >= 1:
            continue
        out.append(t)
        seen_session.add(key)
        inst_entries[inst].append(dt)
        if t['net'] <= 0:
            last_loss[inst] = dt
    return out


def summarize(trades, all_days):
    vals = [t['net'] for t in trades]
    if not vals:
        return None
    wins = [v for v in vals if v > 0]
    losses = [v for v in vals if v <= 0]
    byday = defaultdict(lambda: {'pnl': 0.0, 'trades': 0, 'wins': 0, 'losses': 0})
    reasons = Counter(t['reason'] for t in trades)
    for t in trades:
        d = t['entry_ts'][:10]
        byday[d]['pnl'] += t['net']
        byday[d]['trades'] += 1
        if t['net'] > 0:
            byday[d]['wins'] += 1
        else:
            byday[d]['losses'] += 1
    cum = 0
    daily = []
    for d in all_days:
        pnl = byday[d]['pnl']
        cum += pnl
        daily.append({'date': d, 'trades': byday[d]['trades'], 'wins': byday[d]['wins'], 'losses': byday[d]['losses'], 'daily_pct': round(pnl, 3), 'cum_pct': round(cum, 3)})
    day_vals = [byday[d]['pnl'] for d in all_days]
    active = [x for x in day_vals if abs(x) > 1e-12]
    return {
        'trades': len(vals), 'wins': len(wins), 'losses': len(losses), 'win_rate': len(wins) / len(vals) * 100,
        'net_sum': sum(vals), 'net_avg': sum(vals) / len(vals), 'pf': sum(wins) / abs(sum(losses)) if losses else 999,
        'max_loss': min(vals), 'max_win': max(vals), 'avg_calendar_day': sum(day_vals) / len(all_days),
        'active_days': len(active), 'pos_calendar_days': sum(1 for x in day_vals if x > 0),
        'calendar_day_win_rate': sum(1 for x in day_vals if x > 0) / len(all_days) * 100,
        'worst_day': min(day_vals), 'best_day': max(day_vals),
        'days_ge_1pct': sum(1 for x in day_vals if x >= 1), 'days_le_neg1pct': sum(1 for x in day_vals if x <= -1),
        'avg_entries_calendar_day': len(vals) / len(all_days), 'reasons': dict(reasons), 'daily': daily,
    }


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
    variants = ['A_session_dedup', 'B_5m_continuation', 'C_pullback_reclaim', 'D_quality_score']
    runs = []
    for v in variants:
        raw = []
        for e in events:
            t = make_trade(e, candles, v)
            if t:
                raw.append(t)
        trades = apply_same_coin_guards(raw)
        s = summarize(trades, all_days)
        runs.append({'variant': v, 'summary': s})
    out = repo / 'data' / 'top5_abcd_no_daily_cap_replay_latest.json'
    out.write_text(json.dumps({
        'range': [all_days[0], all_days[-1]],
        'cost_pct': COST,
        'base': 'Top5 rank1-5 chg3-8 no daily cap; same coin session dedup + 12h max1 + loss cooldown 180m',
        'runs': runs,
    }, indent=2), encoding='utf-8')
    print('saved', out)
    for r in runs:
        s = r['summary']
        print('\n' + r['variant'])
        if not s:
            print('no trades')
            continue
        print('trades', s['trades'], 'wins', s['wins'], 'losses', s['losses'], 'win_rate', round(s['win_rate'], 2),
              'net_sum', round(s['net_sum'], 3), 'net_avg', round(s['net_avg'], 3), 'pf', round(s['pf'], 3),
              'avg_cal_day', round(s['avg_calendar_day'], 3), 'worst_day', round(s['worst_day'], 3),
              'best_day', round(s['best_day'], 3), 'pos_days', s['pos_calendar_days'],
              'days_ge_1', s['days_ge_1pct'], 'days_le_neg1', s['days_le_neg1pct'],
              'avg_entries_day', round(s['avg_entries_calendar_day'], 2), 'reasons', s['reasons'])
        for drow in s['daily']:
            print(drow['date'], drow['trades'], drow['daily_pct'], drow['cum_pct'])


if __name__ == '__main__':
    main()
