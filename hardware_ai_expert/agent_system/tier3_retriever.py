"""
Tier3 公网检索器 — 轻量纯 Python 实现

不依赖 Docker / Firecrawl，直接用 requests + html2text + Ollama 实现。

策略：
  3a: 定点抓取 — MPN 前缀匹配供应商 → URL 模板 → requests 抓取 → LLM 结构化提取
  3b: 通用搜索 — 预留（需搜索引擎后端，当前百度内网不可用）

安全原则：
  - 只携带 MPN 出公网，不携带任何电路上下文
  - 查询结果自动缓存到 Tier1 (ChromaDB)
  - 提取参数经 HITL 审批后才落盘到 AMR/规则引擎
"""

from __future__ import annotations

import os
import re
import json
import logging
from typing import Optional
from datetime import datetime

import requests
import html2text
from pydantic import BaseModel, Field
from dotenv import load_dotenv

from agent_system.knowledge_router import (
    PublicMPNRetriever,
    RetrievalResult,
    TierLevel,
)

logger = logging.getLogger(__name__)

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))


# ============================================================
# 供应商 URL 模板
# ============================================================

SUPPLIER_URL_TEMPLATES: dict[str, dict] = {
    "TI": {
        "prefixes": [
            "TPS", "TLV", "TPD", "TS5", "SN74", "CD74",
            "LM", "LMV", "OPA", "THS", "BQ", "UCC", "UCD",
            "ADS", "DAC", "ADC", "HDC", "TMP", "DRV",
        ],
        # TI 产品页 URL 用基础型号，不带封装后缀
        "url_template": "https://www.ti.com/product/{mpn_base}",
        "datasheet_pattern": "https://www.ti.com/lit/ds/symlink/{mpn_base_lower}.pdf",
        "strip_suffix": True,
    },
    "MURATA": {
        "prefixes": ["GRM", "GCM", "GJM", "NFM", "BLM", "DLP"],
        "url_template": "https://www.murata.com/en-global/products/search?keyword={mpn}",
    },
    "TDK": {
        "prefixes": ["C0402", "C0603", "C1005", "C1608", "CGA", "C3216"],
        "url_template": "https://product.tdk.com/en/search/search_result.html?kw={mpn}",
    },
    "SAMSUNG": {
        "prefixes": ["CL0", "CL1", "C1", "C2"],
        "url_template": "https://api.semiconductor.samsung.com/products/{mpn}",
    },
    "YAGEO": {
        "prefixes": ["RC", "AC", "CC", "SR"],
        "url_template": "https://www.yageo.com/en/product-search?keyword={mpn}",
    },
    "STM": {
        "prefixes": ["STM32", "STM8", "STW", "STB", "L6", "L7"],
        "url_template": "https://www.st.com/en/search.html#q={mpn}",
    },
    "NXP": {
        "prefixes": ["LPC", "S32", "MC33", "74HC", "74LVC", "LPC1"],
        "url_template": "https://www.nxp.com/products/search?searchString={mpn}",
    },
    "INFINEON": {
        "prefixes": ["IRF", "BTS", "TLE", "XMC", "CY8C"],
        "url_template": "https://www.infineon.com/cms/en/product/search?searchString={mpn}",
    },
    "MICROCHIP": {
        "prefixes": ["ATMEGA", "ATTINY", "PIC", "MCP", "KSZ"],
        "url_template": "https://www.microchip.com/en-us/product/{mpn}",
    },
}


def _strip_mpn_suffix(mpn: str, config: dict) -> list[str]:
    """
    生成 MPN 基础型号候选列表（从长到短）。

    TI 产品页 URL 用基础型号，但后缀截断规则不固定。
    策略：生成多个候选，抓取时逐个尝试直到 200。

    TPS5430DDA → [TPS5430DDA, TPS5430]
    TPS7A47 → [TPS7A47]  (47含数字，不截)
    SN74LVC1G34DBVR → [SN74LVC1G34DBVR, SN74LVC1G34]
    """
    if not config.get("strip_suffix"):
        return [mpn]

    candidates = [mpn]
    # 从末尾去掉纯字母后缀
    # TPS5430DDA → TPS5430 (去掉 DDA)
    # SN74LVC1G34DBVR → SN74LVC1G34 (去掉 DBVR)
    # TPS7A47 → 不匹配 (47是数字结尾，A是中间)
    m = re.match(r'^(.*\d+)([A-Z]+)$', mpn, re.IGNORECASE)
    if m:
        base = m.group(1)
        if base != mpn:
            candidates.append(base)

    return candidates


def match_supplier(mpn: str) -> Optional[tuple[str, dict, list[str]]]:
    """
    根据 MPN 前缀匹配供应商和 URL 模板。
    长前缀优先。

    Returns:
        (supplier, config, mpn_candidates) 或 None
    """
    mpn_upper = mpn.upper()
    best_match = None
    best_prefix_len = 0

    for supplier, config in SUPPLIER_URL_TEMPLATES.items():
        for prefix in config["prefixes"]:
            if mpn_upper.startswith(prefix.upper()) and len(prefix) > best_prefix_len:
                mpn_candidates = _strip_mpn_suffix(mpn, config)
                best_match = (supplier, config, mpn_candidates)
                best_prefix_len = len(prefix)

    return best_match


# ============================================================
# 结构化提取 Schema
# ============================================================

class ComponentSpec(BaseModel):
    """从公网提取的器件规格"""
    mpn: str
    description: str = ""
    manufacturer: str = ""
    package: str = ""
    voltage_rating: Optional[float] = None   # V
    current_rating: Optional[float] = None   # A
    power_rating: Optional[float] = None     # W
    temperature_range: str = ""              # "-40~125°C"
    key_params: dict = Field(default_factory=dict)  # 其他参数
    source_url: str = ""
    extracted_at: str = ""


# ============================================================
# LLM 结构化提取 Prompt
# ============================================================

EXTRACT_PROMPT = """You are a hardware component specification extractor.
Given the following web page content about an electronic component, extract key specifications.

Component MPN: {mpn}

Page Content:
{content}

Extract the following as JSON:
{{
  "description": "brief component description",
  "manufacturer": "manufacturer name",
  "package": "package/encapsulation type",
  "voltage_rating": null_or_value_in_volts,
  "current_rating": null_or_value_in_amps,
  "power_rating": null_or_value_in_watts,
  "temperature_range": "operating temp range string",
  "key_params": {{"param_name": "value_with_unit", ...}}
}}

Rules:
- Only extract facts explicitly stated in the content
- Use null for values not found
- Include units in key_params values
- Be precise with numbers, do not guess
- Output ONLY the JSON, no other text"""


# ============================================================
# HTML → Markdown 清洗
# ============================================================

def html_to_clean_markdown(html: str, max_len: int = 6000) -> str:
    """将 HTML 转换为清洗后的 Markdown"""
    h = html2text.HTML2Text()
    h.ignore_links = True
    h.ignore_images = True
    h.ignore_emphasis = True
    h.body_width = 0
    h.skip_internal_links = True

    md = h.handle(html)

    # 清理多余空白
    md = re.sub(r'\n{3,}', '\n\n', md)
    md = re.sub(r'[ \t]+', ' ', md)

    return md[:max_len]


# ============================================================
# LLM 结构化提取
# ============================================================

def _extract_with_llm(mpn: str, content: str) -> Optional[ComponentSpec]:
    """使用本地 Ollama chat_json 从 markdown 内容提取结构化参数"""
    try:
        from agent_system.llm_client import LLMClient
        client = LLMClient()

        prompt = EXTRACT_PROMPT.format(mpn=mpn, content=content[:4000])

        data = client.chat_json(
            prompt=prompt,
            temperature=0.1,
            max_tokens=1024,
        )

        if not data or not isinstance(data, dict):
            logger.warning(f"Tier3 LLM 提取返回非 dict: {type(data)}")
            return None

        return ComponentSpec(
            mpn=mpn,
            description=data.get("description", ""),
            manufacturer=data.get("manufacturer", ""),
            package=data.get("package", ""),
            voltage_rating=data.get("voltage_rating"),
            current_rating=data.get("current_rating"),
            power_rating=data.get("power_rating"),
            temperature_range=data.get("temperature_range", ""),
            key_params=data.get("key_params", {}),
            extracted_at=datetime.now().isoformat(),
        )
    except Exception as e:
        logger.error(f"Tier3 LLM 结构化提取失败: {e}")
        return None


# ============================================================
# WebScraper — 轻量 HTTP 抓取
# ============================================================

class WebScraper:
    """轻量 HTTP 抓取器（requests + html2text）"""

    def __init__(self):
        self.timeout = int(os.getenv("TIER3_SCRAPE_TIMEOUT", "15"))
        self.user_agent = (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": self.user_agent})

    def scrape_html(self, url: str) -> Optional[str]:
        """抓取 HTML 页面并转为 Markdown"""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()

            content_type = resp.headers.get("content-type", "")
            if "pdf" in content_type.lower():
                logger.info(f"Tier3: URL 返回 PDF ({len(resp.content)} bytes)")
                return None

            return html_to_clean_markdown(resp.text)

        except requests.exceptions.Timeout:
            logger.warning(f"Tier3 scrape 超时: {url}")
            return None
        except requests.exceptions.HTTPError as e:
            logger.warning(f"Tier3 scrape HTTP 错误: {e.response.status_code} {url}")
            return None
        except Exception as e:
            logger.error(f"Tier3 scrape 失败: {e}")
            return None

    def scrape_pdf(self, url: str) -> Optional[str]:
        """下载 PDF 并解析（复用 PyMuPDF）"""
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()

            if len(resp.content) < 1000:
                logger.warning(f"Tier3: PDF 太小 ({len(resp.content)} bytes)")
                return None

            try:
                import fitz  # PyMuPDF
                import io
                doc = fitz.open(stream=io.BytesIO(resp.content), filetype="pdf")
                text_parts = []
                for page_num in range(min(len(doc), 5)):  # 最多取前5页
                    text_parts.append(doc[page_num].get_text())
                doc.close()
                full_text = "\n\n".join(text_parts)
                if len(full_text.strip()) > 100:
                    return full_text[:6000]
            except ImportError:
                logger.debug("PyMuPDF 未安装，跳过 PDF 解析")

            return None

        except Exception as e:
            logger.error(f"Tier3 PDF 抓取失败: {e}")
            return None


# ============================================================
# Tier3Retriever — 替换 PublicMPNRetriever
# ============================================================

class Tier3Retriever(PublicMPNRetriever):
    """
    Tier3 公网检索器（轻量纯 Python 实现）

    策略：
      3a: 定点抓取 — MPN 前缀匹配供应商 → URL 模板 → scrape + LLM 提取
      3b: 通用搜索 — 预留（需搜索引擎后端）

    安全：
      - 只携带 MPN，不携带电路上下文
      - 结果自动缓存到 Tier1
    """

    def __init__(self):
        self.enabled = os.getenv("TIER3_ENABLED", "false").lower() in ("true", "1", "yes")
        self._scraper = None
        self._max_content_len = int(os.getenv("TIER3_MAX_CONTENT_LEN", "6000"))
        self._enable_llm_extract = os.getenv("TIER3_LLM_EXTRACT", "true").lower() in ("true", "1", "yes")

    @property
    def scraper(self) -> Optional[WebScraper]:
        """延迟初始化抓取器"""
        if not self.enabled:
            return None
        if self._scraper is None:
            self._scraper = WebScraper()
        return self._scraper

    def search(self, mpn: str, query: str) -> Optional[RetrievalResult]:
        """执行 Tier3 公网检索"""
        if not self.enabled:
            return None

        # 触发延迟初始化
        _ = self.scraper
        if not self._scraper:
            return None

        # 脱敏：只用 MPN，忽略 query 中的电路上下文
        safe_query = self._sanitize_query(mpn, query)
        logger.info(f"Tier3 search: mpn={mpn}, safe_query={safe_query}")

        # 策略 3a: 定点抓取
        result = self._search_by_supplier(mpn, safe_query)
        if result:
            return result

        # 策略 3b: 通用搜索（预留）
        # TODO: 接入 SearXNG / Firecrawl search

        return None

    def _sanitize_query(self, mpn: str, query: str) -> str:
        """
        脱敏：只保留通用查询意图，移除电路上下文
        """
        # 移除 MPN 本身
        cleaned = re.sub(re.escape(mpn), "", query, flags=re.IGNORECASE)

        # 移除具体网络名/引脚名（2-5位大写+数字标识符）
        cleaned = re.sub(r'\b[A-Z]{2,5}\d{1,3}\b', '', cleaned)

        # 保留通用技术关键词
        tech_keywords = {
            "voltage", "current", "power", "rating", "threshold",
            "frequency", "capacitance", "resistance", "temperature",
            "datasheet", "specification", "specs", "pinout",
            "package", "derating", "esr", "tolerance", "input",
            "output", "switching", "buck", "ldo", "regulator",
        }
        words = cleaned.lower().split()
        safe_words = [w for w in words if w in tech_keywords or len(w) > 5]

        return " ".join(safe_words) if safe_words else "specifications"

    # ---- 策略 3a: 定点抓取 ----

    def _search_by_supplier(self, mpn: str, query: str) -> Optional[RetrievalResult]:
        """根据 MPN 前缀匹配供应商，定点抓取产品页"""
        match = match_supplier(mpn)
        if not match:
            logger.debug(f"Tier3: MPN {mpn} 未匹配到供应商模板")
            return None

        supplier, config, mpn_candidates = match

        # 逐个尝试 MPN 候选，直到抓取成功
        for mpn_base in mpn_candidates:
            url = config["url_template"].format(
                mpn=mpn,
                mpn_lower=mpn.lower(),
                mpn_base=mpn_base,
                mpn_base_lower=mpn_base.lower(),
            )
            logger.info(f"Tier3 3a: {supplier} → {url}")

            result = self._try_scrape_supplier(mpn, supplier, config, url, mpn_base)
            if result:
                return result

        return None

    def _try_scrape_supplier(
        self, mpn: str, supplier: str, config: dict, url: str, mpn_base: str
    ) -> Optional[RetrievalResult]:
        """尝试抓取一个供应商 URL"""
        # Step 1: 抓取产品页
        markdown = self.scraper.scrape_html(url)
        if not markdown or len(markdown.strip()) < 100:
            logger.debug(f"Tier3 3a: 页面抓取为空或太短 ({supplier} {url})")
            return None

        # Step 2: 如果有 Datasheet PDF URL 模板，尝试抓取补充
        if "datasheet_pattern" in config:
            ds_url = config["datasheet_pattern"].format(
                mpn=mpn,
                mpn_lower=mpn.lower(),
                mpn_base=mpn_base,
                mpn_base_lower=mpn_base.lower(),
            )
            pdf_text = self.scraper.scrape_pdf(ds_url)
            if pdf_text:
                markdown += "\n\n--- DATASHEET ---\n" + pdf_text[:3000]

        # Step 3: 截断
        markdown = markdown[:self._max_content_len]

        # Step 4: LLM 结构化提取（可选）
        spec = None
        if self._enable_llm_extract:
            spec = _extract_with_llm(mpn, markdown)

        # Step 5: 构建结果
        content = self._build_content(mpn, supplier, url, markdown, spec)

        return RetrievalResult(
            status="success",
            tier=TierLevel.TIER_3,
            content=content,
            source=f"tier3:{supplier}:{url}",
            confidence=0.7,
            mpn=mpn,
        )

    # ---- 辅助方法 ----

    def _build_content(
        self,
        mpn: str,
        source: str,
        url: str,
        markdown: str,
        spec: Optional[ComponentSpec],
    ) -> str:
        """构建 RetrievalResult.content"""
        parts = [f"[Tier3 公网检索 | 来源: {source} | URL: {url}]\n"]

        if spec:
            parts.append(f"## {spec.description or mpn}")
            if spec.manufacturer:
                parts.append(f"制造商: {spec.manufacturer}")
            if spec.package:
                parts.append(f"封装: {spec.package}")
            if spec.voltage_rating is not None:
                parts.append(f"额定电压: {spec.voltage_rating}V")
            if spec.current_rating is not None:
                parts.append(f"额定电流: {spec.current_rating}A")
            if spec.power_rating is not None:
                parts.append(f"额定功率: {spec.power_rating}W")
            if spec.temperature_range:
                parts.append(f"温度范围: {spec.temperature_range}")
            if spec.key_params:
                parts.append("其他参数:")
                for k, v in spec.key_params.items():
                    parts.append(f"  - {k}: {v}")
        else:
            # 无结构化提取，返回清洗后的 markdown 摘要
            parts.append(f"## {mpn} 规格信息（原始提取）")
            summary = re.sub(r'\n{3,}', '\n\n', markdown[:2000])
            parts.append(summary)

        return "\n".join(parts)


# ============================================================
# 工厂函数
# ============================================================

def create_tier3_retriever() -> PublicMPNRetriever:
    """创建 Tier3 检索器实例"""
    tier3_type = os.getenv("TIER3_TYPE", "lightweight").lower()

    if tier3_type in ("lightweight", "python"):
        return Tier3Retriever()
    elif tier3_type == "firecrawl":
        try:
            from agent_system.firecrawl_tier3 import FirecrawlTier3Retriever
            return FirecrawlTier3Retriever()
        except ImportError:
            logger.warning("firecrawl_tier3 不可用，fallback 到轻量实现")
            return Tier3Retriever()
    else:
        return PublicMPNRetriever()
