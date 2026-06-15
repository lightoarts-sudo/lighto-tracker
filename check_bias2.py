import sqlite3
con = sqlite3.connect('data/okx_micro_5m_tracking.sqlite')
con.row_factory = sqlite3.Row

# Check max_change_1h_pct across bars in same session
rows = con.execute('SELECT bar_index_from_entry, max_change_1h_pct, change_1h_pct FROM top10_1h_training_dataset WHERE session_id=1 ORDER BY bar_index_from_entry').fetchall()
for r in rows:
    print(f"  bar {r['bar_index_from_entry']}: max_chg={r['max_change_1h_pct']:.2f}, cur_chg={r['change_1h_pct']:.2f}")

# Check training_rankings for join keys
row = con.execute('SELECT * FROM top10_1h_training_rankings LIMIT 1').fetchone()
print('\ntop10_1h_training_rankings columns:', list(row.keys()))

# Can we join sessions to rankings via run_id?
row2 = con.execute('SELECT * FROM top10_1h_training_runs LIMIT 1').fetchone()
print('\ntop10_1h_training_runs columns:', list(row2.keys()))

con.close()