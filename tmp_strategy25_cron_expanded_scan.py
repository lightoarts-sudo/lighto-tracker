#!/usr/bin/env python3
from __future__ import annotations
import json
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import tmp_strategy20_24_scan as base
import strategy_lab_12h_runner as lab

TZ=timezone(timedelta(hours=8))
OUT='data/okx_micro_strategy25_cron_expanded_scan.json'

EXITS=[
 {'sl':0.45,'tp1':1.2,'frac':0.25,'tp2':4.5,'be':0.25,'trail_start':2.2,'give':0.7,'soft':8,'hard':24,'minprog':0.2},
 {'sl':0.50,'tp1':1.2,'frac':0.30,'tp2':3.6,'be':0.25,'trail_start':2.0,'give':0.6,'soft':8,'hard':18,'minprog':0.2},
 {'sl':0.55,'tp1':1.4,'frac':0.25,'tp2':5.0,'be':0.25,'trail_start':2.4,'give':0.8,'soft':10,'hard':24,'minprog':0.25},
 {'sl':0.60,'tp1':1.4,'frac':0.30,'tp2':4.0,'be':0.25,'trail_start':2.4,'give':0.8,'soft':8,'hard':20,'minprog':0.2},
 {'sl':0.70,'tp1':1.6,'frac':0.25,'tp2':5.0,'be':0.25,'trail_start':2.8,'give':0.9,'soft':10,'hard':24,'minprog':0.25},
 {'sl':0.60,'tp1':1.0,'frac':0.40,'tp2':3.2,'be':0.20,'trail_start':1.8,'give':0.5,'soft':6,'hard':16,'minprog':0.2},
]

# Expanded point-in-time universes: lower TopN should cut frequency and reduce weak tail.
UNIVERSES=[
 ('top','top1h',10),('top','top1h',15),('top','top1h',20),
 ('top','top2h',10),('top','top2h',15),('top','top2h',20),
 ('top','top3h',10),('top','top3h',15),('top','top3h',20),
 ('top','top6h',10),('top','top6h',15),('top','top6h',20),
 ('top','top12h',10),('top','top12h',15),('top','top12h',20),
 ('inter',['top1h','top3h'],20),('inter',['top1h','top3h','top6h'],20),
 ('inter',['top2h','top6h','top12h'],20),('inter',['top1h','top3h','top6h','top12h'],20),
]

def strategy_compatible(name, spec):
    key=json.dumps(spec, ensure_ascii=False)
    if name=='strategy20_6h12h_cool_vwap_reclaim':
        return 'top12h' in key or 'top6h' in key or 'top2h' in key or 'inter' in key
    if name=='strategy21_multi_tf_intersection_ema9_bounce':
        return 'inter' in key or 'top3h' in key or 'top6h' in key
    if name=='strategy22_2h_strength_breakout_retest':
        return 'top2h' in key or 'top3h' in key or 'inter' in key
    if name=='strategy23_top1h_clean_early_breakout':
        return 'top1h' in key or 'top2h' in key
    if name=='strategy24_prior_surge_vwap_second_push':
        return 'top3h' in key or 'top6h' in key or 'inter' in key
    return True

def scan_window(enriched,start,end,min_trades):
    ranks=base.build_rankings(enriched,start,end)
    allow_cache={}
    rows=[]
    for name,(_,eplist) in base.ENTRY_GRIDS.items():
        best=None
        for spec in UNIVERSES:
            if not strategy_compatible(name,spec):
                continue
            skey=json.dumps(spec,ensure_ascii=False)
            allow=allow_cache.get(skey)
            if allow is None:
                allow=base.make_allow(ranks,spec); allow_cache[skey]=allow
            for ep in eplist:
                for xp in EXITS:
                    tr,op=base.sim(enriched,allow,name,ep,xp,start,end)
                    m=lab.metrics(tr,op)
                    n=m['closed_trades'] or 0
                    if n<min_trades: continue
                    if m['max_loss_pct'] is not None and m['max_loss_pct'] < -0.9: continue
                    score=(m['net_expectancy_after_fee_slip_pct'] or -999, m['avg_return_pct'] or -999, m['profit_factor'] or 0, n, -(abs(m['max_loss_pct'] or 99)))
                    rec={'strategy':name,'universe_spec':spec,'entry_params':ep,'exit_params':xp,'metrics':m,'sample_trades':tr[:8]}
                    if best is None or score>best[0]: best=(score,rec)
        if best: rows.append(best[1])
    rows.sort(key=lambda r:(r['metrics']['net_expectancy_after_fee_slip_pct'] or -999,r['metrics']['avg_return_pct'] or -999,r['metrics']['profit_factor'] or 0,r['metrics']['closed_trades'] or 0), reverse=True)
    return rows

def replay(enriched,c,start,end):
    ranks=base.build_rankings(enriched,start,end)
    allow=base.make_allow(ranks,c['universe_spec'])
    tr,op=base.sim(enriched,allow,c['strategy'],c['entry_params'],c['exit_params'],start,end)
    return lab.metrics(tr,op)

def main():
    enriched,mn,mx=base.load(); start=mx-12*3600*1000
    latest8=scan_window(enriched,start,mx,8)
    latest5=scan_window(enriched,start,mx,5)
    candidates=[]
    seen=set()
    for c in latest8+latest5:
        key=(c['strategy'],json.dumps(c['universe_spec'],sort_keys=True),json.dumps(c['entry_params'],sort_keys=True),json.dumps(c['exit_params'],sort_keys=True))
        if key not in seen:
            candidates.append(c); seen.add(key)
        if len(candidates)>=8: break
    rolling=[]
    for w in range(1,5):
        end=mx-w*12*3600*1000; st=end-12*3600*1000
        if st<mn: continue
        for c in candidates[:5]:
            rolling.append({'window':[datetime.fromtimestamp(st/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(end/1000,TZ).isoformat(timespec='minutes')],'strategy':c['strategy'],'universe_spec':c['universe_spec'],'metrics':replay(enriched,c,st,end)})
    out={'generated_at':datetime.now(TZ).isoformat(timespec='seconds'),'data_window':{'start':datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),'end':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),'inst_count':len(enriched)},'top_min8':latest8[:10],'top_min5':latest5[:10],'rolling_prior_12h':rolling}
    open(OUT,'w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({'data_window':out['data_window'],'top_min8':latest8[:6],'top_min5':latest5[:6],'rolling_prior_12h':rolling[:12]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
