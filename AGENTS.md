# AGENTS.md — Spiral 高考志愿 Agent

## 项目定位

基于全省位次 + 等位分换算 + LLM 语义理解的高考志愿填报辅助系统。
后端 Python 3.13 + FastAPI + SQLAlchemy + SQLite，前端 React 19 + Vite + Tailwind。

## 硬性约束

- **LLM 是硬依赖**：所有画像解析、专业匹配、报告生成接口必须配置 `WINCODE_API_KEY`。没有 fallback，没有 mock。不填则接口直接报错。
- **数据年份常量**：`config/province_rules.py` 中 `CURRENT_YEAR = 2026`，`LATEST_HISTORICAL_YEAR = 2025`。推荐引擎只查 `LATEST_HISTORICAL_YEAR` 的数据，禁止回退到旧年份。
- **等位分换算必须有完整一分一段表**：缺失年份直接抛 `ValueError`，不会降级。

## 启动与命令

```cmd
:: 一键启动（前后端同时拉起）
start.bat

:: 后端手动启动
cd backend
python -m venv venv & venv\Scripts\pip install -r requirements.txt
set WINCODE_API_KEY=sk-xxx
python seed_data.py   :: 首次或数据变更时执行
python main.py

:: 前端
cd frontend & npm install & npm run dev
```

- 端口：后端 `11678`，前端 `1678`
- 后端热重载：`main.py` 使用 `reload=True`，保存即生效
- Vite 代理：`/api` → `http://localhost:11678`，前端无需 CORS 配置

## 推荐引擎核心流程

`backend/recommendation.py` → `build_recommendation(profile, db)`：

1. 查最新年份组线数据 → 无数据直接报错
2. LLM 语义专业匹配（`score_major_relevance`）→ 返回相关度 0-1
3. 特殊类型过滤（默认排除国家专项、预科等 13 类）
4. 等位分换算：上一年组线位次 → 目标年份等效位次
5. 概率估算：`estimate_probability(candidate_rank, ref_rank)` — 公式驱动，未做统计校准
6. LLM 决策层对 Top-5 候选重排 + 生成推荐理由
7. 冲/稳/保分档输出（默认 balanced: 冲 15-45%, 稳 45-75%, 保 >75%）

## 数据层

- SQLite 数据库：`backend/gaokao.db`（运行时自动生成）
- 省份规则：`backend/province_rules/{省份}.json`（hubei/hunan/jiangxi/anhui）
- 数据接口：`backend/data/` — 仅保留 `raw_hubei_2024_2025_updated.csv`
- 种子数据依赖：`.tmp_data/ranking_score_hubei_physics.json`、`ranking_score_hubei_history.json`、`2025_score_rank.csv`

## 目录职责

| 路径 | 职责 |
|------|------|
| `backend/agent/` | LLM Agent 编排：core=流程，tools=原子操作，state=数据模型 |
| `backend/routers/` | API 路由：report, agent, rag |
| `backend/services/` | 业务逻辑：profile_parser, major_matcher, llm_service, data_importer, rag_service, search_agent 等 |
| `backend/scripts/` | 一次性数据工具（audit, sync, generate_report, validate_csv） |

## 已知陷阱

- `recommendation.py:46-55`：`_schools_cache` 使用 `db.expunge_all()` 后缓存在进程内存中，重启失效
- `recommendation.py:617`：`_llm_decision_layer()` 无降级，LLM 不可用则整个推荐接口 500
- `agent/tools.py:33-36`：`_require_llm()` 直接读环境变量，不从 config 模块取
- 特殊类型关键词硬编码在 `recommendation.py:189-243` 的 `_SPECIAL_TYPE_CATEGORIES` 字典中
- `start.bat` 使用 `%~dp0` 相对路径，不要改成绝对路径

## 何时修改数据

- 新省份：在 `backend/province_rules/` 添加 `{省份}.json`，在 `data_importer.py` 添加导入逻辑
- 新年份数据：更新 CSV → 运行 `python seed_data.py`（设置 `SPIRAL_SKIP_RAG_SEED=1` 可跳过 RAG 索引加速）
    
