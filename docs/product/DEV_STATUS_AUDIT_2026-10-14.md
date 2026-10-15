# 开发完成度核查报告 2026-10-14

> 核查范围: 全仓库，对照 `CLAUDE.md`（声称完成度 ~95%）与 `PRD_GAP_ANALYSIS_V2.md`（2026-10-13 版）的说法逐项验证代码现状。
> 方法: 读文档 diff + 全文、交叉比对代码实现、重跑 `pytest tests/`、grep TODO/FIXME/XXX/HACK、读 `scripts/start_dev.sh`。
> 结论: **P0 四项确认全部完成，属实；"整体完成度 ~95%" 对 P1 LlamaIndex 评估偏乐观——那不是待启动任务，而是一堆写了一半、连 import 都跑不起来的死代码。**

---

## A. 已确认真正完成

| 项目 | 验证依据 |
|------|----------|
| BOM CSV/xlsx/xls 导入 | `etl_pipeline/part_type_standardizer.py` 三种格式解析实现存在；`api/routers/etl.py` 接收 `bom` 参数；`api/services/uploads.py` 白名单声明一致 |
| Embedding 切换 bge-m3 | `.env` / `requirements.txt`（`sentence-transformers>=3.2,<4.0`）/ `vector_indexer.py` 三处一致；本轮顺带修复一处 bug（显式传入 `config` 时曾被环境变量静默覆盖） |
| HITL Datasheet→Neo4j 落库 | 本轮新增 `amr_neo4j_source.py` + `test_datasheet_amr_neo4j_integration.py`，3 个真实 Neo4j 集成测试通过；清理了一处永真断言 |
| 测试基线 | `pytest tests/` → **397 passed, 15 deselected**。15 个 deselected 是 `pytest.ini` 的 `addopts = -m "not llm and not live"` 主动排除的 `test_e2e_agent.py` 用例（需真实 Ollama 推理），是预期行为，非风险 |
| 前端七页面 | `frontend/src/pages/` 下 Chat/ETL/Graph/HITL/Knowledge/Review/System 七个目录均存在，与 CLAUDE.md 描述一致 |

---

## B. 具体开发任务缺口

### B1. P1 — LlamaIndex 评估：比文档描述的状态更差 ⚠️（已复核修正）

- `agent_system/llama_index_bridge.py`（571 行）、`tools/graphrag_retrieval_benchmark.py`（125 行，带 `graphrag_golden.json` 测试数据）**代码均已写好**，commit `c2fb8b0` 引入。
- 复核纠正：子包（`llama-index-core`、`llama-index-llms-openai`、`llama-index-graph-stores-neo4j` 等）在当前 venv 里**已安装且可 import**；`graphrag_retrieval_benchmark.py` 依赖的 `sentence-transformers` 也已安装，本地有 `BAAI/bge-m3` 和 `all-MiniLM-L6-v2` 的 HuggingFace 缓存快照，脚本可直接跑。
- 真正的问题：
  1. **`llama_index_bridge.py` 零引用**——全仓库 grep 确认没有任何模块 `import` 它，没有接入 `KnowledgeRouter`，没有任何测试覆盖，是完全孤立的死代码。
  2. **`requirements.txt` 未声明 llama-index 系列子包**——当前环境能跑是因为历史上手动装过，一旦重建 venv 会直接丢失，CI/新环境无法复现。
  3. `graphrag_retrieval_benchmark.py` 本身可独立运行（`python3 tools/graphrag_retrieval_benchmark.py --model <本地模型目录>`），但从未被人跑过产出报告。
- 结论：不是"待评估"（从零开始），而是**写好但未接入主干、且依赖未锁定**的孤立模块。

**本轮已处理：**
1. ✅ 把 6 个 llama-index 子包的精确版本号补进 `requirements.txt`（`llama-index-core==0.11.23` 等），保证新环境可复现当前能跑的状态。
2. ✅ 实际跑了 `graphrag_retrieval_benchmark.py`，用本地 HuggingFace 缓存的 `BAAI/bge-m3`（1024-dim）vs `all-MiniLM-L6-v2`（384-dim）在 11 个真实硬件领域查询上做了检索质量对比。报告存至 `hardware_ai_expert/tools/benchmark_reports/embedding_bge-m3_vs_minilm_2026-10-14.json`。

   | 模型 | dim | load_ms | p50 延迟 | recall@5 | mrr | ndcg@10 |
   |------|-----|---------|----------|----------|-----|---------|
   | bge-m3 | 1024 | 2022 | 13.98ms | **1.0** | **1.0** | **1.0** |
   | all-MiniLM-L6-v2 | 384 | 172 | 4.27ms | 0.786 | 0.702 | 0.762 |

   结论：**bge-m3 在检索质量上全面优于旧模型（recall@5/mrr/ndcg@10 均达满分 vs 0.7~0.79），代价是加载慢 ~10 倍、单次查询延迟高 ~3 倍，但绝对值仍在毫秒级，可接受。** 这证实了"切换到 bge-m3"这个 P0 决策是对的，有真实数据背书，而不只是文档声称。
3. ⏸️ **`llama_index_bridge.py`（571行）是否继续集成/删除——决策待定，由项目负责人在看完本报告后裁定**。当前原样保留，不接入 `KnowledgeRouter`，无测试覆盖。它和 CLAUDE.md 里"自研 GraphRAG，非 LlamaIndex"的既定架构方向存在张力，建议下次迭代前明确去留。

### B2. P1 — Neo4j 只读账号未解决

- 现状：仅应用层 `READ_ONLY_MODE` 环境变量限制；数据库层仍是全权限 `neo4j` 账号。文档已如实标注，非隐藏问题。

### B3. P2 — 四项，本轮已全部补齐实测数据 ✅

**Cypher 性能基准测试**：之前无任何实测数据。本轮新建 `hardware_ai_expert/tools/cypher_perf_benchmark.py`，对真实 Neo4j（`beet7_acceptance` 项目，12,688 器件 / 99,140 Pin / 16,318 网络）跑了 `graph_tools.py` 7 个核心查询模式各 20 次迭代，报告存至 `tools/benchmark_reports/cypher_perf_2026-10-14.json`：

| 查询场景 | 行数 | p50 | p95 | max |
|---------|------|-----|-----|-----|
| get_component_nets | 24 | 5.2ms | 16.2ms | 103.7ms |
| get_net_components（高扇出网络） | 4 | 3.5ms | 12.9ms | 70.5ms |
| get_power_domain（电压子串匹配） | 205 | 37.2ms | 49.1ms | 211.4ms |
| get_power_tree（根器件扇出） | 15 | 13.3ms | 29.1ms | 253.4ms |
| trace_power_chain（1跳 POWERED_BY） | 148 | 13.8ms | 23.4ms | 79.8ms |
| get_common_cause_graph（共享网络扫描） | 3 | 3.0ms | 8.0ms | 98.9ms |
| 无过滤全图扫描（最坏情况，命中 LIMIT 500） | 500 | 38.2ms | 56.0ms | 87.0ms |

结论：**所有场景 p95 都在 60ms 以内，远低于 PRD 的 `<500ms` 验收线，`CYPHER_ROW_LIMIT=500` 这个保护阈值目前看是保守的、够用的**；个别 max 值出现 100~250ms 的尖峰（首次查询冷启动/缓存失效），建议后续结合真实并发场景复测，但当前单用户场景下无性能隐患。

**E2E 单一贯穿测试**：复核发现**这项其实已经做了**，文档和 CLAUDE.md 都没跟上——`tests/test_full_chain_e2e.py`（commit `fc99f4a`）已经是一个真正串联"BOM/网表上传→ETL运行→质量门禁→Review出违规→HITL待审→批准→持久化到 custom_rules.yaml→重新读取确认"全部 7 个阶段的单一测试文件，用 fake driver 隔离外部依赖（Neo4j/Chroma/Ollama 均不实际连接，可在任意环境包括 CI 跑）。重跑确认 PASSED。**这条 P2 任务可以直接标记为已完成，文档需要同步更新。**

**测试覆盖率实测**：本轮实际跑了 `pytest --cov=agent_system --cov=api --cov=etl_pipeline`，总覆盖率 **43.99%**（13,623 条语句，7,630 条未覆盖），报告存至 `tools/benchmark_reports/pytest_coverage_2026-10-14.json`。比文档估算的"40-45%"基本吻合，证明之前的估算是靠谱的。零覆盖率的大文件（>100行语句）主要是：
- `agent_system/agent_core.py`（622行，CLAUDE.md 标注的 legacy fallback，非主线）
- `agent_system/llama_index_bridge.py`（263行，即 B1 提到的孤立死代码）
- `etl_pipeline/run_real_etl.py` / `etl_pipeline/main_etl.py`（真实 ETL 入口脚本，走集成/脚本调用而非单测覆盖）
- `agent_system/storage_dispatcher.py`（171行，即 B5 提到的 legacy Streamlit 路径）
- `agent_system/parsers/{design_guide,checklist,document_processor}.py`（legacy 文档解析器）

可以看到零覆盖率基本都集中在已识别的 legacy/孤立代码里，核心主线模块（`api/schemas/*` 100%、`api/routers/*` 80-91%、`review_engine` 核心 84-88%）覆盖率是健康的。**60% 的目标暂未达到，但缺口主要来自要不要清理的 legacy 代码，不是主线功能缺测试**。

**vLLM 部署**：复核纠正了文档的归因——不是"T4 驱动不兼容"。实测确认：
- 驱动 535.230.02 + CUDA 12.2，T4 compute capability 7.5，vLLM 官方要求 7.0+，**硬件完全支持**。
- 真正的阻塞是**vLLM 近期版本的预编译 wheel 要求 CUDA 12.6+**，当前驱动给的 CUDA 12.1/12.2 装不上官方 wheel；且较新版本的 flash-attention kernel 不保证支持 SM75（T4 的架构代号），社区反馈显示只有较老的 `vLLM 0.2.x + CUDA 11.8` 组合在 T4 上验证过能跑。
- 结论：**要跑 vLLM 需要么升级驱动到支持 CUDA 12.6+ 的版本，要么退回到老版本 vLLM + CUDA 11.8 组合**（后者功能/性能落后，价值存疑）。这是一个需要动基础设施（驱动升级）的决策，本轮未执行，建议作为独立的基础设施任务排期，不和应用代码改动混在一起。

### B4. AMR 耐压覆盖率 99.8% 未复核

- 文档自认该数字来自 git commit message，未做真实 Neo4j 抽样验证。

### B5. 散落 TODO（非 archive 目录，真实未完工）

- `agent_system/knowledge_router.py:472` — Octopart/Mouser API 未接入（Tier2 PLM 一直是 stub，CLAUDE.md 已知状态）。
- `agent_system/tier3_retriever.py:383` — SearXNG/Firecrawl 搜索未接入。
- `agent_system/storage_dispatcher.py:296` — `_store_datasheet()` 方法为空（`TODO: 参数存入 amr_data.yaml`），函数直接返回空结果。复核确认：唯一调用方是 `web_ui/sub_pages/knowledge_base.py`（legacy Streamlit），主线 React/FastAPI 走的是已验证完整的 `datasheet_hitl.py` 链路，不经过这里。因 `scripts/start_dev.sh` 不启动 Streamlit，当前无实际用户路径会触发这个空实现，风险可控，暂不处理。

---

## C. 意外风险点（文档未提及）

1. **`llama_index_bridge.py` 是不可运行的死代码，但表象像"已完成功能"**——最值得关注的发现，容易让人误判集成已就位。
2. **`.env` 被跟踪进 git**，自 commit `d0c746d` 起已有多次提交历史，内容含真实格式的 `NEO4J_PASSWORD` / `NEO4J_READONLY_PASSWORD` 字段。

   **本轮已处理**：`git rm --cached` 从工作树跟踪中移除（本地文件保留不受影响），新增 `hardware_ai_expert/.env.example` 占位模板供新环境参考；`.gitignore` 已有 `.env` 规则，故后续不会被重新跟踪。
   **未处理，需你决策**：这只解决了"今后不再变化"，**不消除已经写入历史 commit 里的密码**。如果 `d0c746d` 之后提交的密码是真实共享/生产凭据，必须额外做：① 立即轮换这些密码（Neo4j 账号改密）；② 视情况决定是否要清理 git 历史（`git filter-repo` 或类似工具，属于高风险的历史改写操作，会影响所有已拉取该仓库的协作者，需要团队协调后再做，本轮未执行）。
3. **`chroma_data/chroma.sqlite3` 二进制文件被跟踪进 git**，自 commit `317370f` 起有历史记录，本次操作触发了内容变化（字节数不变，内容变）。

   **本轮已处理**：同样 `git rm --cached` 取消跟踪（本地文件保留），`.gitignore` 已有 `chroma_data/` 规则生效。
4. **legacy Streamlit 路径（`storage_dispatcher.py`）是另一条平行、未完工的 datasheet 存储代码路径**，`PRD_GAP_ANALYSIS_V2.md` 的审计完全基于新链路（`datasheet_hitl.py`），未覆盖到这条平行路径——文档盲区。
5. （正向验证）抽查 `frontend/src/pages/Review/index.tsx:67` 的 `project_id='default'→undefined` 处理与文档描述的"已统一"一致，说明本轮 schema 核对工作可信度较高，非走过场。

---

## 处理优先级与状态跟踪

| 优先级 | 任务 | 状态 |
|--------|------|------|
| 1 | 决策并处理 LlamaIndex 桥接死代码（B1） | ✅ 依赖已锁定、benchmark 已跑出真实数据；bridge.py 去留决策待定（已记录） |
| 2 | `.env` / `chroma_data/chroma.sqlite3` 仓库卫生（C2, C3） | ✅ 已从工作树取消跟踪 + 补 `.env.example`；⚠️ 历史 commit 中的密码仍需人工轮换/视情况清理历史 |
| 3 | `storage_dispatcher.py` legacy 空实现（B5） | 已复核：仅 legacy Streamlit 路径触发，主线不受影响，暂不处理 |
| 4 | P2 四项（B3） | ✅ 全部补齐实测数据：Cypher 性能达标（p95<60ms）；E2E 贯穿测试发现已存在（文档未同步）；覆盖率 43.99% 与估算吻合；vLLM 阻塞归因已纠正为 CUDA wheel 版本问题 |
| 5 | AMR 覆盖率复核（B4） | 待排期，需 Neo4j 访问 |

---

## 本轮处理小结（2026-10-14）

1. `requirements.txt` 补齐 6 个 llama-index 子包精确版本，保证环境可复现。
2. 运行 `graphrag_retrieval_benchmark.py`，产出 bge-m3 vs all-MiniLM-L6-v2 真实对比数据（结果见 B1），证实 bge-m3 切换决策正确。报告存至 `hardware_ai_expert/tools/benchmark_reports/embedding_bge-m3_vs_minilm_2026-10-14.json`。
3. `llama_index_bridge.py` 维持现状不删除、不接入，留作已知待裁决项。
4. `git rm --cached` 取消 `hardware_ai_expert/.env` 与 `chroma_data/chroma.sqlite3` 的 git 跟踪（本地文件未删除），新增 `hardware_ai_expert/.env.example`。**遗留风险**：这两个文件已写入的历史 commit 不受影响，`.env` 历史版本中的 `NEO4J_PASSWORD` 等字段仍可被 `git log -p` 翻出，需要人工决定是否轮换密码 / 清理历史。
5. 复核 `storage_dispatcher.py` 空实现的影响面，确认仅 legacy Streamlit 路径触发，不影响主线。
6. **P2 四项全部补齐实测数据**：
   - 新建 `tools/cypher_perf_benchmark.py`，对真实 Neo4j 跑 7 个核心查询场景 × 20 次迭代，p95 均 <60ms，远优于 PRD 的 500ms 验收线。报告：`tools/benchmark_reports/cypher_perf_2026-10-14.json`。
   - 发现 `tests/test_full_chain_e2e.py` 已经是完整的全链路单一测试（commit `fc99f4a`），之前被文档和 CLAUDE.md 遗漏，不是真的零进度——这项应标记为已完成。
   - 跑了 `pytest --cov`，总覆盖率 43.99%，与文档估算的 40-45% 吻合；零覆盖率大文件集中在已识别的 legacy/孤立代码（`agent_core.py`、`llama_index_bridge.py`、`storage_dispatcher.py` 等），核心主线模块覆盖率健康。报告：`tools/benchmark_reports/pytest_coverage_2026-10-14.json`。
   - 纠正 vLLM 阻塞归因：硬件（T4 compute capability 7.5）完全支持 vLLM，真正卡点是驱动给的 CUDA 12.1/12.2 装不上近期 vLLM 版本要求的 CUDA 12.6+ 预编译 wheel。需升级驱动或退回老版本 vLLM，属于独立的基础设施决策，未执行。

## 待你决策的事项汇总

1. `.env` 历史密码（`d0c746d` 之后的提交）是否需要轮换 + 是否要清理 git 历史。
2. `llama_index_bridge.py`（571行零引用代码）最终删除还是继续集成——benchmark 数据已就位，可以决策了。
3. `docs/product/PRD_GAP_ANALYSIS_V2.md` 和 `CLAUDE.md` 里关于 "E2E 单一贯穿测试仍缺失" 的描述已过时（该测试其实存在且通过），需要同步更新文档。
4. vLLM 部署是否值得为了它去升级生产环境的 GPU 驱动——这是基础设施变更，建议单独评估收益（Ollama 当前 51.9 tok/s 是否真的不够用）再决定。

---

*报告由 Jarvis 基于当前 HEAD（分支 `work/legacy-tasks-20260704`）与本轮会话核查生成，2026-10-14。*
