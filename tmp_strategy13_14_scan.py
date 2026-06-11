import sqlite3,itertools,json
from datetime import datetime,timezone,timedelta
import okx_micro_report_job as job
import strategy_lab_12h_runner as lab
TZ=timezone(timedelta(hours=8)); DB='data/okx_micro_5m_tracking.sqlite'
def pct(a,b): return (a/b-1)*100 if b else 0.0
def ret(rows,i,b): return pct(rows[i]['close'],rows[i-b]['close']) if i-b>=0 else 0.0
def load():
 con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; mn,mx=con.execute('select min(ts_ms),max(ts_ms) from candles_5m').fetchone(); data={}
 for inst, in con.execute('select distinct inst_id from candles_5m'):
  base=inst.split('-')[0]
  if base in job.EXCLUDE or base in job.STABLE_OR_FIAT: continue
  rs=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? order by ts_ms',(inst,)).fetchall()
  if len(rs)>=180: data[inst]=[dict(r) for r in rs]
 enriched,_=job.summarize(data); return enriched,mn,mx
def allow_top(enriched,start,end,bars=12,topn=20):
 rowmap={inst:{r['ts_ms']:(i,r) for i,r in enumerate(rows)} for inst,rows in enriched.items()}; times=sorted(t for t in set(x for m in rowmap.values() for x in m) if start<=t<=end); out={}
 for ts in times:
  rank=[]
  for inst,m in rowmap.items():
   hit=m.get(ts)
   if hit and hit[0]>=bars: rank.append((pct(hit[1]['close'],enriched[inst][hit[0]-bars]['close']),inst))
  out[ts]=set(inst for _,inst in sorted(rank,reverse=True)[:topn])
 return out
EXIT={'sl':0.7,'tp1':1.4,'tp1_frac':0.35,'tp2':3.2,'be':0.25,'trail_start':1.8,'trail_giveback':0.5,'soft_time':6,'hard_time':16,'min_progress':0.2}
def exit_step(rows,i,entry,entry_i,peak,stop,tp1,rem,real):
 r=rows[i]; peak=max(peak,r['high']); pnl=pct(r['close'],entry); pg=pct(peak,entry); xp=None; xr=None; held=i-entry_i; e=EXIT
 if r['low']<=stop: xp=real+rem*pct(stop,entry); xr='SL'
 elif tp1 and r['low']<=entry*(1+e['be']/100): xp=real+rem*e['be']; xr='BE_AFTER_TP1'
 elif tp1 and pg>=e['trail_start'] and (pg-pnl)>=e['trail_giveback']: xp=real+rem*pnl; xr='TRAIL'
 elif (not tp1) and r['high']>=entry*(1+e['tp1']/100):
  tp1=True; real+=e['tp1_frac']*e['tp1']; rem=1-e['tp1_frac']; stop=max(stop,entry*(1+e['be']/100)); return None,None,peak,stop,tp1,rem,real
 elif r['high']>=entry*(1+e['tp2']/100): xp=real+rem*e['tp2']; xr='TP2'
 elif held>=e['soft_time']:
  progress=pnl>=e['min_progress'] and r['close']>=r['ema9']
  if progress and held<e['hard_time']: return None,None,peak,stop,tp1,rem,real
  xp=real+rem*pnl; xr='TIME_STOP'
 elif r['close']<r['ema21']: xp=real+rem*pnl; xr='EMA21_EXIT'
 return xp,xr,peak,stop,tp1,rem,real
def sim13(enriched,allow,p,start,end):
 tr=[]; op=[]
 for inst,rows in enriched.items():
  inpos=False; entry=0; entry_i=0; peak=0; stop=0; tp1=False; rem=1; real=0
  for i in range(145,len(rows)):
   r=rows[i]; ts=r['ts_ms']
   if ts<start: continue
   if ts>end: break
   if not inpos:
    if inst not in allow.get(ts,set()): continue
    r1=ret(rows,i,12); r2=ret(rows,i,24); r3=ret(rows,i,36); r6=ret(rows,i,72); r15=ret(rows,i,3); rng=r['high']-r['low']; upper=(r['high']-r['close'])/rng if rng>0 else 0
    ok=(r['close']>r['high12_prev'] and r['close']>r['ema9']>=r['ema21'] and p['min1h']<=r1<=p['max1h'] and r2>=p['min2h'] and r3>=p['min3h'] and r6>=p['min6h'] and r15<=p['max15m'] and p['vol_min']<=r['vol_ratio']<=p['vol_max'] and upper<=p['upper_max'] and r['close']>r['open'] and pct(r['close'],r['high12_prev'])<=p['max_stretch'])
    if ok: inpos=True; entry=r['close']; entry_i=i; peak=entry; tp1=False; rem=1; real=0; stop=entry*(1-EXIT['sl']/100)
   else:
    xp,xr,peak,stop,tp1,rem,real=exit_step(rows,i,entry,entry_i,peak,stop,tp1,rem,real)
    if xr: tr.append({'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'pnl_pct':round(xp,4),'reason':xr}); inpos=False
  if inpos: op.append({'inst':inst})
 return tr,op
def sim14(enriched,allow,p,start,end):
 tr=[]; op=[]
 for inst,rows in enriched.items():
  inpos=False; entry=0; entry_i=0; peak=0; stop=0; tp1=False; rem=1; real=0
  for i in range(145,len(rows)):
   r=rows[i]; ts=r['ts_ms']
   if ts<start: continue
   if ts>end: break
   if not inpos:
    if inst not in allow.get(ts,set()): continue
    prev=rows[i-1]; r1=ret(rows,i,12); r3=ret(rows,i,36); r15=ret(rows,i,3); vw=lab.vwap(rows,i,24); prev_vw=lab.vwap(rows,i-1,24)
    # prior 6 bars had breakout; previous candle pulled back to EMA9/VWAP but held EMA21; current green reclaim
    prior_break=any(rows[j]['close']>rows[j]['high12_prev'] and rows[j]['vol_ratio']>=p['break_vol'] for j in range(max(25,i-6),i))
    pullback=prev['low']<=max(prev['ema9'],prev_vw)*(1+p['pull_buf']/100) and prev['close']>=prev['ema21']*(1-p['ema21_slack']/100)
    reclaim=r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw
    heat=p['min1h']<=r1<=p['max1h'] and r3>=p['min3h'] and r15<=p['max15m']
    vol=p['vol_min']<=r['vol_ratio']<=p['vol_max']
    if prior_break and pullback and reclaim and heat and vol:
     inpos=True; entry=r['close']; entry_i=i; peak=entry; tp1=False; rem=1; real=0; stop=entry*(1-EXIT['sl']/100)
   else:
    xp,xr,peak,stop,tp1,rem,real=exit_step(rows,i,entry,entry_i,peak,stop,tp1,rem,real)
    if xr: tr.append({'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'pnl_pct':round(xp,4),'reason':xr}); inpos=False
  if inpos: op.append({'inst':inst})
 return tr,op
def main():
 enriched,mn,mx=load(); start=mx-12*3600*1000
 allow1=allow_top(enriched,start,mx,12,20); allow2=allow_top(enriched,start,mx,24,20)
 results={'strategy13':[],'strategy14':[]}
 grid13={'min1h':[0.6,0.9,1.1],'max1h':[2.0,2.8],'min2h':[0.8,1.2],'min3h':[0.0,0.5],'min6h':[0.0],'max15m':[0.9,1.2],'vol_min':[1.4,1.8,2.2],'vol_max':[4.0,6.0],'upper_max':[0.3,0.45],'max_stretch':[0.6,0.9]}
 for vals in itertools.product(*(grid13[k] for k in grid13)):
  p=dict(zip(grid13,vals)); tr,op=sim13(enriched,allow2,p,start,mx); m=lab.metrics(tr,op)
  if (m['closed_trades'] or 0)>=8: results['strategy13'].append((m['avg_return_pct'] or -999,m['net_expectancy_after_fee_slip_pct'] or -999,m['profit_factor'] or 0,m['closed_trades'],p,m))
 grid14={'break_vol':[1.4,1.8,2.2],'pull_buf':[0.1,0.25,0.4],'ema21_slack':[0.0,0.15],'min1h':[0.6,0.9],'max1h':[2.0,2.8],'min3h':[0.0,0.5],'max15m':[0.9,1.2],'vol_min':[0.8,1.1],'vol_max':[3.0,4.5]}
 for vals in itertools.product(*(grid14[k] for k in grid14)):
  p=dict(zip(grid14,vals)); tr,op=sim14(enriched,allow1,p,start,mx); m=lab.metrics(tr,op)
  if (m['closed_trades'] or 0)>=8: results['strategy14'].append((m['avg_return_pct'] or -999,m['net_expectancy_after_fee_slip_pct'] or -999,m['profit_factor'] or 0,m['closed_trades'],p,m))
 out={}
 for name,rows in results.items():
  rows.sort(key=lambda x:(x[0],x[1],x[2],x[3]),reverse=True)
  out[name]=[{'params':p,'last12h':m} for *_,p,m in rows[:8]]
 print('RANGE',datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes'),'coins',len(enriched),'counts',{k:len(v) for k,v in results.items()})
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
