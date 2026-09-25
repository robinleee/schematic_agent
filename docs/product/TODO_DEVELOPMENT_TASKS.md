# 待完成开发任务清单

> 版本: 2026-06-29 | 来源: `PRD_V5.1.md`、`TECHNICAL_IMPLEMENTATION_PLAN.md`、`PRD_GAP_ANALYSIS_V2.md` 与代码交叉检查
>
> 用途: 作为后续开发任务的动态跟踪文档。任务完成后，直接将状态从 `[ ]` 改为 `[x]`，并补充完成日期、相关 PR/commit、验证方式。

## 状态标记约定

- `[ ]` 未开始
- `[~]` 进行中
- `[x]` 已完成
- `[!]` 阻塞中
- `[?]` 需重新确认

## P0 — 优先处理

### [ ] P0-1 部署专业 Embedding 模型

**当前状态**: 未完成。当前仍使用 `all-MiniLM-L6-v2`。

**背景**: GraphRAG 检索质量的头号风险。当前模型偏通用，硬件 datasheet/元器件语义检索效果需要专门评估。

**涉及位置**:
- `hardware_ai_expert/agent_system/embedding.py`
- `hardware_ai_expert/agent_system/graph_rag/schemas.py`
- `hardware_ai_expert/agent_system/graph_rag/indexers/vector_indexer.py`

**建议实现**:
- 评估并部署 `bge-m3` 或 `bge-large-zh-v1.5`
- 重建 Neo4j VectorChunk 向量索引
- 建立固定 query set，比较切换前后 recall@k / precision@k

**验收标准**:
- 新模型可配置化切换，不硬编码
- GraphRAG 索引可重建
- 至少输出一份检索质量对比结果

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P0-2 HITL Datasheet 闭环验证

**当前状态**: 管道已有，真实端到端闭环未验证。

**背景**: `datasheet_parser.py → datasheet_hitl.py → hitl_workflow.py → save_approved_rules()` 相关能力已存在，但还需用真实 datasheet 验证从提取到规则生效的完整闭环。

**涉及位置**:
- `hardware_ai_expert/agent_system/datasheet_parser.py`
- `hardware_ai_expert/agent_system/datasheet_hitl.py`
- `hardware_ai_expert/agent_system/hitl_workflow.py`
- `hardware_ai_expert/agent_system/review_engine/config/default_rules.yaml`
- `hardware_ai_expert/amr_data.yaml`

**建议实现**:
- 选择 3-5 个真实 datasheet
- 跑通参数提取、Pending Review、Approve/Reject、规则写入
- 验证 ReviewRuleEngine 热更新后可读取新规则/参数

**验收标准**:
- 至少 3 个 PDF 样本完成端到端闭环
- 审批后的规则或 AMR 参数可被审查引擎使用
- 失败/拒绝场景有明确记录

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [~] P0-3 前后端全面联调

**当前状态**: 部分已修复，仍需逐页面联调。WebSocket 地址硬编码问题经代码检查已基本解决，当前实现基于当前 host 与 `VITE_WS_URL`。2026-09-22 已将非流式 Chat API 的同步 `ReActAgent.run()` 移到线程池，并增加可配置超时，避免长查询阻塞其他 API；7 页面逐项联调仍未完成。

**背景**: React 前端已有 7 页面，FastAPI 后端已有 7 routers + WebSocket，但仍需统一验证 API schema、错误处理、响应格式与页面交互。

**涉及位置**:
- `frontend/src/pages/Chat/`
- `frontend/src/pages/Review/`
- `frontend/src/pages/HITL/`
- `frontend/src/pages/Knowledge/`
- `frontend/src/pages/ETL/`
- `frontend/src/pages/Graph/`
- `frontend/src/pages/System/`
- `hardware_ai_expert/api/routers/`
- `hardware_ai_expert/api/websocket/chat_ws.py`

**建议实现**:
- 启动 FastAPI + React dev server
- 逐页面手工联调并记录接口错误
- 修复前后端字段名、状态码、错误提示不一致问题
- 为关键 API 增加最小 smoke test

**验收标准**:
- 7 个页面均能完成核心操作
- Chat WebSocket 能正常连接、发送、接收流式推理步骤
- ETL / Review / HITL / Graph 页面无阻断性报错

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

**阶段性验证记录（2026-09-22）**:
- `POST /api/v1/chat` 的 Agent 执行已移出 FastAPI event loop，配置项为 `CHAT_AGENT_TIMEOUT_SECONDS`（默认 300 秒）。
- Agent 请求运行期间，`GET /api/v1/review/rules` 仍可返回 HTTP 200，证明事件循环未被同步调用阻塞。

---

### [ ] P0-4 BOM 数据入库与知识关联完善

**当前状态**: BOM 上传与 CSV/Excel 解析已存在，但主要用于 PartType 标准化；MPN、Manufacturer、Description 等字段与知识库/AMR/Datasheet 的系统性关联仍需完善。

**背景**: 代码已支持 BOM 文件传入 ETL：`api/routers/etl.py` 与 `PartTypeStandardizer` 已能读取 BOM。后续重点不是“能否上传 CSV”，而是把 BOM 作为器件知识关联入口。

**涉及位置**:
- `hardware_ai_expert/api/routers/etl.py`
- `hardware_ai_expert/agent_system/etl_web_bridge.py`
- `hardware_ai_expert/etl_pipeline/part_type_standardizer.py`
- `hardware_ai_expert/etl_pipeline/load_to_neo4j.py`
- `hardware_ai_expert/agent_system/mpn_decoder.py`
- `hardware_ai_expert/agent_system/amr_engine.py`
- `hardware_ai_expert/agent_system/knowledge_router.py`

**建议实现**:
- 解析 BOM 中的 MPN / Manufacturer / Description / RefDes
- 将 BOM 字段写入 Component 节点
- 将 MPN 与 AMR、Datasheet、Tier3/Tier0 知识检索打通
- 增加 BOM 字段缺失、重复 RefDes、多位号拆分等测试

**验收标准**:
- Component 节点可查询到 BOM MPN / Manufacturer / Description
- AMR 引擎可优先使用 BOM MPN 获取耐压/规格参数
- KnowledgeRouter 可基于 BOM MPN 检索 datasheet/公网供应商信息

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

## P1 — 核心功能完善

### [ ] P1-1 网络电压标注率提升

**当前状态**: POWER 网络电压标注率约 95.7%，全网电压标注率约 20.7%。核心网络连通性校验已改为网络级，但 post-injection 的 VoltageLevel 完整性校验仍可增强。

**建议实现**:
- 扩展电压网络模式库，如 VDDQ、VPP、VTT、1V0_DDR 等
- 建立核心网络 VoltageLevel post-injection 校验
- 输出未标注核心网络清单

**验收标准**:
- POWER 网络电压标注率保持 ≥95%
- 核心网络 VoltageLevel 缺失可被明确报告

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P1-2 AMR 电容耐压覆盖率提升到 ≥95%

**当前状态**: 统一口径下当前 AMR 覆盖率约 83.1%。

**建议实现**:
- 统计缺失 voltage_rating 的电容清单
- 按 MPN/封装/厂商聚类缺失类型
- 扩展 `mpn_decoder.py` 与 `amr_data.yaml`
- 借助 BOM/Datasheet/HITL 补齐小众型号

**验收标准**:
- AMR 电容耐压覆盖率 ≥95%
- 缺失项可输出清单并可解释原因

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [x] P1-3 显式 Self-Correction 节点

**当前状态**: 已完成。ReActAgent 对空/无命中工具结果执行显式参数放宽和重试，最多 2 次，并写入 reasoning chain。

**建议实现**:
- Graph Tools 返回空结果时记录失败上下文
- LLM 或规则层生成查询修正策略
- 最多重试 2 次，避免死循环
- 将修正过程写入 reasoning chain

**验收标准**:
- 空结果场景会触发明确的 retry / relax 策略
- 推理链能展示修正过程
- 重试次数有上限并可测试

**完成记录**:
- 完成日期: 2026-09-22
- 关联 commit/PR: 当前代码基线（`react_agent.py` 的 `_self_correct_tool_call`）
- 验证命令/结果: `hardware_ai_expert/tests/test_react_self_correction.py`

---

### [ ] P1-4 LlamaIndex 评估

**当前状态**: 自研 GraphRAG 已作为正式基线，LlamaIndex 不是阻塞项。

**建议实现**:
- 在专业 embedding 部署后，对自研 GraphRAG 做检索质量评估
- 若 recall@k 未达目标，再评估 LlamaIndex 迁移收益
- 输出是否迁移的决策记录

**验收标准**:
- 有固定 query set 和评估结果
- 有明确保留自研或迁移 LlamaIndex 的结论

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P1-5 Tier2 内网 PLM 集成

**当前状态**: `KnowledgeRouter` 中 Tier2 仍是预留/替代实现，未真正接入内网 PLM。

**涉及位置**:
- `hardware_ai_expert/agent_system/knowledge_router.py`

**建议实现**:
- 明确 PLM 查询接口、认证方式、字段映射
- 实现 Tier2 retriever
- Tier2 命中结果缓存到 Tier1
- 增加超时、失败降级到 Tier3 的测试

**验收标准**:
- 可按 MPN 查询内网 PLM
- Tier2 成功命中时优先于 Tier3
- Tier2 失败时可稳定降级

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

## P2 — 质量与生产化

### [ ] P2-1 E2E 自动化测试

**当前状态**: 已有单元/集成测试，但缺完整端到端自动化链路。

**建议实现**:
- 增加网表上传 → ETL → 审查 → 报告 → HITL 审批 E2E 测试
- 可先做 API 层 E2E，再扩展到前端 E2E

**验收标准**:
- 至少覆盖一条完整成功链路
- 覆盖至少一条质量检查失败链路

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-2 测试覆盖率提升到 ≥60%

**当前状态**: 文档估计约 40-45%，目标 ≥60%。

**建议实现**:
- 对 parser、review templates、graph_tools、API routers、HITL workflow 增加测试
- 接入 coverage 报告

**验收标准**:
- 覆盖率报告显示总覆盖率 ≥60%
- 新增测试只覆盖真实需求，不堆无效断言

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-3 Cypher 性能基准测试

**当前状态**: 已有 `CYPHER_ROW_LIMIT=500` 与大网络聚合，但缺固定性能基准。

**建议实现**:
- 固定一组典型查询：get_net_components、get_power_tree、trace_signal_path、discover_diff_pairs 等
- 记录 p50/p95 延迟
- 对超 500ms 的查询建立优化计划

**验收标准**:
- 有可重复运行的 benchmark 脚本
- 关键查询目标 <500ms 或有明确例外说明

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-4 vLLM 部署评估

**当前状态**: 当前正式基线为 Ollama gemma4:26b。vLLM 因 T4 驱动兼容性问题暂缓。

**建议实现**:
- 驱动升级到 ≥535.104.05 后再评估
- 对比 Ollama 与 vLLM 的吞吐、延迟、稳定性

**验收标准**:
- 有性能对比数据
- 有是否迁移 vLLM 的决策记录

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-5 Neo4j 数据库层只读账号

**当前状态**: 当前通过应用层 `NEO4J_READ_ONLY` / `READ_ONLY_MODE` 做保护。Neo4j Community Edition 不支持数据库级只读用户。

**建议实现**:
- 评估 Neo4j Enterprise 或代理层只读方案
- 保留应用层只读保护作为兜底

**验收标准**:
- 只读账号或等效代理方案可阻止写操作
- graph_tools 的应用层保护仍保留

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-6 遗留 Streamlit 下线

**当前状态**: React 前端为主线，`hardware_ai_expert/web_ui/app.py` 仍作为 fallback。

**建议实现**:
- 确认 React 7 页面稳定覆盖 Streamlit 功能
- 归档或删除 Streamlit 入口
- 更新文档与启动脚本

**验收标准**:
- 无仍依赖 Streamlit 的主流程
- 文档不再把 Streamlit 作为当前 UI 入口

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

### [ ] P2-7 GraphRAG 检索质量基准

**当前状态**: PRD 目标包含 recall@k ≥85%，但目前缺固定 query set、golden answer 与统计脚本。

**建议实现**:
- 建立硬件规格查询基准集
- 标注 golden answer / expected sources
- 输出 recall@k、precision@k、MRR 等指标

**验收标准**:
- 基准可重复运行
- 指标可用于比较 embedding / retriever 改动前后的效果

**完成记录**:
- 完成日期:
- 关联 commit/PR:
- 验证命令/结果:

---

## 已完成但需持续关注

### [x] Quality Guard 核心网络识别改为网络级校验

**完成状态**: 已完成。

**说明**: 已从类型级校验改为网络级连通性校验，实测 Beet7 为 1068/1076 有效连通，8 个疑似 stub 被检出。

**后续关注**: 可继续增强 post-injection VoltageLevel 完整性校验。

---

### [x] WebSocket 地址硬编码修复

**完成状态**: 已完成。

**说明**: 当前 `frontend/src/hooks/useWebSocket.ts` 使用 `window.location` 生成 WebSocket 地址，并支持 `VITE_WS_URL` 覆盖。

**后续关注**: 仍需纳入 P0-3 前后端全面联调。
