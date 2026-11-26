# 待办工作总览（2026-11-12 核查）

> **基线**：分支 `work/legacy-tasks-20260704` @ `4994f52`（2026-10-31）
> **核查方式**：实跑测试 / 查询服务健康 / 调 API 读真实数据统计 / 检查 git 状态 / 复核基准产物
> **一句话结论**：PRD 范围内的**功能开发已完成**（约 95%），**交付就绪度约 85%**；剩余 3 项阻塞交付、4 项质量可靠性、5 项能力完善、2 项工程卫生。

---

## 一、当前快照（本次实测，非文档转述）

| 项目 | 实测结果 | 备注 |
|------|----------|------|
| Neo4j | ✅ running，6ms | bolt://localhost:7687 |
| Ollama | ✅ running，2ms | gemma4:26b，2×T4 |
| API | ✅ running | :8501，`/api/v1/system/status` 正常 |
| 前端 | ✅ HTTP 200 | `dist/` 构建于 2026-10-27 |
| ChromaDB | ⚠️ **degraded** | 服务未启动；Tier2 由 Neo4j 向量索引兜底 |
| 测试 | ✅ **418 passed / 15 deselected**，52.41s | 15 个为 `-m "not llm and not live"` 主动排除 |
| 覆盖率 | **46%**（13,559 语句 / 7,362 未覆盖） | 目标 60%；较 10-14 的 43.99% 有提升 |
| 数据规模 | 25,376 器件 / 99,140 引脚 / 16,318 网络 | 多项目聚合口径 |
| PartType 覆盖 | 99.5%，UNKNOWN 121 | 目标 <5%，达标 |
| 代码规模 | 后端 153 个 py / 43,300 行；前端 52 个 ts(x) / 4,824 行 | — |
| Git 状态 | 当前分支领先 `master` **42 个提交** | master 仍停在 `d0c746d`（2026-06-06） |
| 未跟踪文件 | `scripts/trace_engine.py` | 10-31 新增的轮次/工具冗余排查工具 |
| CI | `.github/workflows/offline-tests.yml` 存在 | 仅离线测试 |

---

## 二、总体判断

**已完成（无需再排期）**

- P0 四项：BOM CSV/xlsx/xls 导入、bge-m3 embedding 切换、前后端 API schema 核对、HITL Datasheet→Neo4j 落库
- 核心能力：ETL、Neo4j 图谱、Quality Guard、24 条审查规则、ReAct Agent + Self-Correction、自研 GraphRAG（三级检索 + Louvain 社区）、React/FastAPI 七页面、HITL 审批、多项目隔离、规则热更新、Tier3 公网 MPN 检索
- 10 月新增：Hermes Agent 接入（运行/停止/多审批卡片/SSE/灰度回退）、MCP Server（批量 query_graph + neighborhood 子图）、共因失效查询 180s→0.11s、run 级埋点与指标聚合、双引擎基准与验收门脚本、systemd 三单元部署

**未完成的是"验证与工程化"，不是"功能没写"**：浏览器级联调、基准样本量、覆盖率、发布基线合并。

---

## 三、待办清单

### P0 — 阻塞交付（3 项）

#### P0-1 合并开发分支，统一发布基线
- **现状**：`work/legacy-tasks-20260704` 领先 `master` 42 个提交（2026-09-22 → 10-31），master 停留在 6 月的 `d0c746d`。
- **影响**：任何人按 master 拉代码都拿不到 Hermes 接入、MCP、性能修复、systemd 部署，等于交付物与主线不一致。
- **动作**：
  1. 确认 42 个提交的合并方式（建议 `--no-ff` 合并到 master，保留历史）
  2. 合并前在干净环境跑一次 `pytest` + `npm run build`
  3. 打 tag（如 `v0.9.0-rc1`），更新 `CLAUDE.md` 完成度与基线 commit
- **验收**：master 与开发分支内容一致；干净 clone 后测试全过、`bash scripts/start_dev.sh` 可起服务
- **预估**：0.5～1 天（主要是回归验证）

#### P0-2 七页面浏览器人工联调
- **现状**：接口层已全量核对（2026-10-13），但从未在浏览器逐页面点过。PRD 验收门槛明确要求。
- **影响**：接口通 ≠ 交互对。图表渲染、WebSocket 流式、上传交互、错误提示都属未验证区。
- **动作**：按下列清单逐项点验并记录截图/问题：
  - Chat：普通问答 + WebSocket 流式 + 停止按钮 + 刷新恢复
  - Review：执行审查、违规列表、严重等级、规则详情
  - HITL：Pending 列表、单条/批量 Approve/Reject、Datasheet 参数沉淀页签
  - Knowledge：上传 PDF、索引状态、检索结果
  - ETL：网表 + BOM 上传、Preview、Run、进度、质量报告、项目切换/删除
  - Graph：电源树、电源链路、故障溯源、共因失效、组件关系
  - System：四服务真实状态、数据统计口径
- **验收**：七页面核心操作全部通过，问题清单闭环；把结果回写本文档
- **预估**：1 天（含修复小问题）
- **✅ 2026-11-24 已完成**（Playwright 无头浏览器，脚本 `scripts/ui_smoke_pages.py`，Chat 另跑两引擎）：
  - 结果：ETL 新建项目/预览/导入/删除、Review、Graph、Knowledge 上传+检索、HITL、System 全部 PASS；
    Chat 经典引擎（WebSocket 流式，24s）与 Hermes 引擎（12s，MCP 工具调用）均返回正确网络列表；无 console 错误、无 4xx/5xx。
  - 联调中发现并修复的问题：
    1. **新建项目不出现在项目列表**：`list_projects()` 读 `Project.id`，ETL 写的是 `Project.project_id`；
       前端随后把当前项目重置回 `default`，导致「导入到新项目」实际写进了 default。改为同时读两种字段并补上只存在于 Component 上的项目（如 `legacy`）。
    2. **刷新页面丢失当前项目**：project store 未持久化，刷新后回到 default（全库），Review/Graph 会对全部项目执行。已改为 localStorage 持久化。
    3. **全库审查阻塞整个 API**：`/review/run` 在 async 路由里同步执行约 130s，期间其他请求全部卡住。改为线程池执行，实测审查期间 health 2ms 返回。
    4. **图谱可视化不分项目**：`/graph/visualize` 无 project_id，同名位号（如 U1）会把其他项目的器件画在一起。请求增加 `project_id`，查询按项目过滤；节点计数不再把 DOT 的 `node [...]`/`edge [...]` 默认属性行算作节点。
  - 已知限制（非缺陷）：Hermes 灰度期只绑定 `HERMES_BOUND_PROJECT=legacy`，其他项目在 Hermes 下返回 409，需切回经典引擎。
  - 未覆盖：HITL 审批按钮（当前无待审批数据，Hermes 审批卡片由 `scripts/ui_e2e_agent.py` 覆盖）。
  - 遗留 lint：`ChatContainer.tsx` handleSend 缺 `scopedProjectId` 依赖（warning），`System/index.tsx` 多余的 eslint-disable（error）；均为既有问题。

#### P0-3 双引擎基准补样至 ≥20 次/引擎
- **现状**：`bench_report.py` 的 `MIN_SAMPLES = 20`，实际只有 2～6 次，结论一直是 `insufficient_samples`。
  - 小样本 smoke：p95 比值 0.11（hermes 更快）
  - C1/C2 三轮：p95 比值 1.49（刚好卡在 ≤1.5 门槛）
  - 波动极大，不能作为"可以切换引擎"的依据
- **动作**：
  1. `python scripts/bench_engines.py` 按标准任务集跑满 20 次/引擎（C1 review、C2 diagnosis、A1 qa、B1 graph）
  2. `python scripts/bench_report.py logs/bench_runs.jsonl` 出报告
  3. 若 p95 > 1.5× 或成功率劣化，先定位再决定灰度比例
- **验收**：报告结论为 PASS（样本量、成功率、p95、工具覆盖率四项全绿）
- **预估**：1～2 天（受 Ollama 推理速度限制，diagnosis 单次约 2 分钟）
- **2026-11-24 补样完成，验收门 FAIL**（`logs/bench/bench_report_20261124.md`，7 题 × 3 轮，每引擎 21 次，当前代码）：

  | 引擎 | 严格成功率 | p50 | p95 | 工具均值 |
  |---|---|---|---|---|
  | legacy | 76.2%（16/21） | 65.7s | 168.2s | 3.3 |
  | hermes | 100%（21/21） | 60.0s | 407.5s | 9.0 |

  - 样本量 PASS，成功率 PASS，**p95 比值 2.42，超过 1.5 的门槛**。
  - 慢在 diagnosis（C2）：Hermes p50 407s、平均 18.7 次工具调用；review（C1）平均 23 次工具调用。qa 和 graph 题 Hermes 反而更快（qa p50 23s vs 79s）。
  - legacy 的 p95 只统计成功样本（B2 3/3、C2 2/3 失败）。把失败样本也算进去，legacy p95 为 171s，比值 2.38，仍不达标。
  - 跑基准期间（18:22～18:35）本机同时在跑离线测试，有少量 CPU 争用；最慢的一次（C2 407s）发生在测试结束之后，不是争用导致的。
  - **结论**：现在不能把 Hermes 设为默认引擎。下一步应先用 `scripts/trace_engine.py --task C2 --engine hermes` 查清诊断/审查为何要调 18～25 次工具，再复测。
- **2026-11-25 排查结果**（trace：`logs/trace/C2-hermes-20261125a.jsonl`、`C1-hermes-20261125a.jsonl`；逐轮数据取自 Hermes `state.db`）：
  - **慢的不是工具，是模型轮次和推理**。C2 共 363s：工具执行合计约 25s（7%），其余是 6 轮 LLM 调用。
    输出 13.2k token，其中可见答案只有 2.9k 字，推理文本 3.1 万字（最后一轮单轮 1.4 万字、约 110s）。输入 5.3 万 + 缓存读 12 万 token。
  - Hermes 用的是远端 `DeepSeek-V4.1-Flash`（`reasoning_effort: medium`），经典引擎用本地 gemma4，所以这组基准同时比较了引擎和模型。
  - **C1 调 21 次工具的直接原因是 bug**：MCP `run_review` 读了不存在的 `item.message` 字段，违规样例描述全空，
    且 10 条样例全部来自同一条规则。模型看不到其他规则的明细，只好按 rule_id 逐条再调了 14 次。**已修**：
    每条规则给 2 条去重样例（指定规则时给 3 条），带位号、网络和描述。MCP Server 是 Hermes 网关的常驻子进程，重启网关后生效。
  - C2 的多余调用：`project_overview`（9.4k 字）、`i2c_devices`（13k 字）、全项目 `run_review`、两次未命中的知识检索，
    以及 `tool_describe`、`list_prompts`、`list_resources` 这类元工具。`query_graph` 邻域查询默认 depth=2，单次返回 28k 字，
    且 JSON 再被包一层字符串，引号全部转义，token 进一步膨胀。
  - **建议（按收益排序，均待确认）**：① 重启网关让 run_review 修复生效后复测 C1；② schematic profile 的 `reasoning_effort`
    试降为 `low`，对比答案质量；③ 邻域查询默认 depth 改 1，结果改为紧凑文本、不做 JSON 套 JSON；
    ④ 在 Hermes 侧关掉 schematic MCP 的 list_prompts/list_resources；⑤ 为诊断任务给固定的工具顺序提示（邻域 → root_cause → power_chain → 作答）。
  - 顺带发现：profile 里 `SCHEMATIC_ENABLE_WRITE_TOOLS: "1"`，与设计文档「写工具默认关闭」不一致；
    `POWER_1V8_DECAP` 把 `*_1V8_RGMII_TXD1` 这类信号网络当成 1.8V 电源网络，属规则误报。
  - **2026-11-26 网关重启后复测**：
    - C1（审查）3 次：工具 3 / 6 / 3 次（原 21），耗时 71s / 101s / 74s（原 130s），LLM 轮次 3～5（原 8），输出 token 2.5k～4.4k（原 5.7k）。
      答案按规则列出了具体位号和网络。6 次那一轮仍调了 `list_resources`/`list_prompts` 和一次补查。
    - C2（诊断）2 次：工具 15 / 16 次，耗时 507s / 483s，LLM 8～9 轮，输出 1.9 万～2.0 万 token。这个修复对诊断题无效（诊断题本来就不靠 run_review），
      瓶颈仍是轮次和推理长度，需按上面建议 ②③⑤ 处理。
  - **2026-11-26 推理档位**：`/api/v1/agent/runs` 支持 `reasoning_effort`（low/medium/high，其余 422），Chat 页 Hermes 模式下可选
    「自动 / 快速 / 标准 / 深入」，浏览器记住上次选择；运行指标记录实际档位。low vs medium 各 3 轮（中位耗时）：
    A2 问答 29s vs 43s，B3 图谱 61s vs 98s，C1 审查 44s vs 106s，C2 诊断 134s vs 364s；low 的工具调用更少，C2 答案覆盖的位号与排查要点相当。
    **「自动」默认改为 low**（见 `agent_runs._TASK_REASONING_DEFAULT`）。尚未用 low 重跑与经典引擎对比的完整验收门基准。

---

### P1 — 质量与可靠性（4 项）

#### P1-1 测试覆盖率 46% → 60%
- **缺口分布**（本次 coverage 实测）：
  - `agent_system/agent_core.py`（622 行，legacy fallback，0%）
  - `agent_system/storage_dispatcher.py`（171 行，legacy Streamlit 路径，0%）
  - `etl_pipeline/run_real_etl.py` / `main_etl.py`（脚本入口）
  - `etl_pipeline/refine_passive_types.py`（47 行，0%）
  - `agent_system/parsers/*`（legacy 文档解析器）
- **前提决策**：先定 legacy 代码去留（见 P2-4）。删除/归档后再补覆盖率，性价比最高。
- **动作**：优先补主线未覆盖分支（API routers 边界、review_engine 模板、graph_rag 检索路由），不为 legacy 代码补测试
- **验收**：`pytest --cov` 总覆盖率 ≥60%，且主线模块（api / review_engine / graph_rag）≥80%
- **预估**：3～5 天

#### P1-2 Neo4j 备份 + 恢复演练
- **现状**：`scripts/recovery.py` 只有计划生成，从未真实执行过恢复。
- **动作**：在隔离实例（不同端口/不同 data 目录）执行一次 dump → restore → 校验节点/关系数
- **验收**：恢复后 Component/Net/Pin 计数与源库一致，写一份 runbook（`docs/ops/`）
- **预估**：0.5～1 天

#### P1-3 Neo4j 数据库层只读账号
- **现状**：仅应用层 `READ_ONLY_MODE` 环境变量；数据库账号仍是全权限。
- **背景**：Community Edition 不支持 DB 级只读用户，需评估是升级 Enterprise / 还是接受现状
- **验收**：明确结论并写入文档；若实施，Agent 查询路径使用只读凭据
- **预估**：0.5 天（决策为主）
- **✅ 2026-11-24**：不升级 Enterprise、不靠账号。实测 Community 版中 `graph_reader` 等账号没有角色、实际可写；
  改为 `NEO4J_READ_ONLY=true` 时以 `READ_ACCESS` 会话执行查询，写语句由服务端拒绝（已实测）。详见 `docs/ops/NEO4J_READONLY.md`。

#### P1-4 核心数据指标真实复核
- **现状**：AMR 耐压覆盖率 99.8% 来自 commit message，未连真实库抽样；电压标注率、核心网络识别率同样陈旧（口径为单项目 12,688 器件时代）。
- **动作**：基于当前 25,376 器件多项目数据跑 `scripts/check_data_quality.py`，抽样 100 个电容核对降额判定；输出报告到 `tools/benchmark_reports/`
- **验收**：三项指标有真实数字 + 抽样明细；差异 >2% 时定位原因
- **预估**：1 天
- **✅ 2026-11-24**：报告 `hardware_ai_expert/tools/benchmark_reports/data_quality_review_2026-11-24.md`。要点：
  - AMR 电容耐压「99.8%」属实，但其中 14.3% 是封装+容值经验表推断；只算真实数据（`amr_data.yaml`）为 **85.6%**。
  - 节点上存储的 `voltage_rating` 属性：legacy 80.9%，beet7_acceptance **0%**。
  - 核心网络连通 100%，核心网络电压已标注 91.1% / 89.7%；全网电压标注率 20.7% / 19.4%。
  - 抽样 100 颗：3 颗疑似 `amr_data.yaml` 耐压记错（10V 挂 12V 轨）；1 颗差分检测电容被按最高网络电压误判，AMR 应改用两端电压差。

---

### P2 — 能力完善（5 项）

#### P2-1 Tier2 PLM 适配器 + mock 契约测试
- 现状：Octopart / Mouser 接口是 stub；无厂商资料/凭据。
- 动作：补可配置适配器 + mock 契约测试，文档明确标注"非真实集成"
- 预估：1～2 天
- **✅ 2026-11-24 核实已具备**：`knowledge_router.InternalPLMRetriever` 已是可配置适配器（`PLM_ENDPOINT` / `PLM_TOKEN` / 五个 `PLM_*_FIELD` 字段映射，未配置时 fail-closed），
  `tests/test_task11_plm_fallback.py` 7 个 mock 契约测试覆盖命中缓存、未命中、超时/失败、配置缺失、降级到公网且只发 MPN。
  **非真实集成**：没有 PLM 接口地址和凭据，接入真实系统时只需配置环境变量并补一次 live 验收。
  `PublicMPNRetriever`（Octopart/Mouser stub）已被 `tier3_retriever.py` 取代，可随 P2-4 一并清理。

#### P2-2 Tier3 搜索后端接入
- 现状：`tier3_retriever.py` 用 9 个供应商模板直连；SearXNG / Firecrawl 未接。
- 动作：评估是否值得接（当前模板已覆盖主流原厂），不接就明确标注能力边界
- 预估：1 天（评估） / 2～3 天（实施）
- **结论（2026-11-24）：暂不接入**。理由：① 通用搜索需要把 MPN 发给第三方元搜索/爬取服务，扩大了外发面；
  ② 9 个原厂模板已覆盖主流料号，缺口是小众型号，靠 HITL Datasheet 沉淀补齐更可控。
  能力边界：Tier3 只能命中模板内厂商的公开产品页/PDF，且默认 `TIER3_ENABLED=false`。

#### P2-3 vLLM 决策
- 现状：阻塞点是驱动只提供 CUDA 12.1/12.2，装不上近期 vLLM 要求的 CUDA 12.6+ wheel（**不是**硬件/驱动不兼容）。
- 选项：① 升级驱动 + CUDA 12.6；② 退回 vLLM 0.2.x + CUDA 11.8；③ 继续用 Ollama（51.9 tok/s）
- 建议：先量化"51.9 tok/s 是否真的不够"，再决定是否动基础设施
- 预估：决策 0.5 天
- **结论（2026-11-24）：继续用 Ollama**。当前是单机少量用户，延迟主要来自 Agent 的工具轮次和长输出，
  不是单流吞吐；vLLM 的收益集中在并发吞吐，换来的是驱动/CUDA 升级的停机风险。并发用户超过 2～3 个、或排队成为瓶颈时再评估。

#### P2-4 Legacy 代码收口
- 范围：`web_ui/`（Streamlit）、`agent_core.py`、`storage_dispatcher.py`、`parsers/`
- 动作：确认无用户路径依赖后，删除 / 移到 `archive/` / 显式标注 Legacy
- 收益：直接抬高覆盖率分母质量，减少维护与误判
- 预估：1 天（含依赖检查）
- **依赖检查（2026-11-24）**：`agent_core` / `agent_orchestrator` / `llm_intent_router` / `storage_dispatcher` /
  `kb_persistence` / `datasheet_processor` / `parsers/` 只被 `web_ui/`（Streamlit）引用；
  `fix_p0_issues` 等 8 个模块是无人 import 的一次性脚本。二者已在 `.coveragerc` 中排除，覆盖率口径与既有的 `web_ui/` 排除一致。
  **不能直接删 `web_ui/`**：`/api/v1/graph/visualize` 仍从 `web_ui/sub_pages/graph_viz.py` 引用 DOT 生成函数，
  需要先把这些函数迁到 `agent_system/` 再归档 Streamlit。删除/归档留待确认后执行。

#### P2-5 工具与文档补录
- `scripts/trace_engine.py` 提交入库（SSE 事件序列抓取，排查轮次/工具冗余）
- `logs/bench/` 基准产物纳入文档索引；`docs/README.md` 增加本文档入口
- 预估：0.5 天

---

### 工程卫生（2 项）

#### H-1 历史提交中的凭据处理
- **现状**：`.env` 曾被跟踪，历史 commit 中含真实格式的 `NEO4J_PASSWORD` / `NEO4J_READONLY_PASSWORD`；工作树已 `git rm --cached`，但历史仍在。
- **动作**：① 轮换 Neo4j 密码；② 评估是否 `git filter-repo` 清史（高风险，需协调所有协作者）
- **建议**：至少先完成密码轮换（低成本、高收益）

#### H-2 ChromaDB 状态收口
- **现状**：未启动，System 页面显示 `degraded`，容易让使用者误判系统故障。
- **动作**：二选一 —— 补 systemd 单元真正跑起来；或从健康检查中移除并明确"Tier2 已由 Neo4j 向量索引替代"
- **预估**：0.5 天
- **✅ 2026-11-24**：选择让它常驻。原因：`KnowledgeRouter` 连不上服务端时会静默回退到另一份本地库
  （`hardware_ai_expert/data/chroma_db`），离线期间写入的知识在服务恢复后查不到，"由 Neo4j 兜底"的说法不成立。
  已新增 `deploy/systemd/chromadb.service`（安装需 sudo），当前由 `scripts/start_dev.sh` 拉起，健康检查 4/4。
  回退库里 10-27 写入的数据尚未合并回服务端，需人工确认后处理。

---

## 四、建议排期（3 周）

| 周次 | 内容 | 产出 |
|------|------|------|
| W1 | P0-1 分支合并 + P0-2 七页面联调 + H-2 ChromaDB 收口 | 可交付基线 tag + 联调报告 |
| W2 | P0-3 基准补样 + P1-4 数据指标复核 | 基准 PASS 报告 + 数据质量报告 |
| W3 | P1-1 覆盖率 + P1-2 备份演练 + P1-3 只读账号决策 | 覆盖率 ≥60% + 恢复 runbook |
| 按需 | P2-1～P2-5、H-1 | — |

**里程碑建议**：W1 结束打 `v0.9.0-rc1`，W3 结束视结果打 `v1.0.0`。

---

## 五、验收命令

```bash
cd /data/schematic_agent

# 1. 测试
source .venv/bin/activate && python -m pytest -q

# 2. 覆盖率
python -m pytest -q --cov=hardware_ai_expert/agent_system \
  --cov=hardware_ai_expert/api --cov=hardware_ai_expert/etl_pipeline

# 3. 服务
systemctl status schematic-api neo4j ollama --no-pager
curl -s http://localhost:8501/api/v1/system/status | python3 -m json.tool

# 4. 前端构建
cd frontend && npm run build

# 5. 双引擎基准（补样）
cd /data/schematic_agent && python scripts/bench_engines.py
python scripts/bench_report.py logs/bench_runs.jsonl

# 6. 数据质量
python scripts/check_data_quality.py
```

---

## 六、本次核查证据

```
$ systemctl is-active schematic-api neo4j ollama
active
active
active

$ pytest -q
418 passed, 15 deselected, 11 warnings in 52.41s

$ pytest --cov=... (TOTAL)
13559 statements, 7362 missed, 46%

$ curl http://localhost:8501/api/v1/system/status
Neo4j running 6ms | Ollama running 2ms | ChromaDB degraded | API running
components 25,376 | pins 99,140 | nets 16,318 | part_type_coverage 99.5 | UNKNOWN 121

$ git log --oneline master..HEAD | wc -l
42
$ git log -1 --format='%h %ad' --date=short master
d0c746d 2026-06-06

$ bench_report.py (latest)
legacy 2 runs / hermes 2 runs → 结论 insufficient_samples
（MIN_SAMPLES = 20）
```

---

_文档生成：2026-11-12 15:12（Asia/Shanghai）｜核查人：Jarvis_
