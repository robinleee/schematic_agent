# 前后端联调报告

> Date: 2026-06-08 | FastAPI + React + TypeScript + Ant Design

---

## 一、接口对比总表

| # | 前端方法 | 前端路径 | 后端路由 | 方法 | 状态 |
|---|----------|----------|----------|------|------|
| 1 | `reviewApi.getRules()` | `GET /api/v1/review/rules` | `GET /api/v1/review/rules` | ✅ | 正常 |
| 2 | `reviewApi.runReview()` | `POST /api/v1/review/run` | `POST /api/v1/review/run` | ✅ | 已修复 |
| 3 | `hitlApi.getPending()` | `GET /api/v1/hitl/pending` | `GET /api/v1/hitl/pending` | ✅ | 已修复 |
| 4 | `hitlApi.reviewAction()` | `POST /api/v1/hitl/action` | `POST /api/v1/hitl/action` | ✅ | 已修复 |
| 5 | `hitlApi.export()` | `POST /api/v1/hitl/export` | `POST /api/v1/hitl/export` | ✅ | 已修复 |
| 6 | `knowledgeApi.upload()` | `POST /api/v1/knowledge/upload` | `POST /api/v1/knowledge/upload` | ✅ | 已修复 |
| 7 | `knowledgeApi.search()` | `POST /api/v1/knowledge/search` | `POST /api/v1/knowledge/search` | ✅ | 已修复 |
| 8 | `knowledgeApi.getStats()` | `GET /api/v1/knowledge/stats` | `GET /api/v1/knowledge/stats` | ✅ | 已修复 |
| 9 | `etlApi.getProjects()` | `GET /api/v1/etl/projects` | `GET /api/v1/etl/projects` | ✅ | 正常 |
| 10 | `etlApi.createProject()` | `POST /api/v1/etl/projects` | `POST /api/v1/etl/projects` | ✅ | 正常 |
| 11 | `etlApi.deleteProject()` | `DELETE /api/v1/etl/projects/{name}` | `DELETE /api/v1/etl/projects/{project_name}` | ✅ | 正常 |
| 12 | `etlApi.preview()` | `POST /api/v1/etl/preview` | `POST /api/v1/etl/preview` | ✅ | 正常 |
| 13 | `etlApi.run()` | `POST /api/v1/etl/run` | `POST /api/v1/etl/run` | ✅ | 正常 |
| 14 | `etlApi.getProgress()` | `GET /api/v1/etl/progress/{jobId}` | `GET /api/v1/etl/progress/{job_id}` | ✅ | 正常 |
| 15 | `graphApi.visualize()` | `POST /api/v1/graph/visualize` | `POST /api/v1/graph/visualize` | ✅ | 已修复 |
| 16 | `systemApi.getStatus()` | `GET /api/v1/system/status` | `GET /api/v1/system/status` | ✅ | 正常 |
| 17 | `systemApi.healthCheck()` | `GET /api/v1/health` | `GET /api/v1/health` | ✅ | 正常 |
| 18 | `chatApi.sendMessage()` | `POST /api/v1/chat` | `POST /api/v1/chat` | ⚠️ | 未测试（耗时太长） |
| 19 | WebSocket | `WS /ws/chat` | `WS /ws/chat` | ⚠️ | 已修复URL，未实测流式 |

---

## 二、发现的问题及修复

### 问题1：前端 baseURL 硬编码 localhost ✅ 已修复
- **文件**: `frontend/src/api/client.ts`
- **问题**: `API_BASE_URL` 默认值 `'http://localhost:8501'`，浏览器从 B2 访问时请求发到用户本机
- **修复**: 改为空字符串 `''`，使用相对路径

### 问题2：WebSocket 地址硬编码 ✅ 已修复
- **文件**: `frontend/src/hooks/useWebSocket.ts`
- **问题**: 默认值 `'ws://localhost:8501/ws/chat'`
- **修复**: 改为动态获取 `window.location.protocol` 和 `window.location.host` 构造 URL

### 问题3：HITL 路由调用不存在的方法 ✅ 已修复
- **文件**: `hardware_ai_expert/api/routers/hitl.py`
- **问题**:
  - `get_pending_reviews()` → 实际为 `get_pending_list()`
  - `process_review_action()` → 实际为 `approve()` / `reject()`
  - `export_to_bos()` → 实际为 `save_approved_rules()`
- **修复**: 重写路由逻辑，调用正确方法，适配返回格式

### 问题4：review/run 中 Violation 对象访问方式错误 ✅ 已修复
- **文件**: `hardware_ai_expert/api/routers/review.py`
- **问题**: `ReviewRuleEngine.run_rules()` 返回的是 `Violation` 对象（有属性），不是 dict，`v.get()` 会报错
- **修复**: 统一使用 `hasattr()` + 属性访问，加 dict fallback

### 问题5：knowledge/search 中 RetrievalResult 对象访问方式错误 ✅ 已修复
- **文件**: `hardware_ai_expert/api/routers/knowledge.py`
- **问题**: `KnowledgeRouter.search()` 返回 `RetrievalResult` 对象，不是 dict
- **修复**: 统一使用 `_get()` 辅助函数，兼容 dict 和对象

### 问题6：graph/visualize 函数名不匹配 ✅ 已修复
- **文件**: `hardware_ai_expert/api/routers/graph.py`
- **问题**:
  - 导入 `build_xxx` 但实际函数名是 `_build_xxx`（私有）
  - `build_fault_trace_dot` 实际为 `_build_fault_root_dot`
  - `_build_common_cause_dot` 接受 `graph_data: dict`，不是 `refdes`
  - 原代码取 `result.get("dot_content")` 但函数直接返回 DOT 字符串
- **修复**: 修正函数名、参数、调用方式，common_cause 先调 `get_common_cause_graph()` 获取数据

---

## 三、API 实测结果

| 接口 | HTTP 状态 | 返回数据 | 验证结果 |
|------|-----------|----------|----------|
| `GET /api/v1/review/rules` | 200 | 24 条规则 | ✅ |
| `POST /api/v1/review/run` | 200 | 1453 个违规 | ✅ |
| `GET /api/v1/hitl/pending` | 200 | total=0 | ✅ |
| `GET /api/v1/system/status` | 200 | 4 个服务全在线 | ✅ |
| `GET /api/v1/health` | 200 | success=True | ✅ |
| `GET /api/v1/etl/projects` | 200 | ['default', 'HW7.0'] | ✅ |
| `GET /api/v1/knowledge/stats` | 200 | tier2=True, tier3=True | ✅ |
| `POST /api/v1/knowledge/search` | 200 | tier=Tier0 | ✅ |
| `POST /api/v1/graph/visualize` | 200 | nodes=2004 | ✅ |

---

## 四、仍需人工验证的项

| # | 项目 | 说明 |
|---|------|------|
| 1 | **Chat 页面流式对话** | WebSocket 连接已修复 URL，但需在浏览器实测流式输出 |
| 2 | **ETL 文件上传** | 需要 3 个网表文件才能测试，当前无测试数据 |
| 3 | **Knowledge 文件上传** | 需要真实 PDF 文件测试 |
| 4 | **Graph 可视化渲染** | API 返回 DOT 字符串，需验证前端 d3-graph 渲染效果 |
| 5 | **HITL 审批操作** | 当前 pending=0，需先运行审查产生违规，再测试审批流 |
| 6 | **跨域访问** | CORS 当前只允许 localhost，从 B2 (172.20.98.190) 访问可能需添加 |

---

## 五、CORS 需更新

当前 FastAPI CORS 只允许 `localhost` 来源。从 B2 (172.20.98.190) 访问时，浏览器 Origin 是 `http://172.20.98.190:8501`，可能被 CORS 拒绝。

**建议**: 在 `main.py` 的 `allow_origins` 中添加 B2 的 IP，或改为 `["*"]`（内网环境可接受）。
