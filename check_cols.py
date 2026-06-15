import sqlite3
con = sqlite3.connect('data/okx_micro_5m_tracking.sqlite')
con.row_factory = sqlite3.Row
row = con.execute('SELECT * FROM top10_1h_training_dataset LIMIT 1').fetchone()
print('Columns in top10_1h_training_dataset:')
for k in row.keys():
    print(f'  {k}')

# Also check the session table for entry-time snapshot data
row2 = con.execute('SELECT * FROM top10_1h_training_sessions LIMIT 1').fetchone()
print('\nColumns in top10_1h_training_sessions:')
for k in row2.keys():
    print(f'  {k}')

con.close()