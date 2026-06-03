import json
from datetime import datetime, timezone
from pathlib import Path

TOP10_RENDER_STRATEGY_IDS = [
    "top10v1_rank5_chg3_10_sl1_trail09_t12",
    "top10v2_rank5_chg3_10_sl1_trail09_t18",
    "top10v3_rank5_chg3_10_sl08_trail09_t12",
    "top10v4_rank5_chg3_10_sl08_trail09_t18",
    "top10v5_delay1_rank3_chg1_5_sl15_trail12_t12",
]
TOP10_OKX_LIVE_STRATEGY_ID = "top10v1_rank5_chg3_10_sl1_trail09_t12"


def _rnd(value, digits=4):
    try:
        return round(float(value), digits)
    except Exception:
        return 0


TOP10_OPTIMIZER_SNAPSHOT = {
    "dataset": {
        "sessions": 1874,
        "closedSessions": 1864,
        "activeSessions": 10,
        "instruments": 193,
        "minTs": "2026-05-31T21:30+08:00",
        "maxTs": "2026-06-03T18:15+08:00",
        "roundTripCostPct": 0.16,
    },
    "strategies": [
        {"strategy": "top10v1_rank5_chg3_10_sl1_trail09_t12", "optimizerName": "delay0_rank5_chg3-10 + sl1.0_be0.6_trail0.9x0.4_t12", "entries": 103, "closedTrades": 103, "wins": 50, "losses": 53, "winRate": 48.54, "netAvgReturnPct": 0.4253, "profitFactor": 2.03, "maxLossPct": -1.16},
        {"strategy": "top10v2_rank5_chg3_10_sl1_trail09_t18", "optimizerName": "delay0_rank5_chg3-10 + sl1.0_be0.6_trail0.9x0.4_t18", "entries": 103, "closedTrades": 103, "wins": 50, "losses": 53, "winRate": 48.54, "netAvgReturnPct": 0.4253, "profitFactor": 2.03, "maxLossPct": -1.16},
        {"strategy": "top10v3_rank5_chg3_10_sl08_trail09_t12", "optimizerName": "delay0_rank5_chg3-10 + sl0.8_be0.6_trail0.9x0.4_t12", "entries": 103, "closedTrades": 103, "wins": 49, "losses": 54, "winRate": 47.57, "netAvgReturnPct": 0.4247, "profitFactor": 2.11, "maxLossPct": -0.96},
        {"strategy": "top10v4_rank5_chg3_10_sl08_trail09_t18", "optimizerName": "delay0_rank5_chg3-10 + sl0.8_be0.6_trail0.9x0.4_t18", "entries": 103, "closedTrades": 103, "wins": 49, "losses": 54, "winRate": 47.57, "netAvgReturnPct": 0.4247, "profitFactor": 2.11, "maxLossPct": -0.96},
        {"strategy": "top10v5_delay1_rank3_chg1_5_sl15_trail12_t12", "optimizerName": "delay1_rank3_chg1-5 + sl1.5_be0.8_trail1.2x0.6_t12", "entries": 104, "closedTrades": 104, "wins": 55, "losses": 49, "winRate": 52.88, "netAvgReturnPct": 0.4207, "profitFactor": 2.23, "maxLossPct": -1.66},
    ],
}


def load_top10_optimizer_snapshot():
    path = Path("data/top10_1h_optimizer_latest_min100.json")
    strategies = [dict(row) for row in TOP10_OPTIMIZER_SNAPSHOT["strategies"]]
    dataset = dict(TOP10_OPTIMIZER_SNAPSHOT["dataset"])
    source = "embedded_snapshot"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            source = str(path)
            stats = data.get("db_stats") or {}
            dataset.update({
                "sessions": stats.get("sessions", dataset.get("sessions")),
                "closedSessions": stats.get("closed_sessions", dataset.get("closedSessions")),
                "activeSessions": stats.get("active_sessions", dataset.get("activeSessions")),
                "instruments": stats.get("insts", dataset.get("instruments")),
                "minTs": stats.get("min_ts_iso", dataset.get("minTs")),
                "maxTs": stats.get("max_ts_iso", dataset.get("maxTs")),
                "roundTripCostPct": data.get("round_trip_cost_pct", dataset.get("roundTripCostPct")),
            })
            parsed = []
            for idx, row in enumerate((data.get("top") or [])[:5]):
                entry = row.get("entry") or {}
                exit_cfg = row.get("exit") or {}
                parsed.append({
                    "strategy": TOP10_RENDER_STRATEGY_IDS[idx] if idx < len(TOP10_RENDER_STRATEGY_IDS) else f"top10v{idx+1}",
                    "optimizerName": f"{entry.get('name')} + {exit_cfg.get('name')}",
                    "entries": int(row.get("entries") or 0),
                    "closedTrades": int(row.get("closed_trades") or 0),
                    "wins": int(row.get("wins") or 0),
                    "losses": int(row.get("losses") or 0),
                    "winRate": _rnd(row.get("win_rate")),
                    "netAvgReturnPct": _rnd(row.get("net_avg_return")),
                    "profitFactor": _rnd(row.get("profit_factor")),
                    "maxLossPct": _rnd(row.get("max_loss")),
                })
            if parsed:
                strategies = parsed
        except Exception:
            source = "embedded_snapshot_fallback"
    return {"dataset": dataset, "strategies": strategies, "source": source}


def summarize_top10_render_performance(config, performance12h):
    rows_by_strategy = {row.get("strategy"): row for row in (performance12h.get("byStrategy") or [])}
    current_rows = {row.get("strategy"): row for row in ((performance12h.get("current") or {}).get("rows") or [])}
    active = set(config.get("microActiveStrategies") or [])
    out = []
    for strategy in TOP10_RENDER_STRATEGY_IDS:
        hist = rows_by_strategy.get(strategy, {})
        cur = current_rows.get(strategy, {})
        out.append({
            "strategy": strategy,
            "deployed": strategy in active,
            "currentEntries": int(cur.get("entries") or 0),
            "currentClosedTrades": int(cur.get("closedTrades") or 0),
            "currentOpenTrades": int(cur.get("openTrades") or 0),
            "currentRealizedPnl": _rnd(cur.get("realizedPnl")),
            "currentWinRate": _rnd(cur.get("winRate")),
            "currentAvgRoePct": _rnd(cur.get("avgPnlRoePct")),
            "closedTrades": int(hist.get("closedTrades") or 0),
            "realizedPnl": _rnd(hist.get("realizedPnl")),
            "cumulativeReturnPct": _rnd(hist.get("cumulativeReturnPct")),
            "annualizedReturnPct": _rnd(hist.get("annualizedReturnPct")),
            "elapsedDays": _rnd(hist.get("elapsedDays")),
            "windows": hist.get("windows") or [],
        })
    return out


async def top10_strategy_overview_payload(*, crypto_bot, config, okx_live_performance_payload):
    optimizer = load_top10_optimizer_snapshot()
    performance12h = await crypto_bot.refresh_micro_strategy_performance_12h()
    okx = await okx_live_performance_payload()
    okx_strategy = next((row for row in (okx.get("byStrategy") or []) if row.get("strategy") == TOP10_OKX_LIVE_STRATEGY_ID), None)
    if okx_strategy is None:
        okx_strategy = {"strategy": TOP10_OKX_LIVE_STRATEGY_ID, "closedTrades": 0, "wins": 0, "losses": 0, "winRate": 0, "pnlUsd": 0, "pnlPct": 0}
    return {
        "updatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "top10StrategyCount": len(optimizer.get("strategies") or []),
        "optimizer": optimizer,
        "render": {
            "deployedStrategies": list(config.get("microActiveStrategies") or []),
            "top10DeployedCount": sum(1 for s in config.get("microActiveStrategies", []) if s in TOP10_RENDER_STRATEGY_IDS),
            "lastRunAt": crypto_bot.micro_last_run_at,
            "lastError": crypto_bot.micro_last_error,
            "performance12hCurrent": performance12h.get("current"),
            "strategies": summarize_top10_render_performance(config, performance12h),
        },
        "okxLive": {
            "strategy": TOP10_OKX_LIVE_STRATEGY_ID,
            "summary": okx.get("summary") or {},
            "strategyPerformance": okx_strategy,
            "openPositions": okx.get("openPositions") or [],
            "closedTrades": okx.get("closedTrades") or [],
            "events": okx.get("events") or [],
            "account": okx.get("account") or {},
            "positionsHistory": okx.get("positionsHistory") or {},
            "logGlob": okx.get("logGlob"),
            "stateGlob": okx.get("stateGlob"),
        },
    }


TOP10_STRATEGY_OVERVIEW_HTML = """<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>1H Top10 Strategy Overview</title>
<style>body{margin:0;background:#f6f7f4;color:#19211f;font-family:Inter,Segoe UI,Arial,sans-serif}.top{display:flex;justify-content:space-between;gap:16px;padding:22px 28px;background:#fffefa;border-bottom:1px solid #dce3df;position:sticky;top:0;z-index:2}.controls{display:flex;gap:8px;flex-wrap:wrap}a.btn,button{border:1px solid #dce3df;border-radius:8px;background:#fff;padding:0 12px;height:40px;font-weight:800;cursor:pointer;color:#19211f;text-decoration:none;display:inline-flex;align-items:center}main{max-width:1360px;margin:auto;padding:24px}.grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}.metric,.panel{background:#fff;border:1px solid #dce3df;border-radius:8px;box-shadow:0 12px 32px rgba(31,45,42,.08)}.metric{padding:16px}.metric span,.label{display:block;color:#65706e;font-size:12px;text-transform:uppercase}.metric strong{display:block;margin-top:10px;font-size:24px}.panel{padding:18px;margin:16px 0 22px;overflow-x:auto}.good{color:#16835f}.bad{color:#c53b3b}.muted{color:#65706e}.pill{display:inline-flex;border:1px solid #dce3df;border-radius:999px;padding:4px 9px;background:#fbfcfb;font-size:12px;font-weight:800}table{width:100%;min-width:1050px;border-collapse:collapse;font-size:13px}th{text-align:left;color:#65706e;background:#f8faf8;padding:9px;border-bottom:1px solid #dce3df}td{padding:9px;border-bottom:1px solid #eef2ef;vertical-align:top}tr:hover td{background:#fbfcfb}.note{line-height:1.6;color:#46514f}.warn{border-left:4px solid #d59b23;padding:10px 12px;background:#fff9ec}@media(max-width:900px){.grid{grid-template-columns:1fr 1fr}}@media(max-width:620px){.grid{grid-template-columns:1fr}.top{align-items:flex-start;flex-direction:column}}</style></head>
<body><header class="top"><div><h1>1H Top10 策略總覽</h1><p id="status">Loading...</p></div><div class="controls"><button id="refresh">Refresh</button><a class="btn" href="/micro">Micro</a><a class="btn" href="/okx-live">OKX Live</a><a class="btn" href="/crypto">Strategy Lab</a></div></header><main><section class="grid"><div class="metric"><span>根據 1H Top10 選出的策略數</span><strong id="allCount">--</strong></div><div class="metric"><span>Render 已上線 Top10 策略</span><strong id="renderCount">--</strong></div><div class="metric"><span>OKX 實盤策略</span><strong id="okxStrategy">--</strong></div><div class="metric"><span>OKX Live P/L</span><strong id="okxPnl">--</strong></div></section><section class="panel"><h2>目前策略分層</h2><p class="note">這頁回答三件事：① 目前根據 1HR Top10 研發/挑出的策略有幾個、回測績效如何；② 推上 Render paper/shadow 監測的是哪些、目前績效如何；③ 真正放上 OKX 實盤的是哪個策略、目前績效如何。</p><p class="warn">注意：optimizer 小樣本結果是研究排名；Render paper/shadow 與 OKX live 才是後續實際監測績效。</p></section><section class="panel"><h2>1HR Top10 策略池 / Optimizer 回測排名</h2><p id="optimizerMeta" class="muted"></p><div id="optimizer"></div></section><section class="panel"><h2>Render 已推上線的 Top10 paper/shadow 策略績效</h2><p id="renderMeta" class="muted"></p><div id="render"></div></section><section class="panel"><h2>OKX 真錢實盤策略與績效</h2><p id="okxMeta" class="muted"></p><div id="okx"></div></section><section class="panel"><h2>OKX 目前未平倉與 hard stop</h2><div id="positions"></div></section></main>
<script>
const $=s=>document.querySelector(s);$("#refresh").onclick=()=>load();setInterval(load,15000);load();
async function load(){try{const d=await (await fetch('/api/crypto/top10-strategies/overview')).json();render(d);}catch(e){$("#status").textContent='Load failed: '+e;}}
function render(d){const opt=d.optimizer||{}, ds=opt.dataset||{}, ren=d.render||{}, ok=d.okxLive||{}, sum=ok.summary||{}, strat=ok.strategyPerformance||{};$("#status").textContent=`Updated ${d.updatedAt?new Date(d.updatedAt).toLocaleString():'--'} · Render ${ren.lastRunAt?new Date(ren.lastRunAt).toLocaleString():'not run yet'}${ren.lastError?' · error '+ren.lastError:''}`;$("#allCount").textContent=d.top10StrategyCount||0;$("#renderCount").textContent=`${ren.top10DeployedCount||0} / ${(ren.deployedStrategies||[]).length}`;$("#okxStrategy").textContent=ok.strategy||'--';$("#okxPnl").textContent=`${money(strat.pnlUsd)} / ${pct(strat.pnlPct)}`;$("#okxPnl").className=tone(strat.pnlUsd);$("#optimizerMeta").textContent=`Source ${opt.source||''} · sessions ${ds.sessions||0} / closed ${ds.closedSessions||0} · instruments ${ds.instruments||0} · ${ds.minTs||''} → ${ds.maxTs||''} · round-trip cost ${pct(ds.roundTripCostPct)}`;renderOptimizer(opt.strategies||[]);$("#renderMeta").textContent=`Active strategies: ${(ren.deployedStrategies||[]).join(', ')} · latest 12h window ${(ren.performance12hCurrent||{}).windowStartTaipei||'--'} → ${(ren.performance12hCurrent||{}).windowEndTaipei||'--'}`;renderRender(ren.strategies||[]);$("#okxMeta").textContent=`OKX account ${(ok.account||{}).ok?'OK':'not available'} · ${(ok.account||{}).simulated?'simulated':'real'} · open positions ${sum.openPositions||0} · closed ${strat.closedTrades||0} · logs ${ok.logGlob||''}`;renderOkx(strat,sum);renderPositions(ok.openPositions||[]);}
function renderOptimizer(rows){if(!rows.length){$("#optimizer").innerHTML='<p>No optimizer rows.</p>';return}$("#optimizer").innerHTML=`<table><thead><tr><th>#</th><th>Strategy</th><th>Optimizer config</th><th>Trades</th><th>Win Rate</th><th>Net Avg Return</th><th>PF</th><th>Max Loss</th></tr></thead><tbody>${rows.map((r,i)=>`<tr><td>${i+1}</td><td><strong>${esc(r.strategy)}</strong></td><td>${esc(r.optimizerName||'')}</td><td>${r.closedTrades||0} / ${r.entries||0}<br><span class="label">W ${r.wins||0} / L ${r.losses||0}</span></td><td>${pct(r.winRate)}</td><td class="${tone(r.netAvgReturnPct)}">${pct(r.netAvgReturnPct)}</td><td>${num(r.profitFactor)}</td><td class="bad">${pct(r.maxLossPct)}</td></tr>`).join('')}</tbody></table>`}
function renderRender(rows){if(!rows.length){$("#render").innerHTML='<p>No Render Top10 rows.</p>';return}$("#render").innerHTML=`<table><thead><tr><th>Deployed</th><th>Strategy</th><th>Latest 12h</th><th>All monitored windows</th><th>Realized P/L</th><th>Cumulative Return</th><th>Annualized</th></tr></thead><tbody>${rows.map(r=>`<tr><td>${r.deployed?'<span class="pill good">Render ON</span>':'<span class="pill">off</span>'}</td><td><strong>${esc(r.strategy)}</strong></td><td>entries ${r.currentEntries||0}, closed ${r.currentClosedTrades||0}, open ${r.currentOpenTrades||0}<br><span class="label">win ${pct(r.currentWinRate)} · avg ROE ${pct(r.currentAvgRoePct)}</span></td><td>closed ${r.closedTrades||0}<br><span class="label">days ${num(r.elapsedDays)}</span></td><td class="${tone(r.realizedPnl)}">${money(r.realizedPnl)}</td><td class="${tone(r.cumulativeReturnPct)}">${pct(r.cumulativeReturnPct)}</td><td class="${tone(r.annualizedReturnPct)}">${pct(r.annualizedReturnPct)}</td></tr>`).join('')}</tbody></table>`}
function renderOkx(r,sum){$("#okx").innerHTML=`<table><thead><tr><th>Live Strategy</th><th>Open</th><th>Closed</th><th>Wins/Losses</th><th>Win Rate</th><th>P/L USD</th><th>P/L %</th><th>Hard Stop Coverage</th></tr></thead><tbody><tr><td><strong>${esc(r.strategy||'')}</strong><br><span class="label">only strategy allowed on OKX pilot</span></td><td>${sum.openPositions||0}</td><td>${r.closedTrades||0}</td><td><span class="good">${r.wins||0}</span> / <span class="bad">${r.losses||0}</span></td><td>${pct(r.winRate)}</td><td class="${tone(r.pnlUsd)}">${money(r.pnlUsd)}</td><td class="${tone(r.pnlPct)}">${pct(r.pnlPct)}</td><td>${sum.hardStopProtectedBuys||0} / ${sum.buyEvents||0}</td></tr></tbody></table>`}
function renderPositions(rows){if(!rows.length){$("#positions").innerHTML='<p>No open OKX positions from live log/API.</p>';return}$("#positions").innerHTML=`<table><thead><tr><th>Coin</th><th>Strategy</th><th>Entry Time</th><th>Entry</th><th>Margin</th><th>Size</th><th>Hard Stop</th><th>Reason</th></tr></thead><tbody>${rows.map(r=>`<tr><td><strong>${r.instId}</strong></td><td>${esc(r.strategy)}</td><td>${dt(r.entryTime)}</td><td>${money(r.entryPrice)}</td><td>${money(r.margin)}</td><td>${num(r.sz)}</td><td>${r.hardStopAlgoId?'<span class="pill good">ON</span> '+money(r.hardStopPrice):'<span class="pill bad">missing</span>'}</td><td>${esc(r.entryReason||'')}</td></tr>`).join('')}</tbody></table>`}
function money(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:6})}function num(v){return Number(v||0).toLocaleString(undefined,{maximumFractionDigits:4})}function pct(v){v=Number(v||0);return `${v>=0?'+':''}${v.toFixed(2)}%`}function tone(v){return Number(v)>=0?'good':'bad'}function dt(v){return v?new Date(v).toLocaleString():'--'}function esc(v){return String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
</script></body></html>"""
