# 剩余任务 TODO（2026-10-04 整理）

> 依据：`docs/product/DELIVERY_CLOSURE_TASK_LIST.md` 最终验收门槛 18 项 + `.comate/specs/delivery-closure-track/tasks.md` 15 项交叉核对。
> 环境确认：本地 Neo4j/Ollama/ChromaDB 可用；5 个 datasheet PDF 为公开资料可用于验证；用户可配合浏览器人工验收；PLM 接口资料不可用（只能 mock）。
> 原则：真实验证优先，拿不到资源的项目明确标记"阻塞"，不伪造通过。

## P0 — 阻塞交付的核心项

- [x] **1a. Chat/Agent 真实服务核对** ✅ 2026-10-04（七页面全量联调仍未完成，见下）
  - 用真实请求核对了 System/ETL/HITL/Knowledge/Graph/Review/Chat 共7个接口，全部跑通
  - 过程中发现并修复 Chat/WS 从未传递 project_id 的严重 bug（Agent 查任何具体器件都失败）
  - 浏览器人工点击仍未做，接口层验证 ≠ 完整的七页面联调
- [ ] **1b. 七页面浏览器人工联调**（Chat/Review/HITL/Knowledge/ETL/Graph/System）
  - 需要在浏览器中逐页面执行核心操作，确认视觉/交互正确
- [x] **2. 独立测试项目做真实 A/B 隔离验证**（Task 5/8）✅ 2026-10-04
  - 用隔离 project_id（`closure_ab_test_A`/`closure_ab_test_B`）跑通 ETL Preview→Run→Review→HITL→Knowledge 全链路
  - 验证通过：Neo4j Component/Net 数据正确隔离（A/B 各自2个器件，互不可见）；Review 按项目返回不同违规（A:1条, B:1条）；HITL 跨项目 approve 正确拒绝；Knowledge 搜索 B 看不到 A 上传的文档
  - 过程中发现并修复两个真实 bug（Chroma 集合维度不匹配导致 Knowledge 上传全部 503；删除项目接口返回类型不匹配导致 500）
  - 测试数据已清理

- [ ] **3. Datasheet HITL 真实闭环（3+ 个真实 PDF，接真实 Neo4j）**（Task 7）
  - 用 datasheets/ 下的 PDF 跑完整链路：解析→Pending→Approve→持久化到 AMR/规则→重启后可查询
  - 不同于已有的 mock 测试，这次要接真实 Neo4j 写入
- [ ] **4. BOM→MPN→AMR/知识库关联可追溯性验证**（Task 6）
  - 用 ≥20 条边界 fixture（重复 RefDes、缺失 MPN、厂商别名等）验证 part_type_standardizer 的冲突处理
  - 确认 Component.MPN 实际驱动了 AMR 查询和知识检索，而非仅停留在图谱属性

## P1 — 核心功能完善

- [ ] **5. GraphRAG 检索质量 benchmark（真实 bge-m3 模型）**（Task 9）
  - 构造固定 query set + golden answer，用已切换的 bge-m3 索引跑 Recall@5/10、MRR、NDCG
  - 对比新旧索引（384维 vs 1024维）检索质量差异
- [ ] **6. 电压标注率/AMR 覆盖率真实复核**（Task 10）
  - 连真实 Neo4j 跑一次 `scripts/check_data_quality.py`，核实 AMR 覆盖率是否真的到 99.8%（目前只是 commit message 里的数字，未实测复核）
  - 核实核心网络识别率现状
- [ ] **7. Tier2 PLM 适配器 + 契约测试（mock，明确标注非真实集成）**（Task 11 剩余部分）
  - 已有 Tier3 降级，PLM 地址/认证资料缺失，只补充可配置适配器 + mock 契约测试

## P2 — 质量与生产化

- [ ] **8. 测试覆盖率补齐到 60%**（Task 12 剩余）
  - 当前核心模块 42.4%，重点补 `agent_core.py`(622行,0%)、`storage_dispatcher.py`(171行,0%) 等大文件
- [ ] **9. 性能基准测试（真实服务）**（Task 13 剩余）
  - 图查询、Review、GraphRAG、Agent 在真实 Neo4j+Ollama 上测 P50/P95，对比目标（图查询<500ms, GraphRAG<2s, Agent<10s, Review<30s）
- [ ] **10. Neo4j 备份恢复演练**（Task 14 剩余）
  - `scripts/recovery.py` 已有计划生成，在隔离环境真实执行一次备份+恢复
- [ ] **11. Streamlit 遗留入口收口**
  - 确认七页面验收通过后，给 `web_ui/app.py` 加明确 Legacy 标注或归档

---

## 执行顺序

P0 四项是阻塞交付的硬门槛，按 1→2→3→4 顺序做（1是最耗时但最直接的，2/3/4 依赖真实 Neo4j 已验证可用可以并行推进其中的编码部分）。P1/P2 在 P0 完成后视情况推进，其中 **7 和 10 大概率只能停在"mock/预案"阶段**（PLM 资料缺失、生产恢复演练需要用户明确授权才能在真实服务上做破坏性操作）。

每完成一项，用真实运行证据（请求/响应记录、测试通过数、截图或人工确认）更新本文件状态，不以代码存在作为完成依据。
