#!/usr/bin/env python3
from __future__ import annotations
import json, sqlite3, itertools, os
from datetime import datetime, timezone, timedelta
from collections import Counter
import okx_micro_report_job as job
import strategy_lab_12h_runner as lab
import tmp_pit_strategy_scan as pit
import tmp_strategy20_24_scan as s20

TZ=timezone(timedelta(hours=8))
DB='data/okx_micro_5m_tracking.sqlite'
OUT='data/okx_micro_cron_quick_pit_review.json'

def db_status():
    con=sqlite3.connect(DB); cur=con.cursor()
    mn,mx,insts,rows=cur.execute('select min(ts_ms),max(ts_ms),count(distinct inst_id),count(*) from candles_5m').fetchone()
    since=mx-12*3600*1000
    inst12,rows12=cur.execute('select count(distinct inst_id),count(*) from candles_5m where ts_ms>=?',(since,)).fetchone()
    counts=[r[0] for r in cur.execute('select count(*) from candles_5m where ts_ms>=? group by inst_id',(since,)).fetchall()]
    ge100=sum(1 for c in counts if c>=100)
    con.close()
    return {
      'db_min':datetime.fromtimestamp(mn/1000,TZ).isoformat(timespec='minutes'),
      'db_max':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),
      'db_inst_count':insts,'db_rows':rows,
      'latest_12h_start':datetime.fromtimestamp(since/1000,TZ).isoformat(timespec='minutes'),
      'latest_12h_end':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),
      'latest_12h_inst_count':inst12,'latest_12h_rows':rows12,
      'latest_12h_inst_ge100_bars':ge100,
      'latest_12h_bar_count_min':min(counts) if counts else 0,
      'latest_12h_bar_count_max':max(counts) if counts else 0,
    }

def eval_789():
    enriched,max_ts,since12=pit.load_24h(); ranks,rowmap=pit.build_ranks(enriched)
    unis=['top12','top24','top36','top72','top144','inter_1h3h6h12h','inter_2h6h12h','top2h_and_12h']
    # Very bounded PIT check for cron: evaluate strategy7/8/9 with a small set of stable parameter candidates.
    params_by_strategy={
      'strategy7_vwap_reclaim_stability':[
        {'prior_1h':0.8,'min_1h':0.2,'max_15m':0.8,'pullback_buffer':0.35,'vol_min':0.6,'vol_max':2.5,'vwap_lookback':24,'sl':0.7,'tp1':1.0,'tp2':2.4,'be':0.2,'trail_start':1.5,'trail_giveback':0.7,'time_stop_bars':6,'struct_stop':True},
        {'prior_1h':1.2,'min_1h':0.45,'max_15m':1.2,'pullback_buffer':0.15,'vol_min':0.8,'vol_max':2.5,'vwap_lookback':24,'sl':0.85,'tp1':0.8,'tp2':1.8,'be':0.12,'trail_start':1.1,'trail_giveback':0.4,'time_stop_bars':4,'struct_stop':True},
      ],
      'strategy8_breakout_retest_only':[
        {'break_vol':1.1,'confirm_vol':0.6,'min_1h':0.25,'max_15m':1.3,'retest_tolerance':0.3,'hold_margin':0.0,'sl':0.7,'tp1':1.0,'tp2':2.4,'be':0.2,'trail_start':1.5,'trail_giveback':0.7,'time_stop_bars':6,'struct_stop':True},
        {'break_vol':1.4,'confirm_vol':0.9,'min_1h':0.5,'max_15m':0.9,'retest_tolerance':0.15,'hold_margin':0.0,'sl':0.85,'tp1':0.8,'tp2':1.8,'be':0.12,'trail_start':1.1,'trail_giveback':0.4,'time_stop_bars':4,'struct_stop':True},
      ],
      'strategy9_ema9_bounce_low_heat':[
        {'min_1h':0.55,'max_1h':2.2,'max_15m':0.9,'touch_buffer':0.25,'ema21_slack':0.1,'vol_min':0.7,'vol_max':2.5,'sl':0.7,'tp1':1.0,'tp2':2.4,'be':0.2,'trail_start':1.5,'trail_giveback':0.7,'time_stop_bars':6,'struct_stop':True},
        {'min_1h':0.7,'max_1h':1.8,'max_15m':0.7,'touch_buffer':0.25,'ema21_slack':0.1,'vol_min':1.0,'vol_max':2.5,'sl':0.8,'tp1':0.8,'tp2':1.8,'be':0.12,'trail_start':1.0,'trail_giveback':0.4,'time_stop_bars':6,'struct_stop':True},
      ],
    }
    out=[]
    for strat,plist in params_by_strategy.items():
        best=None
        for p in plist:
            for uni in unis:
                tr,op=pit.simulate_pit(enriched,ranks,rowmap,strat,p,uni,since12)
                m=lab.metrics(tr,op)
                if (m['closed_trades'] or 0)<3: continue
                score=((m['closed_trades'] or 0)>=8,
                       m['net_expectancy_after_fee_slip_pct'] if m['net_expectancy_after_fee_slip_pct'] is not None else -999,
                       m['profit_factor'] or 0,
                       -(abs(m['max_loss_pct'] if m['max_loss_pct'] is not None else 99)),
                       m['closed_trades'] or 0)
                rec={'strategy':strat,'universe':uni,'params':p,'metrics':m,'sample_trades':tr[:5]}
                if best is None or score>best[0]: best=(score,rec)
        if best: out.append(best[1])
    return {'data_window':{'start':datetime.fromtimestamp(since12/1000,TZ).isoformat(timespec='minutes'),'end':datetime.fromtimestamp(max_ts/1000,TZ).isoformat(timespec='minutes'),'inst_count':len(enriched)},'results':out}

def latest_20_24():
    enriched,mn,mx=s20.load(); start=mx-12*3600*1000
    latest=s20.scan_window(enriched,start,mx,8)
    return {'data_window':{'start':datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),'end':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),'inst_count':len(enriched)},'top':latest[:5]}

def main():
    status=db_status()
    r789=eval_789()
    r20=latest_20_24()
    combined=[]
    combined.extend(r789['results'])
    combined.extend(r20['top'])
    combined.sort(key=lambda r: ((r['metrics']['closed_trades'] or 0)>=8,
                                 r['metrics']['net_expectancy_after_fee_slip_pct'] if r['metrics']['net_expectancy_after_fee_slip_pct'] is not None else -999,
                                 r['metrics']['profit_factor'] or 0,
                                 -(abs(r['metrics']['max_loss_pct'] if r['metrics']['max_loss_pct'] is not None else 99))), reverse=True)
    out={'generated_at':datetime.now(TZ).isoformat(timespec='seconds'),'db_status':status,'pit_789':r789,'strategy20_24':r20,'combined_top':combined[:10]}
    os.makedirs('data',exist_ok=True)
    open(OUT,'w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({'db_status':status,'pit_789':r789,'combined_top':combined[:8]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
