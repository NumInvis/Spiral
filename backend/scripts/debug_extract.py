from extract_2025_official import extract_group_lines
from pathlib import Path

rows = extract_group_lines(Path(".tmp_data/2025_physics.pdf"), "物理")
for r in rows[:5]:
    print(r)
