import sqlite3
db_path = r"C:/Users/fuful/OneDrive/Desktop/LIGHTOARTS/_render_lighto_tracker/data/okx_micro_5m_tracking.sqlite"
con = sqlite3.connect(db_path)
con.row_factory = sqlite3.Row

# Get all table schemas
tables = con.execute("SELECT name, sql FROM sqlite_master WHERE type='table'").fetchall()
for t in tables:
    print(f"=== {t['name']} ===")
    print(t['sql'])
    print()

# Sample data from main tables
for table in ['top10_1h_training_dataset', 'top10_1h_training_sessions', 'top10_1h_training_candles']:
    try:
        print(f"\n--- Sample from {table} ---")
        rows = con.execute(f"SELECT * FROM {table} LIMIT 3").fetchall()
        for r in rows:
            print(dict(r))
    except Exception as e:
        print(f"Error: {e}")

con.close()