import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from database import SessionLocal, init_db
from models import Profile
from recommendation import build_recommendation

init_db()
db = SessionLocal()
try:
    profile = Profile(province='湖北', subject_type='物理', score=620, rank=15000, preferred_major='计算机', preferred_city='武汉', risk_preference='balanced', accept_adjustment=True, allow_special_types=False)
    result = build_recommendation(profile, db)
    print('total', result['total_groups'], '冲', result['冲_count'], '稳', result['稳_count'], '保', result['保_count'])
    for g in result['recommendations'][:10]:
        print(g.group_index, g.level, g.school_name, g.group_code, g.probability, g.majors[0]['name'], g.data_confidence, g.reason)
finally:
    db.close()
