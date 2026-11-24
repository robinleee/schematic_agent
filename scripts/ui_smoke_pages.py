#!/usr/bin/env python3
"""Playwright 七页面冒烟：在一个临时项目上跑 ETL → Review → Graph → Knowledge → HITL → System，最后删除该项目。

用法：
    /data/Easel/.venv/bin/python scripts/ui_smoke_pages.py [临时项目名]

逐项打印 PASS/FAIL，截图与 results.json 写到 /tmp/ui_pages/pass2/。
只写入临时项目（结束时经 UI 删除），不触碰已有项目数据。Chat 页另见 scripts/ui_e2e_agent.py。
"""
import asyncio, json, os, sys, tempfile, time
from playwright.async_api import async_playwright

BASE = "http://127.0.0.1:8501"
OUT = "/tmp/ui_pages/pass2"
FIX = tempfile.mkdtemp(prefix="ui_smoke_")
FIXTURE = {
    "pstxnet.dat": "NET_NAME\n'VCC_3V3'\nNODE_NAME U1 1\nNODE_NAME C1 1\nNET_NAME\n'GND'\nNODE_NAME U1 2\nNODE_NAME C1 2\n",
    "pstxprt.dat": "PART_NAME\nU1 'MCU_DEMO'\nPART_NAME\nC1 'CAP_DEMO'\n",
    "pstchip.dat": "primitive 'MCU_DEMO'\nbody\nVALUE='DEMO'\nend_body\nend_primitive\n"
                   "primitive 'CAP_DEMO'\nbody\nVALUE='0.1UF'\nend_body\nend_primitive\n",
    "bom.csv": "RefDes,MPN,Manufacturer,Description,Package,Quantity\n"
               "U1,DEMO-MCU,Example,Microcontroller,QFN,1\nC1,DEMO-C,Example,Capacitor,0402,1\n",
}
for _name, _text in FIXTURE.items():
    with open(os.path.join(FIX, _name), "w") as _fh:
        _fh.write(_text)
PROJECT = sys.argv[1] if len(sys.argv) > 1 else f"ui-smoke-{int(time.time())}"
results = []


def rec(step, ok, detail=""):
    results.append({"step": step, "ok": ok, "detail": str(detail)[:400]})
    print(("PASS " if ok else "FAIL ") + step + " :: " + str(detail)[:300], flush=True)


async def body(page):
    return await page.inner_text("body")


async def main():
    os.makedirs(OUT, exist_ok=True)
    async with async_playwright() as p:
        browser = await p.chromium.launch()
        ctx = await browser.new_context(viewport={"width": 1440, "height": 1000})
        page = await ctx.new_page()
        errs, bad = [], []
        page.on("console", lambda m: errs.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda ex: errs.append("PAGEERROR " + str(ex)))
        page.on("response", lambda r: bad.append(f"{r.status} {r.request.method} {r.url}") if r.status >= 400 else None)

        # ---- ETL: create project, upload, preview, run ----
        await page.goto(f"{BASE}/etl", wait_until="networkidle")
        await page.get_by_role("button", name="新建项目").click()
        await page.get_by_placeholder("输入项目名称").fill(PROJECT)
        await page.locator(".ant-modal").get_by_role("button", name="OK").or_(
            page.locator(".ant-modal").get_by_role("button", name="确 定")).first.click()
        await page.wait_for_timeout(1500)
        t = await body(page)
        rec("etl.create_project", PROJECT in t, "header/select shows project" if PROJECT in t else t[:300])

        inputs = page.locator("input[type=file]")
        n = await inputs.count()
        for i, f in enumerate(["pstxnet.dat", "pstxprt.dat", "pstchip.dat", "bom.csv"][:n]):
            await inputs.nth(i).set_input_files(os.path.join(FIX, f))
        await page.get_by_role("button", name="预览").click()
        await page.wait_for_selector("text=预览结果", timeout=60000)
        t = await body(page)
        rec("etl.preview", "预览结果" in t and "BOM 关联器件" in t, t[t.find("预览结果"):][:300])
        await page.screenshot(path=f"{OUT}/etl_preview.png", full_page=True)

        await page.get_by_role("button", name="执行导入").click()
        await page.locator(".ant-modal-confirm").get_by_role("button", name="确认导入").click()
        ok = False
        for _ in range(80):
            await page.wait_for_timeout(1500)
            t = await body(page)
            if "导入结果" in t and ("质量检查通过" in t or "质量检查未通过" in t):
                ok = "质量检查通过" in t
                break
        rec("etl.run", ok, t[t.find("导入结果"):][:300] if "导入结果" in t else t[-400:])
        await page.screenshot(path=f"{OUT}/etl_run.png", full_page=True)

        # ---- Review ----
        await page.goto(f"{BASE}/review", wait_until="networkidle")
        t0 = time.time()
        await page.get_by_role("button", name="执行审查").click()
        try:
            await page.wait_for_function("() => !document.body.innerText.includes('点击「执行审查」开始检查')", timeout=300000)
            await page.wait_for_timeout(1500)
            t = await body(page)
            rec("review.run", PROJECT in t, f"{time.time()-t0:.1f}s :: " + t[t.find("违规列表"):][:300])
        except Exception as e:
            rec("review.run", False, e)
        await page.screenshot(path=f"{OUT}/review.png", full_page=True)

        # ---- Graph ----
        await page.goto(f"{BASE}/graph", wait_until="networkidle")
        await page.get_by_placeholder("例如：U30004").fill("U1")
        await page.get_by_role("button", name="生成图谱").click()
        await page.wait_for_timeout(5000)
        t = await body(page)
        i = t.find("节点 ")
        rec("graph.component", i >= 0 and not t[i:].startswith("节点 0"), t[i:i+40])
        await page.screenshot(path=f"{OUT}/graph.png", full_page=True)

        # ---- Knowledge: upload + search ----
        await page.goto(f"{BASE}/knowledge", wait_until="networkidle")
        txt = os.path.join(FIX, "uismoke_note.txt")
        with open(txt, "w") as fh:
            fh.write("UISMOKE-001 是用于前端联调的测试器件，额定电压 3.3V，最大电流 500mA。\n")
        await page.get_by_placeholder("例如：MT25QU256ABA8E12").first.fill("UISMOKE-001")
        await page.locator("input[type=file]").first.set_input_files(txt)
        await page.wait_for_timeout(6000)
        t = await body(page)
        rec("knowledge.upload", "失败" not in t, [s for s in t.split("\n") if "成功" in s or "失败" in s][:3])
        await page.get_by_role("tab", name="知识检索测试").click()
        await page.get_by_placeholder("输入查询内容").fill("UISMOKE-001 额定电压")
        await page.locator(".ant-tabs-tabpane-active").get_by_role("button").last.click()
        await page.wait_for_timeout(8000)
        t = await body(page)
        rec("knowledge.search", "3.3V" in t, t[t.find("输入查询内容"):][:300] if "3.3V" not in t else "hit contains 3.3V")
        await page.screenshot(path=f"{OUT}/knowledge.png", full_page=True)

        # ---- HITL ----
        await page.goto(f"{BASE}/hitl", wait_until="networkidle")
        t = await body(page)
        rec("hitl.load", "待审批" in t, t[t.find("待审批"):][:200])
        await page.get_by_role("tab", name="Datasheet 参数沉淀").click()
        await page.wait_for_timeout(1500)
        await page.screenshot(path=f"{OUT}/hitl.png", full_page=True)

        # ---- System ----
        await page.goto(f"{BASE}/system", wait_until="networkidle")
        await page.wait_for_timeout(2000)
        t = await body(page)
        rec("system.status", t.count("运行中") >= 4, t[t.find("服务状态"):][:200])

        # ---- ETL: delete the throwaway project ----
        await page.goto(f"{BASE}/etl", wait_until="networkidle")
        await page.get_by_role("button", name="删除项目").click()
        await page.locator(".ant-modal-confirm").get_by_role("button", name="删 除").or_(
            page.locator(".ant-modal-confirm").get_by_role("button", name="删除")).first.click()
        await page.wait_for_timeout(3000)
        t = await body(page)
        rec("etl.delete_project", "项目删除成功" in t or PROJECT not in t, t[:200])

        rec("console_errors", not errs, errs[:10])
        rec("http_errors", not bad, bad[:10])
        await browser.close()
    json.dump(results, open(f"{OUT}/results.json", "w"), ensure_ascii=False, indent=1)
    return 0 if all(r["ok"] for r in results) else 1


sys.exit(asyncio.run(main()))
