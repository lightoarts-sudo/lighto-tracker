import sqlite3
from pathlib import Path
from collections import Counter, defaultdict
import datetime
import matplotlib.pyplot as plt

DB_PATH = (
    Path(r'C:\Users\fuful\OneDrive\Desktop\LIGHTOARTS\_render_lighto_tracker')
    / 'data' / 'okx_micro_5m_tracking.sqlite'
)
conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute(
    """
    SELECT
      inst_id,
      MIN(ts_ms) as first_ts_ms,
      MAX(ts_ms) as last_ts_ms,
      COUNT(*) as candle_count,
      COUNT(DISTINCT DATE(ts_ms/1000, 'unixepoch')) as calendar_days
    FROM candles_5m
    GROUP BY inst_id
    ORDER BY inst_id
    """
).fetchall()
conn.close()

# Buckets in hours
label_bounds = [
    ('< 1h', 0, 1),
    ('1–2h', 1, 2),
    ('2–4h', 2, 4),
    ('4–8h', 4, 8),
    ('8–12h', 8, 12),
    ('12–24h', 12, 24),
    ('24–48h', 24, 48),
    ('48–72h', 48, 72),
    ('72–96h', 72, 96),
    ('96–120h', 96, 120),
    ('120–168h', 120, 168),
    ('168–336h', 168, 336),
    ('> 336h', 336, float('inf')),
]
labels = [lbl for lbl, _, _ in label_bounds]
bucket_counts = Counter()
per_bucket_items = defaultdict(list)

per_coin = []
for r in rows:
    inst_id = r['inst_id']
    duration_h = (r['last_ts_ms'] - r['first_ts_ms']) / 3_600_000
    first_ts = datetime.datetime.fromtimestamp(r['first_ts_ms'] / 1000, tz=datetime.timezone.utc)
    last_ts = datetime.datetime.fromtimestamp(r['last_ts_ms'] / 1000, tz=datetime.timezone.utc)
    item = {
        'inst_id': inst_id,
        'duration_h': duration_h,
        'candles': r['candle_count'],
        'calendar_days': r['calendar_days'],
        'first': first_ts.isoformat(),
        'last': last_ts.isoformat(),
    }
    per_coin.append(item)
    placed = False
    for lbl, lo, hi in label_bounds:
        if lo <= duration_h < hi:
            bucket_counts[lbl] += 1
            per_bucket_items[lbl].append(inst_id)
            placed = True
            break
    if not placed:
        bucket_counts['unknown'] += 1
        per_bucket_items['unknown'].append(inst_id)

out_dir = DB_PATH.parent

print('=== Duration Distribution ===')
for lbl in labels + ['unknown']:
    cnt = bucket_counts.get(lbl, 0)
    ids = per_bucket_items.get(lbl, [])
    if cnt:
        print(f'\n{lbl}: {cnt} coins')
        print('  ids:', ids)

# summary counts
counts = [bucket_counts.get(lbl, 0) for lbl in labels + (['unknown'] if bucket_counts.get('unknown') else [])]
used_labels = labels + (['unknown'] if bucket_counts.get('unknown') else [])

# Plot 1: bar chart of duration buckets
plt.figure(figsize=(12, 5))
bars = plt.bar(used_labels, counts, color='steelblue')
plt.title('Data Duration Distribution per Coin (5m bars)')
plt.xlabel('Duration bucket (hours)')
plt.ylabel('Number of coins')
plt.xticks(rotation=35, ha='right')
for bar, cnt in zip(bars, counts):
    if cnt:
        plt.text(bar.get_x() + bar.get_width() / 2, bar.get_height() + 1, str(cnt), ha='center', va='bottom', fontsize=9)
plt.tight_layout()
bar_path = out_dir / 'data_duration_distribution_bar.png'
plt.savefig(bar_path, dpi=150)
plt.close()

# Plot 2: horizontal bar per coin
per_coin_sorted = sorted(per_coin, key=lambda x: (x['duration_h'], x['inst_id']))
plt.figure(figsize=(10, max(6, len(per_coin_sorted) * 0.07)))
plt.barh([x['inst_id'] for x in per_coin_sorted], [x['duration_h'] for x in per_coin_sorted], color='teal')
plt.xlabel('Duration (hours)')
plt.title('Per-Coin Data Duration (first -> last 5m bar)')
plt.tight_layout()
per_coin_path = out_dir / 'data_duration_per_coin.png'
plt.savefig(per_coin_path, dpi=150)
plt.close()

print('\nSaved:', bar_path)
print('Saved:', per_coin_path)
