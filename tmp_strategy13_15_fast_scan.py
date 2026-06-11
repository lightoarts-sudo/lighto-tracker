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
 return {k:job.indicators(v) for k,v in data.items()},mn,mx
def build_allow(enriched,start,end,bars,topn=20):
 rowmap={inst:{r['ts_ms']:(i,r) for i,r in enumerate(rows)} for inst,rows in enriched.items()}; times=sorted(t for t in set(x for m in rowmap.values() for x in m) if start<=t<=end); out={}
 for ts in times:
  rank=[]
  for inst,m in rowmap.items():
   hit=m.get(ts)
   if hit and hit[0]>=bars: rank.append((pct(hit[1]['close'],enriched[inst][hit[0]-bars]['close']),inst))
  out[ts]=set(inst for _,inst in sorted(rank,reverse=True)[:topn])
 return out
def vwap(rows,i,look=24):
 s=pv=0
 for r in rows[max(0,i-look+1):i+1]:
  vol=(r.get('vol_ccy') or r.get('vol',0)*r['close']); s+=vol; pv+=r['close']*vol
 return pv/s if s else rows[i]['close']
def ok_entry(name,rows,i,p):
 r=rows[i]; prev=rows[i-1]; r1=ret(rows,i,12); r2=ret(rows,i,24); r3=ret(rows,i,36); r6=ret(rows,i,72); r15=ret(rows,i,3); rng=r['high']-r['low']; upper=(r['high']-r['close'])/rng if rng>0 else 0
 if name=='strategy12_top1h_controlled_breakout':
  return r['close']>r['high12_prev'] and r['close']>r['open'] and r['close']>r['ema9']>=r['ema21'] and p['min1h']<=r1<=p['max1h'] and r3>=p['min3h'] and r15<=p['max15m'] and p['vol_min']<=r['vol_ratio']<=p['vol_max'] and upper<=p['upper_max'] and pct(r['close'],r['high12_prev'])<=p['max_stretch']
 if name=='strategy13_top2h_retest_continuation':
  old=rows[i-2]['high12_prev']; prev_break=prev['close']>old and prev['vol_ratio']>=p['break_vol'] and prev['close']>prev['ema9']>=prev['ema21']
  return prev_break and r2>=p['min2h'] and r1<=p['max1h'] and r15<=p['max15m'] and r['low']<=old*(1+p['retest_tol']/100) and r['close']>=old and r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=p['confirm_vol']
 if name=='strategy14_top3h_vwap_reclaim':
  vw=vwap(rows,i,24); pv=vwap(rows,i-1,24)
  return r3>=p['min3h'] and r6>=p['min6h'] and r1<=p['max1h'] and r15<=p['max15m'] and prev['low']<=max(prev['ema9'],pv)*(1+p['pull_buf']/100) and r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw and p['vol_min']<=r['vol_ratio']<=p['vol_max']
 if name=='strategy15_top6h_squeeze_breakout':
  win=rows[i-p['look']:i]; hi=max(x['high'] for x in win); lo=min(x['low'] for x in win); avgv=sum(x['vol_ratio'] for x in win)/len(win)
  return r6>=p['min6h'] and r1<=p['max1h'] and (hi/lo-1)*100<=p['range_pct'] and avgv<=p['compress_vr'] and r['close']>hi and r['close']>r['open'] and r['vol_ratio']>=p['expand_vr'] and r['ema9']>=r['ema21'] and r15<=p['max15m']
 return False
def sim(enriched,allow,name,entryp,exitp,start,end):
 tr=[]; op=[]
 for inst,rows in enriched.items():
  inpos=False; entry=entry_i=peak=stop=0; tp1=False; rem=1; real=0
  for i in range(145,len(rows)):
   r=rows[i]; ts=r['ts_ms']
   if ts<start: continue
   if ts>end: break
   if not inpos:
    if inst not in allow.get(ts,set()): continue
    if ok_entry(name,rows,i,entryp):
     inpos=True; entry=r['close']; entry_i=i; peak=entry; tp1=False; rem=1; real=0; stop=entry*(1-exitp['sl']/100)
   else:
    peak=max(peak,r['high']); pnl=pct(r['close'],entry); pg=pct(peak,entry); held=i-entry_i; xp=xr=None
    if r['low']<=stop: xp=real+rem*pct(stop,entry); xr='SL'
    elif tp1 and r['low']<=entry*(1+exitp['be']/100): xp=real+rem*exitp['be']; xr='BE_AFTER_TP1'
    elif tp1 and pg>=exitp['trail_start'] and (pg-pnl)>=exitp['trail_giveback']: xp=real+rem*pnl; xr='TRAIL'
    elif (not tp1) and r['high']>=entry*(1+exitp['tp1']/100): tp1=True; real+=exitp['tp1_frac']*exitp['tp1']; rem=1-exitp['tp1_frac']; stop=max(stop,entry*(1+exitp['be']/100)); continue
    elif r['high']>=entry*(1+exitp['tp2']/100): xp=real+rem*exitp['tp2']; xr='TP2'
    elif held>=exitp['soft_time']:
     if pnl>=exitp['min_progress'] and r['close']>=r['ema9'] and held<exitp['hard_time']: continue
     xp=real+rem*pnl; xr='TIME_STOP'
    elif r['close']<r['ema21']: xp=real+rem*pnl; xr='EMA21_EXIT'
    if xr: tr.append({'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'pnl_pct':round(xp,4),'reason':xr}); inpos=False
  if inpos: op.append({'inst':inst})
 return tr,op
def main():
 enriched,mn,mx=load(); start=mx-12*3600*1000
 allows={'top1h':build_allow(enriched,start,mx,12),'top2h':build_allow(enriched,start,mx,24),'top3h':build_allow(enriched,start,mx,36),'top6h':build_allow(enriched,start,mx,72)}
 entries={
 'strategy12_top1h_controlled_breakout':('top1h',[{'min1h':1.1,'max1h':2.0,'min3h':0.0,'max15m':1.2,'vol_min':1.8,'vol_max':4.0,'upper_max':0.3,'max_stretch':0.9},{'min1h':0.8,'max1h':2.4,'min3h':0.5,'max15m':1.4,'vol_min':1.4,'vol_max':4.5,'upper_max':0.35,'max_stretch':1.1}]),
 'strategy13_top2h_retest_continuation':('top2h',[{'min2h':1.6,'max1h':2.4,'max15m':1.2,'break_vol':1.2,'confirm_vol':0.7,'retest_tol':0.3},{'min2h':2.2,'max1h':3.0,'max15m':1.5,'break_vol':1.1,'confirm_vol':0.6,'retest_tol':0.45}]),
 'strategy14_top3h_vwap_reclaim':('top3h',[{'min3h':2.0,'min6h':1.0,'max1h':2.0,'max15m':1.0,'pull_buf':0.25,'vol_min':0.7,'vol_max':3.5},{'min3h':1.2,'min6h':0.5,'max1h':1.6,'max15m':0.8,'pull_buf':0.4,'vol_min':0.6,'vol_max':3.0}]),
 'strategy15_top6h_squeeze_breakout':('top6h',[{'min6h':2.0,'max1h':2.0,'look':8,'range_pct':1.4,'compress_vr':1.1,'expand_vr':1.4,'max15m':1.1},{'min6h':3.0,'max1h':2.6,'look':10,'range_pct':1.8,'compress_vr':1.2,'expand_vr':1.2,'max15m':1.4}])}
 exits=[
  {'sl':0.7,'tp1':1.4,'tp1_frac':0.35,'tp2':3.2,'be':0.25,'trail_start':1.8,'trail_giveback':0.5,'soft_time':6,'hard_time':16,'min_progress':0.2},
  {'sl':0.7,'tp1':1.2,'tp1_frac':0.35,'tp2':3.2,'be':0.25,'trail_start':1.8,'trail_giveback':0.5,'soft_time':6,'hard_time':16,'min_progress':0.2},
  {'sl':0.6,'tp1':1.0,'tp1_frac':0.5,'tp2':2.8,'be':0.2,'trail_start':1.8,'trail_giveback':0.5,'soft_time':6,'hard_time':12,'min_progress':0.2},
  {'sl':0.7,'tp1':1.4,'tp1_frac':0.35,'tp2':2.8,'be':0.25,'trail_start':2.2,'trail_giveback':0.5,'soft_time':8,'hard_time':16,'min_progress':0.2},
  {'sl':0.6,'tp1':1.2,'tp1_frac':0.35,'tp2':2.4,'be':0.15,'trail_start':1.8,'trail_giveback':0.8,'soft_time':6,'hard_time':12,'min_progress':0.0},
 ]
 rows=[]
 for name,(allowname,eplist) in entries.items():
  for ei,ep in enumerate(eplist):
   best=None
   for xp in exits:
    tr,op=sim(enriched,allows[allowname],name,ep,xp,start,mx); m=lab.metrics(tr,op); n=m['closed_trades'] or 0
    if n<8: continue
    score=(m['avg_return_pct'] or -999,m['profit_factor'] or 0,n)
    if best is None or score>best[0]: best=(score,ep,xp,m)
   if best: rows.append({'strategy':name,'universe':allowname,'entry_variant':ei,'entry_params':best[1],'exit_params':best[2],'metrics':best[3]})
 rows.sort(key=lambda r:(r['metrics']['avg_return_pct'] or -999,r['metrics']['profit_factor'] or 0,r['metrics']['closed_trades']),reverse=True)
 out={'range':[datetime.fromtimestamp(start/1000,TZ).isoformat(timespec='minutes'),datetime.fromtimestamp(mx/1000,TZ).isoformat(timespec='minutes')],'coins':len(enriched),'top':rows}
 open('data/okx_micro_strategy13_15_scan.json','w',encoding='utf-8').write(json.dumps(out,ensure_ascii=False,indent=2))
 print(json.dumps(out,ensure_ascii=False,indent=2))
if __name__=='__main__': main()
