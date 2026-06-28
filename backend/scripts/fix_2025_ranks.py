import pandas as pd, os
base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
raw_path = os.path.join(base, 'backend','data','raw_hubei_2024_2025.csv')
pdf_path = os.path.join(base, '.tmp_data','2025_group_lines_from_pdf.csv')
df = pd.read_csv(raw_path, low_memory=False, dtype=str)
pdf = pd.read_csv(pdf_path, low_memory=False, dtype=str)
# map by 专业组代码_2025
pdf_map = pdf.set_index('专业组代码')

def update_row(row):
    code = str(row.get('专业组代码_2025','')).strip()
    if code and code in pdf_map.index:
        row['专业组最低分_2025'] = pdf_map.loc[code, '投档最低分_2025']
        row['专业组最低位次_2025'] = pdf_map.loc[code, '投档最低位次_2025']
    return row

df = df.apply(update_row, axis=1)
out_path = os.path.join(base, 'backend','data','raw_hubei_2024_2025_fixed.csv')
df.to_csv(out_path, index=False, encoding='utf-8-sig')
print('wrote', out_path)
# check sample
print(df[['院校代码','专业组代码','专业组代码_2025','专业组最低分_2025','专业组最低位次_2025']].head(10).to_string())
