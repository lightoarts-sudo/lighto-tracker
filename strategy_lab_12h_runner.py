#!/usr/bin/env python3
from __future__ import annotations
import json, os, math, itertools
from datetime import datetime, timezone, timedelta
from collections import Counter
import okx_micro_report_job as job

TZ = timezone(timedelta(hours=8))
LAB='data/okx_micro_strategy_lab.json'
STATE='data/okx_micro_paper_strategy_state.json'
FEE_SLIP=0.16

def pct(a,b): return (a/b-1)*100 if b else 0.0

def ret(rows,i,bars):
    if i-bars < 0: return 0.0
    return pct(rows[i]['close'], rows[i-bars]['close'])

def vwap(rows,i,lookback=24):
    s=pv=0.0
    for r in rows[max(0,i-lookback+1):i+1]:
        vol = r.get('vol_ccy') or r.get('vol',0)*r['close']
        s += vol
        pv += r['close']*vol
    return pv/s if s else rows[i]['close']

def metrics(trades, open_trades=None):
    rs=[t['pnl_pct'] for t in trades]
    wins=[r for r in rs if r>0]; losses=[r for r in rs if r<=0]
    n=len(rs); gross_win=sum(wins); gross_loss=abs(sum(losses))
    avg_win=sum(wins)/len(wins) if wins else 0.0
    avg_loss=sum(losses)/len(losses) if losses else 0.0
    exp=sum(rs)/n if n else None
    return {
        'entries': n + (len(open_trades or [])),
        'closed_trades': n,
        'win_rate_pct': round(len(wins)/n*100,2) if n else None,
        'avg_return_pct': round(exp,4) if exp is not None else None,
        'avg_win_pct': round(avg_win,4),
        'avg_loss_pct': round(avg_loss,4),
        'expectancy_pct': round(exp,4) if exp is not None else None,
        'net_expectancy_after_fee_slip_pct': round(exp-FEE_SLIP,4) if exp is not None else None,
        'profit_factor': round(gross_win/gross_loss,4) if gross_loss else (999.0 if gross_win else None),
        'max_loss_pct': round(min(rs),4) if rs else None,
        'open_trades': len(open_trades or []),
        'exit_reasons': dict(Counter(t['reason'] for t in trades)),
        'sample_size': n,
        'sample_note': '樣本不足' if n<8 else ('樣本偏少' if n<20 else '樣本尚可')
    }

def is_qualified(m):
    if (m.get('closed_trades') or 0) < 8:
        return False, '樣本不足，未達8筆已平倉'
    if (m.get('expectancy_pct') or -999) <= 0:
        return False, 'expectancy未轉正'
    if (m.get('profit_factor') or 0) <= 1.2:
        return False, 'profit factor未達1.2'
    if m.get('max_loss_pct') is not None and m['max_loss_pct'] < -1.35:
        return False, '最大單筆虧損超出小幣短線可控區'
    if (m.get('avg_return_pct') or 0) <= FEE_SLIP:
        return False, '平均報酬未明顯高於手續費/滑價假設成本'
    return True, '達暫定合格條件'

def simulate(enriched, watch, strategy, params):
    trades=[]; opens=[]
    for inst in watch:
        rows=enriched.get(inst)
        if not rows or len(rows)<40: continue
        inpos=False; entry=0; entry_i=0; peak=0; stop=0; tp1=False; rem=1; real=0; meta={}
        for i in range(25,len(rows)):
            r=rows[i]
            if not inpos:
                enter=False; reason=''
                r1=ret(rows,i,12); r15=ret(rows,i,3); r12=pct(r['close'],rows[0]['close'])
                if strategy=='strategy1':
                    ma = r['close']>r['ema9']>r['ema21'] and r12>params.get('min_12h',0) and r1>params['min_1h']
                    breakout = r['close']>rows[i-1]['high12_prev'] and r['vol_ratio']>=params['vol_min']
                    upper_ok = (r['high']-r['close'])/(r['high']-r['low']) < 0.45 if r['high']>r['low'] else True
                    enter = ma and breakout and upper_ok
                    reason='MA_stack_breakout'
                elif strategy=='strategy2':
                    vr=params['vol_min'] <= r['vol_ratio'] <= params['vol_max']
                    enter = r1>=params['min_1h'] and r15>=params['min_15m'] and vr and r['close']>r['ema9'] and r['ema9']>=r['ema21']
                    reason='surge_momentum'
                elif strategy=='strategy3_pullback_after_surge':
                    prior=max(ret(rows,j,12) for j in range(max(25,i-12),i+1))
                    vw=vwap(rows,i,24)
                    touched = rows[i-1]['low'] <= max(rows[i-1]['ema21'], vwap(rows,i-1,24))*1.004
                    reclaim = r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw
                    enter = prior>=params['surge_1h'] and touched and reclaim and 0.6<=r['vol_ratio']<=params['vol_max']
                    reason='pullback_after_surge'
                elif strategy=='strategy4_breakout_confirmation':
                    prev=rows[i-1]; prev2=rows[i-2]
                    prev_break = prev['close']>prev2['high12_prev'] and prev['vol_ratio']>=params['break_vol'] and prev['close']>prev['ema9']>prev['ema21']
                    hold = r['low']>=prev2['high12_prev']*params['hold_factor'] and r['close']>prev['close']*(1+params['confirm_gain']/100)
                    enter = prev_break and hold and ret(rows,i,12)>=params['min_1h'] and r['vol_ratio']>=params['confirm_vol']
                    reason='confirmed_breakout'
                elif strategy=='strategy6_volume_compression_expansion':
                    vols=[x['vol_ratio'] for x in rows[i-8:i]]
                    hi=max(x['high'] for x in rows[i-8:i]); lo=min(x['low'] for x in rows[i-8:i])
                    compression = max(vols)<params['compress_vr'] and pct(hi,lo)<params['range_pct']
                    enter = compression and r['close']>hi and r['vol_ratio']>=params['expand_vr'] and r['close']>r['ema9']>=r['ema21']
                    reason='volume_compression_expansion'
                elif strategy=='strategy7_vwap_reclaim_stability':
                    # High-selectivity pullback: only enter after an established intraday uptrend,
                    # a shallow pullback to VWAP/EMA21, and a candle reclaiming both VWAP and EMA9.
                    # This favors win-rate/stability over entry frequency.
                    prior_1h=max(ret(rows,j,12) for j in range(max(25,i-12),i+1))
                    prev=rows[i-1]
                    vw=vwap(rows,i,params.get('vwap_lookback',24)); prev_vw=vwap(rows,i-1,params.get('vwap_lookback',24))
                    shallow_pullback = prev['low'] <= max(prev['ema21'], prev_vw)*(1+params['pullback_buffer']/100)
                    reclaimed = r['close']>r['open'] and r['close']>r['ema9'] and r['close']>vw
                    trend_ok = r['ema9']>=r['ema21'] and ret(rows,i,12)>=params['min_1h'] and prior_1h>=params['prior_1h']
                    not_overheated = ret(rows,i,3) <= params['max_15m'] and r['vol_ratio'] <= params['vol_max']
                    enter = trend_ok and shallow_pullback and reclaimed and not_overheated and r['vol_ratio']>=params['vol_min']
                    reason='vwap_reclaim_stability'
                elif strategy=='strategy8_breakout_retest_only':
                    # Avoid first-breakout chasing. Require the prior breakout candle, then a retest
                    # that holds the old range high and closes green. Fewer trades, intended higher win rate.
                    prev=rows[i-1]; prev2=rows[i-2]
                    old_hi=prev2['high12_prev']
                    prev_break = prev['close']>old_hi and prev['vol_ratio']>=params['break_vol'] and prev['close']>prev['ema9']>=prev['ema21']
                    retest_held = r['low'] <= old_hi*(1+params['retest_tolerance']/100) and r['close']>=old_hi*(1+params['hold_margin']/100)
                    reclaim = r['close']>r['open'] and r['close']>r['ema9'] and r['vol_ratio']>=params['confirm_vol']
                    enter = prev_break and retest_held and reclaim and ret(rows,i,12)>=params['min_1h'] and ret(rows,i,3)<=params['max_15m']
                    reason='breakout_retest_only'
                elif strategy=='strategy9_ema9_bounce_low_heat':
                    # Trend-continuation bounce: use many coins as opportunity source but demand
                    # low-heat pullback and quick reclaim, avoiding vertical candles.
                    prev=rows[i-1]
                    touched_ema9 = prev['low'] <= prev['ema9']*(1+params['touch_buffer']/100)
                    held_ema21 = prev['close'] >= prev['ema21']*(1-params['ema21_slack']/100)
                    bounce = r['close']>r['open'] and r['close']>r['ema9'] and r['ema9']>=r['ema21']
                    heat_ok = params['min_1h'] <= ret(rows,i,12) <= params['max_1h'] and ret(rows,i,3)<=params['max_15m']
                    vol_ok = params['vol_min'] <= r['vol_ratio'] <= params['vol_max']
                    enter = touched_ema9 and held_ema21 and bounce and heat_ok and vol_ok
                    reason='ema9_bounce_low_heat'
                if enter:
                    inpos=True; entry=r['close']; entry_i=i; peak=entry; tp1=False; rem=1; real=0; meta={'entry_reason':reason}
                    stop=entry*(1-params['sl']/100)
                    if params.get('struct_stop', True): stop=max(stop, min(r['ema21'], r['low12_prev'])*0.998)
                    continue
            else:
                peak=max(peak,r['high']); pnl=pct(r['close'],entry); peak_gain=pct(peak,entry)
                xp=None; xr=None
                if strategy=='strategy2' and i-entry_i==params['nft_bars'] and pct(r['close'], entry) < params['nft_min_gain']:
                    xp=pnl; xr='NO_FOLLOW_THROUGH'
                elif r['low']<=stop:
                    xp=real + rem*pct(stop,entry); xr='SL'
                elif tp1 and r['low']<=entry*(1+params.get('be',0.15)/100):
                    xp=real + rem*params.get('be',0.15); xr='BE_AFTER_TP1'
                elif tp1 and peak_gain>=params['trail_start'] and (peak_gain-pnl)>=params['trail_giveback']:
                    xp=real + rem*pnl; xr='TRAIL'
                elif strategy=='strategy2' and i-entry_i>=3 and ret(rows,i,3)<-params.get('mom_loss_15m',0.3):
                    xp=pnl; xr='MOMENTUM_LOSS_15M'
                elif (not tp1) and r['high']>=entry*(1+params['tp1']/100):
                    tp1=True; real += 0.5*params['tp1']; rem=0.5; stop=max(stop, entry*(1+params.get('be',0.15)/100)); continue
                elif r['high']>=entry*(1+params['tp2']/100):
                    xp=real + rem*params['tp2']; xr='TP2'
                elif i-entry_i>=params['time_stop_bars']:
                    xp=real + rem*pnl; xr='TIME_STOP'
                elif r['close']<r['ema21']:
                    xp=real + rem*pnl; xr='EMA21_EXIT'
                if xr:
                    trades.append({'strategy':strategy,'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'exit_time':r['ts_iso'],'pnl_pct':round(xp,4),'reason':xr,**meta})
                    inpos=False
        if inpos:
            last=rows[-1]
            opens.append({'strategy':strategy,'inst':inst,'entry_time':rows[entry_i]['ts_iso'],'entry_price':entry,'last_price':last['close'],'unrealized_pct':round(pct(last['close'],entry),4),'stop':round(stop,10),**meta})
    return trades, opens

def scan(enriched, watch, candidates):
    best=[]
    for sid, grid in candidates.items():
        keys=list(grid.keys())
        rows=[]
        for vals in itertools.product(*(grid[k] for k in keys)):
            p=dict(zip(keys,vals))
            if p.get('tp2',9)<=p.get('tp1',0): continue
            if p.get('trail_start',9)<p.get('tp1',0): continue
            tr,op=simulate(enriched, watch, sid, p)
            m=metrics(tr,op)
            rows.append((m,p,tr,op))
        rows.sort(key=lambda x: ((x[0]['expectancy_pct'] if x[0]['expectancy_pct'] is not None else -999), (x[0]['profit_factor'] or 0), -(abs(x[0]['max_loss_pct'] or 99)), (x[0]['avg_return_pct'] or -999), x[0]['closed_trades']), reverse=True)
        best.append((sid, rows[0]))
    # Cross-strategy priority keeps the required expectancy/PF ordering inside each scan,
    # but does not let a <8 closed-trade micro-sample outrank a robust candidate.
    best.sort(key=lambda x: (x[1][0]['closed_trades']>=8, (x[1][0]['expectancy_pct'] if x[1][0]['expectancy_pct'] is not None else -999), (x[1][0]['profit_factor'] or 0), x[1][0]['closed_trades']), reverse=True)
    return best

def main():
    con,data,since,max_ts=job.load_data(); enriched,stats=job.summarize(data)
    all_watch=[s['inst'] for s in sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret12'],x['max_vol_ratio']), reverse=True)[:25]]
    start=datetime.fromtimestamp(since/1000,TZ); end=datetime.fromtimestamp(max_ts/1000,TZ)
    s1p={'min_1h':0.25,'min_12h':0.0,'vol_min':1.15,'sl':1.0,'tp1':1.2,'tp2':2.5,'be':0.2,'trail_start':1.8,'trail_giveback':0.8,'time_stop_bars':6,'struct_stop':True}
    s2p={'min_1h':1.4,'min_15m':0.35,'vol_min':1.2,'vol_max':6.0,'nft_bars':2,'nft_min_gain':0.15,'sl':1.1,'tp1':1.0,'tp2':2.2,'be':0.15,'trail_start':1.6,'trail_giveback':0.7,'time_stop_bars':5,'mom_loss_15m':0.35,'struct_stop':False}
    s1tr,s1op=simulate(enriched,all_watch,'strategy1',s1p); s2tr,s2op=simulate(enriched,all_watch,'strategy2',s2p)
    s1m=metrics(s1tr,s1op); s2m=metrics(s2tr,s2op); q1,r1=is_qualified(s1m); q2,r2=is_qualified(s2m)
    grids={
      'strategy3_pullback_after_surge':{'surge_1h':[1.0,1.5,2.0],'vol_max':[3.0,5.0],'sl':[0.8,1.0],'tp1':[0.8,1.0],'tp2':[1.8,2.4],'be':[0.2],'trail_start':[1.6,2.0],'trail_giveback':[0.6,0.9],'time_stop_bars':[4,8],'struct_stop':[True]},
      'strategy4_breakout_confirmation':{'break_vol':[1.4,2.0],'hold_factor':[0.998,1.0],'confirm_gain':[0.0,0.2],'confirm_vol':[0.8,1.1],'min_1h':[0.4,0.9],'sl':[0.8,1.0],'tp1':[0.8,1.0],'tp2':[1.8,2.4],'be':[0.2],'trail_start':[1.6,2.0],'trail_giveback':[0.6,0.9],'time_stop_bars':[4,8],'struct_stop':[True]},
      'strategy6_volume_compression_expansion':{'compress_vr':[0.9,1.1],'range_pct':[1.2,1.8],'expand_vr':[1.4,2.0],'sl':[0.8,1.0],'tp1':[0.8,1.0],'tp2':[1.6,2.2],'be':[0.2],'trail_start':[1.4,1.8],'trail_giveback':[0.6],'time_stop_bars':[4,8],'struct_stop':[True]},
      'strategy7_vwap_reclaim_stability':{'prior_1h':[0.9,1.3],'min_1h':[0.25,0.5],'max_15m':[0.9,1.3],'pullback_buffer':[0.15,0.35],'vol_min':[0.7,0.9],'vol_max':[2.5,4.0],'vwap_lookback':[24],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.4,1.8],'be':[0.12,0.2],'trail_start':[1.0,1.4],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]},
      'strategy8_breakout_retest_only':{'break_vol':[1.2,1.6],'confirm_vol':[0.7,1.0],'min_1h':[0.35,0.7],'max_15m':[1.0,1.5],'retest_tolerance':[0.1,0.25],'hold_margin':[0.0,0.1],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.5,2.0],'be':[0.12,0.2],'trail_start':[1.1,1.5],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]},
      'strategy9_ema9_bounce_low_heat':{'min_1h':[0.4,0.7],'max_1h':[1.8,2.5],'max_15m':[0.7,1.0],'touch_buffer':[0.1,0.25],'ema21_slack':[0.1,0.25],'vol_min':[0.8,1.0],'vol_max':[2.5,4.0],'sl':[0.6,0.8],'tp1':[0.6,0.8],'tp2':[1.4,1.8],'be':[0.12,0.2],'trail_start':[1.0,1.4],'trail_giveback':[0.4,0.6],'time_stop_bars':[4,6],'struct_stop':[True]}
    }
    need_new=(not q1) or (not q2)
    best=scan(enriched,all_watch,grids) if need_new else []
    top_candidate=best[0] if best else None
    now=datetime.now(TZ).isoformat(timespec='seconds')
    old_lab={}
    if os.path.exists(LAB):
        try: old_lab=json.load(open(LAB,encoding='utf-8'))
        except Exception: old_lab={}
    history=old_lab.get('candidates',[])
    cand_records=[]
    rulebook={
      'strategy3_pullback_after_surge':{'entry_rules':'1H曾強漲後，回踩EMA21/VWAP附近不破，下一根收紅重回EMA9與VWAP才進','exit_rules':'SL 0.8~1.0%，TP1半倉，TP2/追蹤出場，時間停損20~45m','risk_rules':'只做回踩確認，不追第一根爆量；單筆紙上風險0.35%~0.5%','filters':'surge_1h、vol_max、防過熱量能','invalid_conditions':'回踩跌破EMA21/VWAP且無收復、BTC/ETH同步急跌','market_state':'強勢輪動但第一波追高勝率差','why_better':'用回踩確認降低strategy2追高後無延續風險'},
      'strategy4_breakout_confirmation':{'entry_rules':'爆量突破後不立刻追，下一根5m守住突破位且續強才進','exit_rules':'SL 0.8~1.0%，TP1半倉，TP2/追蹤出場，時間停損20~45m','risk_rules':'跳空/長上影假突破不進；最大同時3筆','filters':'break_vol、confirm_gain、confirm_vol、min_1h','invalid_conditions':'確認K跌回突破位、量縮且收黑','market_state':'區間突破多但假突破頻繁','why_better':'犧牲部分早段利潤換取較高expectancy與較小假突破損失'},
      'strategy6_volume_compression_expansion':{'entry_rules':'8根5m量縮窄幅整理後，放量突破區間高點且EMA多頭','exit_rules':'較短TP/SL，30m內未走出即退','risk_rules':'不在過大區間後追；避免流動性太薄','filters':'compress_vr、range_pct、expand_vr','invalid_conditions':'突破後跌回整理區間、放量不續強','market_state':'小幣輪動前的低波壓縮','why_better':'避開已過熱幣，尋找壓縮後擴張，理論上盈虧比優於追高'},
      'strategy7_vwap_reclaim_stability':{'entry_rules':'先有1H趨勢，再等回踩VWAP/EMA21附近，下一根收紅同時站回VWAP與EMA9才進','exit_rules':'SL 0.6~0.8%，TP1半倉，較早breakeven，TP2/追蹤出場，20~30m不走即退','risk_rules':'刻意降低進場頻率，只挑回踩後重新轉強；避免急拉追高','filters':'prior_1h、min_1h、max_15m、VWAP reclaim、vol_min/vol_max','invalid_conditions':'跌破VWAP/EMA21無法收復、15m漲幅過熱、量能失控','market_state':'小幣多頭輪動但追高容易被洗掉','why_better':'把大量幣種當機會池，只選回踩確認後進場，目標是提高勝率與降低單筆虧損'},
      'strategy8_breakout_retest_only':{'entry_rules':'前一根放量突破12根高點後不追，下一根回測突破位守住並收紅站回EMA9才進','exit_rules':'SL 0.6~0.8%，TP1半倉，TP2/追蹤出場，20~30m時間停損','risk_rules':'錯過直線噴出也不追，只做突破後回測守住的較穩定型態','filters':'break_vol、confirm_vol、retest_tolerance、hold_margin、max_15m','invalid_conditions':'回測跌回突破位下方、確認K量價不續強','market_state':'假突破多、但突破後回測守住者較有延續性','why_better':'避免strategy1/2常見的第一根追高，改等市場證明突破位有效'},
      'strategy9_ema9_bounce_low_heat':{'entry_rules':'EMA9>=EMA21的溫和趨勢中，前一根回踩EMA9且守住EMA21，下一根收紅重回EMA9才進','exit_rules':'SL 0.6~0.8%，TP1半倉，較緊追蹤與時間停損','risk_rules':'排除1H/15m過熱，專做低熱度續漲回踩，不追垂直K','filters':'min_1h/max_1h、max_15m、touch_buffer、vol_min/vol_max','invalid_conditions':'跌破EMA21、量能過熱或15m已急拉','market_state':'幣種多時不缺機會，選擇低熱度趨勢延續型態','why_better':'勝率優先：接受較小TP與較少進場，換取更小止損與更穩定訊號'}
    }
    for sid,(m,p,tr,op) in best:
        qual,rea=is_qualified(m)
        cand_records.append({'strategy_id':sid,'version':'lab_2026_05_22_12h','status':'testing' if qual else 'candidate','created_at':now,'updated_at':now,'rules':rulebook[sid],'params':p,'metrics':m,'sample_size':m['closed_trades'],'reasoning':rea + '；排序依expectancy > PF > 最大虧損控制 > 平均報酬 > 勝率','next_test':'下一輪12H以同參數紙上觀察，若連續2輪優於strategy1/2且樣本>=8，標記建議升級正式strategy3。'} )
    lab={'updated_at':now,'data_window':{'start':start.isoformat(timespec='minutes'),'end':end.isoformat(timespec='minutes'),'inst_count':len(enriched)},'formal_strategies':{'strategy1':{'params':s1p,'metrics':s1m,'qualified':q1,'reason':r1},'strategy2':{'params':s2p,'metrics':s2m,'qualified':q2,'reason':r2}},'candidates':cand_records + history[:20]}
    os.makedirs('data',exist_ok=True); json.dump(lab,open(LAB,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
    watch=[s['inst'] for s in sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret1'],x['ret12']), reverse=True)[:10]]
    state={'updated_at':now,'strategy1':{'params':s1p,'metrics':s1m,'qualified':q1,'reason':r1},'strategy2':{'params':s2p,'metrics':s2m,'qualified':q2,'reason':r2},'new_strategy_candidates':cand_records[:3],'last_12h_metrics':{'strategy1':s1m,'strategy2':s2m,'best_candidate':cand_records[0] if cand_records else None},'candidate_params':{c['strategy_id']:c['params'] for c in cand_records[:3]},'watchlist':watch,'open_paper_trades':s1op+s2op+(top_candidate[1][3] if top_candidate else []),'risk_notes':['紙上/模擬研究，非真實下單','小幣滑價暫以來回0.16%估算，若流動性惡化需提高成本','任一策略樣本<8不得宣稱合格','BTC/ETH 5m同步轉弱時取消突破追價']}
    json.dump(state,open(STATE,'w',encoding='utf-8'),ensure_ascii=False,indent=2)
    strong=sorted(stats,key=lambda x:(x['top10_1h_count'],x['ret12']), reverse=True)[:6]
    title='OKX 小幣 strategy lab 12H 優化報告（晚上9點）' if datetime.now(TZ).hour>=12 else 'OKX 小幣 strategy lab 12H 優化報告（早上9點）'
    def ml(m):
        return f"進場{m['entries']} / 平倉{m['closed_trades']}；勝率{m['win_rate_pct'] if m['win_rate_pct'] is not None else 'N/A'}%；均報酬{m['avg_return_pct'] if m['avg_return_pct'] is not None else 'N/A'}%；均獲利{m['avg_win_pct']}%；均虧損{m['avg_loss_pct']}%；Expectancy {m['expectancy_pct'] if m['expectancy_pct'] is not None else 'N/A'}%；PF {m['profit_factor'] if m['profit_factor'] is not None else 'N/A'}；最大單筆虧損{m['max_loss_pct'] if m['max_loss_pct'] is not None else 'N/A'}%；未平倉{m['open_trades']}；Exit {m['exit_reasons']}"
    def coinline(s): return f"{s['inst'].replace('-USDT','')} 12H{s['ret12']:+.1f}%/1H{s['ret1']:+.1f}%/Top10 {s['top10_1h_count']}次/VR峰{s['max_vol_ratio']:.1f}x"
    report=[]
    report.append(title)
    report.append('')
    report.append(f"資料時間範圍：{start.strftime('%m/%d %H:%M')}～{end.strftime('%m/%d %H:%M')}（OKX現貨USDT小幣5m；可用幣種{len(enriched)}，不足時已用OKX公開API補抓）")
    report.append('')
    report.append('strategy1（MA Stack / Volume / Breakout）')
    report.append('- '+ml(s1m))
    report.append(f"- 判定：{'合格' if q1 else '不合格'}；{r1}")
    report.append('')
    report.append('strategy2（Surge Momentum）')
    report.append('- '+ml(s2m))
    report.append(f"- 判定：{'合格' if q2 else '不合格'}；{r2}")
    if need_new:
        report.append('')
        report.append('新策略設計模式：已回測候選（bounded scan，排序：expectancy > PF > 最大虧損控制 > 平均報酬 > 勝率）')
        for c in cand_records[:3]:
            m=c['metrics']; q,rea=is_qualified(m)
            report.append(f"- {c['strategy_id']}：{ml(m)}；狀態 {c['status']}；最佳參數 {c['params']}")
            report.append(f"  規則：{c['rules']['entry_rules']}；失效：{c['rules']['invalid_conditions']}；為何可能優於1/2：{c['rules']['why_better']}")
        if cand_records and is_qualified(cand_records[0]['metrics'])[0] and cand_records[0]['metrics']['expectancy_pct'] > max([x for x in [s1m.get('expectancy_pct'),s2m.get('expectancy_pct')] if x is not None] or [-999]):
            report.append(f"- 標記：{cand_records[0]['strategy_id']} 本輪優於正式策略；需再連續觀察，不直接改production。")
    report.append('')
    report.append('下一輪觀察幣種與條件')
    report.append('- 強勢/輪動名單：'+'；'.join(coinline(s) for s in strong))
    report.append('- Watchlist：'+(', '.join(w.replace('-USDT','') for w in watch) if watch else '暫無'))
    report.append('- strategy1只做EMA9>EMA21、1H>+0.25%、收盤突破12根高點且VR>=1.15；長上影突破取消。')
    report.append('- strategy2只做1H>+1.4%、15m>+0.35%、VR 1.2~6.0；10分鐘無+0.15% follow-through即退。')
    if cand_records:
        bestc=cand_records[0]
        report.append(f"- 候選優先觀察：{bestc['strategy_id']}，依最佳參數紙上跑；若下一輪仍PF>1.2且expectancy>0，再評估升級。")
    report.append('')
    report.append('是否建議修改正式參數/新增正式策略')
    if cand_records and is_qualified(cand_records[0]['metrics'])[0]:
        report.append(f"- 建議：暫不改production；將 {cand_records[0]['strategy_id']} 列為testing。若連續2輪明顯優於strategy1/2，建議升級為正式strategy3。")
    else:
        report.append('- 建議：暫不修改正式參數；目前以樣本與PF/expectancy驗證為先。')
    report.append('')
    report.append('風險提醒')
    report.append('- 本報告為模擬/紙上策略研究，不代表真實下單。小幣插針、滑價與成交深度會使實際結果劣於回測。樣本不足時不宣稱合格；若BTC/ETH 5m同步轉弱，所有突破/追高訊號降級或取消。')
    print('\n'.join(report))
    con.close()
if __name__=='__main__': main()
