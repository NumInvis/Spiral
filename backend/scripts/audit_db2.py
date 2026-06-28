import sqlite3, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
conn=sqlite3.connect('gaokao.db')
c=conn.cursor()
print('confidence by year:')
c.execute("SELECT year,data_confidence,COUNT(*) FROM major_scores GROUP BY year,data_confidence")
for r in c.fetchall(): print(r)
print('2025 group_code sample:')
c.execute("""
SELECT s.name, ms.group_code, ms.group_lowest_score, ms.group_lowest_rank, COUNT(*) as cnt
FROM major_scores ms
JOIN majors m ON m.id=ms.major_id
JOIN schools s ON s.id=m.school_id
WHERE ms.year=2025 AND ms.subject_type='物理'
GROUP BY s.id, ms.group_code
ORDER BY ms.group_lowest_rank
LIMIT 20
""")
for r in c.fetchall(): print(r)
print('A001 2025:')
c.execute("""
SELECT s.name, m.name, ms.group_code, ms.group_lowest_score, ms.group_lowest_rank, ms.data_confidence
FROM major_scores ms
JOIN majors m ON m.id=ms.major_id
JOIN schools s ON s.id=m.school_id
WHERE ms.year=2025 AND s.code='A001' AND ms.subject_type='物理'
ORDER BY ms.group_code, m.name
LIMIT 30
""")
for r in c.fetchall(): print(r)
conn.close()
