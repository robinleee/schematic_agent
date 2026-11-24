# UI E2E: Hermes 审批卡片全链路脚本

## 怎么跑

```bash
/data/Easel/.venv/bin/python scripts/ui_e2e_agent.py \
  --base-url http://127.0.0.1:8501 \
  --timeout 240 \
  --out-dir /tmp/ui_e2e
```

三个参数都有默认值（如上），服务已在本机跑的话可以直接：

```bash
/data/Easel/.venv/bin/python scripts/ui_e2e_agent.py
```

## 依赖

- `/data/Easel/.venv/bin/python`：已装 `playwright` + chromium，脚本本身不装任何包。
- 目标服务需已启动并可访问（默认 `http://127.0.0.1:8501`），脚本不负责拉起服务。

## 断言了什么

1. 打开 `{base-url}/chat`，切换「经典引擎」→「Hermes 引擎」。
2. 发送一条会触发 `submit_hitl_decision` 的消息。
3. 等待页面出现「需要你确认」审批卡片（超时 `--timeout` 秒），截图 `approval_card.png`。
4. 点击「仅本次允许」按钮。
5. 等待页面出现「已允许」标签（固定 60s 超时），截图 `after_approve.png`。
6. 收集页面 console 的 error 级别日志。

退出码：全部通过 `0`；任一步失败 `1`，并打印一行 `FAILED <原因>`。
结束前固定打印三行检查点：`CARD_VISIBLE` / `APPROVED_TAG_VISIBLE` / `CONSOLE_ERRORS`。

## 失败怎么排查

- `CARD_VISIBLE False` + 超时：先看服务是否真的在跑（`curl {base-url}/chat`），
  再看是否把「经典引擎/Hermes 引擎」文案改了，或 Hermes 后端未配置/未连通。
- `APPROVED_TAG_VISIBLE False`：说明卡片出现了但按钮点击或审批回调失败，
  查看 `--out-dir` 下的 `approval_card.png` 确认卡片内容，再查后端 approval 接口日志。
- `CONSOLE_ERRORS` 非空：打开对应时间点的前端 console 错误，定位是否是该次改动引入的回归。
- 截图路径：`{out-dir}/<时间戳>/approval_card.png` 和 `after_approve.png`。
