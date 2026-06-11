#!/usr/bin/env python
from __future__ import annotations
import json, sqlite3, math
from pathlib import Path
from dataclasses import dataclass, asdict
from collections import defaultdict, Counter
from datetime import datetime, timedelta, timezone

DB=Path('data/okx_micro_5m_tracking.sqlite')
OUT=Path('data/daily_top_rank_strategy_scan_latest.json')
COST_PCT=0.18

@dataclass(frozen=True)
class P:
    family:str
    rank_min:int
    rank_max:int
    chg_min:float
    chg_max:float
    vol_min:float
    stop_pct:float
    trail_start:float
    trail_giveback:float
    hold_bars:int
    cooldown_min:int=180
    max_inst_12h:int=1
    max_daily_entries:int=999
    @property
    def name(self):
        return (f'{self.family}_r{self.rank_min}_{self.rank_max}_chg{self.chg_min:g}_{self.chg_max:g}'
                f'_vol{self.vol_min:g}_sl{self.stop_pct:g}_tr{self.trail_start:g}x{self.trail_giveback:g}'
                f'_h{self.hold_bars}_cap{self.max_daily_entries}').replace('.','')

def parse_ts(s):
    return datetime.fromisoformat(s.replace('Z','+00:00'))

def load():
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    snaps=[]
    for sid,ts in con.execute('select id,captured_at from snapshots order by id'):
        ranks=[dict(r) for r in con.execute('select * from rankings where snapshot_id=? order by rank_1h',(sid,))]
        snaps.append({'id':sid,'ts':ts,'dt':parse_ts(ts),'ranks':ranks})
    candles=defaultdict(list)
    for r in con.execute('select inst_id, ts_iso, ts_ms, open, high, low, close from candles_5m order by inst_id, ts_ms'):
        candles[r['inst_id']].append(dict(r))
    return snaps,candles

def first_candle_at_or_after(bars, dt):
    # linear ok enough per instrument? use binary search on ts_iso parsed cache not available
    target=dt.timestamp()*1000
    lo,hi=0,len(bars)
    while lo<hi:
        mid=(lo+hi)//2
        if int(bars[mid]['ts_ms']) < target: lo=mid+1
        else: hi=mid
    return lo if lo < len(bars) else None

def make_events(snaps, family, rmin, rmax):
    events=[]; prev_in=set()
    for snap in snaps:
        cur=set()
        for r in snap['ranks']:
            rank=int(r['rank_1h'])
            inst=r['inst_id']
            if rmin <= rank <= rmax:
                cur.add(inst)
                # only new entries into the rank bucket to avoid repeated chase every snapshot
                if inst not in prev_in:
                    events.append({
                        'family':family,'ts':snap['ts'],'dt':snap['dt'],'inst_id':inst,'rank':rank,
                        'chg':float(r['change_1h_pct'] or 0),'vol_ratio':float(r['vol_ratio_5m'] or 0),
                        'price':float(r['last'] or 0)
                    })
        prev_in=cur
    return events

def trade_for_event(e,p,candles):
    if not (p.rank_min <= e['rank'] <= p.rank_max): return None
    if not (p.chg_min <= e['chg'] <= p.chg_max): return None
    if e['vol_ratio'] < p.vol_min: return None
    bars=candles.get(e['inst_id']) or []
    idx=first_candle_at_or_after(bars,e['dt'])
    if idx is None or idx>=len(bars): return None
    entry=float(bars[idx]['close'] or e['price'])
    if entry<=0: return None
    stop=entry*(1-p.stop_pct/100.0)
    peak=entry; exit_px=None; reason=None; exit_i=idx
    end=min(len(bars)-1, idx+p.hold_bars)
    for i in range(idx+1,end+1):
        b=bars[i]; high=float(b['high']); low=float(b['low']); close=float(b['close'])
        peak=max(peak, high)
        if low <= stop:
            exit_px=stop; reason='hard_stop'; exit_i=i; break
        runup=(peak/entry-1)*100
        if p.trail_start>0 and runup >= p.trail_start:
            trail=peak*(1-p.trail_giveback/100.0)
            if low <= trail:
                exit_px=trail; reason='trail'; exit_i=i; break
    if exit_px is None:
        exit_px=float(bars[end]['close']); reason='time_stop'; exit_i=end
    raw=(exit_px/entry-1)*100
    net=raw-COST_PCT
    return {**e,'strategy':p.name,'entry_ts':bars[idx]['ts_iso'],'exit_ts':bars[exit_i]['ts_iso'],
            'entry':entry,'exit':exit_px,'net':net,'raw':raw,'reason':reason,'bars_held':exit_i-idx}

def apply_guards(trades,p):
    trades=sorted(trades,key=lambda x:x['entry_ts'])
    out=[]; last_loss_dt={}; inst_entries=defaultdict(list); daily_count=defaultdict(int)
    for t in trades:
        dt=parse_ts(t['entry_ts']); day=t['entry_ts'][:10]; inst=t['inst_id']
        if daily_count[day] >= p.max_daily_entries: continue
        if inst in last_loss_dt and (dt-last_loss_dt[inst]).total_seconds() < p.cooldown_min*60: continue
        cutoff=dt-timedelta(hours=12)
        inst_entries[inst]=[x for x in inst_entries[inst] if x>=cutoff]
        if len(inst_entries[inst]) >= p.max_inst_12h: continue
        out.append(t); daily_count[day]+=1; inst_entries[inst].append(dt)
        if t['net'] <= 0: last_loss_dt[inst]=dt
    return out

def summarize(p,trades):
    vals=[t['net'] for t in trades]
    if not vals: return None
    wins=[v for v in vals if v>0]; losses=[v for v in vals if v<=0]
    days=defaultdict(float); day_counts=defaultdict(int)
    reasons=Counter(t['reason'] for t in trades)
    inst=defaultdict(float)
    for t in trades:
        d=t['entry_ts'][:10]; days[d]+=t['net']; day_counts[d]+=1; inst[t['inst_id']]+=t['net']
    day_vals=list(days.values())
    return {**asdict(p),'strategy':p.name,'trades':len(vals),'wins':len(wins),'losses':len(losses),
            'win_rate':len(wins)/len(vals)*100,'net_avg':sum(vals)/len(vals),'net_sum':sum(vals),
            'pf':sum(wins)/abs(sum(losses)) if losses else 999,'max_loss':min(vals),'max_win':max(vals),
            'days':len(days),'pos_days':sum(1 for x in day_vals if x>0),'day_win_rate':sum(1 for x in day_vals if x>0)/len(day_vals)*100,
            'avg_day':sum(day_vals)/len(day_vals),'worst_day':min(day_vals),'best_day':max(day_vals),
            'days_ge_1pct':sum(1 for x in day_vals if x>=1.0),'days_le_neg1pct':sum(1 for x in day_vals if x<=-1.0),
            'avg_entries_day':sum(day_counts.values())/len(day_counts),'reasons':dict(reasons),
            'worst_instruments':sorted(inst.items(),key=lambda kv:kv[1])[:5],
            'best_instruments':sorted(inst.items(),key=lambda kv:kv[1], reverse=True)[:5]}

def grid():
    fams=[('top10',1,10),('top5',1,5),('top20',1,20),('rank6_20',6,20),('pretop11_20',11,20),('pretop11_30',11,30)]
    for fam,rmin,rmax in fams:
      for chg_min,chg_max in [(0.5,2),(1,3),(2,5),(3,8),(5,15)]:
       for vol in [0,0.5,0.8,1.2,2.0]:
        for stop in [0.5,0.8,1.0,1.2]:
         for tr_start,give in [(0.8,0.4),(1.0,0.5),(1.5,0.7),(2.0,1.0)]:
          for hold in [6,12,18,36]:
           for cap in [3,5,8,999]:
            yield P(fam,rmin,rmax,chg_min,chg_max,vol,stop,tr_start,give,hold,max_daily_entries=cap)

def main():
    snaps,candles=load()
    events_by={}
    for fam,rmin,rmax in [('top10',1,10),('top5',1,5),('top20',1,20),('rank6_20',6,20),('pretop11_20',11,20),('pretop11_30',11,30)]:
        events_by[fam]=make_events(snaps,fam,rmin,rmax)
    results=[]; trade_examples={}
    for p in grid():
        raw=[]
        for e in events_by[p.family]:
            t=trade_for_event(e,p,candles)
            if t: raw.append(t)
        guarded=apply_guards(raw,p)
        if len(guarded) < 25: continue
        s=summarize(p,guarded)
        if not s: continue
        # stable-ish filters: not only headline avg
        results.append(s)
        trade_examples[p.name]=guarded[:10]
    results.sort(key=lambda s:(s['avg_day']>=1.0, s['day_win_rate'], s['avg_day'], s['pf'], s['trades']), reverse=True)
    out={'db':str(DB),'snapshot_count':len(snaps),'first_snapshot':snaps[0]['ts'] if snaps else None,'last_snapshot':snaps[-1]['ts'] if snaps else None,
         'cost_pct':COST_PCT,'events':{k:len(v) for k,v in events_by.items()},'result_count':len(results),'top':results[:100]}
    OUT.write_text(json.dumps(out,indent=2),encoding='utf-8')
    print(json.dumps({**out,'top':results[:20]},indent=2))
if __name__=='__main__': main()
