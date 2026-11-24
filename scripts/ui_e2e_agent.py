#!/usr/bin/env python3
"""Playwright 端到端脚本：Hermes 引擎 HITL 审批卡片全链路验证。

流程：打开 {base-url}/chat → 切到 Hermes 引擎 → 发一条会触发
submit_hitl_decision 的消息 → 等待审批卡片出现 → 点击「仅本次允许」→
断言出现「已允许」→ 截图。

运行：
    /data/Easel/.venv/bin/python scripts/ui_e2e_agent.py

退出码：成功 0，失败 1（失败时打印 FAILED 原因）。
"""
import argparse
import asyncio
import os
import sys
from datetime import datetime

from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

PROMPT = "调用 submit_hitl_decision，review_id=UI-1，decision=approve，comment=前端联调"


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--base-url", default="http://127.0.0.1:8501",
                     help="前端/后端基础地址（默认 http://127.0.0.1:8501）")
    ap.add_argument("--timeout", type=int, default=240,
                     help="等待审批卡片出现的超时秒数（默认 240）")
    ap.add_argument("--out-dir", default="/tmp/ui_e2e",
                     help="截图输出目录（默认 /tmp/ui_e2e）")
    return ap.parse_args()


async def run(base_url: str, timeout_s: int, out_dir: str) -> int:
    os.makedirs(out_dir, exist_ok=True)
    url = base_url.rstrip("/") + "/chat"
    timeout_ms = timeout_s * 1000

    errors = []
    checkpoints = {"CARD_VISIBLE": False, "APPROVED_TAG_VISIBLE": False}
    fail_reason = None

    async with async_playwright() as p:
        browser = await p.chromium.launch()
        page = await browser.new_page(viewport={"width": 1440, "height": 900})
        page.on(
            "console",
            lambda m: errors.append(f"{m.type}: {m.text}") if m.type == "error" else None,
        )

        try:
            await page.goto(url, wait_until="networkidle")

            await page.get_by_text("经典引擎").click()
            await page.get_by_text("Hermes 引擎").click()

            box = page.locator("textarea").first
            await box.fill(PROMPT)
            await box.press("Enter")

            try:
                await page.wait_for_selector("text=需要你确认", timeout=timeout_ms)
            except PlaywrightTimeoutError:
                fail_reason = f"等待审批卡片超时（{timeout_s}s 内未出现「需要你确认」）"
                raise

            checkpoints["CARD_VISIBLE"] = True
            await page.screenshot(path=os.path.join(out_dir, "approval_card.png"), full_page=False)

            try:
                await page.get_by_role("button", name="仅本次允许").click()
            except Exception as exc:
                fail_reason = f"未找到「仅本次允许」按钮：{exc}"
                raise

            try:
                await page.wait_for_selector("text=已允许", timeout=60000)
            except PlaywrightTimeoutError:
                fail_reason = "点击「仅本次允许」后 60s 内未出现「已允许」标签"
                raise

            checkpoints["APPROVED_TAG_VISIBLE"] = True
            await page.wait_for_timeout(2000)
            await page.screenshot(path=os.path.join(out_dir, "after_approve.png"), full_page=False)

        except Exception as exc:
            if fail_reason is None:
                fail_reason = str(exc)
        finally:
            await browser.close()

    print(f"CARD_VISIBLE {checkpoints['CARD_VISIBLE']}", flush=True)
    print(f"APPROVED_TAG_VISIBLE {checkpoints['APPROVED_TAG_VISIBLE']}", flush=True)
    print(f"CONSOLE_ERRORS {errors[:5]}", flush=True)

    if fail_reason:
        print(f"FAILED {fail_reason}", flush=True)
        return 1
    return 0


def main():
    args = parse_args()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = os.path.join(args.out_dir, ts) if not os.path.isabs(args.out_dir) else args.out_dir
    return asyncio.run(run(args.base_url, args.timeout, out_dir))


if __name__ == "__main__":
    sys.exit(main())
