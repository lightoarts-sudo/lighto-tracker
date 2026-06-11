import sqlite3,itertools,json,math
from datetime import datetime,timezone,timedelta
from collections import Counter
import okx_micro_report_job as job
import strategy_lab_12h_runner as lab
TZ=timezone(timedelta(hours=8)); DB='data/okx_micro_5m_tracking.sqlite'
def pct(a,b): return (a/b-1)*100 if b else 0.0
def ret(rows,i,b): return pct(rows[i]['close'],rows[i-b]['close']) if i-b>=0 else 0.0
def load():
    # ensure fallback top-up if stale
    con0,data12,since,max_ts=job.load_data(); con0.close()
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    mn,mx=con.execute('select min(ts_ms),max(ts_ms) from candles_5m').fetchone()
    data={}
    for inst, in con.execute('select distinct inst_id from candles_5m'):
        base=inst.split('-')[0]
        if base in job.EXCLUDE or base in job.STABLE_OR_FIAT: continue
        rs=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? order by ts_ms',(inst,)).fetchall()
        if len(rs)>=180: data[inst]=[dict(r) for r in rs]
    con.close()
    return {k:job.indicators(v) for k,v in data.items()},mn,mx
def vwap(rows,i,look=24):
    s=pv=0.0
    for r in rows[max(0,i-look+1):i+1]:
        vol=(r.get('vol_ccy') or r.get('vol',0)*r['close']); s+=vol; pv+=r['close']*vol
    return pv/s if s else rows[i]['close']
def build_allow(enriched,start,end,bars,topn):
    rowmap={inst:{r['ts_ms']:i for i,r in enumerate(rows)} for inst,rows in enriched.items()}
    times=sorted(t for t in set(x for m in rowmap.values() for x in m) if start<=t<=end)
    out={}
    for ts in times:
        arr=[]
        for inst,mp in rowmap.items():
            i=mp.get(ts)
            if i is not None and i>=bars:
                arr.append((ret(enriched[inst],i,bars),inst))
        out[ts]=set(inst for _,inst in sorted(arr,reverse=True)[:topn])
    return out
def ok_entry(name,rows,i,p):
    r=rows[i]; prev=rows[i-1]; prev2=rows[i-2]
    r1=ret(rows,i,12); r2=ret(rows,i,24); r3=ret(rows,i,36); r6=ret(rows,i,72); r12=ret(rows,i,144); r15=ret(rows,i,3)
    rng=r['high']-r['low']; upper=(r['high']-r['close'])/rng if rng>0 else 0
    if name=='s16_top1h_clean_breakout':
        return r['close']>r['high12_prev'] and r['close']>r['open'] and r['close']>r['ema9']>=r['ema21'] and p['min1']<=r1<=p['max1'] and r3>=p['min3'] and r15<=p['max15'] and p['vmin']<=r['vol_ratio']<=p['vmax'] and upper<=p['upper'] and pct(r['close'],r['high12_prev'])<=p['stretch']
    if name=='s17_top3h_vwap_reclaim_runner':
        vw=vwap(rows,i); pv=vwap(rows,i-1)
        return r3>=p['min3'] and r6>=p['min6'] and r1<=p['max1'] and r15<=p['max15'] and prev['low']<=max(prev['ema9'],pv)*(1+p['buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and p['vmin']<=r['vol_ratio']<=p['vmax']
    if name=='s18_top2h_retest_runner':
        old=prev2['high12_prev']; pb=prev['close']>old and prev['vol_ratio']>=p['bvol'] and prev['close']>prev['ema9']>=prev['ema21']
        return pb and r2>=p['min2'] and r1<=p['max1'] and r15<=p['max15'] and r['low']<=old*(1+p['tol']/100) and r['close']>=old and r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=p['cvol']
    if name=='strategy9_ema9_bounce_low_heat':
        return prev['low']<=prev['ema9']*(1+p['touch_buffer']/100) and prev['close']>=prev['ema21']*(1-p['ema21_slack']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['ema9']>=r['ema21'] and p['min_1h']<=r1<=p['max_1h'] and r15<=p['max_15m'] and p['vol_min']<=r['vol_ratio']<=p['vol_max']
    if name=='s19_top12h_cool_vwap_bounce':
        vw=vwap(rows,i); pv=vwap(rows,i-1)
        return r12>=p['min12'] and r6>=p['min6'] and r1<=p['max1'] and r15<=p['max15'] and prev['low']<=max(prev['ema21'],pv)*(1+p['buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and r['ema9']>=r['ema21'] and p['vmin']<=r['vol_ratio']<=p['vmax']
    return False
def sim(enriched,allow,name,ep,xp,start,end):
    tr=[]; op=[]
    for inst,rows in enriched.items():
        inpos=False; entry=peak=stop=0; ei=0; real=0; rem=1; tp1=False
        for i in range(145,len(rows)):
            r=rows[i]; ts=r['ts_ms']
            if ts<start: continue
            if ts>end: break
            if not inpos:
                if inst in allow.get(ts,set()) and ok_entry(name,rows,i,ep):
                    inpos=True; entry=r['close']; peak=entry; ei=i; real=0; rem=1; tp1=False; stop=entry*(1-xp['sl']/100)
            else:
                peak=max(peak,r['high']); pnl=pct(r['close'],entry); pg=pct(peak,entry); held=i-ei; out=reason=None
                if r['low']<=stop: out=real+rem*pct(stop,entry); reason='SL'
                elif tp1 and r['low']<=entry*(1+xp['be']/100): out=real+rem*xp['be']; reason='BE_AFTER_TP1'
                elif tp1 and pg>=xp['trail_start'] and (pg-pnl)>=xp['give']: out=real+rem*pnl; reason='TRAIL'
                elif (not tp1) and r['high']>=entry*(1+xp['tp1']/100): tp1=True; real+=xp['frac']*xp['tp1']; rem=1-xp['frac']; stop=max(stop,entry*(1+xp['be']/100)); continue
                elif r['high']>=entry*(1+xp['tp2']/100): out=real+rem*xp['tp2']; reason='TP2'
                elif held>=xp['soft']:
                    if pnl>=xp['minprog'] and r['close']>=r['ema9'] and held<xp['hard']: continue
                    out=real+rem*pnl; reason='TIME_STOP'
                elif r['close']<r['ema21']: out=real+rem*pnl; reason='EMA21_EXIT'
                if reason: tr.append({'inst':inst,'pnl_pct':round(out,4),'reason':reason}); inpos=False
        if inpos: op.append({'inst':inst})
    return tr,op
def scan_window(enriched,start,end):
    allows={
      'top1h20':build_allow(enriched,start,end,12,20),'top2h20':build_allow(enriched,start,end,24,20),'top3h20':build_allow(enriched,start,end,36,20),'top12h20':build_allow(enriched,start,end,144,20),
      'top1h10':build_allow(enriched,start,end,12,10),'top3h10':build_allow(enriched,start,end,36,10)}
    exits=[
      {'sl':0.6,'tp1':1.4,'frac':0.3,'tp2':4.0,'be':0.25,'trail_start':2.4,'give':0.8,'soft':8,'hard':16,'minprog':0.2},
      {'sl':0.5,'tp1':1.2,'frac':0.3,'tp2':4.0,'be':0.25,'trail_start':2.0,'give':0.8,'soft':8,'hard':16,'minprog':0.2},
      {'sl':0.6,'tp1':1.0,'frac':0.5,'tp2':2.8,'be':0.2,'trail_start':1.8,'give':0.5,'soft':6,'hard':12,'minprog':0.2},
      {'sl':0.8,'tp1':0.8,'frac':0.5,'tp2':1.8,'be':0.2,'trail_start':1.4,'give':0.4,'soft':6,'hard':6,'minprog':0.0},
    ]
    entries={
      's16_top1h_clean_breakout':('top1h20',[{'min1':a,'max1':b,'min3':c,'max15':d,'vmin':e,'vmax':4.5,'upper':u,'stretch':s} for a in [1.1,1.4,1.7] for b in [2.4,2.8,3.4] for c in [0.5,1.0] for d in [1.0,1.2,1.5] for e in [1.2,1.6] for u in [0.25,0.35] for s in [0.7,1.0]]),
      's17_top3h_vwap_reclaim_runner':('top3h20',[{'min3':a,'min6':b,'max1':c,'max15':d,'buf':buf,'vmin':0.5,'vmax':3.5} for a in [1.5,2.0,3.0] for b in [0.5,1.0,2.0] for c in [1.6,2.0,2.4] for d in [0.8,1.0,1.2] for buf in [0.25,0.4]]),
      's18_top2h_retest_runner':('top2h20',[{'min2':a,'max1':b,'max15':c,'bvol':bv,'cvol':0.6,'tol':tol} for a in [1.4,2.0,2.6] for b in [2.4,3.0] for c in [1.2,1.5] for bv in [1.1,1.3] for tol in [0.3,0.45]]),
      'strategy9_ema9_bounce_low_heat':('top1h20',[{'min_1h':a,'max_1h':b,'max_15m':c,'touch_buffer':tb,'ema21_slack':0.1,'vol_min':vm,'vol_max':4.0} for a in [0.5,0.7,0.9] for b in [2.0,2.5,3.0] for c in [0.7,1.0] for tb in [0.1,0.25] for vm in [0.8,1.0]]),
      's19_top12h_cool_vwap_bounce':('top12h20',[{'min12':a,'min6':b,'max1':c,'max15':d,'buf':buf,'vmin':0.5,'vmax':3.5} for a in [2.0,4.0,6.0] for b in [1.0,2.0,3.0] for c in [1.6,2.2,3.0] for d in [0.8,1.2] for buf in [0.25,0.45]]),
    }
    rows=[]
    for name,(allowname,eplist) in entries.items():
        best=None
        for ep in eplist:
            for xp in exits:
                tr,op=sim(enriched,allows[allowname],name,ep,xp,start,end); m=lab.metrics(tr,op); n=m['closed_trades'] or 0
                if n<8: continue
                score=(m['avg_return_pct'] or -999, m['profit_factor'] or 0, -abs(m['max_loss_pct'] or -99), n)
                if best is None or score>best[0]: best=(score,allowname,ep,xp,m)
        if best: rows.append({'strategy':name,'universe':best[1],'entry_params':best[2],'exit_params':best[3],'metrics':best[4]})
    rows.sort(key=lambda r:(r['metrics']['avg_return_pct'] or -999,r['metrics']['profit_factor'] or 0,r['metrics']['closed_trades']),reverse=True)
    return rows
if __name__=='__main__':
    enriched,mn,mx=load(); latest_start=mx-12*3600*1000
    latest=scan_window(enriched,latest_start,mx)
    # Evaluate latest winners on previous three 12h windows with same params/universe for robustness
    candidates=latest[:5]
    roll=[]
    for w in range(1,4):
        end=mx-w*12*3600*1000; start=end-12*3600*1000
        if start<mn: continue
        allows_cache={}
        for c in candidates:
            uni=c['universe']; bars={'top1h20':12,'top2h20':24,'top3h20':36,'top12h20':144}.get(uni,12)
            if uni not in allows_cache: allows_cache[uni]=build_allow(enriched,start,end,bars,20)
            tr,op=sim(enriched,allows_cache[uni],c['strategy'],c['entry_params'],c['exit_params'],start,end)
            roll.append({'window':[datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(end/1000,TZ).isoformat(timespec='minutes')],'strategy':c['strategy'],'metrics':lab.metrics(tr,op)})
    res={'generated_at':datetime.now(TZ).isoformat(timespec='seconds'),'data_window':{'start':datetime.fromtimestamp(latest_start/1000,TZ).isoformat(timespec='minutes'),'end':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),'inst_count':len(enriched)},'top':latest[:10],'rolling_prior_12h':roll}
    open('data/okx_micro_cron_targeted_scan.json','w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=2))
    print(json.dumps({'data_window':res['data_window'],'top':latest[:5],'rolling_prior_12h':roll[:15]},ensure_ascii=False,indent=2))
