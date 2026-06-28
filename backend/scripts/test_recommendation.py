import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import SessionLocal, init_db
from models import Profile
from recommendation import build_recommendation

init_db()
db = SessionLocal()
try:
    profile = Profile(
        province="湖北",
        subject_type="物理",
        score=600,
        rank=15000,
        preferred_major="计算机、人工智能、电子信息",
        preferred_city="武汉、北京、上海",
        strategy="balanced",
        accept_adjustment=True,
        allow_special_types=False,
    )
    result = build_recommendation(profile, db)
    print("total groups:", result["total_groups"])
    print("counts:", result["冲_count"], result["稳_count"], result["保_count"])
    print("warnings:", result["warnings"])
    for r in result["recommendations"][:5]:
        print(r.level, r.school_name, r.group_code, r.probability, r.majors[0]["ref_rank"], r.majors[0]["data_confidence"])
finally:
    db.close()
