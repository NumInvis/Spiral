import pdfplumber, csv, os, re

BASE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.tmp_data')

def load_rank_table():
    ranks = {}
    path = os.path.join(BASE, '2025_score_rank_from_pdf.csv')
    with open(path, 'r', encoding='utf-8-sig') as f:
        reader = csv.DictReader(f)
        for r in reader:
            subj = r['科类'].strip()
            score = int(r['分数'])
            acc = int(r['累计人数'])
            ranks.setdefault(subj, {})[score] = acc
    return ranks

RANKS = load_rank_table()

def extract_groups(pdf_path, subject):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for t in tables:
                for r in t:
                    if not r or len(r) < 4:
                        continue
                    code = (r[0] or '').strip().replace('\n','')
                    name = (r[1] or '').strip().replace('\n','') if len(r) > 1 else ''
                    req = (r[2] or '').strip().replace('\n','') if len(r) > 2 else ''
                    score_s = (r[3] or '').strip().replace('\n','') if len(r) > 3 else ''
                    note = (r[-1] or '').strip().replace('\n','') if len(r) > 11 else ''
                    if not code or not re.match(r'^[A-Z]\d{5}$', code):
                        continue
                    score_s = re.sub(r'[^0-9]', '', score_s)
                    if not score_s:
                        continue
                    try:
                        score = int(score_s)
                    except Exception:
                        continue
                    rank = RANKS.get(subject, {}).get(score)
                    rows.append({
                        '科类': subject,
                        '专业组代码': code,
                        '专业组名称': name,
                        '选科限制': req,
                        '投档最低分_2025': score,
                        '投档最低位次_2025': rank,
                        '备注': note,
                    })
    return rows

def main():
    phys = extract_groups(os.path.join(BASE, '2025_physics.pdf'), '物理')
    hist = extract_groups(os.path.join(BASE, '2025_history.pdf'), '历史')
    all_rows = phys + hist
    out = os.path.join(BASE, '2025_group_lines_from_pdf.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.DictWriter(f, fieldnames=['科类','专业组代码','专业组名称','选科限制','投档最低分_2025','投档最低位次_2025','备注'])
        w.writeheader()
        w.writerows(all_rows)
    print('wrote', out, 'rows', len(all_rows))
    # compare with old
    old_path = os.path.join(BASE, '2025_group_ranks.csv')
    if os.path.exists(old_path):
        with open(old_path, 'r', encoding='utf-8-sig') as f:
            old = {r['专业组代码']: r for r in csv.DictReader(f)}
        new_map = {r['专业组代码']: r for r in all_rows}
        mism = []
        for code, r in new_map.items():
            o = old.get(code)
            if not o:
                mism.append(('missing_old', code, r))
                continue
            if int(r['投档最低分_2025']) != int(o['投档最低分_2025']):
                mism.append(('score_diff', code, r, o))
            if (r['投档最低位次_2025'] is None) != (o['投档最低位次_2025'] in (None,'')):
                pass
            elif r['投档最低位次_2025'] is not None and o['投档最低位次_2025'] not in (None,'') and int(r['投档最低位次_2025']) != int(o['投档最低位次_2025']):
                mism.append(('rank_diff', code, r, o))
        print('mismatches', len(mism))
        for m in mism[:20]:
            print(m)

if __name__ == '__main__':
    main()
