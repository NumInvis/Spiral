import pandas as pd, os
base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
df = pd.read_csv(os.path.join(base,'backend','data','raw_hubei_2024_2025.csv'), low_memory=False, dtype=str)
# show distinct 专业组代码_2025 per school code prefix
sub = df[['院校代码','专业组代码','专业组代码_2025','院校名称']].dropna(subset=['专业组代码_2025'])
print('unique 2025 groups count', sub['专业组代码_2025'].nunique())
print(sub[sub['院校代码'].str.startswith('A003')].drop_duplicates().head(20).to_string())
print('sample A001')
print(sub[sub['院校代码'].str.startswith('A001')].drop_duplicates().to_string())
