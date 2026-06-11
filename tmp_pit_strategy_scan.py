#!/usr/bin/env python3
from __future__ import annotations
import sqlite3,json,itertools,math
from collections import Counter,defaultdict
from datetime import datetime,timezone,timedelta
import okx_micro_report_job as job
from strategy_lab_12h_runner import pct, vwap, metrics, is_qualified

TZ=timezone(timedelta(hours=8))
DB='data/okx_micro_5m_tracking.sqlite'
FEE=0.16

def load_24h():
    # top up via existing loader first
    con0,data12,since12,max_ts=job.load_data(); con0.close()
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    since=max_ts-24*3600*1000
    data={}
    for inst, in con.execute('select distinct inst_id from candles_5m where ts_ms>=?',(since,)):
        base=inst.split('-')[0]
        if base in job.EXCLUDE or base in job.STABLE_OR_FIAT: continue
        rows=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? and ts_ms>=? order by ts_ms',(inst,since)).fetchall()
        if len(rows)>=120:
            data[inst]=[dict(r) for r in rows]
    enriched={k:job.indicators(v) for k,v in data.items()}
    return enriched,max_ts,max_ts-12*3600*1000

def ret(rows,i,bars):
    if i-bars<0: return None
    return pct(rows[i]['close'], rows[i-bars]['close'])

def build_ranks(enriched, horizons=(12,24,36,72,144), topn=20):
    rowmap={inst:{r['ts_ms']:idx for idx,r in enumerate(rows)} for inst,rows in enriched.items()}
    times=sorted(set(ts for rows in enriched.values() for ts in [r['ts_ms'] for r in rows]))
    ranks={h:{} for h in horizons}
    for ts in times:
        for h in horizons:
            arr=[]
            for inst,mp in rowmap.items():
                i=mp.get(ts)
                if i is None or i<h: continue
                rows=enriched[inst]
                arr.append((pct(rows[i]['close'],rows[i-h]['close']),inst))
            ranks[h][ts]=set(inst for _,inst in sorted(arr,reverse=True)[:topn])
    return ranks,rowmap

def in_universe(inst,ts,uni,ranks):
    if uni=='inter_1h3h6h12h':
        return all(inst in ranks[h].get(ts,set()) for h in (12,36,72,144))
    if uni=='inter_2h6h12h':
        return all(inst in ranks[h].get(ts,set()) for h in (24,72,144))
    if uni=='top2h_and_12h':
        return inst in ranks[24].get(ts,set()) and inst in ranks[144].get(ts,set())
    if uni.startswith('top'):
        h=int(uni[3:]); return inst in ranks[h].get(ts,set())
    return True

def entry_signal(strategy, rows, i, p):
    r=rows[i]; prev=rows[i-1]; prev2=rows[i-2]
    r1=ret(rows,i,12) or 0; r2=ret(rows,i,24) or 0; r3=ret(rows,i,36) or 0; r6=ret(rows,i,72) or 0; r12=ret(rows,i,144) or 0; r15=ret(rows,i,3) or 0
    if strategy=='strategy7_vwap_reclaim_stability':
        prior_1h=max((ret(rows,j,12) or -999) for j in range(max(25,i-12),i+1))
        vw=vwap(rows,i,p.get('vwap_lookback',24)); prev_vw=vwap(rows,i-1,p.get('vwap_lookback',24))
        return (r['ema9']>=r['ema21'] and r1>=p['min_1h'] and prior_1h>=p['prior_1h'] and
                prev['low'] <= max(prev['ema21'], prev_vw)*(1+p['pullback_buffer']/100) and
                r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and
                r15 <= p['max_15m'] and p['vol_min'] <= r['vol_ratio'] <= p['vol_max']), 'vwap_reclaim_stability'
    if strategy=='strategy8_breakout_retest_only':
        old_hi=prev2['high12_prev']
        return (prev['close']>old_hi and prev['vol_ratio']>=p['break_vol'] and prev['close']>prev['ema9']>=prev['ema21'] and
                r['low'] <= old_hi*(1+p['retest_tolerance']/100) and r['close']>=old_hi*(1+p['hold_margin']/100) and
                r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=p['confirm_vol'] and r1>=p['min_1h'] and r15<=p['max_15m']), 'breakout_retest_only'
    if strategy=='strategy9_ema9_bounce_low_heat':
        return (prev['low'] <= prev['ema9']*(1+p['touch_buffer']/100) and prev['close']>=prev['ema21']*(1-p['ema21_slack']/100) and
                r['close']>r['open'] and r['close']>r['ema9'] and r['ema9']>=r['ema21'] and
                p['min_1h'] <= r1 <= p['max_1h'] and r15<=p['max_15m'] and p['vol_min']<=r['vol_ratio']<=p['vol_max']), 'ema9_bounce_low_heat'
    if strategy=='strategy10_multi_tf_cool_reclaim':
        # 12H/6H/3H strength but no 15m chase; pullback to VWAP/EMA9 and reclaim.
        vw=vwap(rows,i,p.get('vwap_lookback',24)); prev_vw=vwap(rows,i-1,p.get('vwap_lookback',24))
        cool = r15 <= p['max_15m'] and r1 <= p['max_1h']
        strength = r3>=p['min_3h'] and r6>=p['min_6h'] and r12>=p['min_12h']
        pull = prev['low'] <= max(prev['ema9'],prev_vw)*(1+p['pullback_buffer']/100)
        reclaim = r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and r['ema9']>=r['ema21']
        return strength and cool and pull and reclaim and p['vol_min']<=r['vol_ratio']<=p['vol_max'], 'multi_tf_cool_reclaim'
    if strategy=='strategy11_2h_strength_breakout_retest':
        old_hi=prev2['high12_prev']
        prev_break=prev['close']>old_hi and prev['vol_ratio']>=p['break_vol'] and prev['close']>prev['ema9']>=prev['ema21']
        return (r2>=p['min_2h'] and r1<=p['max_1h'] and r15<=p['max_15m'] and prev_break and
                r['low']<=old_hi*(1+p['retest_tolerance']/100) and r['close']>=old_hi*(1+p['hold_margin']/100) and
                r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=p['confirm_vol']), '2h_strength_breakout_retest'
    if strategy=='strategy12_vwap_squeeze_pop':
        look=p.get('range_lookback',8); window=rows[i-look:i]
        hi=max(x['high'] for x in window); lo=min(x['low'] for x in window)
        avgvr=sum(x['vol_ratio'] for x in window)/look
        vw=vwap(rows,i,24)
        return ((hi/lo-1)*100<=p['range_pct'] and avgvr<=p['compress_vr'] and r['close']>hi and r['close']>vw and r['ema9']>=r['ema21'] and r['vol_ratio']>=p['expand_vr'] and r1>=p['min_1h'] and r15<=p['max_15m']), 'vwap_squeeze_pop'
    return False,''

def simulate_pit(enriched,ranks,rowmap,strategy,p,uni,since12):
    trades=[]; opens=[]
    for inst,rows in enriched.items():
        inpos=False; entry=entry_i=peak=stop=0; tp1=False; rem=1; real=0; meta={}
        for i in range(25,len(rows)):
            r=rows[i]
            if r['ts_ms'] < since12: continue
            if not inpos:
                if not in_universe(inst,r['ts_ms'],uni,ranks): continue
                ok,reason=entry_signal(strategy,rows,i,p)
                if ok:
                    inpos=True; entry=r['close']; entry_i=i; peak=entry; tp1=False; rem=1; real=0; meta={'entry_reason':reason,'universe':uni}
                    stop=entry*(1-p['sl']/100)
                    if p.get('struct_stop',True): stop=max(stop, min(r['ema21'], r['low12_prev'])*0.998)
                    continue
            else:
                peak=max(peak,r['high']); pnl=pct(r['close'],entry); peak_gain=pct(peak,entry)
                xp=xr=None
                if r['low']<=stop:
                    xp=real+rem*pct(stop,entry); xr='SL'
                elif tp1 and r['low']<=entry*(1+p.get('be',0.15)/100):
                    xp=real+rem*p.get('be',0.15); xr='BE_AFTER_TP1'
                elif tp1 and peak_gain>=p['trail_start'] and (peak_gain-pnl)>=p['trail_giveback']:
                    xp=real+rem*pnl; xr='TRAIL'
                elif (not tp1) and r['high']>=entry*(1+p['tp1']/100):
                    tp1=True; real += 0.5*p['tp1']; rem=0.5; stop=max(stop, entry*(1+p.get('be',0.15)/100)); continue
                elif r['high']>=entry*(1+p['tp2']/100):
                    xp=real+rem*p['tp2']; xr='TP2'
                elif i-entry_i>=p['time_stop_bars']:
                    xp=real+rem*pnl; xr='TIME_STOP'
                elif r['close']<r['ema21']:
                    xp=real+rem*pnl; xr='EMA21_EXIT'
                if xr:
                    trades.append({'strategy':strategy,'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'exit_time':r['ts_iso'],'pnl_pct':round(xp,4),'reason':xr,**meta})
                    inpos=False
        if inpos:
            last=rows[-1]
            opens.append({'strategy':strategy,'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'unrealized_pct':round(pct(last['close'],entry),4),**meta})
    return trades,opens

def grid_defs():
    base_exit={'sl':[0.55,0.7,0.85],'tp1':[0.8,1.0],'tp2':[1.8,2.4,3.0],'be':[0.12,0.2],'trail_start':[1.1,1.5,2.0],'trail_giveback':[0.4,0.7],'time_stop_bars':[4,6,8],'struct_stop':[True]}
    return {
      'strategy7_vwap_reclaim_stability':{'prior_1h':[0.8,1.2],'min_1h':[0.2,0.45],'max_15m':[0.8,1.2],'pullback_buffer':[0.15,0.35],'vol_min':[0.6,0.8],'vol_max':[2.5,4.0],'vwap_lookback':[24],**base_exit},
      'strategy8_breakout_retest_only':{'break_vol':[1.1,1.4],'confirm_vol':[0.6,0.9],'min_1h':[0.25,0.5],'max_15m':[0.9,1.3],'retest_tolerance':[0.15,0.3],'hold_margin':[0.0,0.1],**base_exit},
      'strategy9_ema9_bounce_low_heat':{'min_1h':[0.3,0.55],'max_1h':[1.5,2.2],'max_15m':[0.6,0.9],'touch_buffer':[0.1,0.25],'ema21_slack':[0.1,0.25],'vol_min':[0.7,0.9],'vol_max':[2.5,4.0],**base_exit},
      'strategy10_multi_tf_cool_reclaim':{'min_3h':[0.8,1.5],'min_6h':[1.2,2.5],'min_12h':[1.5,3.0],'max_1h':[1.6,2.5],'max_15m':[0.6,1.0],'pullback_buffer':[0.15,0.35],'vol_min':[0.6,0.8],'vol_max':[2.5,4.0],'vwap_lookback':[24],**base_exit},
      'strategy11_2h_strength_breakout_retest':{'min_2h':[0.8,1.4,2.0],'max_1h':[1.8,2.8],'max_15m':[0.8,1.2],'break_vol':[1.1,1.4],'confirm_vol':[0.6,0.9],'retest_tolerance':[0.15,0.3],'hold_margin':[0.0,0.1],**base_exit},
      'strategy12_vwap_squeeze_pop':{'range_lookback':[6,8,10],'range_pct':[0.8,1.2,1.6],'compress_vr':[0.9,1.1],'expand_vr':[1.2,1.6],'min_1h':[0.2,0.5],'max_15m':[0.8,1.2],**base_exit},
    }

def main():
    enriched,max_ts,since12=load_24h(); ranks,rowmap=build_ranks(enriched)
    unis=['top12','top24','top36','top72','top144','inter_1h3h6h12h','inter_2h6h12h','top2h_and_12h']
    grids=grid_defs(); out=[]
    for strat,grid in grids.items():
        keys=list(grid)
        combos=list(itertools.product(*(grid[k] for k in keys)))
        # bounded: sample every combo, grids are small enough ~ few k each
        for uni in unis:
            best=None
            for vals in combos:
                p=dict(zip(keys,vals))
                if p['tp2']<=p['tp1'] or p['trail_start']<p['tp1']: continue
                tr,op=simulate_pit(enriched,ranks,rowmap,strat,p,uni,since12)
                m=metrics(tr,op)
                if m['closed_trades']<5: continue
                score=(m['closed_trades']>=8, m['avg_return_pct'] or -999, m['profit_factor'] or 0, m['closed_trades'], -(abs(m['max_loss_pct'] or -99)))
                rec={'strategy':strat,'universe':uni,'params':p,'metrics':m,'trades':tr[:5]}
                if best is None or score>((best['metrics']['closed_trades']>=8), best['metrics']['avg_return_pct'] or -999, best['metrics']['profit_factor'] or 0, best['metrics']['closed_trades'], -(abs(best['metrics']['max_loss_pct'] or -99))):
                    best=rec
            if best: out.append(best)
    out.sort(key=lambda r: ((r['metrics']['closed_trades']>=8), r['metrics']['avg_return_pct'] or -999, r['metrics']['profit_factor'] or 0, r['metrics']['closed_trades']), reverse=True)
    start=datetime.fromtimestamp(since12/1000,TZ).isoformat(timespec='minutes'); end=datetime.fromtimestamp(max_ts/1000,TZ).isoformat(timespec='minutes')
    result={'generated_at':datetime.now(TZ).isoformat(timespec='seconds'),'data_window':{'start':start,'end':end,'inst_count':len(enriched)},'top':out[:30]}
    with open('data/okx_micro_pit_strategy_scan.json','w',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps({'data_window':result['data_window'],'top':[{k:r[k] for k in ('strategy','universe')}|{'metrics':r['metrics'],'params':r['params']} for r in out[:10]]},ensure_ascii=False,indent=2))
if __name__=='__main__': main()
