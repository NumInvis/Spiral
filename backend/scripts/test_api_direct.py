import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ['WINCODE_API_KEY'] = 'sk-HkWZiubZ34Fl2fIwZrULIpqWQtO0UUG1AzEKmlKpPmYYRQLg'
os.environ['SPIRAL_SKIP_RAG_SEED'] = '1'
from fastapi.testclient import TestClient
from main import app
client = TestClient(app)
r = client.post('/api/recommendations/from-text', json={'text':'湖北物理类考生，位次15000，想学计算机，想去武汉','rank':15000,'province':'湖北'}, timeout=200)
print('status', r.status_code)
print(r.text[:2000])
