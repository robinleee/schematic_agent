# schematic_agent 后续任务开发清单

> 版本：2026-08
> 更新日期：2026-08-21
> 目标：将 schematic_agent 从“核心功能研发完成的验证版”推进到“可稳定交付的产品版本”。

## 一、总体判断

当前项目已经具备以下核心能力：

- Cadence 网表与 BOM ETL 导入
- Neo4j 异构硬件图谱
- PartType、Pin.Type、电源网络和电压信息标准化
- 24 条规则的原理图审查引擎
- ReAct Agent 与多 Agent 编排
- 电源链路、故障根因、信号路径、差分对、共因失效分析
- Neo4j 原生向量索引与 GraphRAG
- Datasheet 知识库与 HITL 审批框架
- React + FastAPI 前后端
- 多项目 `project_id` 数据隔离
- Tier3 公网 MPN 检索

当前主要差距不在于继续增加算法，而在于：

1. 恢复并验证完整运行环境
2. 跑通真实业务闭环
3. 统一数据质量指标
4. 补齐测试和性能基准
5. 完成安全及生产化配置

---

# P0：恢复可运行状态

## P0-1. 统一服务启动与健康检查

**目标：** 开发环境可以一键启动、停止和检查所有依赖服务。

### 任务

- [ ] 确认 Neo4j 当前运行状态
- [ ] 启动并验证 Ollama
- [ ] 启动并验证 ChromaDB
- [ ] 启动 FastAPI
- [ ] 启动 React 前端
- [ ] 增加统一启动脚本
- [ ] 增加统一停止脚本
- [ ] 增加统一健康检查脚本
- [ ] 检查端口冲突和环境变量
- [ ] 在 System 页面展示真实服务状态
- [ ] 对服务不可用状态显示 `degraded`，不能伪装成正常

### 建议新增

```text
scripts/start_dev.sh
scripts/stop_dev.sh
scripts/healthcheck.sh
scripts/check_data_quality.py
```

### 验收标准

- [ ] Neo4j 可连接
- [ ] Ollama `/api/tags` 正常
- [ ] ChromaDB health/heartbeat 正常
- [ ] FastAPI `/api/v1/system/status` 正常
- [ ] React 页面可访问
- [ ] WebSocket 可建立连接

## P0-2. 修复测试环境依赖问题

**当前问题：** Agent E2E 测试会直接连接 Ollama，服务未启动时失败。

### 任务

- [ ] 将测试拆分为 unit/integration/e2e/live
- [ ] 默认单元测试不依赖真实 Ollama
- [ ] 增加 LLM Mock Server
- [ ] Neo4j 测试使用独立数据库或测试数据
- [ ] 增加服务不可用时的明确 skip 标记
- [ ] 清理过期 `.pytest_cache` 失败记录
- [ ] 统一测试命令

### 建议命令

```bash
pytest tests/unit -q
pytest tests/integration -q
pytest tests/e2e -q
pytest -m live -q
```

### 验收标准

- [ ] 无服务环境下单元测试全部通过
- [ ] 依赖服务启动后集成测试全部通过
- [ ] 真实 Ollama 测试单独标记，不阻塞普通 CI

---

# P1：完成核心业务闭环

## P1-1. 网表 + BOM → ETL → Neo4j 闭环

**目标：** 验证真实输入能够形成完整、隔离、可追溯的图谱。

### 任务

- [ ] 准备一套固定测试网表
- [ ] 准备对应 BOM CSV
- [ ] 准备 BOM Excel
- [ ] 验证网表上传
- [ ] 验证 BOM 上传
- [ ] 验证 ETL Preview
- [ ] 验证 ETL Run
- [ ] 验证进度查询
- [ ] 验证项目创建和项目隔离
- [ ] 验证项目删除
- [ ] 验证异常文件提示
- [ ] 验证重复项目处理
- [ ] 验证 ETL 失败时不会留下脏数据

### 重点检查

```text
Component
Pin
Net
POWERED_BY
PartType
MPN
Manufacturer
Description
VoltageLevel
project_id
```

### 验收标准

- [ ] 网表和 BOM 均可从前端上传
- [ ] Preview 数据与实际导入数据一致
- [ ] 项目之间数据不串库
- [ ] Quality Guard 能阻止低质量数据导入
- [ ] 导入结果可追溯到原始文件和项目

## P1-2. 审查闭环

**目标：** 完成“导入 → 审查 → 报告”的主流程。

### 任务

- [ ] 执行全量 Review
- [ ] 验证 24 条规则均可加载
- [ ] 验证规则热更新
- [ ] 验证 `project_id` 过滤
- [ ] 验证违规结果展示
- [ ] 验证严重程度颜色和排序
- [ ] 验证规则摘要统计
- [ ] 验证报告导出
- [ ] 验证空结果场景
- [ ] 验证大网络场景
- [ ] 验证重复执行不会产生脏结果

### 验收标准

- [ ] 能完成一次真实网表全量审查
- [ ] 每条违规可定位到器件或网络
- [ ] 规则解释和修复建议不为空
- [ ] 报告内容与页面结果一致
- [ ] 审查失败时有明确错误信息
- [ ] 结果可按规则、严重程度和项目筛选

## P1-3. Agent 查询和诊断闭环

**目标：** 验证自然语言查询可以稳定调用正确工具并输出可解释结果。

### 任务

- [ ] 查询器件信息
- [ ] 查询网络连接关系
- [ ] 查询电源树
- [ ] 追踪电源链路
- [ ] 追踪故障根因
- [ ] 追踪信号路径
- [ ] 查询差分对
- [ ] 查询共因失效
- [ ] 验证中文问题
- [ ] 验证中英文混合问题
- [ ] 验证不存在的器件
- [ ] 验证空输入
- [ ] 验证复杂复合问题
- [ ] 验证工具调用重复限制
- [ ] 验证自纠错逻辑
- [ ] 验证最大步骤限制

### 验收标准

- [ ] Agent 能识别 query/review/diagnosis 三类任务
- [ ] 诊断任务优先调用电源和故障工具
- [ ] 空结果可进行一次合理参数放宽
- [ ] 无法确认时明确输出“不确定”
- [ ] 推理链页面展示完整
- [ ] LLM JSON 异常不会导致服务崩溃

## P1-4. BOM → MPN → AMR/知识库关联

**目标：** 补齐 BOM 的实际业务价值。

### 任务

- [ ] BOM MPN 与 `Component.MPN` 关联
- [ ] MPN Decoder 接入 BOM 信息
- [ ] BOM Manufacturer 与 MPN Decoder 联动
- [ ] BOM Description 参与 PartType 标准化
- [ ] MPN 与 Datasheet KnowledgeSource 关联
- [ ] MPN 与 GraphRAG 关联
- [ ] MPN 缺失时支持 RefDes 降级
- [ ] MPN 格式清洗和后缀归一化
- [ ] 处理一对多 MPN
- [ ] 处理重复 RefDes
- [ ] 输出无法关联的 BOM 清单

### 验收标准

- [ ] BOM 中的关键 MPN 能进入 AMR 查询
- [ ] MPN 能关联 Datasheet 知识
- [ ] MPN 关联失败时有明确原因
- [ ] AMR 覆盖率能按 BOM 统计
- [ ] 结果可追溯到原始 BOM 行

## P1-5. Datasheet + HITL 闭环

**目标：** 验证知识库人工审核链路。

### 任务

- [ ] 上传真实 Datasheet PDF
- [ ] 解析器提取器件信息
- [ ] 提取额定电压、电流、温度、封装等参数
- [ ] 生成 Pending 审批项
- [ ] 审批项展示原文依据
- [ ] 支持 Approve
- [ ] 支持 Reject
- [ ] 支持批量审批
- [ ] 审批结果持久化
- [ ] 审批后写入 Neo4j
- [ ] 审批后写入规则/AMR 数据源
- [ ] 触发规则热更新
- [ ] 验证审批后的参数可被查询

### 验收标准

```text
PDF
 → 解析
 → Pending
 → Approve/Reject
 → 持久化
 → 知识库/AMR 更新
 → 查询可见
```

---

# P1：统一数据质量指标

## P1-6. 统一数据质量报告

当前文档中的 AMR 和电压覆盖率存在多个统计口径，需要统一。

### 任务

- [ ] 统一 Component 数量
- [ ] 统一 Pin 数量
- [ ] 统一 Net 数量
- [ ] 统一 POWERED_BY 数量
- [ ] 统一 PartType 覆盖率
- [ ] 统一核心电源网络识别率
- [ ] 统一全网电压标注率
- [ ] 统一 POWER 网络电压覆盖率
- [ ] 统一 AMR 覆盖率
- [ ] 统一 GraphRAG chunk 数量
- [ ] 统一 DESCRIBES 关系数量
- [ ] 统一向量模型和维度
- [ ] 输出缺失项明细

### 建议指标定义

```text
PartType 覆盖率
= 已识别 PartType 的 Component / 全部 Component

全网电压标注率
= 有 VoltageLevel 的 Net / 全部 Net

POWER 电压覆盖率
= 有 VoltageLevel 的 POWER Net / 全部 POWER Net

AMR 覆盖率
= 有有效 AMR 参数的目标器件 / 目标器件总数
```

### 验收标准

- [ ] System 页面和命令行工具数字一致
- [ ] 报告中明确每个指标的分母和分子
- [ ] 每个指标都有缺失清单
- [ ] 指标可以按 `project_id` 查询

---

# P2：GraphRAG 和知识检索质量

## P2-1. 专业 Embedding 模型评估

当前默认模型为 `all-MiniLM-L6-v2`，建议评估 `bge-m3` 和 `bge-large-zh-v1.5`。

### 任务

- [ ] 确认当前线上使用的 Embedding 模型
- [ ] 建立中文硬件问题测试集
- [ ] 测试 MPN 检索
- [ ] 测试电源问题检索
- [ ] 测试 Datasheet 参数检索
- [ ] 测试规则检索
- [ ] 比较不同模型的 Recall@K
- [ ] 比较 MRR/NDCG
- [ ] 评估内存和速度
- [ ] 重建 Neo4j 向量索引
- [ ] 更新模型版本记录

### 重要修复

- [ ] 禁止 embedding 加载失败时静默写入零向量
- [ ] 索引构建失败时明确失败
- [ ] System 页面显示 embedding degraded
- [ ] 查询结果附带数据质量状态

## P2-2. GraphRAG Benchmark

### 任务

- [ ] 建立固定 Query Set
- [ ] 对比 local/global/graph/auto
- [ ] 测试实体抽取准确率
- [ ] 测试社区检索质量
- [ ] 测试多跳关系检索
- [ ] 测试项目隔离
- [ ] 测试空结果和错误 MPN
- [ ] 测试查询延迟
- [ ] 输出 benchmark 报告

### 验收指标

```text
Recall@5
Recall@10
MRR
P50 latency
P95 latency
实体抽取准确率
项目隔离正确率
```

## P2-3. Tier2 内网 PLM 接入

当前 Tier2 仍不是实际 PLM，属于预留/替代实现。

### 任务

- [ ] 明确 PLM 接口地址
- [ ] 明确认证方式
- [ ] 明确 MPN 查询接口
- [ ] 明确字段映射
- [ ] 实现 PLM Retriever
- [ ] 实现超时和重试
- [ ] 实现结果缓存
- [ ] 实现敏感字段过滤
- [ ] PLM 结果写回本地知识库
- [ ] PLM 失败降级到 Tier3
- [ ] 增加 Mock PLM 测试

### 验收标准

```text
Tier0 未命中
 → Tier1 未命中
 → Tier2 PLM 命中
 → 结果缓存
 → 下一次优先本地返回
```

---

# P2：测试和工程质量

## P2-4. 完整自动化测试体系

### 任务

- [ ] Unit 测试覆盖率达到 60%
- [ ] 核心模块覆盖率达到 80%
- [ ] API Router 测试
- [ ] ETL 测试
- [ ] Review Engine 测试
- [ ] Graph Tools 测试
- [ ] KnowledgeRouter 测试
- [ ] Agent 异常路径测试
- [ ] 项目隔离测试
- [ ] 并发任务测试
- [ ] 大网络性能测试
- [ ] E2E 测试

### 最低验收标准

```text
Unit tests: 100% pass
Integration tests: 100% pass
E2E smoke tests: 100% pass
Coverage: >= 60%
```

## P2-5. 前端质量门禁

### 任务

- [ ] 增加 ESLint 配置
- [ ] 增加 TypeScript 严格检查
- [ ] 增加 Prettier
- [ ] 处理所有 lint error
- [ ] 增加前端单元测试
- [ ] 增加页面级 smoke test
- [ ] 优化大 chunk
- [ ] 路由级动态加载
- [ ] Graph 页面独立分包

### 验收标准

```bash
npm run build       # PASS
npm run lint        # PASS
npm run typecheck   # PASS
npm run test        # PASS
```

## P2-6. API 和错误处理统一

### 任务

- [ ] 统一错误响应结构
- [ ] 增加 `request_id`
- [ ] 增加 `job_id`
- [ ] ETL 失败原因可追踪
- [ ] Agent 超时可追踪
- [ ] LLM 服务不可用时返回明确错误
- [ ] WebSocket 异常断开可恢复
- [ ] 文件上传大小限制
- [ ] 文件类型白名单
- [ ] 临时文件安全清理
- [ ] 防止同名文件覆盖
- [ ] 增加请求超时

---

# P2：安全与部署

## P2-7. 修复生产安全配置

当前代码存在 `allow_origins=["*"]` 与 `allow_credentials=True` 的组合，不适合作为生产配置。

### 任务

- [ ] CORS 改为环境变量白名单
- [ ] 限制上传文件类型
- [ ] 限制上传文件大小
- [ ] 防止路径穿越
- [ ] 防止临时文件冲突
- [ ] Neo4j 密码移出代码和文档
- [ ] Ollama/Neo4j 连接配置统一走环境变量
- [ ] API 增加认证机制
- [ ] 增加只读模式验证
- [ ] 日志脱敏
- [ ] 不记录完整用户输入中的敏感信息

## P2-8. 性能基准和优化

### 任务

- [ ] ETL 导入耗时基准
- [ ] 全量 Review 耗时基准
- [ ] Graph 查询耗时基准
- [ ] GraphRAG 检索耗时基准
- [ ] Agent 单轮耗时基准
- [ ] WebSocket 首 token 延迟
- [ ] 并发请求测试
- [ ] 大网络 LIMIT 策略验证
- [ ] Neo4j 索引检查
- [ ] LLM 缓存命中率统计

### 建议目标

```text
普通图查询       P95 < 500 ms
GraphRAG 查询    P95 < 2 s
普通 Agent 查询  P95 < 10 s
全量审查         < 30 s
WebSocket 首响应 < 3 s
```

---

# P3：产品增强能力

## P3-1. 审查结果可操作化

- [ ] 违规项跳转到图谱位置
- [ ] 违规项跳转到原理图器件
- [ ] 支持按 RefDes 过滤
- [ ] 支持按 Net 过滤
- [ ] 支持批量忽略
- [ ] 支持规则白名单管理
- [ ] 支持审查结果版本对比
- [ ] 支持两次网表差异审查
- [ ] 支持结果导出 CSV/Excel/JSON

## P3-2. 故障诊断增强

- [ ] 保存诊断会话
- [ ] 支持诊断报告导出
- [ ] 支持用户反馈“正确/错误”
- [ ] 支持人工修正根因
- [ ] 统计诊断命中率
- [ ] 记录工具调用成功率
- [ ] 记录自纠错次数
- [ ] 支持多故障同时分析
- [ ] 支持测量数据输入
- [ ] 支持波形/日志辅助诊断

## P3-3. 知识库增强

- [ ] Datasheet 版本管理
- [ ] 知识片段去重
- [ ] 失效知识标记
- [ ] 知识来源可信度
- [ ] 参数冲突检测
- [ ] 同 MPN 多版本合并
- [ ] 供应商优先级
- [ ] 知识更新审计日志
- [ ] 知识库导入/导出
- [ ] 批量重新建立索引

## P3-4. Streamlit 最终收口

当前 React + FastAPI 已经是主线，Streamlit 属于遗留双轨。

- [ ] React 作为唯一主入口
- [ ] Streamlit 标记为 Legacy
- [ ] 文档统一使用 React 启动方式
- [ ] 迁移仍有价值的 Streamlit 功能
- [ ] 验证 React 完成替代后归档 Streamlit

---

# 推荐执行顺序

## Sprint 1：恢复和验收基础环境

```text
P0-1 服务启动与健康检查
P0-2 测试环境分层
P1-1 网表+BOM ETL 闭环
```

目标：系统能启动，数据能正确导入。

## Sprint 2：核心业务闭环

```text
P1-2 审查闭环
P1-3 Agent 查询/诊断闭环
P1-4 BOM → AMR/知识库
```

目标：完成最核心的产品演示路径。

## Sprint 3：知识库和指标治理

```text
P1-5 Datasheet HITL
P1-6 统一数据质量指标
P2-1 Embedding 评估
P2-2 GraphRAG Benchmark
```

目标：让结果可解释、可衡量、可复现。

## Sprint 4：质量和生产化

```text
P2-4 自动化测试
P2-5 前端质量门禁
P2-6 API 错误处理
P2-7 安全配置
P2-8 性能基准
```

目标：从研发验证版变成可交付版本。

## Sprint 5：高级产品能力

```text
P2-3 内网 PLM
P3-1 审查结果增强
P3-2 故障诊断增强
P3-3 知识库增强
P3-4 Streamlit 收口
```

---

# 第一版产品最终验收门槛

- [ ] 服务可一键启动
- [ ] 网表+BOM 可成功导入
- [ ] 项目数据完全隔离
- [ ] 全量审查可执行并导出报告
- [ ] Agent 可完成查询和故障诊断
- [ ] Datasheet 可解析、审批、入库
- [ ] AMR、电压、PartType 指标统一
- [ ] GraphRAG 有固定 benchmark
- [ ] Unit/Integration/E2E 测试分层
- [ ] 覆盖率达到 60% 以上
- [ ] 前端 build/lint/typecheck 全通过
- [ ] CORS 和文件上传安全配置完成
- [ ] 关键接口有超时、重试和错误提示
- [ ] 有一套真实测试项目可以重复验收

## 近期最优先的三个任务

1. **P0-1：恢复并统一启动全部服务**
2. **P1-1：用固定网表+BOM 跑通 ETL 闭环**
3. **P1-2：跑通一次完整 Review 并导出报告**
