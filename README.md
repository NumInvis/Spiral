<div align="center">

# Spiral · 高考志愿智能决策 Agent

**基于全省位次 + 等位分换算 + LLM 语义理解的高考志愿填报辅助系统**

[![Python 3.13](https://img.shields.io/badge/Python-3.13-blue)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688)](https://fastapi.tiangolo.com/)
[![React 19](https://img.shields.io/badge/React-19-61DAFB)](https://react.dev/)
[![License](https://img.shields.io/badge/License-MIT-yellow)](LICENSE)

> 🎯 输入一句自然语言 + 全省位次，输出一份可解释、带图表、带风险提示的 HTML 志愿报告。

</div>

---

## ✨ 为什么叫 Spiral

高考志愿填报是一个**螺旋上升**的决策过程：

```
自我认知 → 数据检索 → 风险评估 → 方案生成 → 模拟验证 → 再次迭代
```

Spiral 把这个过程自动化：用 LLM 理解考生意图，用历史录取数据估算概率，用可视化呈现风险，让人把精力放在最终判断上，而不是反复查表、换算、排序。

---

## 🚀 30 秒预览

```bash
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt
set WINCODE_API_KEY=sk-xxx
python main.py
```

然后打开另一个终端：

```bash
cd frontend
npm install
npm run dev
```

或者直接双击 `start.bat` 一键启动。

访问 http://localhost:1678，在「生成报告」页面输入即可得到一份包含冲/稳/保三档、录取概率、数据置信度、风险提示的完整 HTML 报告。

---

## 🏗️ 架构概览

```
┌─────────────────────────────────────────────────────────────────┐
│                         用户交互层                               │
│   React 19 + Vite + Tailwind CSS + Recharts / ECharts           │
└───────────────────────────┬─────────────────────────────────────┘
                            │ HTTP
┌───────────────────────────▼─────────────────────────────────────┐
│                         API 服务层                               │
│   FastAPI + SQLAlchemy + SQLite + Qdrant（可选 RAG）            │
│   Port: 11678                                                   │
└───────────────────────────┬─────────────────────────────────────┘
                            │
        ┌───────────────────┼───────────────────┐
        ▼                   ▼                   ▼
┌───────────────┐  ┌───────────────┐  ┌───────────────────────┐
│  画像解析      │  │  推荐引擎      │  │  报告生成              │
│  LLM / 规则    │  │  位次法 + 等位分│  │  Jinja2 + ECharts     │
└───────────────┘  └───────────────┘  └───────────────────────┘
        ▲                   ▲
        │                   │
        └─────────┬─────────┘
                  ▼
        ┌───────────────────┐
        │  数据层            │
        │  CSV → SQLite     │
        │  一分一段表 → RankTable │
        │  招生章程 → RAG   │
        └───────────────────┘
```

---

## 🧠 核心能力

### 1. 自由文本画像解析

不依赖固定表单。用户像聊天一样描述：

> "湖北物理类，排名 25000 左右，想学计算机或电子信息，留武汉或长三角，看重专业。"

系统提取：
- 省份、科类、分数、位次
- 意向专业（LLM 扩展为相关具体专业）
- 意向城市、策略偏好
- 是否接受特殊类型招生

### 2. 位次法 + 等位分换算

以**全省位次**为核心，不同年份的分数通过一分一段表换算到同一年份后再比较，避免「去年 600 分 = 今年 600 分」的幻觉。

### 3. A / B / C / D 四级数据置信

| 等级 | 含义 | 说明 |
|------|------|------|
| **A** | 专业真实线 | 该专业有真实录取最低位次 |
| **B** | 同组插值 | 用同专业组其他专业的真实线均值估算 |
| **C** | 组线估算 | 仅有专业组投档线，按专业热度偏移估算 |
| **D** | 数据缺失 | 无有效数据，不推荐 |

### 4. LLM 语义专业匹配

传统关键词匹配会把「计算机科学与技术」和「数据科学与大数据技术」当作无关专业。Spiral 用 LLM 一次性把用户意向扩展为相关具体专业列表和学科门类，再本地快速打分，兼顾语义相关性与性能。

### 5. 风险控制与可解释性

每个推荐院校专业组都附带：
- 冲 / 稳 / 保 档位
- 录取概率估算
- 数据置信等级
- 推荐理由
- 风险提示（调剂风险、大类分流、数据缺失等）

### 6. 特殊类型招生过滤

默认排除预科、国家专项、地方专项、高校专项、定向、民族班、援藏、南疆、边防军人子女等特殊类型，除非考生文本明确提及愿意填报。

---

## 📁 项目结构

```
Spiral/
├── backend/                       # FastAPI 后端
│   ├── main.py                    # API 入口
│   ├── database.py                # SQLAlchemy + SQLite
│   ├── models.py                  # 数据模型
│   ├── schemas.py                 # Pydantic 接口定义
│   ├── recommendation.py          # 冲稳保推荐引擎核心
│   ├── seed_data.py               # 数据初始化脚本
│   ├── config/                    # 省份规则配置
│   ├── province_rules/            # 各省填报规则 JSON
│   ├── routers/                   # API 路由
│   │   ├── report.py              # 自由文本 → HTML 报告
│   │   ├── agent.py               # Search Agent
│   │   └── rag.py                 # RAG 检索
│   ├── services/                  # 业务服务
│   │   ├── profile_parser.py      # 自由文本画像解析
│   │   ├── major_matcher.py       # LLM 语义专业匹配
│   │   ├── llm_service.py         # LLM 客户端
│   │   ├── data_importer.py       # CSV / JSON 数据导入
│   │   ├── rag_service.py         # Qdrant RAG
│   │   ├── document_builder.py    # 招生章程文档生成
│   │   └── search_agent.py        # 联网搜索 Agent
│   ├── agent/                     # LLM Agent 核心
│   │   ├── core.py
│   │   ├── tools.py
│   │   └── state.py
│   ├── scripts/                   # 数据工具脚本
│   ├── templates/report.html      # HTML 报告模板
│   ├── data/                      # CSV/JSON 数据源
│   └── requirements.txt
├── frontend/                      # React 前端
│   ├── src/
│   │   ├── components/            # UI 组件
│   │   ├── pages/                 # 页面
│   │   ├── api.js                 # 后端接口封装
│   │   └── index.css
│   └── package.json
├── start.bat                      # Windows 一键启动
└── README.md
```

---

## 🛠️ 快速开始

### 环境要求

- Python 3.13+
- Node.js 20+
- Windows

### 方式一：一键启动

双击 `start.bat`，或命令行执行：

```cmd
start.bat
```

### 方式二：手动启动

**后端：**

```cmd
cd backend
python -m venv venv
venv\Scripts\pip install -r requirements.txt

REM 必须配置，否则所有推荐和画像解析接口报错
set WINCODE_API_KEY=sk-xxx

REM 首次运行需要初始化数据库
python seed_data.py

python main.py
```

后端地址：http://localhost:11678/docs

**前端：**

```cmd
cd frontend
npm install
npm run dev
```

前端地址：http://localhost:1678

---

## 📡 核心 API

| 接口 | 方法 | 说明 |
|------|------|------|
| `/api/health` | GET | 健康检查 |
| `/api/profiles` | POST | 创建考生画像 |
| `/api/recommendations/{profile_id}` | POST | 按画像生成推荐 |
| `/api/agent/recommend` | POST | Agent 全流程（画像解析 + 推荐 + 风险复核） |
| `/api/reports/from-text` | POST | 自由文本 → HTML 报告 |
| `/api/schools` | GET | 院校列表 |
| `/api/schools/{id}` | GET | 院校详情 |
| `/api/majors/search` | GET | 专业搜索 |

### 生成 HTML 报告示例

```bash
curl -X POST http://localhost:11678/api/reports/from-text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "湖北物理类考生，全省排名25000名左右，想读计算机或电子信息，以后想留武汉或长三角就业，比较看重专业。",
    "rank": 25000
  }'
```

---

## ⚙️ 环境变量

| 变量 | 说明 | 是否必填 |
|------|------|----------|
| `WINCODE_API_KEY` | WinCode / OpenAI 兼容 API Key | **是**（不填则画像解析和推荐接口报错） |
| `WINCODE_BASE_URL` | LLM Base URL，默认 `https://wincode.winning.com.cn/ai/v1` | 否 |
| `SPIRAL_SKIP_RAG_SEED` | 设置为 `1` 可跳过 RAG 索引，加快数据库重建 | 否 |
| `HTTP_PROXY` / `HTTPS_PROXY` | 联网搜索代理 | 否 |

---

## 📊 数据来源与局限性

当前内置数据：
- 湖北省 2024 年本科普通批院校专业组投档线 / 招生计划
- 湖北省物理类 / 历史类一分一段表
- 院校层次、学科评估、硕博点等元数据

生产环境建议接入：
- 各省教育考试院官方一分一段表与投档线
- 阳光高考网招生计划与招生章程
- 各高校本科招生网专业录取线
- 教育部学科评估、软科 / QS 排名

> ⚠️ **免责声明**：本系统输出仅供参考，最终志愿填报请以各省招生考试机构官方信息为准。

---

## 🎨 设计系统

- **视觉风格**：学术粗野主义（Academic Brutalism）
- **字体**：Source Serif 4（标题）+ Inter（正文）+ JetBrains Mono（数据）
- **配色**：米白纸张、深黑墨水、藏蓝强调、砖红警示
- **布局**：厚边框、硬阴影、大量留白、数据表格优先

---

## 🗺️ 路线图

- [x] 自由文本画像解析
- [x] 位次法 + 等位分换算
- [x] A/B/C/D 数据置信
- [x] LLM 语义专业匹配
- [x] HTML 报告与可视化
- [x] 特殊类型招生过滤
- [ ] 多省份规则扩展
- [ ] 实时招生计划与章程 RAG 检索
- [ ] 多轮对话式志愿调整
- [ ] 录取结果回传与模型校准

---

## 🤝 参与贡献

欢迎 Issue 和 PR。请在修改前阅读 `AGENTS.md`（如存在）中的项目约定。

---

## 📜 License

MIT License

---

<div align="center">

**变分无限 · Project Spiral**

</div>
