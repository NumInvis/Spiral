import pandas as pd, os
os.chdir(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
df = pd.read_csv('data/raw_hubei_2024_2025.csv', low_memory=False, dtype=str)
# filter Peking University A001 rows physics
mask = (df['院校代码'].str.startswith('A001')) & (df['科类'] == '物理')
sub = df[mask].copy()
print('rows', len(sub))
print(sub[['院校代码','专业组代码','专业代码','专业名称','录取最低分','录取最低位次','专业组最低分','专业组最低位次','专业组最低分_2025','专业组最低位次_2025','专业组代码_2025']].head(30).to_string())
print('unique raw 院校代码', sub['院校代码'].unique()[:20])
print('unique 专业组代码_2025', sub['专业组代码_2025'].dropna().unique()[:20])
# show duplicate major names within same raw school code
print('duplicate major names count by 院校代码 专业代码')
dup = sub.groupby(['院校代码','专业代码','专业名称']).size().reset_index(name='n').sort_values('n', ascending=False)
print(dup.head(20).to_string())
