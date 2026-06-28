from main import app
from fastapi.testclient import TestClient

with TestClient(app) as c:
    print('health', c.get('/api/health').json())
    print('schools count', len(c.get('/api/schools', params={'province': '湖北'}).json()))
    p = {
        'name': '测试',
        'province': '湖北',
        'subject_type': '物理',
        'score': 580,
        'rank': 25000,
        'strategy': 'balanced',
    }
    r1 = c.post('/api/profiles', json=p)
    print('profile', r1.status_code)
    pid = r1.json()['id']
    r2 = c.post(f'/api/recommendations/{pid}')
    print('rec status', r2.status_code)
    d = r2.json()
    print('groups', d['total_groups'], '冲', d['冲_count'], '稳', d['稳_count'], '保', d['保_count'])
    print('first rec', d['recommendations'][0]['school_name'], d['recommendations'][0]['level'])
