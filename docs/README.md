# 项目文档导航

本目录是 schematic_agent 的项目文档入口。根目录仅保留 Agent/运行上下文文件与项目基础文件；产品、架构、前端、运维、审计类文档统一收敛到 `docs/` 下。

## 当前界面与启动

React + FastAPI 是主线：在仓库根目录执行 `cd frontend && npm run build`，返回根目录后执行 `bash scripts/start_dev.sh`，通过 `http://localhost:8501/` 访问构建后的 React SPA（API 文档：`http://localhost:8501/docs`）。开发时可在 `frontend/` 执行 `npm run dev`，Vite 默认端口为 3000，代理 `/api` 与 `/ws` 到 FastAPI :8501。`scripts/healthcheck.sh` 仅检查服务可达性，不代表七页面业务验收通过。

`hardware_ai_expert/web_ui/app.py` 是保留的 Legacy Streamlit 入口，默认启动脚本不启动它；七页面尚缺逐页实时核心操作验证，不应归档或声称已完成迁移。交付门槛见 `product/DELIVERY_CLOSURE_TASK_LIST.md`，其未通过项目继续保持未勾选。

## 推荐阅读顺序

1. `product/PRD_V5.1.md` — 当前产品需求基线，包含技术选型回写、指标口径、非功能需求与安全要求。
2. `architecture/TECHNICAL_IMPLEMENTATION_PLAN.md` — 当前技术实现方案 V2.0，按代码事实描述系统架构、模块状态与路线图。
3. `product/TODO_DEVELOPMENT_TASKS.md` — 当前待完成开发任务清单，可按完成状态动态更新。
4. `product/PRD_GAP_ANALYSIS_V2.md` — 最新 gap 分析，作为剩余待办与风险排序的参考。
5. `../CLAUDE.md` — 给 AI 编码助手的工作指南与代码库快速索引。

## 文档分区

### product/

产品与需求基线：

- `PRD_V5.1.md` — 当前 PRD，正式基线。
- `TODO_DEVELOPMENT_TASKS.md` — 当前待完成开发任务清单，可动态更新状态。
- `PRD_GAP_ANALYSIS_V2.md` — 最新 gap 分析。
- `DELIVERY_CLOSURE_TASK_LIST.md` — 交付阻塞项与最终验收清单。

### architecture/

架构、模块设计与专项技术方案：

- `TECHNICAL_IMPLEMENTATION_PLAN.md` — 技术实现方案 V2.0。
- `GRAPH_TOOLS_SPEC.md` — 图谱工具规格说明。
- `PARTTYPE_STANDARDIZER_SPEC.md` — PartType 标准化方案。

### frontend/

前后端接口与前端设计：

- `API_SPEC.md` — API 规格。
- `FRONTEND_DESIGN.md` — 前端设计说明。
- `FRONTEND_TASK.md` — 前端任务拆解。

### ops/

环境、部署、修复与运维说明：

- `ENVIRONMENT_FIX.md` — 环境修复说明。
- `ENV_RECOVERY_RUNBOOK.md` — 当前机器服务恢复与健康检查。
- `ducc-remote-setup-guide.md` — DUCC 远程配置指南。

### audit/

审计与历史整改材料：

- `DOC_AUDIT_PRD_TECH_PLAN_2026-06-12.md` — PRD 与技术方案文档审计报告。

## 历史归档

过期 PRD、旧路线图、旧分析报告已移动到 `../archive/`。这些文档仅作为历史参考，不应作为当前开发基线。

## 维护规则

- 新的活文档优先放入 `docs/` 对应分区。
- 过期文档移动到 `archive/`，不要留在根目录。
- 当前基线只认三份活文档：`product/PRD_V5.1.md`、`architecture/TECHNICAL_IMPLEMENTATION_PLAN.md`、`product/PRD_GAP_ANALYSIS_V2.md`；任务跟踪使用 `product/TODO_DEVELOPMENT_TASKS.md`。
- 文档内引用路径变更时，同步更新 `CLAUDE.md` 与本导航页。
