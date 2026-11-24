# PRD 与技术实现方案文档审计报告

> 日期: 2026-06-12 | 代码基线: commit `d0c746d` 时期状态
> 范围: PRD_V5.md / TECHNICAL_IMPLEMENTATION_PLAN.md / PRD_GAP_ANALYSIS_V2.md / ROADMAP_NEXT.md / CLAUDE.md
> 方法: 逐项核对文档声称与代码实际状态（交叉验证）

---

## 一、最严重的问题：技术实现方案已严重过期，与代码事实大面积矛盾

`TECHNICAL_IMPLEMENTATION_PLAN.md` 是 V1.0（2026-04-29，基于 PRD V3.0），之后再未更新（变更记录只有一条），如今几乎每一节都与实际不符：

| 文档声称 | 代码实际状态 |
|---|---|
| `datasheet_processor.py` / `datasheet_linker.py` / `design_guide_processor.py` / `web_ui/app.py`「缺失」 | 全部已存在（`datasheet_processor.py`、`graph_rag_bridge.py`、`web_ui/app.py` 均在，且前端已另有 React 版本） |
| `quality_checker.py` 缺失 | 已实现为 `etl_pipeline/quality_guard.py`，含 90%/100% 阈值熔断 |
| Graph Tools「MAX_RESULTS=50 截断装饰器」 | 截断已废除，现为智能聚合 + `CYPHER_ROW_LIMIT=500`（PRD V5 的 6.1 已落地） |
| 13 条规则、5 模板 | 已 24 条规则、9 模板 |
| 完成度 ~65% | Gap 分析 V2 评估为 ~83% |
| Web UI 框架「建议 Streamlit」 | 已迁移到 FastAPI + React + TypeScript，Streamlit 成了遗留双轨 |
| 7.2「待决策」四项 | 实际全部已被事实决策（词典+LLM、规则推导电源树等），文档未回写 |

**结论：这份文档目前不仅无指导价值，还会误导新人按已完成的任务重复排期。需要整体重写到 V2.0。**

另外两处硬伤：

- **明文密码写进文档**：8.2 节直接写了 `password: SecretPassword123`，应改为引用 `.env`。
- **测试口径不可信**：方案和 gap 分析声称「283 用例」，但 `hardware_ai_expert/tests/` 下只有 8 个测试文件，口径需要核实并统一。

## 二、PRD V5 本身的不合理之处

**1. 技术选型与现实长期背离，且从未回写决策**

- PRD 强制要求 `llama-index + llama-index-graph-stores-neo4j`，实际是自研 `graph_rag/`（向量索引还从 ChromaDB 改成了 Neo4j 原生向量索引，连 PRD 的「ChromaDB+Neo4j 双库」架构图都不成立了）。
- PRD 要求 vLLM + Llama3-70B/Qwen，实际因 T4 驱动不兼容用的是 Ollama gemma4:26b。
- PRD Phase 3 指定 Streamlit UI，实际是 React。

这些偏离本身合理（自研方案可工作、vLLM 装不上），但 PRD 一直不修订，导致每次 gap 分析都要把「未用 LlamaIndex」当差距记一遍。**应在 PRD 中正式决策：承认自研 GraphRAG / Ollama / React 为基线，把 LlamaIndex 与 vLLM 降级为可选优化项，否则永远「欠债」。**

**2. 关键指标定义模糊，实现时被偷换口径**

- 「核心网络识别率 < 100% → 阻断」没有定义核心网络清单和统计口径。`quality_guard.py` 实际实现是 `found_types / expected_types`（类型级：只要每种电压类型出现过一次就算 100%），这是个非常宽松的代理指标，和「每个核心网络都被识别」完全不是一回事。
- 电压标注率三个口径并存：全网 20.7%、POWER 网 95.7%、ROADMAP 里 17.3%，文档间互相矛盾。
- AMR 覆盖率同样混乱（99.8% vs 83.1%，gap 分析自己注明「统计口径可能不同」）。

**3. PRD 结构性残缺，与 Gap 分析引用错位**

PRD_GAP_ANALYSIS_V2 引用了「§8/10 Web UI」「§12 测试与质量」「§14.2 Neo4j 只读账号」，但 PRD_V5 只有 8 章、141 行，根本没有 §10/§12/§14。说明要么 V5 是删节版、完整版丢失，要么 gap 分析对着另一份文档做的。**PRD 缺失的章节正是最该有的内容：非功能需求（性能/并发/响应延迟）、安全要求（只读账号在 Community Edition 下如何落地）、测试与验收标准、Web UI 需求细化。**

**4. 已实现的核心能力 PRD 完全没有覆盖**

多项目数据隔离（project_id 全链路）、多 Agent 编排、前后端分离架构、WebSocket 流式对话、Tier3 公网检索、规则热更新——gap 分析列了 10 项「超出 PRD 的功能」。功能持续超出 PRD 意味着 PRD 已失去需求约束力，演进靠 issue 驱动而非需求驱动。

**5. Embedding 选型这一最大质量风险，PRD 只字未提**

当前用 gemma4:26b（生成模型）产 embedding，是 GraphRAG 检索质量的头号风险（gap 分析也列为高风险），但 PRD 对 embedding 模型选型、检索质量验收指标（如 recall@k）没有任何规定。

**6. 路线图全部过期**

PRD V5 的 Phase 1-3（自 4/30 起 6 周）已到期，内容大多完成或被超越；技术方案的 Phase 1-4 同样如此；`ROADMAP_NEXT.md`（5/2 基线）里的 P0（Pin.Type=0%、AMR 崩溃）也早已修复。三份路线图互相冲突且没有一份反映当前状态——当前真实的待办其实在 PRD_GAP_ANALYSIS_V2 第六节。

## 三、文档体系层面的问题

根目录有 10+ 份分析/状态文档（PRD_GAP_ANALYSIS V1/V2、PROJECT_ANALYSIS、PROJECT_ANALYSIS_REPORT、PROJECT_STATUS_ANALYSIS、PROJECT_STATUS_REPORT、REMAINING_WORK_ANALYSIS、ROADMAP_NEXT…），数据互相矛盾、无单一事实来源。`CLAUDE.md` 也过期了（仍写 65% 完成度、13 条规则、MAX_RESULTS=50、ChromaDB empty）。

## 四、建议的整改优先级

1. **P0 — 重写 `TECHNICAL_IMPLEMENTATION_PLAN.md` 至 V2.0**：以当前代码为基准更新架构图（FastAPI+React+WS、AgentOrchestrator、自研 graph_rag、Neo4j 向量索引）、模块状态表、路线图；删除明文密码。
2. **P0 — PRD 升级到 V5.1**：回写技术选型决策（自研 GraphRAG/Ollama/React 为正式基线）；补全非功能需求、安全、测试验收章节（修复与 gap 分析的引用断裂）；把多项目隔离等已实现能力纳入需求；明确定义「核心网络识别率」「电压标注率」「AMR 覆盖率」的统计口径。
3. **P1 — 文档收敛**：过期分析文档移入 `archive/`，保留 PRD + 技术方案 + 最新 gap 分析三份活文档；同步更新 `CLAUDE.md`。
4. **P1 — 指标核实**：核实测试用例数（8 文件 vs 283 用例）、统一覆盖率口径，并将 Quality Guard 的「核心网络识别」从类型级改为网络级校验。

---

*报告由文档与代码交叉验证生成，2026-06-12*
