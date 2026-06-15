import sqlite3
con = sqlite3.connect('data/okx_micro_5m_tracking.sqlite')
con.row_factory = sqlite3.Row

# Check if rankings table has entry-time data we can join
row = con.execute('SELECT * FROM rankings LIMIT 1').fetchone()
print('rankings columns:', list(row.keys()))

# Check if we can join by timestamp
row2 = con.execute('SELECT * FROM top10_1h_training_sessions LIMIT 1').fetchone()
print('sessions entered_ts_ms:', row2['entered_ts_ms'])

# Check if rankings has captured_at or similar
row3 = con.execute('SELECT captured_at FROM rankings LIMIT 1').fetchone()
print('rankings captured_at:', row3['captured_at'])

# Check max_change_1h_pct across bars in same session
rows = con.execute('SELECT bar_index_from_entry, max_change_1h_pct, change_1h_pct FROM top10_1h_training_dataset WHERE session_id=1 ORDER BY bar_index_from_entry').fetchall()
for r in rows:
    print(f"  bar {r['bar_index_from_entry']}: max_chg={r['max_change_1h_pct']:.2f}, cur_chg={r['change_1h_pct']:.2f}")

con.close()