import pdfplumber
import re
from collections import defaultdict

code_pat = re.compile(r"^[A-Z]\d{5}$")
subjects = set("化学生地政")


def clean_req(cell):
    s = str(cell).replace("\n", "").strip()
    s = re.sub(r"[^化学生地政或和]", "", s)
    if not s or "不限" in s:
        return "不限"
    parts = re.split(r"[或和]", s)
    chars = sorted({p for p in parts if p in subjects})
    return "与".join(chars) if chars else "不限"


def extract(path):
    groups = []
    with pdfplumber.open(path) as pdf:
        for p in pdf.pages:
            for t in p.extract_tables():
                for raw in t[2:]:
                    cells = [str(c).replace("\n", "").strip() if c is not None else "" for c in raw]
                    code_idx = None
                    for i, c in enumerate(cells):
                        if code_pat.match(c):
                            code_idx = i
                            break
                    if code_idx is None:
                        continue
                    code = cells[code_idx]
                    name = ""
                    for c in cells[code_idx + 1 :]:
                        if "第" in c and "组" in c:
                            name = c
                            break
                    if not name:
                        continue
                    req = ""
                    score = ""
                    for i, c in enumerate(cells[code_idx + 1 :], start=code_idx + 1):
                        digits = re.sub(r"[^0-9]", "", c)
                        if re.fullmatch(r"\d{3}", digits) and 100 <= int(digits) <= 800:
                            req = cells[i - 1] if i - 1 >= 0 else ""
                            score = digits
                            break
                    req = clean_req(req)
                    school = name.split("第")[0] if "第" in name else name
                    groups.append((code, name, req, score, school))
    return groups


phys = extract(".tmp_data/2025_physics.pdf")
hist = extract(".tmp_data/2025_history.pdf")
print("phys groups", len(phys), "hist", len(hist))
cnt = defaultdict(int)
for code, name, req, score, school in phys + hist:
    cnt[(school, req)] += 1
multi = [k for k, v in cnt.items() if v > 1]
print("school+req combos total", len(cnt), "multi", len(multi))
print("top multi")
for k in sorted(multi, key=lambda x: cnt[x], reverse=True)[:20]:
    print(k, cnt[k])
