# Neo4j 只读访问方案（决策记录，2026-11-24）

## 结论

不升级 Enterprise，不依赖只读账号。只读由 **会话访问模式** 保证：
`NEO4J_READ_ONLY=true` 时，`graph_tools._run_cypher` 以 `READ_ACCESS` 打开会话，
写语句被 Neo4j 服务端拒绝（`Neo.ClientError.Statement.AccessMode`）。
原有的写关键字正则保留为第一道防线。

## 依据（本机实测）

- 版本：Neo4j 5.26.0 **Community**。
- `SHOW USERS` 中已有 `graph_reader`、`graphreader` 两个账号，`roles` 均为空。
  Community 版没有 RBAC，这两个账号**实际拥有完整写权限**。`.env` 里的
  `NEO4J_READONLY_USER/PASSWORD` 目前没有任何代码使用，也起不到只读作用。
- 在 `READ_ACCESS` 会话中执行 `CREATE`：显式事务和自动提交事务都被服务端拒绝，库里没有留下节点。

## 方案对比

- **升级 Enterprise，用 RBAC 只读角色**：只读最彻底，但需要商业授权和停机迁移，成本与当前单机部署不匹配。
- **只读代理层**：需要解析 Cypher，误判风险高，还多一个组件，不划算。
- **会话 READ_ACCESS（采用）**：零成本，服务端强制执行；但只覆盖经 `_run_cypher` 的查询路径。

## 覆盖范围与边界

- 覆盖：Graph Tools、MCP Server 的只读工具、图谱可视化等所有经 `_run_cypher` 的查询。
- 不覆盖：ETL 导入、HITL 落库、`ReviewRuleEngine`。审查引擎会写 `Net.VoltageLevel`，这些路径持有自己的 driver 会话，必须保留写权限。
- 默认关闭。建议在只做查询的进程上开启，例如由 Hermes 拉起的 MCP Server 进程：
  在其启动环境中加 `NEO4J_READ_ONLY=true`。主 API 进程要负责 ETL 和审批写入，不能开启。

## 后续

- 可删除无效的 `graph_reader` / `graphreader` 账号，避免误以为它们是只读账号（需确认无外部依赖）。
- 测试：`hardware_ai_expert/tests/test_read_only_mode.py`。
