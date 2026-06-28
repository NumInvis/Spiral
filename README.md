# Spiral · 高考志愿 Agent（学术版）

> 变分无限（Variational Infinite）内部项目代号：**Spiral**

前后端完备的湖北高考志愿填报辅助系统。前端端口 `1678`，后端端口 `11678`。

## 核心交互

**输入**：用户用自然语言自由描述志愿意向 + 全省位次。  
**输出**：一份可解释、带图表、带风险提示的 HTML 志愿填报报告。

> 首：自由文本画像解析 → 中：位次法推荐 + LLM 增强 → 尾：结构化 HTML 报告。

## 设计理念

- **学术感 + 新粗野主义**：衬线标题、无衬线正文、厚黑边框、硬阴影、无黄色。
- **位次为王**：推荐完全基于考生全省位次与往年录取位次，分数仅作参考。
- **可解释**：每个志愿都标注档位、概率、数据来源置信度、推荐理由、风险提示。
- **风险控制**：保底志愿不足时给出警告，数据缺失时明确标注。
- **可视化**：推荐结果支持冲稳保分布、概率区间、院校层次等多维度图表展示（基于 Recharts / ECharts）。
- **LLM 增强**：接入 WinCode DeepSeek API 进行自由文本画像解析与报告总结；无配置时自动降级为规则解析。

## 项目结构

```
gaokao-agent/
├── backend/                  # FastAPI + SQLite + Qdrant
│   ├── main.py               # API 入口
│   ├── database.py           # SQLAlchemy 配置
│   ├── models.py             # 数据模型
│   ├── schemas.py            # Pydantic 接口
│   ├── recommendation.py     # 冲稳保推荐引擎
│   ├── seed_data.py          # 湖北演示数据
│   ├── templates/report.html # HTML 报告模板
│   ├── routers/report.py     # 自由文本 → HTML 报告接口
│   ├── services/             # 业务服务
│   │   ├── profile_parser.py # 自由文本画像解析
│   │   ├── llm_service.py    # WinCode / OpenAI 兼容 LLM 调用
│   │   └── ...
│   └── requirements.txt
├── frontend/                 # React + Vite + Tailwind CSS + Recharts
│   ├── src/
│   │   ├── components/       # UI 组件
│   │   ├── pages/            # 页面（含 /report 报告入口）
│   │   ├── api.js            # 后端接口封装
│   │   ├── App.jsx
│   │   └── index.css         # 学术粗野主义样式
│   ├── package.json
│   ├── tailwind.config.js
│   └── vite.config.js
├── start.ps1                 # Windows 一键启动脚本
└── README.md
```

## 快速启动

### 方式一：PowerShell 一键启动

```powershell
cd gaokao-agent
.\start.ps1
```

### 方式二：手动分别启动

**后端：**

```powershell
cd gaokao-agent\backend
python -m pip install -r requirements.txt
set WINCODE_API_KEY=sk-xxx  # 可选，用于 LLM 增强
python main.py
```

后端运行后访问：http://localhost:11678/docs

**前端：**

```powershell
cd gaokao-agent\frontend
npm install
npm run dev
```

前端访问：http://localhost:1678

## 主要功能

1. **首页**：产品理念与流程说明。
2. **生成报告** `/report`：自由文本 + 位次，一键生成 HTML 志愿报告。
3. **智能填报** `/recommend`：结构化表单填写考生画像，生成 45 个院校专业组志愿表。
4. **院校数据** `/data`：浏览湖北本科院校与专业，支持专业搜索。

## 核心接口

| 接口 | 说明 |
|------|------|
| `GET /api/health` | 健康检查 |
| `POST /api/profiles` | 创建考生画像 |
| `POST /api/recommendations/{profile_id}` | 生成推荐方案 |
| `POST /api/recommendations/from-text` | 自由文本生成 JSON 推荐 |
| `POST /api/reports/from-text` | 自由文本生成 HTML 报告 |
| `GET /api/schools` | 院校列表 |
| `GET /api/schools/{id}` | 院校详情 |
| `GET /api/majors/search` | 专业搜索 |

### 生成 HTML 报告示例

```bash
curl -X POST http://localhost:11678/api/reports/from-text \
  -H "Content-Type: application/json" \
  -d '{
    "text": "我是湖北考生，物理类，全省排名25000名左右，想读计算机或电子信息，以后想留武汉或长三角就业，比较看重专业和学校层次，可以接受调剂。",
    "rank": 25000
  }'
```

## 数据说明

当前内置湖北本科院校真实投档/计划数据（含 985、211、双一流、普通本科）。
生产环境建议接入：

- 湖北省教育考试院官方一分一段表、投档线
- 阳光高考招生计划与招生章程
- 各高校本科招生网专业录取分数线
- 教育部学科评估 / 软科排名

## 技术栈

- **后端**：Python 3.13 + FastAPI + SQLAlchemy + SQLite + Qdrant
- **前端**：React 19 + Vite + Tailwind CSS + Lucide Icons + Recharts
- **LLM**：WinCode DeepSeek API（OpenAI 兼容协议）
- **报告可视化**：ECharts
- **设计**：Source Serif 4（标题）+ Inter（正文）+ JetBrains Mono（数据）

## 环境变量

| 变量 | 说明 |
|------|------|
| `WINCODE_API_KEY` | WinCode API Key，用于 LLM 画像解析与报告总结 |
| `WINCODE_BASE_URL` | 可选，默认 `https://wincode.winning.com.cn/ai/v1` |
| `HTTP_PROXY` / `HTTPS_PROXY` | Web Search 代理 |

## 免责声明

本系统输出仅供参考，最终志愿填报请以各省招生考试机构官方信息为准。

---

*© 2026 变分无限（Variational Infinite）· Project Spiral*
