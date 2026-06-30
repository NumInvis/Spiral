# Spiral 开发环境配置与启动指南

## 1. 环境依赖

- **Python 3.13+**（项目使用 Python 3.13 语法特性）
- **Node.js 20+**（前端使用 Vite + React 19）
- **Git**（已使用）

> ⚠️ 当前检测到系统未安装 Python 与 Node.js，请先安装后再执行后续步骤。

## 2. 快速启动（推荐）

项目已提供一键启动脚本，配置好 API Key 后：

```powershell
cd D:\Spiral
.\start.ps1
```

或在 CMD 中：

```cmd
cd D:\Spiral
start.bat
```

脚本会自动：
1. 检测 Python / Node 环境
2. 创建并激活 Python 虚拟环境（`backend\venv`）
3. 安装 Python 依赖（`requirements.txt`）
4. 首次运行初始化 SQLite 数据库（`gaokao.db`）
5. 安装前端 npm 依赖（`node_modules`）
6. 分别启动后端（端口 11678）和前端（端口 1678）

## 3. 手动启动（调试/开发）

### 后端

```powershell
cd D:\Spiral\backend

# 创建虚拟环境（首次）
python -m venv venv

# 激活
.\venv\Scripts\activate

# 安装依赖
python -m pip install -r requirements.txt

# 配置 LLM（必须，否则自由文本接口报错）
$env:WINCODE_API_KEY="sk-xxx"

# 初始化数据库（首次）
$env:SPIRAL_SKIP_RAG_SEED=1
python seed_data.py

# 启动
python main.py
```

后端地址：http://localhost:11678/docs

### 前端

```powershell
cd D:\Spiral\frontend
npm install
npm run dev
```

前端地址：http://localhost:1678

## 4. 关键配置说明

| 变量 | 说明 | 是否必填 |
|------|------|----------|
| `WINCODE_API_KEY` | WinCode / OpenAI 兼容 API Key | **是**（自由文本入口） |
| `WINCODE_BASE_URL` | LLM 基地址 | 否（默认 WinCode） |
| `HTTP_PROXY` / `HTTPS_PROXY` | 联网搜索代理 | 否（Search Agent 使用） |
| `SPIRAL_SKIP_RAG_SEED` | 跳过 RAG 索引加速初始化 | 否 |

## 5. 项目结构速览

```
D:\Spiral/
├── backend/                 # FastAPI 后端
│   ├── main.py              # API 入口
│   ├── database.py            # SQLAlchemy + SQLite
│   ├── models.py              # ORM 模型
│   ├── recommendation.py      # 冲稳保推荐引擎核心
│   ├── seed_data.py           # 数据库初始化
│   ├── requirements.txt       # Python 依赖
│   ├── routers/               # API 路由
│   ├── services/              # 业务服务
│   ├── agent/                 # LLM Agent 核心
│   ├── templates/             # HTML 报告模板
│   └── data/                  # 演示 CSV 数据
├── frontend/                # React 19 + Vite 前端
│   ├── src/
│   ├── package.json
│   └── index.html
├── start.bat / start.ps1    # 一键启动
└── README.md
```

## 6. 已知状态

- [x] 仓库已克隆到 `D:\Spiral`
- [x] 全部 45 个 Python 文件通过语法检查，无错误
- [ ] 需安装 Python 3.13+ 和 Node.js 20+
- [ ] 需配置 `WINCODE_API_KEY` 到 `.env` 或环境变量
- [ ] 首次运行需执行 `seed_data.py` 初始化数据库
- [ ] 可选：安装 Qdrant 客户端与 sentence-transformers 以启用 RAG

## 7. 开发建议

- 后端修改后 `main.py` 已启用 `reload=True`，保存即热重载
- 前端 `npm run dev` 同样支持热重载
- 数据层使用 SQLite，生产环境建议迁移到 PostgreSQL + 独立 Qdrant
- 当前内置数据以 **湖北 2024/2025** 为主，扩展其他省份需补充 `province_rules/` 和 CSV 数据

## 8. 常用开发命令

```bash
# 后端单元测试入口
python -m pytest backend/tests/  # 如有测试目录

# 数据库审计脚本
python backend/scripts/audit_db.py
python backend/scripts/audit_db2.py

# 数据导入
python backend/scripts/sync_full_data.py

# 报告生成测试
python backend/scripts/generate_sample_report.py
```

---
**最后更新**：2025-06-29
**版本**：Spiral v0.2.1
