import json
from pathlib import Path
from collections import defaultdict
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
plt.switch_backend('Agg')

root = Path('.').resolve()
latest = root / 'data' / 'strategy_rd_8h_latest.json'
out_heat = root / 'data' / 'cross_strategy_heatmap.png'
out_html = root / 'data' / 'cross_strategy_leaderboard.html'
data = json.loads(latest.read_text(encoding='utf-8'))
candidates = data.get('candidates', [])

rows = []
for c in candidates:
    en = c['entry']['name']
    ex = c['exit']['name']
    rows.append({
        'entry': en,
        'exit': ex,
        'trades': c.get('closed_trades', 0),
        'win_rate': c.get('win_rate', 0.0),
        'net_return': c.get('net_avg_return', 0.0),
        'profit_factor': min(float(c.get('profit_factor', 0.0) or 0.0), 50.0),
        'max_loss': c.get('max_loss', 0.0) or 0.0,
    })

if not rows:
    raise SystemExit('No candidates found in latest report')

df = pd.DataFrame(rows)
pivot = df.pivot_table(index='entry', columns='exit', values='net_return', aggfunc='mean')
plt.figure(figsize=(18, 12))
sns.heatmap(
    pivot,
    cmap='RdYlGn',
    center=0.0,
    linewidths=0.4,
    linecolor='#1b1f24',
    annot=True,
    fmt='.2f',
    cbar_kws={'label': 'Net Avg Return %'},
)
plt.title('Entry × Exit Interaction Heatmap (Net Avg Return %)', pad=14, color='#e6e8eb')
plt.tight_layout()
plt.savefig(out_heat, dpi=180)
plt.close()

best = max(candidates, key=lambda x: (x.get('net_avg_return', 0.0), x.get('closed_trades', 0)) or 0)

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>LIGHTOARTS Cross Strategy Leaderboard</title>
<style>
  body {{ background:#0b0f14; color:#e6e8eb; font-family: Inter, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial, sans-serif; margin: 0; padding: 24px; }}
  header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap; margin-bottom: 18px; }}
  h1 {{ font-size: 20px; margin: 0; }}
  .pill {{ background:#11161d; border:1px solid #232a33; padding: 8px 12px; border-radius: 999px; color:#cfe3ff; font-size: 13px; }}
  select,button {{ background:#11161d; color:#e6e8eb; border:1px solid #232a33; padding: 8px 10px; border-radius: 10px; }}
  table {{ width:100%; border-collapse: collapse; }}
  th, td {{ padding: 10px 8px; text-align:left; border-bottom:1px solid #1c232b; }}
  th {{ color:#8a93a2; font-weight: 600; font-size:12px; letter-spacing:.03em; cursor:pointer; user-select:none; }}
  tr:hover td {{ background:#0f141a; }}
  .good {{ color:#7ee787; }} .bad {{ color:#ff6b6b; }} .muted {{ color:#8a93a2; }}
  .top1 {{ background:#162119; }}
  code {{ background:#0d1117; border:1px solid #232a33; padding:2px 6px; border-radius:6px; color:#cfe3ff; font-size:12px; word-break: break-all; }}
  .summary {{ display:flex; gap:12px; flex-wrap:wrap; margin-bottom: 14px; }}
  .kpi {{ background:#11161d; border:1px solid #232a33; padding:10px 12px; border-radius:12px; min-width:140px; }}
  .kpi b {{ display:block; font-size: 18px; }}
  .kpi span {{ color:#8a93a2; font-size:12px; }}
  img {{ max-width:100%; border:1px solid #232a33; border-radius:12px; background:#0b0f14; }}
  a {{ color:#cfe3ff; }}
</style>
</head>
<body>
<header>
  <div>
    <h1>LIGHTOARTS Cross Strategy Leaderboard</h1>
    <div class="pill">Top1: <code>{best['entry']['name']} / {best['exit']['name']}</code></div>
  </div>
  <div style="display:flex; gap:8px; align-items:center;">
    <label class="pill" for="sort">Sort by</label>
    <select id="sort" onchange="render()">
      <option value="net_return">Net Return</option>
      <option value="win_rate">Win Rate</option>
      <option value="profit_factor">Profit Factor</option>
      <option value="trades">Trades</option>
      <option value="max_loss">Max Loss</option>
    </select>
  </div>
</header>

<div class="summary">
  <div class="kpi"><b>{data['db_stats'].get('sessions', '-')}</b><span>Sessions</span></div>
  <div class="kpi"><b>{data['db_stats'].get('closed_sessions', '-')}</b><span>Closed</span></div>
  <div class="kpi"><b>{data['db_stats'].get('insts', '-')}</b><span>Instruments</span></div>
  <div class="kpi"><b>{data['candidate_count']}</b><span>Candidates</span></div>
  <div class="kpi"><b>{data['db_stats'].get('timeRange', '-')}</b><span>Time range</span></div>
</div>

<section>
  <h2 style="font-size:14px; color:#8a93a2;">Heatmap: Entry × Exit (net return %)</h2>
  <img src="cross_strategy_heatmap.png" alt="heatmap">
</section>

<section style="margin-top:18px;">
  <h2 style="font-size:14px; color:#8a93a2;">Ranked strategies</h2>
  <table id="table">
    <thead>
      <tr>
        <th onclick="sortCol('net_return')">Net%</th>
        <th onclick="sortCol('win_rate')">Win Rate</th>
        <th onclick="sortCol('profit_factor')">PF</th>
        <th onclick="sortCol('trades')">Trades</th>
        <th onclick="sortCol('max_loss')">Max Loss</th>
        <th>Entry</th>
        <th>Exit</th>
      </tr>
    </thead>
    <tbody></tbody>
  </table>
</section>

<script>
  const DATA = {json.dumps(rows, ensure_ascii=False)};
  const BEST_ENTRY = "{best['entry']['name']}";
  const BEST_EXIT = "{best['exit']['name']}";
  let sortKey = 'net_return';
  let asc = false;
  function fmt(n, digits=2) {{
    const v = Number(n);
    if (!Number.isFinite(v)) return '-';
    return v.toFixed(digits);
  }}
  function colorize(val, key) {{
    const v = Number(val);
    if (key === 'max_loss') return v <= -1.0 ? 'bad' : v <= -0.5 ? '' : 'good';
    if (key === 'win_rate') return v >= 70 ? 'good' : v >= 50 ? '' : 'bad';
    if (key === 'profit_factor') return v >= 2 ? 'good' : v >= 1 ? '' : 'bad';
    return '';
  }}
  function render() {{
    const key = document.getElementById('sort').value;
    sortKey = key; asc = false;
    draw();
  }}
  function sortCol(key) {{
    if (sortKey === key) asc = !asc;
    else {{ sortKey = key; asc = false; }}
    draw();
  }}
  function draw() {{
    const tbody = document.querySelector('#table tbody');
    const sorted = DATA.slice().sort((a,b) => {{
      const av = Number(a[sortKey]); const bv = Number(b[sortKey]);
      if (!Number.isFinite(av) && !Number.isFinite(bv)) return 0;
      if (!Number.isFinite(av)) return 1;
      if (!Number.isFinite(bv)) return -1;
      return (av - bv) * (asc ? 1 : -1);
    }});
    tbody.innerHTML = sorted.map((r) => {{
      const top = (r.entry === BEST_ENTRY && r.exit === BEST_EXIT) ? 'top1' : '';
      return `<tr class="${{top}}">
        <td class="${{colorize(r.net_return,'net_return')}}">${{fmt(r.net_return)}}%</td>
        <td class="${{colorize(r.win_rate,'win_rate')}}">${{fmt(r.win_rate,1)}}%</td>
        <td class="${{colorize(r.profit_factor,'profit_factor')}}">${{fmt(r.profit_factor,2)}}</td>
        <td>${{r.trades}}</td>
        <td class="${{colorize(r.max_loss,'max_loss')}}">${{fmt(r.max_loss,3)}}%</td>
        <td><code>${{r.entry}}</code></td>
        <td><code>${{r.exit}}</code></td>
      </tr>`;
    }}).join('');
  }}
  draw();
</script>
</body>
</html>
"""
out_html.write_text(html, encoding='utf-8')
print('saved', out_heat)
print('saved', out_html)
