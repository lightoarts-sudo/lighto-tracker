import json
from datetime import datetime, timezone, timedelta
import okx_micro_report_job as job
import strategy_lab_12h_runner as lab
TZ=timezone(timedelta(hours=8))

def main():
    con,data,since,max_ts=job.load_data(); enriched,stats=job.summarize(data)
    watch=[s['inst'] for s in sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret12'],x['max_vol_ratio']), reverse=True)[:25]]
    grids={
      'strategy7_vwap_reclaim_stability':{'prior_1h':[0.9,1.3],'min_1h':[0.25,0.5],'max_15m':[0.9,1.3],'pullback_buffer':[0.15,0.35],'vol_min':[0.7,0.9],'vol_max':[2.5,4.0],'vwap_lookback':[24],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.4,1.8],'be':[0.12,0.2],'trail_start':[1.0,1.4],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]},
      'strategy8_breakout_retest_only':{'break_vol':[1.2,1.6],'confirm_vol':[0.7,1.0],'min_1h':[0.35,0.7],'max_15m':[1.0,1.5],'retest_tolerance':[0.1,0.25],'hold_margin':[0.0,0.1],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.5,2.0],'be':[0.12,0.2],'trail_start':[1.1,1.5],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]},
      'strategy9_ema9_bounce_low_heat':{'min_1h':[0.4,0.7],'max_1h':[1.8,2.5],'max_15m':[0.7,1.0],'touch_buffer':[0.1,0.25],'ema21_slack':[0.1,0.25],'vol_min':[0.8,1.0],'vol_max':[2.5,4.0],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.4,1.8],'be':[0.12,0.2],'trail_start':[1.0,1.4],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]}
    }
    best=lab.scan(enriched, watch, grids)
    out=[]
    for sid,(m,p,tr,op) in best:
        qual, reason=lab.is_qualified(m)
        out.append({
            'strategy':sid,
            'qualified':qual,
            'reason':reason,
            'params':p,
            'metrics':m,
            'open_trades':op[:10],
            'closed_trade_examples':tr[:10]
        })
    result={
        'window_start':datetime.fromtimestamp(since/1000,TZ).isoformat(timespec='minutes'),
        'window_end':datetime.fromtimestamp(max_ts/1000,TZ).isoformat(timespec='minutes'),
        'coins':len(enriched),
        'watch_size':len(watch),
        'watch':[w.replace('-USDT','') for w in watch],
        'results':out
    }
    print(json.dumps(result,ensure_ascii=False,indent=2))
    con.close()
if __name__=='__main__': main()
