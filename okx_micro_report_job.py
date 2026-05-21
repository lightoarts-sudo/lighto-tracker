import os, sqlite3, json, math, statistics, time
from datetime import datetime, timezone, timedelta
from urllib.request import urlopen, Request
from urllib.parse import urlencode

DB='data/okx_micro_5m_tracking.sqlite'
STATE='data/okx_micro_paper_strategy_state.json'
EXCLUDE=set('BTC ETH SOL BNB XRP ADA DOGE TRX TON AVAX LINK DOT MATIC POL LTC BCH ETC FIL ATOM NEAR APT SUI OP ARB WLD UNI PEPE SHIB LDO ICP HBAR XLM HYPE ONDO'.split())
STABLE_OR_FIAT=set('USDC USDG USD1 RLUSD DAI TUSD USDP EURT BRZ TRYB XAUT'.split())
TZ=timezone(timedelta(hours=8))

MICRO_STOP_LOSS_PCT = 1.0
MICRO_TAKE_PROFIT_1_PCT = 1.2
MICRO_TAKE_PROFIT_2_PCT = 2.5
MICRO_BREAKEVEN_LOCK_PCT = 0.2
MICRO_TRAILING_START_PCT = 1.8
MICRO_TRAILING_GIVEBACK_PCT = 0.8
MICRO_TIME_STOP_BARS = 6

def parse_iso(s):
    return datetime.fromisoformat(s.replace('Z','+00:00'))

def now_tz():
    return datetime.now(TZ)

def okx_get(path, params=None):
    url='https://www.okx.com'+path
    if params: url += '?' + urlencode(params)
    req=Request(url, headers={'User-Agent':'LIGHTOARTS-research/1.0'})
    with urlopen(req, timeout=15) as r:
        return json.loads(r.read().decode())

def fetch_fallback(con, needed_since_ms):
    # Public API fallback: populate top quote-volume USDT spot small coins when local DB is stale/insufficient.
    try:
        tick=okx_get('/api/v5/market/tickers', {'instType':'SPOT'})['data']
        rows=[]
        for t in tick:
            inst=t.get('instId','')
            if not inst.endswith('-USDT'): continue
            base=inst.split('-')[0]
            if base in EXCLUDE or base in STABLE_OR_FIAT: continue
            try: qv=float(t.get('volCcy24h') or 0)
            except: qv=0
            if qv>0: rows.append((qv,inst,base))
        rows=sorted(rows, reverse=True)[:80]
        cap=now_tz().isoformat(timespec='seconds')
        con.execute("insert into snapshots(captured_at,source,candidate_count,notes) values(?,?,?,?)",(cap,'okx_api_fallback',len(rows),'fallback 5m candles for report'))
        sid=con.execute('select last_insert_rowid()').fetchone()[0]
        for rank,(qv,inst,base) in enumerate(rows[:30],1):
            candles=okx_get('/api/v5/market/candles', {'instId':inst,'bar':'5m','limit':'150'}).get('data',[])
            vals=[]
            for c in candles:
                ts=int(c[0]);
                if ts < needed_since_ms: continue
                dt=datetime.fromtimestamp(ts/1000, TZ).isoformat(timespec='minutes')
                vals.append((inst,ts,dt,float(c[1]),float(c[2]),float(c[3]),float(c[4]),float(c[5]),float(c[6] or 0),cap))
            con.executemany('insert or ignore into candles_5m values(?,?,?,?,?,?,?,?,?,?)', vals)
            if vals:
                last=vals[0][6]
                old=vals[min(12,len(vals)-1)][6]
                ch=(last/old-1)*100 if old else 0
                con.execute('insert or ignore into rankings(snapshot_id,rank_1h,inst_id,base_ccy,last,change_1h_pct,quote_vol_24h) values(?,?,?,?,?,?,?)',(sid,rank,inst,base,last,ch,qv))
            time.sleep(0.08)
        con.commit()
    except Exception as e:
        print('fallback_failed', e)

def ema(vals, span):
    k=2/(span+1); out=[]; prev=None
    for v in vals:
        prev = v if prev is None else v*k + prev*(1-k)
        out.append(prev)
    return out

def load_data():
    con=sqlite3.connect(DB)
    con.row_factory=sqlite3.Row
    max_ts=con.execute('select max(ts_ms) from candles_5m').fetchone()[0]
    if not max_ts:
        fetch_fallback(con, int((now_tz()-timedelta(hours=12)).timestamp()*1000))
        max_ts=con.execute('select max(ts_ms) from candles_5m').fetchone()[0]
    # If the hourly capture is behind, top up from OKX public API so the report is based on the latest available 12h window.
    if datetime.now(TZ).timestamp()*1000 - max_ts > 20*60*1000:
        fetch_fallback(con, int((now_tz()-timedelta(hours=12)).timestamp()*1000))
        max_ts=con.execute('select max(ts_ms) from candles_5m').fetchone()[0]
    since=max_ts-12*3600*1000
    inst_counts=con.execute('select inst_id,count(*) c from candles_5m where ts_ms>=? group by inst_id having c>=100',(since,)).fetchall()
    if len(inst_counts)<20:
        fetch_fallback(con, since)
        max_ts=con.execute('select max(ts_ms) from candles_5m').fetchone()[0]
        since=max_ts-12*3600*1000
    data={}
    for inst, in con.execute('select distinct inst_id from candles_5m where ts_ms>=?',(since,)):
        base=inst.split('-')[0]
        if base in EXCLUDE or base in STABLE_OR_FIAT: continue
        rows=con.execute('select ts_ms,ts_iso,open,high,low,close,vol,vol_ccy from candles_5m where inst_id=? and ts_ms>=? order by ts_ms',(inst,since)).fetchall()
        if len(rows)>=80: data[inst]=[dict(r) for r in rows]
    return con, data, since, max_ts

def indicators(rows):
    closes=[r['close'] for r in rows]; highs=[r['high'] for r in rows]; lows=[r['low'] for r in rows]; vols=[r['vol_ccy'] if r['vol_ccy'] else r['vol']*r['close'] for r in rows]
    e9=ema(closes,9); e21=ema(closes,21)
    out=[]
    for i,r in enumerate(rows):
        rr=dict(r); rr['ema9']=e9[i]; rr['ema21']=e21[i]
        start=max(0,i-12); rr['high12_prev']=max(highs[start:i]) if i>0 else highs[i]
        rr['low12_prev']=min(lows[start:i]) if i>0 else lows[i]
        vwin=vols[max(0,i-20):i]
        rr['vol_ratio']=(vols[i]/(sum(vwin)/len(vwin))) if vwin and sum(vwin)>0 else 1
        rr['green']=r['close']>r['open']
        out.append(rr)
    return out

def summarize(data):
    enriched={k:indicators(v) for k,v in data.items()}
    stats=[]
    for inst, rows in enriched.items():
        first=rows[0]['close']; last=rows[-1]['close']; h1base=rows[-13]['close'] if len(rows)>=13 else first
        ret12=(last/first-1)*100; ret1=(last/h1base-1)*100
        eok=last>rows[-1]['ema9']>rows[-1]['ema21']
        vr=rows[-1]['vol_ratio']; maxvr=max(r['vol_ratio'] for r in rows[-36:])
        pullback=(max(r['high'] for r in rows[-24:])/last-1)*100
        stats.append({'inst':inst,'ret12':ret12,'ret1':ret1,'ema_bull':eok,'vol_ratio':vr,'max_vol_ratio':maxvr,'pullback':pullback,'last':last})
    # rolling 1h ranking appearances top 10
    times=sorted(set(r['ts_ms'] for rows in enriched.values() for r in rows))
    app={k:0 for k in enriched}; top3={k:0 for k in enriched}
    rowmap={k:{r['ts_ms']:r for r in rows} for k,rows in enriched.items()}
    for ts in times[12::3]:  # every 15m to reduce noise
        rank=[]
        for inst,m in rowmap.items():
            if ts in m:
                rows=enriched[inst]; idx=next((i for i,r in enumerate(rows) if r['ts_ms']==ts),None)
                if idx is not None and idx>=12:
                    c=rows[idx]['close']; old=rows[idx-12]['close']; rank.append(((c/old-1)*100,inst))
        for j,(ret,inst) in enumerate(sorted(rank, reverse=True)[:10],1):
            app[inst]+=1
            if j<=3: top3[inst]+=1
    for s in stats:
        s['top10_1h_count']=app.get(s['inst'],0); s['top3_1h_count']=top3.get(s['inst'],0)
    return enriched, stats

def load_state():
    if os.path.exists(STATE):
        try:
            with open(STATE,'r',encoding='utf-8') as f: return json.load(f)
        except: pass
    return {'strategy_version':'v0_initial','entry_rules':{'type':'baseline'},'exit_rules':{},'risk_rules':{},'watchlist':[], 'open_paper_trades':[]}

def backtest(enriched, state, stats):
    watch=state.get('watchlist') or [s['inst'] for s in sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret12']), reverse=True)[:12]]
    trades=[]; open_trades=[]
    for inst in watch:
        rows=enriched.get(inst)
        if not rows: continue
        inpos=False; entry=0; entry_i=0; stop=0; peak=0; remaining=1.0; realized_pct=0.0; tp1=False
        for i in range(25,len(rows)):
            r=rows[i]; prev=rows[i-1]
            if not inpos:
                ret1=(r['close']/rows[i-12]['close']-1)*100
                ret12=(r['close']/rows[0]['close']-1)*100
                breakout=r['close']>prev['high12_prev'] and r['ema9']>r['ema21'] and ret1>0.35 and ret12>0 and r['vol_ratio']>=1.15
                pullback=prev['low']<=prev['ema21']*1.003 and r['close']>r['open'] and r['close']>r['ema9']>r['ema21'] and ret1>0.1
                if breakout or pullback:
                    inpos=True; entry=r['close']; entry_i=i; etype='突破' if breakout else '回踩'
                    structural_stop=min(r['ema21'], r['low12_prev'])*0.998
                    hard_stop=entry*(1-MICRO_STOP_LOSS_PCT/100)
                    stop=max(structural_stop, hard_stop)
                    peak=entry; remaining=1.0; realized_pct=0.0; tp1=False
            else:
                peak=max(peak, r['high'])
                pnl=(r['close']/entry-1)*100
                lowp=(r['low']/entry-1)*100
                reason=None; xp=None
                breakeven_stop=entry*(1+MICRO_BREAKEVEN_LOCK_PCT/100)
                peak_gain=(peak/entry-1)*100
                giveback=peak_gain-pnl
                if r['low']<=stop:
                    reason='硬停損-1%' if stop >= entry*0.99 else '停損/破EMA21'
                    xp=realized_pct + remaining*((stop/entry-1)*100)
                elif tp1 and r['low']<=breakeven_stop:
                    reason='TP1後保本停利'; xp=realized_pct + remaining*MICRO_BREAKEVEN_LOCK_PCT
                elif tp1 and peak_gain>=MICRO_TRAILING_START_PCT and giveback>=MICRO_TRAILING_GIVEBACK_PCT:
                    reason='追蹤停利'; xp=realized_pct + remaining*pnl
                elif r['high']>=entry*(1+MICRO_TAKE_PROFIT_2_PCT/100):
                    reason='TP2+尾倉續抱'; xp=realized_pct + remaining*MICRO_TAKE_PROFIT_2_PCT
                elif (not tp1) and r['high']>=entry*(1+MICRO_TAKE_PROFIT_1_PCT/100):
                    tp1=True; realized_pct += 0.5*MICRO_TAKE_PROFIT_1_PCT; remaining=0.5; stop=max(stop, breakeven_stop)
                    continue
                elif i-entry_i>=MICRO_TIME_STOP_BARS:
                    reason='30m時間停損'; xp=realized_pct + remaining*pnl
                elif r['close']<r['ema21']:
                    reason='跌破EMA21'; xp=realized_pct + remaining*pnl
                if reason:
                    trades.append({'inst':inst,'entry_i':entry_i,'exit_i':i,'pnl_pct':round(xp,3),'reason':reason})
                    inpos=False
        if inpos:
            last=rows[-1]; open_trades.append({'inst':inst,'entry_price':entry,'last_price':last['close'],'unrealized_pct':(last['close']/entry-1)*100,'entry_time':rows[entry_i]['ts_iso'],'stop':stop})
    n=len(trades); wins=sum(1 for t in trades if t['pnl_pct']>0)
    metrics={'trades':n,'win_rate_pct':round(wins/n*100,1) if n else None,'avg_return_pct':round(sum(t['pnl_pct'] for t in trades)/n,3) if n else None,'max_loss_pct':round(min([t['pnl_pct'] for t in trades], default=0),3),'open_trades':open_trades,'sample_note':'樣本不足，僅供調參' if n<20 else '樣本尚可'}
    return metrics, trades

def write_state_and_report():
    con,data,since,max_ts=load_data(); enriched,stats=summarize(data); old=load_state(); metrics,trades=backtest(enriched,old,stats)
    strong=sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret12']), reverse=True)[:8]
    weak=[s for s in sorted(stats,key=lambda x:x['ret1'])[:8] if s['ret12']>0 or s['top10_1h_count']>0]
    vol=sorted(stats,key=lambda x:x['max_vol_ratio'], reverse=True)[:6]
    fake=sorted([s for s in stats if s['pullback']>1.5 and s['ret1']<0], key=lambda x:x['pullback'], reverse=True)[:6]
    watch=[]
    for s in strong:
        if s['ema_bull'] and s['ret1']>-0.2: watch.append(s['inst'])
    for s in sorted(stats,key=lambda x:x['ret1'], reverse=True):
        if s['inst'] not in watch and s['ema_bull'] and s['ret12']>0: watch.append(s['inst'])
        if len(watch)>=10: break
    conservative = (metrics['win_rate_pct'] is None or metrics['win_rate_pct']<50 or metrics['trades']<20)
    risk_pct=0.35 if conservative else 0.6
    version_num=1
    if old.get('strategy_version','').startswith('v'):
        import re; m=re.search(r'(\d+)',old.get('strategy_version',''))
        if m: version_num=int(m.group(1))+1
    new_state={
        'strategy_version':f'v{version_num}_winrate_first_5m',
        'updated_at':datetime.fromtimestamp(max_ts/1000,TZ).isoformat(timespec='seconds'),
        'entry_rules':{
            'trend_filter':'近1H > +0.2%、近12H不為負，且5m EMA9 > EMA21',
            'breakout':'收盤突破前12根5m高點，量能比>=1.2；爆量>2.5時等下一根不跌回突破價才進',
            'pullback':'回踩EMA9/EMA21後重新收紅並站回EMA9，優先勝率'
        },
        'exit_rules':{
            'take_profit':'半倉+1.2%，剩餘+2.5%或+1.8%後回吐0.8%追蹤停利；TP1後停損移到+0.2%',
            'stop_loss':'硬停損最多-1.0%，並取EMA21/前12根低點較近者',
            'time_stop':'進場後6根5m(30分鐘)未達+0.6%則出場'
        },
        'risk_rules':{'paper_only':True,'risk_per_trade_pct':risk_pct,'max_concurrent_trades':3,'avoid':'5m長上影且下一根量縮跌回突破位'},
        'watchlist':watch[:10],
        'open_paper_trades':metrics['open_trades'],
        'last_12h_metrics':metrics
    }
    os.makedirs('data',exist_ok=True)
    with open(STATE,'w',encoding='utf-8') as f: json.dump(new_state,f,ensure_ascii=False,indent=2)
    start=datetime.fromtimestamp(since/1000,TZ).strftime('%m/%d %H:%M'); end=datetime.fromtimestamp(max_ts/1000,TZ).strftime('%m/%d %H:%M')
    title='OKX 小幣 12H 追蹤報告（晚上9點）' if now_tz().hour>=12 else 'OKX 小幣 12H 追蹤報告（早上9點）'
    def fmt(lst, kind='strong'):
        out=[]
        for s in lst[:5]: out.append(f"{s['inst'].replace('-USDT','')} 12H {s['ret12']:+.1f}% / 1H {s['ret1']:+.1f}% / Top10 {s['top10_1h_count']}次 / 量能峰值{xround(s['max_vol_ratio'])}x")
        return '；'.join(out) if out else '無明顯名單'
    def xround(v): return f'{v:.1f}'
    trade_line = f"進場 {metrics['trades']} 次；勝率 {metrics['win_rate_pct'] if metrics['win_rate_pct'] is not None else 'N/A'}%；平均報酬 {metrics['avg_return_pct'] if metrics['avg_return_pct'] is not None else 'N/A'}%；最大虧損 {metrics['max_loss_pct']}%。"
    if metrics['open_trades']:
        trade_line += ' 未平倉：' + '、'.join([f"{t['inst'].replace('-USDT','')} {t['unrealized_pct']:+.2f}%" for t in metrics['open_trades'][:5]])
    else: trade_line += ' 目前無未平倉模擬單。'
    plan=[]
    for inst in watch[:6]:
        s=next(x for x in stats if x['inst']==inst); name=inst.replace('-USDT','')
        plan.append(f"{name}：只在EMA9>EMA21且1H維持正值時做；突破12根高點或回踩EMA21收紅進；TP +1.0%先出半並移保本、+2.0%再出剩餘或尾倉追蹤；硬SL -1.0%內；若跌回突破位/量縮則失效。")
    report=f"""{title}

資料時間範圍：{start}～{end}（5MIN K，OKX 現貨 USDT 小幣；已排除主流大幣）

12H 觀察重點
- 強勢幣：{fmt(strong)}
- 轉弱幣：{fmt(weak)}
- 爆量幣：{fmt(vol)}
- 假突破風險：{fmt(fake)}

上一輪模擬交易結果
- {trade_line}
- 評語：{metrics['sample_note']}；本輪調整仍以勝率>50%為優先，不追單長上影爆量K。

策略調整
- 新版本：{new_state['strategy_version']}
- 進場：保留「突破12根高點」與「EMA9/21回踩收紅」，但爆量突破需下一根確認，避免假突破。
- 出場：+1.0%先收半並把剩餘停損推到+0.2%，+2.0%再收/尾倉追蹤；硬停損限制在-1.0%。
- 風控：單筆模擬風險 {risk_pct:.2f}%；最多3筆同時持倉；樣本不足或勝率未達標時不加倉。

下一輪 12H 模擬交易計畫
- 觀察名單：{', '.join([w.replace('-USDT','') for w in watch[:10]]) if watch else '暫無，等待新強勢幣'}
""" + '\n'.join([f"- {p}" for p in plan]) + f"""

風險提醒
- 以上為模擬交易計畫，不是真實下單建議。小幣滑價與插針風險高；若 BTC/ETH 5MIN 同步轉弱，所有突破單降級或取消。
- 若下一輪樣本仍不足20筆，維持保守倉位，優先等待回踩確認，不做第一根爆量追高。
"""
    print(report)

if __name__ == '__main__':
    write_state_and_report()
