import sqlite3, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
conn = sqlite3.connect('gaokao.db')
c = conn.cursor()
c.execute("SELECT name FROM sqlite_master WHERE type='table'")
print('tables:', [r[0] for r in c.fetchall()])
c.execute("SELECT COUNT(*) FROM major_scores")
print('major_scores', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM schools")
print('schools', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM majors")
print('majors', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM admission_plans")
print('admission_plans', c.fetchone()[0])
c.execute("SELECT COUNT(*) FROM rank_tables")
print('rank_tables', c.fetchone()[0])
print('confidence by year:')
c.execute("SELECT year, data_confidence, COUNT(*) FROM major_scores GROUP BY year, data_confidence")
for r in c.fetchall(): print(r)
print('sample A001 physics:')
c.execute("""
SELECT s.name, m.name, ms.year, ms.lowest_score, ms.lowest_rank,
       ms.group_lowest_score, ms.group_lowest_rank, ms.data_confidence, ms.data_source
FROM major_scores ms
JOIN majors m ON m.id = ms.major_id
JOIN schools s ON s.id = m.school_id
WHERE s.code = 'A001' AND ms.subject_type = '物理'
ORDER BY ms.year DESC, m.name
LIMIT 20
""")
for r in c.fetchall(): print(r)
conn.close()
