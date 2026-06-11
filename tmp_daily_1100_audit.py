import asyncio, json, os, sqlite3, subprocess, sys
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT=Path('.')
LOG=ROOT/'data/okx_top10_live_pilot_log.jsonl'
STATE=ROOT/'data/okx_top10_live_pilot_state.json'
PAUSE=ROOT/'data/okx_top10_live_pilot_paused.flag'
DB=ROOT/'data/okx_micro_5m_tracking.sqlite'

def f(x,n=4):
    try: return round(float(x), n)
    except Exception: return x

def load_log():
    rows=[]
    if LOG.exists():
        for line in LOG.read_text(encoding='utf-8', errors='ignore').splitlines():
            line=line.strip()
            if line:
                try: rows.append(json.loads(line))
                except Exception as e: rows.append({'event':'PARSE_ERROR','error':str(e),'raw':line[:200]})
    return rows

def local_summary(rows):
    buys=[r for r in rows if r.get('event')=='BUY']
    sells=[r for r in rows if r.get('event')=='SELL']
    exch=[r for r in rows if r.get('event')=='EXCHANGE_POSITION_CLOSED']
    starts=[r for r in rows if r.get('event')=='start']
    by_inst=Counter(r.get('instId') for r in buys)
    buy_with_stop=sum(1 for r in buys if r.get('hardStopAlgoId'))
    slip=[float(r.get('slippagePct') or 0) for r in buys]
    spread=[float(r.get('spreadPct') or 0) for r in buys if r.get('spreadPct') is not None]
    buy_slip=[float(r.get('buySlippagePct') or 0) for r in buys if r.get('buySlippagePct') is not None]
    weak=Counter()
    for r in buys:
        sig=r.get('signal') or {}
        if float(sig.get('pct15') or 0) < 0: weak['pct15<0']+=1
        if float(sig.get('pct2h') or 0) < 0: weak['pct2h<0']+=1
        if float(sig.get('pct3h') or 0) < 0: weak['pct3h<0']+=1
        if float(sig.get('volumeRatio') or 0) < 1.2: weak['volumeRatio<1.2']+=1
        if float(r.get('spreadPct') or 0) > 0.12: weak['spread>0.12']+=1
        if abs(float(r.get('buySlippagePct') or 0)) > 0.5: weak['absBuySlip>0.5']+=1
    pnl_by_inst=defaultdict(float)
    for r in sells:
        pnl_by_inst[r.get('instId')]+=float(r.get('realizedPnl') or 0)
    return {
        'total_log_rows':len(rows), 'starts':starts[-3:], 'buy_count':len(buys), 'runner_sell_count':len(sells),
        'exchange_position_closed_count':len(exch), 'buy_hard_stop_coverage': f'{buy_with_stop}/{len(buys)}',
        'avg_buy_fill_slippage_pct': f(sum(slip)/len(slip) if slip else 0),
        'avg_orderbook_buy_slippage_pct': f(sum(buy_slip)/len(buy_slip) if buy_slip else 0),
        'avg_spread_pct': f(sum(spread)/len(spread) if spread else 0),
        'top_repeated_buys': by_inst.most_common(10), 'weak_entry_counts': dict(weak),
        'runner_realized_pnl_sum_excludes_exchange_native_stops': f(sum(float(r.get('realizedPnl') or 0) for r in sells)),
        'runner_best_inst': sorted(pnl_by_inst.items(), key=lambda x:x[1], reverse=True)[:5],
        'runner_worst_inst': sorted(pnl_by_inst.items(), key=lambda x:x[1])[:5],
    }

def db_summary():
    out={}
    con=sqlite3.connect(DB)
    cur=con.cursor()
    for table in ['top10_1h_training_runs','top10_1h_training_rankings','top10_1h_training_sessions','top10_1h_training_candles']:
        try: out[table]=cur.execute(f'select count(*) from {table}').fetchone()[0]
        except Exception as e: out[table]=f'ERR:{e}'
    try: out['runs_range']=cur.execute('select min(captured_at), max(captured_at) from top10_1h_training_runs').fetchone()
    except Exception as e: out['runs_range']=str(e)
    try: out['distinct_instruments']=cur.execute('select count(distinct inst_id) from top10_1h_training_rankings').fetchone()[0]
    except Exception as e: out['distinct_instruments']=str(e)
    try: out['active_sessions']=cur.execute('select count(*) from top10_1h_training_sessions where is_active=1').fetchone()[0]
    except Exception as e: out['active_sessions']=str(e)
    con.close(); return out

def proc_summary():
    cmd='wmic.exe process where "CommandLine like \'%okx_strategy22_live_pilot.py%\'" get ProcessId,CommandLine'
    try:
        p=subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=20)
        lines=[ln.strip() for ln in (p.stdout or '').splitlines() if ln.strip()]
        # filter diagnostic command itself crudely
        matches=[ln for ln in lines if 'okx_strategy22_live_pilot.py' in ln and 'wmic.exe' not in ln]
        return {'exit_code':p.returncode,'matches':matches[:10], 'raw_first_lines':lines[:5]}
    except Exception as e: return {'error':str(e)}

async def okx_private_summary():
    try:
        import httpx
        from okx_strategy22_live_pilot import OkxCredentials, OkxPrivateClient
    except Exception as e:
        return {'blocker':f'import failed: {e}'}
    try:
        creds=OkxCredentials.from_env()
    except Exception as e:
        return {'blocker':f'credentials unavailable: {e}'}
    out={'simulated':creds.simulated}
    async with httpx.AsyncClient(timeout=20) as client:
        oc=OkxPrivateClient(client, creds)
        try:
            pos=await oc.positions()
            out['open_positions']=[r for r in pos.get('data',[]) if abs(float(r.get('pos') or 0))>0]
        except Exception as e: out['positions_blocker']=str(e)
        try:
            alg=await oc.request('GET','/api/v5/trade/orders-algo-pending?ordType=conditional&instType=SWAP')
            out['pending_conditional_algos']=alg.get('data',[])
        except Exception as e: out['pending_algos_blocker']=str(e)
        try:
            hist=await oc.request('GET','/api/v5/account/positions-history?instType=SWAP&limit=100')
            rows=hist.get('data',[])
            # OKX fields vary; use realizedPnl/pnl/fee/fundingFee if present
            pnls=[]; fees=[]; funds=[]; by=defaultdict(float)
            for r in rows:
                pnl=float(r.get('realizedPnl') or r.get('pnl') or 0)
                fee=float(r.get('fee') or 0); fund=float(r.get('fundingFee') or 0)
                pnls.append(pnl); fees.append(fee); funds.append(fund); by[r.get('instId')]+=pnl+fee+fund
            wins=[x for x in pnls if x>0]; losses=[x for x in pnls if x<=0]
            gp=sum(wins); gl=-sum(losses)
            out['positions_history']={'rows':len(rows),'sum_realized_pnl':f(sum(pnls)),'sum_fee':f(sum(fees)),'sum_funding':f(sum(funds)),'net_pnl_fee_funding':f(sum(pnls)+sum(fees)+sum(funds)),'win_rate':f(len(wins)/len(pnls) if pnls else 0),'profit_factor':f(gp/gl if gl else None),'best':sorted(by.items(), key=lambda x:x[1], reverse=True)[:5],'worst':sorted(by.items(), key=lambda x:x[1])[:5]}
        except Exception as e: out['positions_history_blocker']=str(e)
    return out

async def main():
    rows=load_log()
    state=json.loads(STATE.read_text(encoding='utf-8')) if STATE.exists() else {}
    res={'generated_at':datetime.now(timezone.utc).isoformat(), 'pause_flag_exists':PAUSE.exists(), 'pause_text':PAUSE.read_text(encoding='utf-8', errors='ignore')[:500] if PAUSE.exists() else '', 'state':state, 'local_log':local_summary(rows), 'db':db_summary(), 'process':proc_summary(), 'okx_private':await okx_private_summary()}
    print(json.dumps(res, ensure_ascii=False, indent=2))
if __name__=='__main__': asyncio.run(main())
