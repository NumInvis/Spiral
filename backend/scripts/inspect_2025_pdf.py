import pdfplumber, os
base = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), '.tmp_data')
for fn in ['2025_physics.pdf','2025_history.pdf']:
    print('\n===', fn, '===')
    with pdfplumber.open(os.path.join(base, fn)) as pdf:
        for i, page in enumerate(pdf.pages[:2]):
            print('--- page', i, '---')
            tables = page.extract_tables()
            for ti, t in enumerate(tables[:2]):
                print('table', ti, 'rows', len(t), 'cols', len(t[0]) if t else 0)
                for r in t[:6]:
                    print(r)
