import sqlite3,itertools,json
from datetime import datetime,timezone,timedelta
from collections import Counter
import okx_micro_report_job as job
import strategy_lab_12h_runner as lab
TZ=timezone(timedelta(hours=8)); DB='data/okx_micro_5m_tracking.sqlite'

def pct(a,b): return (a/b-1)*100 if b else 0.0

def ret(rows,i,b): return pct(rows[i]['close'],rows[i-b]['close']) if i-b>=0 else 0.0

def load():
    # use report loader once to top-up, then load longer history for PIT replay
    con0,data12,since,max_ts=job.load_data(); con0.close()
    con=sqlite3.connect(DB); con.row_factory=sqlite3.Row
    mn,mx=con.execute('select min(ts_ms),max(ts_ms) from candles_5m').fetchone(); data={}
    for inst, in con.execute('select distinct inst_id from candles_5m'):
        base=inst.split('-')[0]
        if base in job.EXCLUDE or base in job.STABLE_OR_FIAT: continue
        rs=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? order by ts_ms',(inst,)).fetchall()
        if len(rs)>=180: data[inst]=[dict(r) for r in rs]
    con.close(); return {k:job.indicators(v) for k,v in data.items()},mn,mx

def vwap(rows,i,look=24):
    s=pv=0.0
    for r in rows[max(0,i-look+1):i+1]:
        vol=(r.get('vol_ccy') or r.get('vol',0)*r['close']); s+=vol; pv+=r['close']*vol
    return pv/s if s else rows[i]['close']

def build_rankings(enriched,start,end):
    bars_map={'top1h':12,'top2h':24,'top3h':36,'top6h':72,'top12h':144}
    rowmap={inst:{r['ts_ms']:i for i,r in enumerate(rows)} for inst,rows in enriched.items()}
    times=sorted(t for t in set(x for m in rowmap.values() for x in m) if start<=t<=end)
    ranks={name:{} for name in bars_map}
    for ts in times:
        for name,bars in bars_map.items():
            arr=[]
            for inst,mp in rowmap.items():
                i=mp.get(ts)
                if i is not None and i>=bars:
                    arr.append((ret(enriched[inst],i,bars),inst))
            ordered=[inst for _,inst in sorted(arr,reverse=True)]
            ranks[name][ts]=ordered
    return ranks

def make_allow(ranks, spec):
    # spec examples: ('top3h',20), ('inter',['top1h','top3h','top6h'],20), ('union',[...],20)
    out={}; times=sorted(next(iter(ranks.values())).keys())
    typ=spec[0]
    for ts in times:
        if typ=='top': out[ts]=set(ranks[spec[1]].get(ts,[])[:spec[2]])
        elif typ=='inter':
            sets=[set(ranks[h].get(ts,[])[:spec[2]]) for h in spec[1]]
            out[ts]=set.intersection(*sets) if sets else set()
        elif typ=='union':
            s=set()
            for h in spec[1]: s.update(ranks[h].get(ts,[])[:spec[2]])
            out[ts]=s
    return out

def ok_entry(name,rows,i,p):
    r=rows[i]; prev=rows[i-1]; prev2=rows[i-2]
    r1=ret(rows,i,12); r2=ret(rows,i,24); r3=ret(rows,i,36); r6=ret(rows,i,72); r12=ret(rows,i,144); r15=ret(rows,i,3)
    rng=r['high']-r['low']; upper=(r['high']-r['close'])/rng if rng>0 else 0
    body=(r['close']/r['open']-1)*100 if r['open'] else 0
    if name=='strategy20_6h12h_cool_vwap_reclaim':
        vw=vwap(rows,i); pv=vwap(rows,i-1)
        return (r12>=p['min12'] and r6>=p['min6'] and r3>=p['min3'] and p['min1']<=r1<=p['max1'] and r15<=p['max15'] and
                prev['low']<=max(prev['ema21'],pv)*(1+p['buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and
                r['ema9']>=r['ema21'] and p['vmin']<=r['vol_ratio']<=p['vmax'] and upper<=p['upper'])
    if name=='strategy21_multi_tf_intersection_ema9_bounce':
        return (r12>=p['min12'] and r6>=p['min6'] and r3>=p['min3'] and r1<=p['max1'] and r15<=p['max15'] and
                prev['low']<=prev['ema9']*(1+p['touch']/100) and prev['close']>=prev['ema21']*(1-p['slack']/100) and
                r['close']>r['open'] and body>=p['body'] and r['close']>r['ema9'] and r['ema9']>=r['ema21'] and p['vmin']<=r['vol_ratio']<=p['vmax'])
    if name=='strategy22_2h_strength_breakout_retest':
        old=prev2['high12_prev']; prev_break=prev['close']>old and prev['vol_ratio']>=p['bvol'] and prev['close']>prev['ema9']>=prev['ema21']
        return (prev_break and r2>=p['min2'] and r3>=p['min3'] and r1<=p['max1'] and r15<=p['max15'] and
                r['low']<=old*(1+p['tol']/100) and r['close']>=old*(1+p['hold']/100) and r['close']>r['open'] and r['close']>r['ema9'] and
                r['vol_ratio']>=p['cvol'] and upper<=p['upper'])
    if name=='strategy23_top1h_clean_early_breakout':
        stretch=pct(r['close'],r['high12_prev'])
        return (r['close']>r['high12_prev'] and r['close']>r['open'] and body>=p['body'] and r['close']>r['ema9']>=r['ema21'] and
                p['min1']<=r1<=p['max1'] and r3>=p['min3'] and r15<=p['max15'] and p['vmin']<=r['vol_ratio']<=p['vmax'] and upper<=p['upper'] and 0<=stretch<=p['stretch'])
    if name=='strategy24_prior_surge_vwap_second_push':
        vw=vwap(rows,i); pv=vwap(rows,i-1)
        prior_start=max(145,i-18)
        if prior_start>=i:
            return False
        prior1=max(ret(rows,j,12) for j in range(prior_start,i))
        prior3=max(ret(rows,j,36) for j in range(prior_start,i))
        return (prior1>=p['prior1'] and prior3>=p['prior3'] and r1<=p['max1'] and r15<=p['max15'] and r3>=p['min3'] and
                prev['low']<=max(prev['ema9'],pv)*(1+p['buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and
                p['vmin']<=r['vol_ratio']<=p['vmax'] and upper<=p['upper'])
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
                elif (not tp1) and r['high']>=entry*(1+xp['tp1']/100):
                    tp1=True; real+=xp['frac']*xp['tp1']; rem=1-xp['frac']; stop=max(stop,entry*(1+xp['be']/100)); continue
                elif r['high']>=entry*(1+xp['tp2']/100): out=real+rem*xp['tp2']; reason='TP2'
                elif held>=xp['soft']:
                    if pnl>=xp['minprog'] and r['close']>=r['ema9'] and held<xp['hard']: continue
                    out=real+rem*pnl; reason='TIME_STOP'
                elif r['close']<r['ema21']: out=real+rem*pnl; reason='EMA21_EXIT'
                if reason:
                    tr.append({'inst':inst,'entry_time':rows[ei]['ts_iso'],'exit_time':r['ts_iso'],'pnl_pct':round(out,4),'reason':reason}); inpos=False
        if inpos: op.append({'inst':inst,'entry_time':rows[ei]['ts_iso']})
    return tr,op

ENTRY_GRIDS={
 'strategy20_6h12h_cool_vwap_reclaim':(('top','top12h',20),[{'min12':a,'min6':b,'min3':c,'min1':0.0,'max1':d,'max15':e,'buf':bf,'vmin':0.5,'vmax':3.5,'upper':0.65} for a in [2,6] for b in [1,3] for c in [0.5,1.5] for d in [1.6,3.0] for e in [0.8,1.2] for bf in [0.25,0.45]]),
 'strategy21_multi_tf_intersection_ema9_bounce':(('inter',['top1h','top3h','top6h'],20),[{'min12':a,'min6':b,'min3':c,'max1':d,'max15':e,'touch':t,'slack':0.15,'body':bd,'vmin':0.7,'vmax':3.5} for a in [0,4] for b in [1,2] for c in [1,3] for d in [1.8,3.0] for e in [0.8,1.2] for t in [0.25,0.45] for bd in [0,0.15]]),
 'strategy22_2h_strength_breakout_retest':(('top','top2h',20),[{'min2':a,'min3':b,'max1':c,'max15':d,'bvol':bv,'cvol':0.5,'tol':tol,'hold':0,'upper':0.7} for a in [1.2,2.4] for b in [0,0.8] for c in [2.0,3.2] for d in [1.0,1.4] for bv in [1.0,1.3] for tol in [0.25,0.7]]),
 'strategy23_top1h_clean_early_breakout':(('top','top1h',20),[{'min1':a,'max1':b,'min3':c,'max15':d,'vmin':vm,'vmax':4.5,'upper':u,'stretch':s,'body':0.1} for a in [0.8,1.4] for b in [2.2,3.4] for c in [0,1.0] for d in [0.8,1.4] for vm in [1.2,2.0] for u in [0.25,0.5] for s in [0.5,1.1]]),
 'strategy24_prior_surge_vwap_second_push':(('top','top3h',20),[{'prior1':a,'prior3':b,'min3':c,'max1':d,'max15':e,'buf':bf,'vmin':0.5,'vmax':3.5,'upper':0.65} for a in [1.2,2.4] for b in [1.5,3.5] for c in [0.5,1.0] for d in [1.8,3.0] for e in [0.8,1.2] for bf in [0.25,0.45]])
}
EXITS=[
 {'sl':0.5,'tp1':1.2,'frac':0.3,'tp2':3.6,'be':0.25,'trail_start':2.0,'give':0.6,'soft':8,'hard':18,'minprog':0.2},
 {'sl':0.6,'tp1':1.4,'frac':0.3,'tp2':4.0,'be':0.25,'trail_start':2.4,'give':0.8,'soft':8,'hard':20,'minprog':0.2},
 {'sl':0.7,'tp1':1.6,'frac':0.25,'tp2':5.0,'be':0.25,'trail_start':2.8,'give':0.9,'soft':10,'hard':24,'minprog':0.25},
 {'sl':0.8,'tp1':0.8,'frac':0.5,'tp2':1.8,'be':0.2,'trail_start':1.4,'give':0.4,'soft':6,'hard':6,'minprog':0.0},
 {'sl':0.6,'tp1':1.0,'frac':0.5,'tp2':2.8,'be':0.2,'trail_start':1.8,'give':0.5,'soft':6,'hard':12,'minprog':0.2},
]

def scan_window(enriched,start,end,min_trades=8):
    ranks=build_rankings(enriched,start,end); allow_cache={}; rows=[]
    for name,(spec,eplist) in ENTRY_GRIDS.items():
        key=json.dumps(spec)
        if key not in allow_cache: allow_cache[key]=make_allow(ranks,spec)
        allow=allow_cache[key]
        best=None
        for ep in eplist:
            for xp in EXITS:
                tr,op=sim(enriched,allow,name,ep,xp,start,end); m=lab.metrics(tr,op); n=m['closed_trades'] or 0
                if n<min_trades: continue
                # Rank by net expectancy after fee/slip, then PF and avg return; keep max-loss controlled.
                if (m['max_loss_pct'] is not None) and m['max_loss_pct']<-1.0: continue
                score=(m['net_expectancy_after_fee_slip_pct'] if m['net_expectancy_after_fee_slip_pct'] is not None else -999,
                       m['avg_return_pct'] if m['avg_return_pct'] is not None else -999,
                       m['profit_factor'] or 0,n)
                if best is None or score>best[0]: best=(score,spec,ep,xp,m,tr[:5])
        if best:
            rows.append({'strategy':name,'universe_spec':best[1],'entry_params':best[2],'exit_params':best[3],'metrics':best[4],'sample_trades':best[5]})
    rows.sort(key=lambda r:(r['metrics']['net_expectancy_after_fee_slip_pct'] or -999,r['metrics']['avg_return_pct'] or -999,r['metrics']['profit_factor'] or 0,r['metrics']['closed_trades']),reverse=True)
    return rows

def replay_candidate(enriched,c,start,end):
    ranks=build_rankings(enriched,start,end); allow=make_allow(ranks,c['universe_spec'])
    tr,op=sim(enriched,allow,c['strategy'],c['entry_params'],c['exit_params'],start,end)
    return lab.metrics(tr,op)

if __name__=='__main__':
    enriched,mn,mx=load(); start=mx-12*3600*1000
    latest=scan_window(enriched,start,mx,8)
    candidates=latest[:5]; rolling=[]
    for w in range(1,5):
        end=mx-w*12*3600*1000; st=end-12*3600*1000
        if st<mn: continue
        for c in candidates:
            rolling.append({'window':[datetime.fromtimestamp(st/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(end/1000,TZ).isoformat(timespec='minutes')],'strategy':c['strategy'],'metrics':replay_candidate(enriched,c,st,end)})
    out={'generated_at':datetime.now(TZ).isoformat(timespec='seconds'),'data_window':{'start':datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),'end':datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),'inst_count':len(enriched)},'top':latest[:10],'rolling_prior_12h':rolling}
    open('data/okx_micro_strategy20_24_scan.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
    print(json.dumps({'data_window':out['data_window'],'top':latest[:10],'rolling_prior_12h':rolling},ensure_ascii=False,indent=2))
