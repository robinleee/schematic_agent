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

#### P1-4 核心数据指标真实复核
- **现状**：AMR 耐压覆盖率 99.8% 来自 commit message，未连真实库抽样；电压标注率、核心网络识别率同样陈旧（口径为单项目 12,688 器件时代）。
- **动作**：基于当前 25,376 器件多项目数据跑 `scripts/check_data_quality.py`，抽样 100 个电容核对降额判定；输出报告到 `tools/benchmark_reports/`
- **验收**：三项指标有真实数字 + 抽样明细；差异 >2% 时定位原因
- **预估**：1 天

---

### P2 — 能力完善（5 项）

#### P2-1 Tier2 PLM 适配器 + mock 契约测试
- 现状：Octopart / Mouser 接口是 stub；无厂商资料/凭据。
- 动作：补可配置适配器 + mock 契约测试，文档明确标注"非真实集成"
- 预估：1～2 天

#### P2-2 Tier3 搜索后端接入
- 现状：`tier3_retriever.py` 用 9 个供应商模板直连；SearXNG / Firecrawl 未接。
- 动作：评估是否值得接（当前模板已覆盖主流原厂），不接就明确标注能力边界
- 预估：1 天（评估） / 2～3 天（实施）

#### P2-3 vLLM 决策
- 现状：阻塞点是驱动只提供 CUDA 12.1/12.2，装不上近期 vLLM 要求的 CUDA 12.6+ wheel（**不是**硬件/驱动不兼容）。
- 选项：① 升级驱动 + CUDA 12.6；② 退回 vLLM 0.2.x + CUDA 11.8；③ 继续用 Ollama（51.9 tok/s）
- 建议：先量化"51.9 tok/s 是否真的不够"，再决定是否动基础设施
- 预估：决策 0.5 天

#### P2-4 Legacy 代码收口
- 范围：`web_ui/`（Streamlit）、`agent_core.py`、`storage_dispatcher.py`、`parsers/`
- 动作：确认无用户路径依赖后，删除 / 移到 `archive/` / 显式标注 Legacy
- 收益：直接抬高覆盖率分母质量，减少维护与误判
- 预估：1 天（含依赖检查）

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
