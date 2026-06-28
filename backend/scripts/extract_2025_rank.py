import pdfplumber, csv, os, re

def extract(pdf_path, subject):
    rows = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            for table in tables:
                for tr in table:
                    # tr has 9 cells: score,num,acc, score,num,acc, score,num,acc
                    if not tr or len(tr) < 3:
                        continue
                    for i in range(0, len(tr), 3):
                        score_s = tr[i] if tr[i] else ''
                        num_s = tr[i+1] if i+1 < len(tr) and tr[i+1] else ''
                        acc_s = tr[i+2] if i+2 < len(tr) and tr[i+2] else ''
                        score_s = score_s.strip() if isinstance(score_s, str) else str(score_s)
                        num_s = num_s.strip() if isinstance(num_s, str) else str(num_s)
                        acc_s = acc_s.strip() if isinstance(acc_s, str) else str(acc_s)
                        if not score_s or not num_s or not acc_s:
                            continue
                        # clean noisy characters
                        score_s = re.sub(r'[^0-9\-]', '', score_s)
                        num_s = re.sub(r'[^0-9]', '', num_s)
                        acc_s = re.sub(r'[^0-9]', '', acc_s)
                        if not score_s or not num_s or not acc_s:
                            continue
                        try:
                            score = int(score_s)
                            num = int(num_s)
                            acc = int(acc_s)
                        except Exception:
                            continue
                        rows.append((subject, score, num, acc))
    return rows

def main():
    base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.tmp_data')
    phys = extract(os.path.join(base, '2025_rank_physics.pdf'), '物理')
    hist = extract(os.path.join(base, '2025_rank_history.pdf'), '历史')
    rows = phys + hist
    out = os.path.join(base, '2025_score_rank_from_pdf.csv')
    with open(out, 'w', newline='', encoding='utf-8-sig') as f:
        w = csv.writer(f)
        w.writerow(['科类','分数','人数','累计人数'])
        w.writerows(rows)
    print('wrote', out, 'rows', len(rows))
    # show top/bottom physics
    p = sorted([r for r in rows if r[0]=='物理'], key=lambda x: x[1], reverse=True)
    print('physics top', p[:10])
    print('physics bottom', p[-10:])

if __name__ == '__main__':
    main()
