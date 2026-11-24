# Hardware AI Expert 交付收口待完成任务清单

> 版本：V1.0  
> 基线日期：2026-09-22  
> 依据：`docs/product/PRD_V5.1.md`、`docs/product/TODO_DEVELOPMENT_TASKS.md`、当前代码和已完成的在线验证  
> 目标：将项目从“核心功能可运行的研发验证版”推进到“功能闭环、接口一致、指标可量化、可安全交付”的产品版本。

---

## 一、当前基线判断

当前项目不是“所有功能已开发完成”，而是：

- 核心技术能力已基本具备：ETL、Neo4j 图谱、Quality Guard、24 条审查规则、ReAct Agent、Self-Correction、GraphRAG、React/FastAPI、HITL 框架均有实现。
- 运行环境已可启动：Neo4j、Ollama、ChromaDB、FastAPI 可通过 `scripts/start_dev.sh` 启动，健康检查可达到 4/4。
- 部分真实链路已验证：Agent 可通过 API 调用 Ollama、Graph Tools 和 Neo4j；图谱摘要已与 System 页面统计口径统一。
- 主要缺口集中在：前后端联调、BOM 知识关联、HITL 真实闭环、GraphRAG 质量评估、接口契约、安全、性能和 E2E 测试。

建议将当前状态理解为：

- 核心功能代码完成度：约 75%～82%
- 真实业务验证完成度：约 55%～65%
- 可交付产品完成度：约 50%～60%

以下任务按“阻塞产品交付”的优先级排列。

---

## 二、P0：必须优先完成的交付阻塞项

## P0-1 前后端 API 契约与七页面联调

### 当前问题

React 页面、FastAPI 路由和 TypeScript 类型已经存在，但尚未完成逐页面联调。当前代码检查已经发现至少以下接口风险：

- Knowledge 上传页面调用的 `upload_document()` 方法需要确认后端是否真实存在。
- HITL 审批接口的后端返回结构为 `results` 列表，但 schema/前端类型仍按字典声明。
- HITL 导出接口前端期待 `download_url`，后端实际返回规则保存结果。
- ETL 进度接口当前返回固定完成状态，不是真实异步任务进度。

涉及位置：

- `frontend/src/pages/`
- `frontend/src/api/`
- `frontend/src/types/`
- `hardware_ai_expert/api/routers/`
- `hardware_ai_expert/api/schemas/`

### 要完成的工作

1. 建立 API 契约清单，逐项记录：
   - 请求方法和路径
   - 请求参数
   - 成功响应
   - 失败响应
   - 前端使用位置
2. 修复 Knowledge 上传接口：
   - 确认 `KnowledgeRouter` 的真实公开方法
   - 统一后端路由调用和知识库服务方法
   - 支持 PDF/文本上传的明确错误提示
3. 修复 HITL 审批响应：
   - 统一后端 schema、实际返回值和前端 TypeScript 类型
   - 明确单条审批、批量审批、Reject 的响应结构
4. 修复 HITL 导出接口：
   - 如果是直接保存规则，前端改为展示保存结果
   - 如果需要下载，后端生成真实导出文件并返回有效下载地址
5. 完成 ETL 页面接口联调：
   - Preview
   - Run
   - Progress
   - Quality Report
   - Project 切换和删除
6. 完成 Chat、Review、HITL、Knowledge、ETL、Graph、System 七个页面的核心操作验证。

### 目标

- 七个页面均可打开并完成其核心操作。
- 前端类型与后端 Pydantic schema 完全一致。
- 不再出现前端请求字段正确但后端 500 的情况。
- 所有错误都能在页面显示可理解的错误信息。

### 验收标准

- Chat：可发送消息，能收到普通响应和 WebSocket 流式响应。
- Review：可执行审查，能展示违规项、严重等级和规则信息。
- HITL：可查看 Pending 项，Approve/Reject 后状态正确更新。
- Knowledge：可上传并索引至少一个测试文档。
- ETL：可上传网表和 BOM，Preview 与 Run 结果一致。
- Graph：至少一种图谱可视化场景能正常加载。
- System：真实显示 Neo4j/Ollama/ChromaDB/API 状态。
- 所有接口成功响应均能被前端正确解析。

### 验证方式

```bash
cd /data/schematic_agent
bash scripts/start_dev.sh
bash scripts/healthcheck.sh
cd frontend
npm run build
npm run lint
```

随后使用浏览器逐页执行核心路径，并保留：

- 页面截图或录屏
- API 请求/响应日志
- 失败用例清单
- 修复前后对比

### 产出物

- API 契约清单
- 七页面联调报告
- 修复后的 Pydantic schema 和 TypeScript 类型
- 页面 smoke test

### 依赖

- P0-2 接口契约修复必须先完成关键阻断项。
- P0-3 真实 ETL 数据闭环可为 ETL/Review 页面提供验收数据。

---

## P0-2 修复接口实现缺陷和数据契约不一致

### 当前问题

当前项目存在“路由存在但实现不完整”以及“声明结构与实际返回不一致”的问题。此类问题会直接导致页面功能失败，即使底层模块本身已经存在。

重点检查项：

- Knowledge 上传方法是否存在并可调用。
- HITL 审批响应 schema 与实际返回值不一致。
- HITL 导出响应与前端 `download_url` 预期不一致。
- ETL 进度没有真实任务状态。
- System 的 Agent 统计仍是固定值：
  - `query_count=0`
  - `token_usage=0`
  - `recent_queries=[]`

### 要完成的工作

1. 对所有 API Router 做实际调用扫描。
2. 为每个 API 响应建立 Pydantic 严格校验。
3. 禁止在成功路径中返回与 schema 不匹配的数据。
4. 为固定占位值增加明确的状态字段：
   - 未实现时返回 `available=false` 或 `status=degraded`
   - 不得伪装成真实统计
5. 为 Agent 统计增加最小可用实现：
   - 请求次数
   - 总耗时
   - 工具调用次数
   - token 使用量（如果模型返回）
   - 最近请求摘要

### 目标

- API 实际返回结构、Pydantic schema、前端类型三者一致。
- 任何未实现能力都能明确返回 degraded/unavailable，而不是返回空的正常结果。
- API 500 错误率在核心 smoke test 中为 0。

### 验收标准

- 所有核心 API 使用 `TestClient` 或真实服务请求验证。
- 每个接口至少覆盖：
  - 成功场景
  - 参数错误
  - 外部服务不可用
  - 空数据
  - 权限/项目隔离
- OpenAPI 文档与前端 API client 一致。

### 验证方式

```bash
PYTHONPATH=hardware_ai_expert .venv/bin/python -m pytest -q hardware_ai_expert/tests
curl -f http://127.0.0.1:8501/openapi.json
```

重点检查：

```bash
curl -f http://127.0.0.1:8501/api/v1/system/status
curl -f http://127.0.0.1:8501/api/v1/review/rules
curl -f http://127.0.0.1:8501/api/v1/etl/projects
```

### 产出物

- API 契约修复清单
- API smoke test
- OpenAPI 与前端类型同步记录

---

## P0-3 网表+BOM→ETL→Neo4j→Review 真实业务闭环

### 当前问题

ETL、BOM、Review 和图谱加载代码均存在，但还缺少一套固定输入数据的可重复全链路验收。当前已有 Beet7 图谱数据，但不能替代“从上传文件重新导入到审查报告”的完整流程。

### 要完成的工作

1. 准备固定测试输入：
   - 一套小型可公开测试网表
   - 对应 `.pstxnet`
   - 对应 `.pstxprt`
   - 对应 `.pstchip`
   - 对应 BOM CSV
   - 可选 BOM Excel
2. 记录输入文件版本和校验和。
3. 验证 Preview：
   - Component 数量
   - Pin 数量
   - Net 数量
   - PartType 分布
   - BOM 字段解析
4. 验证 Run：
   - 指定 project_id
   - 质量守门
   - 图谱写入
   - 失败时不留下脏数据
5. 验证 Review：
   - 24 条规则加载
   - 全量审查
   - 违规项保存/返回
   - 项目过滤
6. 验证重复导入和失败重试行为。

### 目标

固定输入能够稳定重现：

```text
网表+BOM
  → Preview
  → ETL Run
  → Quality Guard
  → Neo4j 图谱
  → Review
  → 审查报告
```

### 验收标准

- Preview 统计与实际 Neo4j 写入统计一致。
- Component 节点包含需要的 BOM 字段：
  - MPN
  - Manufacturer
  - Description
  - Package
  - Quantity
- Quality Guard 失败时阻止写入。
- 项目 A 的数据不会被项目 B 查询到。
- 重复执行不会产生重复节点或脏关系。
- 审查结果能定位到具体 RefDes 或 Net。

### 验证方式

建议增加：

```text
tests/e2e/test_etl_review_flow.py
tests/fixtures/netlist/
tests/fixtures/bom/
```

运行：

```bash
PYTHONPATH=hardware_ai_expert .venv/bin/python -m pytest -q tests/e2e/test_etl_review_flow.py
```

同时使用 `scripts/check_data_quality.py --project <project_id>` 对比导入前后数据质量。

### 产出物

- 固定测试网表和 BOM
- ETL/Review E2E 测试
- 导入前后质量报告
- 失败场景和回滚报告

### 依赖

- P0-1 API 契约稳定后执行。
- 需要可写的独立测试 Neo4j 项目或测试数据库。

---

## P0-4 BOM→MPN→AMR/Datasheet/GraphRAG 知识关联

### 当前问题

BOM CSV/Excel 已可读取，也能参与 PartType 标准化，但 BOM 字段还没有完全成为知识检索和 AMR 的统一入口。

### 要完成的工作

1. 统一 BOM 字段模型：
   - RefDes
   - MPN
   - Manufacturer
   - Description
   - Package
   - Quantity
2. 将字段写入 Component 节点，并保留原始 BOM 行号。
3. 规范 MPN：
   - 去空格
   - 后缀清洗
   - 大小写规范
   - 厂商别名统一
4. 将 Component.MPN 接入：
   - `mpn_decoder.py`
   - `amr_engine.py`
   - Datasheet KnowledgeSource
   - GraphRAG 实体关联
   - Tier3 公网 MPN 查询
5. 处理异常：
   - MPN 缺失
   - 一对多 MPN
   - 重复 RefDes
   - 同一 MPN 多厂商
   - BOM 与网表无法匹配
6. 输出无法关联清单和原因。

### 目标

用户通过 BOM 导入后，可以基于 RefDes 或 MPN 查询器件规格、AMR 参数和 Datasheet 知识。

### 验收标准

- Component 节点可以追溯到原始 BOM 行。
- 给定 MPN 能查询到对应 Datasheet 或明确的未命中原因。
- AMR 优先使用 BOM MPN，而不是仅依赖 RefDes/Model。
- MPN 缺失时，系统有明确降级策略。
- 多项目下同一个 MPN 不会返回其他项目的私有上下文。

### 验证方式

建立至少 20 条 BOM fixture，覆盖：

- 正常 MPN
- 小众 MPN
- 缺 MPN
- 重复 RefDes
- 多位号拆分
- 中文 Description
- 不同厂商后缀

验证：

```bash
PYTHONPATH=hardware_ai_expert .venv/bin/python -m pytest -q hardware_ai_expert/tests/test_bom_metadata.py
```

并增加 API 级验证：

```text
BOM 上传 → Component 查询 → AMR 查询 → KnowledgeRouter 查询
```

### 产出物

- BOM 规范化模块
- BOM→MPN 关联报告
- AMR/知识库关联测试
- 无法关联项清单

---

## P0-5 HITL Datasheet 真实闭环

### 当前问题

Datasheet 解析、Pending Review、Approve/Reject、规则写入代码已经存在，但当前缺少至少 3 个真实 PDF 的完整验收。

### 要完成的工作

1. 准备 3～5 个真实 Datasheet：
   - 电容或被动器件
   - PMIC/BUCK/LDO
   - 一个包含明确额定电压、电流或温度参数的器件
2. 验证 PDF 解析：
   - MPN
   - Manufacturer
   - Package
   - Voltage rating
   - Current rating
   - Temperature range
3. 生成 Pending Review 项。
4. 验证前端展示原文依据。
5. 分别验证：
   - Approve
   - Reject
   - 批量 Approve
   - 重复审批
   - 无效 review_id
6. 验证审批后的数据：
   - 写入 Neo4j
   - 写入 AMR 数据源
   - 写入审查规则配置
   - 触发规则热更新
7. 修复 HITL API schema 与前端类型不一致问题。

### 目标

完整跑通：

```text
PDF
 → 解析
 → Pending Review
 → Approve/Reject
 → 持久化
 → 规则/AMR 更新
 → 热加载
 → 查询和审查可见
```

### 验收标准

- 至少 3 个真实 PDF 全流程成功。
- Approve 后参数可被查询和审查使用。
- Reject 后参数不会进入正式规则。
- 重启服务后审批结果仍然存在。
- 失败和拒绝场景有明确审计信息。

### 验证方式

```bash
PYTHONPATH=hardware_ai_expert .venv/bin/python -m pytest -q \
  hardware_ai_expert/tests/test_datasheet_hitl_loop.py
```

同时执行一份真实 PDF 手工验收并保存：

- 原始 PDF 校验和
- 提取 JSON
- Pending 记录
- Approve/Reject 响应
- 规则或 AMR 更新前后 diff

### 产出物

- Datasheet fixture 和验收记录
- HITL E2E 测试
- 审批审计记录
- 前后端 schema 修复

---

## P1：核心质量和能力完善

## P1-1 多项目隔离闭环

### 当前问题

图谱工具已经支持 project_id，默认项目统计问题也已经修复，但知识库写入、GraphRAG VectorChunk、电源树生成和部分 ETL 关系仍需确认是否全链路携带 project_id。

### 要完成的工作

1. 梳理所有写入 Neo4j/ChromaDB 的入口。
2. 梳理所有读取和检索入口。
3. 明确三类数据：
   - 项目私有数据
   - 共享知识数据
   - 系统级元数据
4. 为私有数据强制写入 project_id。
5. 为共享知识显式标记 `scope=shared`，避免用缺失 project_id 代替业务语义。
6. GraphRAG VectorChunk 增加项目归属或共享范围。
7. 电源树、Review、KnowledgeRouter、Tier3 查询统一隔离策略。

### 目标

任何项目 A 的查询、审查、知识检索和图谱可视化都不会读取项目 B 的私有数据。

### 验收标准

- 创建项目 A/B，各导入一组唯一器件和网络。
- A 查询只能看到 A 和明确允许的共享知识。
- B 查询只能看到 B 和明确允许的共享知识。
- 删除 A 后，A 的节点、关系、向量和知识引用都被清理或明确标记。
- 默认 aggregate 模式只在用户未选择具体项目时生效。

### 验证方式

增加：

```text
tests/e2e/test_project_isolation.py
```

最少覆盖：

- Component
- Pin
- Net
- POWERED_BY
- Review
- KnowledgeRouter
- GraphRAG
- HITL Pending 项

---

## P1-2 专业 Embedding 与 GraphRAG 质量评估

### 当前问题

当前默认模型仍为 `all-MiniLM-L6-v2`。代码支持环境变量切换，但尚未完成 bge-m3 部署、索引重建和量化效果评估。

### 要完成的工作

1. 建立硬件领域固定 Query Set，至少覆盖：
   - MPN 规格查询
   - 电源树查询
   - Datasheet 参数查询
   - 电容耐压查询
   - 接口/差分对查询
   - 审查规则知识查询
2. 为每个 Query 标注：
   - golden answer
   - expected source
   - 允许的同义答案
3. 对比：
   - `all-MiniLM-L6-v2`
   - `bge-m3` 或 `bge-large-zh-v1.5`
4. 重建 Neo4j VectorChunk 索引。
5. 记录内存、延迟和索引大小。
6. 处理 embedding 加载失败：
   - 禁止静默写入零向量
   - 索引失败必须显式失败
   - System 页面标记 degraded

### 目标

检索质量有可重复、可比较的量化依据，而不是仅凭演示判断。

### 验收标准

- 记录 Recall@5、Recall@10、MRR、NDCG。
- 目标 Recall@K 达到 PRD 要求或有书面例外说明。
- 新模型可以通过环境变量切换。
- 模型和向量维度记录在索引元数据中。
- 模型加载失败时 API 返回可识别错误。

### 验证方式

建议新增：

```text
scripts/graphrag_benchmark.py
tests/fixtures/graphrag_queries.json
docs/benchmarks/graphrag_<date>.md
```

运行示例：

```bash
SCHEMATIC_EMBEDDING_MODEL=all-MiniLM-L6-v2 \
  .venv/bin/python scripts/graphrag_benchmark.py
SCHEMATIC_EMBEDDING_MODEL=bge-m3 \
  .venv/bin/python scripts/graphrag_benchmark.py
```

---

## P1-3 网络电压与 AMR 指标提升

### 当前问题

- 全网电压标注率约 20.7%，POWER 网络标注率约 95.7%。
- 核心网络已有网络级连通性检查，但 VoltageLevel post-injection 完整性仍需增强。
- AMR 电容耐压覆盖率约 83.1%，目标为 ≥95%。

### 要完成的工作

1. 扩展电压网络模式：
   - VDDQ
   - VPP
   - VTT
   - 1V0/1V2/1V5
   - DDR/LPDDR 相关电源网络
2. 生成缺失 VoltageLevel 的核心网络清单。
3. 将“网络存在”“网络连通”“电压已标注”分成三个独立指标。
4. 生成缺失 `voltage_rating` 的电容清单。
5. 按 MPN、封装、厂商和器件类型聚类分析缺失项。
6. 通过 BOM、MPN Decoder、Datasheet 和 HITL 补齐参数。

### 目标

- 核心网络识别与电压标注口径一致。
- POWER 网络标注率保持 ≥95%。
- AMR 电容耐压覆盖率达到 ≥95%。
- 所有指标能按 project_id 查询，并给出缺失明细。

### 验收标准

- 同一数据集重复运行结果一致。
- 指标报告同时展示分子、分母和缺失项。
- 质量报告、System 页面和命令行工具数字一致。
- Quality Guard 不再把“无电压标注”误判为“已完成”。

### 验证方式

```bash
.venv/bin/python scripts/check_data_quality.py
.venv/bin/python scripts/check_data_quality.py --project beet7_acceptance
```

保存每次指标报告，比较：

- 核心网络识别率
- POWER 网络电压标注率
- 全网电压标注率
- AMR 覆盖率

---

## P1-4 Tier2 PLM 与 Tier3 公网能力收口

### 当前问题

Tier2 当前不是实际内网 PLM，而是替代性本地检索层。Tier3 有轻量实现，但默认关闭，通用搜索和真实公网链路仍缺少完整验收。

### 要完成的工作

1. 明确 PLM：
   - 接口地址
   - 认证方式
   - MPN 查询接口
   - 字段映射
   - 数据权限
2. 实现 Tier2 Retriever：
   - 超时
   - 重试
   - 缓存
   - 脱敏
   - 失败降级 Tier3
3. 验证 Tier3：
   - MPN 发送脱敏
   - 供应商模板
   - HTML/PDF 解析
   - LLM 提取
   - 结果可信度
4. 明确公网能力在无网络时的 degraded 行为。

### 目标

检索路由稳定遵循：

```text
Tier0 GraphRAG
 → Tier1 本地知识
 → Tier2 PLM
 → Tier3 公网 MPN
```

### 验收标准

- Tier2 命中时优先返回 PLM 结果。
- Tier2 超时或失败时可降级，不阻塞 Agent。
- Tier3 只发送脱敏后的 MPN。
- 结果包含来源、时间、可信度和失败原因。

### 验证方式

使用 Mock PLM 和 Mock 公网服务覆盖：

- 命中
- 未命中
- 超时
- 认证失败
- 解析失败
- 降级成功

---

## P2：测试、性能、安全和生产化

## P2-1 完整 E2E 自动化测试体系

### 当前问题

当前测试较多，但以单元测试、Mock 测试和模块集成为主，没有覆盖完整产品链路。

### 要完成的工作

1. 重组测试目录：

```text
tests/unit/
tests/integration/
tests/e2e/
tests/live/
tests/fixtures/
```

2. 明确测试服务依赖：
   - unit 不依赖 Neo4j/Ollama
   - integration 使用独立测试数据
   - e2e 使用固定测试项目
   - live 单独标记，不阻塞普通 CI
3. 增加全链路 smoke test：
   - 上传
   - ETL
   - Quality Guard
   - Review
   - Agent
   - HITL
4. 增加失败链路：
   - 质量不达标
   - Neo4j 不可用
   - Ollama 不可用
   - 文件格式错误
   - 项目不存在

### 目标

每次提交都能自动判断核心链路是否仍然可运行。

### 验收标准

- Unit tests 100% pass。
- Integration tests 100% pass。
- E2E smoke tests 100% pass。
- 依赖服务关闭时测试能明确 skip 或失败原因。
- 测试不会污染生产项目和用户数据。

### 验证方式

```bash
.venv/bin/python -m pytest -q tests/unit
.venv/bin/python -m pytest -q tests/integration
.venv/bin/python -m pytest -q tests/e2e
.venv/bin/python -m pytest -m live -q
```

---

## P2-2 测试覆盖率与 CI 门禁

### 要完成的工作

1. 引入 `pytest-cov`。
2. 对以下模块补覆盖：
   - parser
   - ETL bridge
   - Quality Guard
   - Review templates
   - Graph Tools
   - KnowledgeRouter
   - API routers
   - HITL workflow
3. 配置 CI：
   - 格式检查
   - 类型检查
   - 单元测试
   - 集成测试
   - 覆盖率报告
4. 设定逐步门槛：
   - 第一阶段总覆盖率 ≥60%
   - 核心模块覆盖率 ≥80%

### 验收标准

- CI 能在干净环境中安装依赖并运行。
- 覆盖率低于门槛时 CI 失败。
- 新增代码不能降低覆盖率。

### 验证方式

```bash
.venv/bin/python -m pytest --cov=hardware_ai_expert \
  --cov-report=term-missing \
  --cov-fail-under=60
```

---

## P2-3 性能基准与 Agent 响应优化

### 当前问题

真实 Agent 查询曾耗时约 18～287 秒，远高于 PRD 的单轮推理和路线图 P95 目标。Chat 已移入线程池，解决了事件循环阻塞，但没有解决实际耗时。

### 要完成的工作

1. 建立固定性能场景：
   - 普通图查询
   - 大网络查询
   - 电源树
   - 差分对
   - Review
   - GraphRAG
   - Agent 单轮
2. 记录：
   - P50
   - P95
   - 首 token 延迟
   - 总耗时
   - token 数
   - 工具调用次数
3. 优化 Agent：
   - 限制无效工具调用
   - 缩短 Observation
   - 对统计类查询使用确定性工具
   - 对简单问题关闭或减少 thinking
   - 增加缓存
4. 优化 Neo4j：
   - 检查索引
   - 优化 Cypher
   - 验证大网络聚合
5. 评估多 worker、任务队列和 WebSocket 流式架构。

### 目标

建议目标：

- 普通图查询 P95 < 500ms
- GraphRAG P95 < 2s
- Agent 普通查询 P95 < 10s
- 全量 Review < 30s
- WebSocket 首响应 < 3s
- 长任务不阻塞其他请求

### 验收标准

- 有可重复运行的 benchmark。
- 每项指标有当前值、目标值和差距。
- 超标查询有优化记录或明确例外。
- 至少 10 个并发请求下健康检查和规则 API 仍然可用。

### 验证方式

新增：

```text
scripts/benchmark_api.py
scripts/benchmark_graph_tools.py
docs/benchmarks/
```

---

## P2-4 生产安全配置

### 当前问题

当前仍存在以下风险：

- CORS 使用 `allow_origins=["*"]`。
- 后端没有真正认证授权。
- 多处存在默认 Neo4j 密码 fallback。
- 文件上传直接拼接 `/tmp/{filename}`。
- 缺少文件大小、类型和路径安全控制。

### 要完成的工作

1. CORS 改为环境变量白名单。
2. 增加 API 认证：
   - API token 或 JWT
   - WebSocket 鉴权
   - System/health 是否公开需要明确
3. 删除所有默认密码 fallback。
4. 文件上传：
   - 允许的扩展名白名单
   - 文件大小限制
   - UUID 临时文件名
   - 防路径穿越
   - `finally` 清理临时文件
   - 防止同名覆盖
5. 日志脱敏：
   - 不记录密码/token
   - 不记录完整敏感用户输入
   - 公网检索只记录脱敏 MPN
6. 增加只读模式启动检查。

### 目标

系统在生产配置下不依赖默认密码，不允许未授权用户执行数据读取/写入，且文件上传不可造成路径穿越或任意文件覆盖。

### 验收标准

- 安全扫描找不到有效代码中的明文默认密码。
- 未认证请求按接口策略返回 401/403。
- 非白名单文件被拒绝。
- 超大文件被拒绝。
- `../`、绝对路径和同名覆盖测试均失败。
- CORS 只允许配置白名单。

### 验证方式

```bash
grep -R "SecretPassword123" hardware_ai_expert --include='*.py'
curl -i -H 'Origin: https://untrusted.example' http://127.0.0.1:8501/api/v1/system/status
```

同时增加 API 安全测试和静态扫描。

---

## P2-5 运行、监控和故障恢复

### 当前问题

当前已有启动、停止和健康检查脚本，但缺少完整生产运行能力：

- 没有统一服务监控和告警。
- Agent 统计仍有占位值。
- Neo4j/Ollama/ChromaDB 异常恢复策略不完整。
- 缺少备份恢复演练。
- ETL/Agent 长任务缺少 job_id 和可追踪状态。

### 要完成的工作

1. 所有后台任务生成 `job_id`。
2. 记录任务状态：
   - queued
   - running
   - succeeded
   - failed
   - cancelled
   - timeout
3. System 页面展示真实状态和 degraded 原因。
4. 增加：
   - Neo4j 备份
   - Ollama 进程恢复
   - ChromaDB 恢复
   - API 重启策略
5. 增加结构化日志和 request_id。
6. 记录 Agent：
   - 请求数
   - 成功率
   - 超时数
   - 工具失败数
   - 平均延迟

### 验收标准

- 关闭任一依赖服务后，System 页面显示 degraded，而不是误报 running。
- ETL/Agent 任务可通过 job_id 查询状态。
- 进程重启后任务失败原因可追溯。
- 能完成一次备份和恢复演练。

### 验证方式

```bash
bash scripts/start_dev.sh
bash scripts/healthcheck.sh
bash scripts/stop_dev.sh
```

配合手工停止 Neo4j/Ollama/ChromaDB，检查状态、日志和恢复行为。

---

## P2-6 遗留 Streamlit 收口

### 当前问题

React + FastAPI 已是主线，但 Streamlit 仍作为遗留入口存在，功能边界和启动方式容易造成混淆。

当前边界：`scripts/start_dev.sh` 启动 FastAPI，不启动 Streamlit；`docs/README.md` 和 `docs/ops/ENV_RECOVERY_RUNBOOK.md` 说明了主线与 Legacy 入口。尚无七页面逐页实时核心操作验收记录，故不能执行归档或将最终清单的 Streamlit 收口项标记为完成。

### 要完成的工作

1. 确认 React 已覆盖 Streamlit 主流程。
2. 将 Streamlit 标记为 Legacy。
3. 更新 README、Runbook、PRD 和启动脚本。
4. 迁移仍有价值但 React 缺失的功能。
5. 在确认无人依赖后归档 Streamlit。

### 验收标准

- 新用户只按 React + FastAPI 文档即可启动。
- 主流程不依赖 Streamlit。
- Streamlit 入口有明确弃用说明。

---

## 三、推荐执行顺序

建议按以下顺序执行，避免前面的接口问题影响后续验收：

### Sprint 1：接口和主链路

1. P0-1 前后端 API 契约和七页面联调
2. P0-2 API 实现缺陷修复
3. P0-3 网表+BOM→ETL→Review 真实闭环

交付目标：用户可以从前端上传数据、完成 ETL、执行审查并看到一致结果。

### Sprint 2：知识和人工审核

4. P0-4 BOM→MPN→AMR/知识库关联
5. P0-5 HITL Datasheet 真实闭环
6. P1-1 多项目隔离闭环

交付目标：BOM 和 Datasheet 能真正驱动 AMR、知识检索和审查规则。

### Sprint 3：质量和性能

7. P1-2 Embedding 与 GraphRAG 质量评估
8. P1-3 电压和 AMR 指标提升
9. P2-1 E2E 自动化测试
10. P2-2 覆盖率和 CI
11. P2-3 性能基准与 Agent 优化

交付目标：结果可量化、可重复、性能差距透明。

### Sprint 4：安全和生产化

12. P1-4 Tier2/Tier3 收口
13. P2-4 生产安全配置
14. P2-5 运行监控和故障恢复
15. P2-6 Streamlit 收口

交付目标：达到可交付、可运维、可审计状态。

---

## 四、最终版本验收门槛

以下条件全部满足后，才能宣布“第一版产品功能开发完成”：

- [ ] 七个 React 页面核心操作全部通过
- [ ] 网表+BOM 可从前端上传并完成 ETL
- [ ] Preview 与实际 Neo4j 数据一致
- [ ] Quality Guard 能阻断低质量数据
- [ ] 项目 A/B 数据完全隔离
- [ ] 全量 Review 可执行并展示一致报告
- [ ] Agent 可完成查询、审查和故障诊断
- [ ] Agent 普通查询 P95 达到约定目标
- [ ] Datasheet 至少 3 个真实 PDF 完成 HITL 闭环
- [ ] BOM→MPN→AMR/知识库关联可追溯
- [ ] GraphRAG 有固定 benchmark 和 Recall/MRR 结果
- [ ] Tier2 PLM 或明确的替代方案完成验收
- [ ] Unit/Integration/E2E 分层测试通过
- [ ] 总测试覆盖率 ≥60%
- [ ] CI 门禁生效
- [ ] CORS、认证、上传安全和凭据管理完成
- [ ] 关键服务有健康检查、日志、备份和恢复方案
- [ ] Streamlit 遗留入口已明确收口

在上述门槛全部通过前，项目应继续标记为：

> **研发验证版 / Beta 候选，不是最终交付版。**
