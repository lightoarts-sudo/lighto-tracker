import sqlite3,json
from datetime import datetime,timezone,timedelta
import okx_micro_report_job as job, strategy_lab_12h_runner as lab
TZ=timezone(timedelta(hours=8)); DB='data/okx_micro_5m_tracking.sqlite'
def pct(a,b): return (a/b-1)*100 if b else 0.0
def ret(rows,i,b): return pct(rows[i]['close'],rows[i-b]['close']) if i-b>=0 else 0.0
def load():
 con=sqlite3.connect(DB); con.row_factory=sqlite3.Row; mx=con.execute('select max(ts_ms) from candles_5m').fetchone()[0]; since=mx-30*3600*1000; data={}
 for inst, in con.execute('select distinct inst_id from candles_5m where ts_ms>=?',(since,)):
  base=inst.split('-')[0]
  if base in job.EXCLUDE or base in job.STABLE_OR_FIAT: continue
  rs=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? and ts_ms>=? order by ts_ms',(inst,since)).fetchall()
  if len(rs)>=180: data[inst]=[dict(r) for r in rs]
 return {k:job.indicators(v) for k,v in data.items()},mx
def vwap(rows,i):
 s=pv=0
 for r in rows[max(0,i-23):i+1]:
  vol=(r.get('vol_ccy') or r.get('vol',0)*r['close']); s+=vol; pv+=r['close']*vol
 return pv/s if s else rows[i]['close']
def ranks(enriched,start,end,bars,topn=20):
 mp={inst:{r['ts_ms']:i for i,r in enumerate(rows)} for inst,rows in enriched.items()}; out={}
 for ts in sorted({r['ts_ms'] for rows in enriched.values() for r in rows if start<=r['ts_ms']<=end}):
  arr=[]
  for inst,m in mp.items():
   i=m.get(ts)
   if i is not None and i>=bars: arr.append((ret(enriched[inst],i,bars),inst))
  out[ts]=set(x for _,x in sorted(arr,reverse=True)[:topn])
 return out
def entry(name,rows,i,p):
 r=rows[i]; prev=rows[i-1]; prev2=rows[i-2]; r1=ret(rows,i,12); r2=ret(rows,i,24); r3=ret(rows,i,36); r6=ret(rows,i,72); r15=ret(rows,i,3); rng=r['high']-r['low']; upper=(r['high']-r['close'])/rng if rng else 0
 if name=='s16_top1h_clean_breakout': return r['close']>r['high12_prev'] and r['close']>r['open'] and r['close']>r['ema9']>=r['ema21'] and p['min1']<=r1<=p['max1'] and r3>=p['min3'] and r15<=p['max15'] and p['vmin']<=r['vol_ratio']<=p['vmax'] and upper<=p['upper'] and pct(r['close'],r['high12_prev'])<=p['stretch']
 if name=='s17_top3h_vwap_reclaim_runner':
  vw=vwap(rows,i); pv=vwap(rows,i-1); return r3>=p['min3'] and r6>=p['min6'] and r1<=p['max1'] and r15<=p['max15'] and prev['low']<=max(prev['ema9'],pv)*(1+p['buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and p['vmin']<=r['vol_ratio']<=p['vmax']
 if name=='s18_top2h_retest_runner':
  old=prev2['high12_prev']; pb=prev['close']>old and prev['vol_ratio']>=p['bvol'] and prev['close']>prev['ema9']>=prev['ema21']; return pb and r2>=p['min2'] and r1<=p['max1'] and r15<=p['max15'] and r['low']<=old*(1+p['tol']/100) and r['close']>=old and r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=p['cvol']
 return False
def sim(enriched,allow,name,ep,xp,start,end):
 tr=[]; op=[]
 for inst,rows in enriched.items():
  inpos=False; ent=peak=stop=0; ei=0; real=0; rem=1; tp1=False
  for i in range(145,len(rows)):
   r=rows[i]; ts=r['ts_ms']
   if ts<start: continue
   if ts>end: break
   if not inpos:
    if inst in allow.get(ts,set()) and entry(name,rows,i,ep): inpos=True; ent=r['close']; peak=ent; ei=i; real=0; rem=1; tp1=False; stop=ent*(1-xp['sl']/100)
   else:
    peak=max(peak,r['high']); pnl=pct(r['close'],ent); pg=pct(peak,ent); held=i-ei; out=reason=None
    if r['low']<=stop: out=real+rem*pct(stop,ent); reason='SL'
    elif tp1 and r['low']<=ent*(1+xp['be']/100): out=real+rem*xp['be']; reason='BE_AFTER_TP1'
    elif tp1 and pg>=xp['trail_start'] and (pg-pnl)>=xp['give']: out=real+rem*pnl; reason='TRAIL'
    elif (not tp1) and r['high']>=ent*(1+xp['tp1']/100): tp1=True; real+=xp['frac']*xp['tp1']; rem=1-xp['frac']; stop=max(stop,ent*(1+xp['be']/100)); continue
    elif r['high']>=ent*(1+xp['tp2']/100): out=real+rem*xp['tp2']; reason='TP2'
    elif held>=xp['soft']:
     if pnl>=xp['minprog'] and r['close']>=r['ema9'] and held<xp['hard']: continue
     out=real+rem*pnl; reason='TIME_STOP'
    elif r['close']<r['ema21']: out=real+rem*pnl; reason='EMA21_EXIT'
    if reason: tr.append({'inst':inst,'pnl_pct':round(out,4),'reason':reason}); inpos=False
  if inpos: op.append({'inst':inst})
 return tr,op
def main():
 enriched,mx=load(); start=mx-12*3600*1000
 allows={'top1h':ranks(enriched,start,mx,12,20),'top2h':ranks(enriched,start,mx,24,20),'top3h':ranks(enriched,start,mx,36,20)}
 entries={
 's16_top1h_clean_breakout':('top1h',[{'min1':1.1,'max1':2.8,'min3':0.5,'max15':1.4,'vmin':1.4,'vmax':4.5,'upper':0.35,'stretch':1.0},{'min1':1.4,'max1':2.8,'min3':1.0,'max15':1.2,'vmin':1.6,'vmax':4.0,'upper':0.3,'stretch':0.8}]),
 's17_top3h_vwap_reclaim_runner':('top3h',[{'min3':2.0,'min6':1.0,'max1':2.0,'max15':1.0,'buf':0.25,'vmin':0.7,'vmax':3.5},{'min3':3.0,'min6':2.0,'max1':2.4,'max15':0.8,'buf':0.4,'vmin':0.5,'vmax':3.5}]),
 's18_top2h_retest_runner':('top2h',[{'min2':2.2,'max1':3.0,'max15':1.5,'bvol':1.1,'cvol':0.6,'tol':0.45},{'min2':1.6,'max1':2.4,'max15':1.2,'bvol':1.2,'cvol':0.7,'tol':0.3}])}
 exits=[
 {'sl':0.6,'tp1':1.2,'frac':0.35,'tp2':2.4,'be':0.15,'trail_start':1.8,'give':0.8,'soft':6,'hard':12,'minprog':0},
 {'sl':0.7,'tp1':1.4,'frac':0.35,'tp2':3.2,'be':0.25,'trail_start':1.8,'give':0.5,'soft':6,'hard':16,'minprog':0.2},
 {'sl':0.5,'tp1':1.2,'frac':0.3,'tp2':4.0,'be':0.25,'trail_start':2.0,'give':0.8,'soft':8,'hard':16,'minprog':0.2},
 {'sl':0.6,'tp1':1.4,'frac':0.3,'tp2':4.0,'be':0.25,'trail_start':2.4,'give':0.8,'soft':8,'hard':16,'minprog':0.2}]
 out=[]
 for name,(an,eps) in entries.items():
  for ep in eps:
   for xp in exits:
    tr,op=sim(enriched,allows[an],name,ep,xp,start,mx); m=lab.metrics(tr,op)
    if (m['closed_trades'] or 0)>=8: out.append({'strategy':name,'universe':an,'entry_params':ep,'exit_params':xp,'metrics':m})
 out.sort(key=lambda r:(r['metrics']['avg_return_pct'] or -999,r['metrics']['profit_factor'] or 0,r['metrics']['closed_trades']),reverse=True)
 res={'range':[datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes')],'coins':len(enriched),'top':out[:20]}
 open('data/okx_micro_morning_strategy_scan.json','w',encoding='utf-8').write(json.dumps(res,ensure_ascii=False,indent=2)); print(json.dumps(res,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
