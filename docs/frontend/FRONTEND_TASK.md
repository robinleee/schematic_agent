# 前端重构任务书

## 项目背景

schematic_agent 是一个硬件 AI 专家系统，基于 EDA 异构数据图谱 + GraphRAG + ReAct Agent，
实现原理图审查与故障诊断。当前前端为 Streamlit（~4400 行），需要重构为**现代化独立前端**。

## 项目路径

- 代码：`/data/schematic_agent`
- 前端新目录：`/data/schematic_agent/frontend`
- 后端 API 新目录：`/data/schematic_agent/hardware_ai_expert/api`

## 当前功能清单（必须完整覆盖）

### 1. 智能对话 (Chat)
- ReAct Agent 对话：用户输入 → 多步推理 → 返回结果
- 推理链路展示：时间线布局，折叠面板，步骤图标（思考/执行/观察/结论），耗时，错误高亮
- 快速操作：清空对话、系统概览
- 主题切换：亮色/暗色

### 2. 原理图审查 (Review)
- 触发审查：选择规则或全量审查
- 审查报告：规则摘要表格 + 严重程度着色（Critical/Major/Minor/Info）
- 违规详情：展开查看具体器件/网络/引脚信息

### 3. HITL 审批面板
- 待审批列表（pending/approved/rejected 状态筛选）
- 单条/批量审批（approve/reject + 备注）
- BOS 导出（审批通过的规则导出为 JSON）

### 4. 知识库管理
- 文档上传：PDF/文本 → 解析 → 分类 → 存储
- 知识检索测试：输入 MPN + 查询 → 展示 Tier0/1/2/3 结果
- 知识库统计：chunks 数量、来源分布

### 5. ETL 导入
- 文件上传：网表(.txt) + BOM(.csv) → 预览 → 执行导入
- 导入进度展示
- 数据质量报告（Component/Pin/Net 数量、PartType 覆盖率等）
- 项目管理：创建/删除/切换项目

### 6. 图谱可视化 (Graph Viz)
- 5 种可视化模式：组件关系、电源链路、故障溯源、共因失效、电源树
- 可视化控制：深度滑块、方向选择
- DOT → Graphviz 渲染

### 7. 系统状态
- 服务状态（Neo4j/Ollama/ChromaDB/Streamlit）
- 数据统计（Components/Pins/Nets/PartType 覆盖率）
- Agent 统计（查询次数、Token 用量）

## 后端核心模块（已有 Python 代码，需要封装为 REST API）

| 模块 | 文件 | 核心类/函数 |
|------|------|-------------|
| ReAct Agent | `agent_system/react_agent.py` | `ReActAgent.run()`, `.review()`, `.diagnose()`, `.query_spec()` |
| Graph Tools | `agent_system/graph_tools.py` | 14 个 `@tool` 函数 (get_component_nets, get_power_domain, etc.) |
| Knowledge Router | `agent_system/knowledge_router.py` | `KnowledgeRouter.search()`, `.get_stats()` |
| Review Engine | `agent_system/review_engine/engine.py` | `ReviewEngine.run_rules()`, `.generate_report()` |
| HITL Workflow | `agent_system/hitl_workflow.py` | `HITLManager.add_pending()`, `.approve()`, `.reject()`, `.get_pending_list()` |
| Datasheet HITL | `agent_system/datasheet_parser.py` | `DatasheetHITLManager` |
| ETL Bridge | `agent_system/etl_web_bridge.py` | `run_etl_pipeline()`, `get_etl_preview()` |
| Graph Viz | `web_ui/sub_pages/graph_viz.py` | DOT 生成函数 (5种) |
| AMR Engine | `agent_system/amr_engine.py` | `AMREngine` |
| MPN Decoder | `agent_system/mpn_decoder.py` | `MPNDecoder.decode()` |

## 技术要求

### 前端
- **框架**: React + TypeScript（或 Vue 3 + TypeScript，由 Claude 决定）
- **UI 库**: Ant Design / Material UI / Shadcn（由 Claude 决定，推荐中文友好）
- **图谱可视化**: D3.js 或 react-force-graph
- **对话 UI**: 类 ChatGPT 的消息流
- **响应式**: 支持桌面和平板
- **暗色/亮色主题切换**
- **中文界面**

### 后端
- **框架**: FastAPI（轻量、异步、自动 OpenAPI 文档）
- **WebSocket**: 对话流式输出
- **文件上传**: multipart/form-data
- **CORS**: 开发模式允许 localhost

### 构建部署
- 前端 Vite 构建，产物放 `frontend/dist/`
- 后端 FastAPI 提供 SPA fallback（同时服务前端静态文件）
- 单端口部署（如 8501）

## 任务步骤

### Step 1: 方案设计文档
输出以下文档（写入 `/data/schematic_agent/docs/`）：

1. **`FRONTEND_DESIGN.md`** — 前端架构设计
   - 技术栈选型理由
   - 项目结构（目录树）
   - 页面路由设计
   - 组件设计（核心组件列表 + Props/State）
   - 状态管理方案
   - 主题方案
   - 响应式断点

2. **`API_SPEC.md`** — 后端 REST API 接口文档
   - 所有 API 端点（URL、Method、Request/Response Schema）
   - WebSocket 协议（对话流式）
   - 错误码定义
   - 数据模型（Pydantic Schema）

### Step 2: 等待评审
Claude 完成方案设计后**停止**，等待我的评审反馈。
我评审通过后才允许进入 Step 3。

### Step 3: 编码实现
- 先实现后端 FastAPI（确保 API 可用）
- 再实现前端（页面 + 组件 + API 调用）
- 确保 `pip install` 依赖可正常安装

### Step 4: 测试验证
- 后端 API 测试（pytest + httpx）
- 前端构建测试（npm run build 无错误）
- 端到端功能验证（每个页面可正常操作）

## 约束

1. **不破坏现有代码**：Streamlit 版本保留不动，新前端是独立新增
2. **Python 3.8 兼容**：后端代码必须兼容 Python 3.8
3. **无额外 Docker 依赖**：纯 Python + Node.js 方案
4. **单端口部署**：FastAPI 同时服务 API 和前端静态文件
5. **本地 LLM**：Ollama gemma4:26b，不需要外部 API Key
6. **数据目录**：`/data/schematic_agent/` 下所有数据保持不变
