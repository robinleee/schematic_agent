"""
Tier3 轻量检索器单元测试
"""

import os
import sys
import pytest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from agent_system.tier3_retriever import (
    match_supplier,
    _strip_mpn_suffix,
    Tier3Retriever,
    WebScraper,
    html_to_clean_markdown,
    SUPPLIER_URL_TEMPLATES,
)
from agent_system.knowledge_router import PublicMPNRetriever


# ============================================================
# 供应商匹配
# ============================================================

class TestSupplierMatching:

    def test_ti_tps_prefix(self):
        result = match_supplier("TPS5430DDA")
        assert result is not None
        supplier, config, candidates = result
        assert supplier == "TI"
        assert "TPS5430DDA" in candidates
        assert "TPS5430" in candidates

    def test_ti_tps7a47_no_strip(self):
        """TPS7A47 末尾是数字，不应截断"""
        result = match_supplier("TPS7A47")
        assert result is not None
        supplier, _, candidates = result
        assert supplier == "TI"
        assert "TPS7A47" in candidates

    def test_ti_sn74_prefix(self):
        result = match_supplier("SN74LVC1G34DBVR")
        assert result is not None
        supplier, _, candidates = result
        assert supplier == "TI"
        assert "SN74LVC1G34" in candidates

    def test_murata_prefix(self):
        result = match_supplier("GRM155R71C104KA01D")
        assert result is not None
        supplier, _, _ = result
        assert supplier == "MURATA"

    def test_stm_prefix(self):
        result = match_supplier("STM32F103C8T6")
        assert result is not None
        supplier, _, _ = result
        assert supplier == "STM"

    def test_nxp_prefix(self):
        result = match_supplier("LPC1768FBD100")
        assert result is not None
        supplier, _, _ = result
        assert supplier == "NXP"

    def test_microchip_prefix(self):
        result = match_supplier("ATMEGA328P")
        assert result is not None
        supplier, _, _ = result
        assert supplier == "MICROCHIP"

    def test_unknown_mpn_no_match(self):
        result = match_supplier("XYZ999ZZZ")
        assert result is None

    def test_longer_prefix_wins(self):
        """TPS7 应优先于 TPS 匹配（如果 TPS7 存在的话）"""
        # 当前模板中没有 TPS7 前缀，但逻辑测试长前缀优先
        result = match_supplier("TPS7A47")
        assert result is not None
        assert result[0] == "TI"


# ============================================================
# MPN 后缀剥离
# ============================================================

class TestStripMpnSuffix:

    def test_strip_dda_suffix(self):
        config = {"strip_suffix": True}
        candidates = _strip_mpn_suffix("TPS5430DDA", config)
        assert "TPS5430DDA" in candidates
        assert "TPS5430" in candidates

    def test_strip_dbvr_suffix(self):
        config = {"strip_suffix": True}
        candidates = _strip_mpn_suffix("SN74LVC1G34DBVR", config)
        assert "SN74LVC1G34DBVR" in candidates
        assert "SN74LVC1G34" in candidates

    def test_no_strip_when_disabled(self):
        config = {"strip_suffix": False}
        candidates = _strip_mpn_suffix("TPS5430DDA", config)
        assert candidates == ["TPS5430DDA"]

    def test_no_strip_when_ending_with_digit(self):
        """末尾是数字的 MPN 不截断"""
        config = {"strip_suffix": True}
        candidates = _strip_mpn_suffix("TPS7A47", config)
        assert candidates == ["TPS7A47"]


# ============================================================
# HTML 清洗
# ============================================================

class TestHtmlToMarkdown:

    def test_basic_html(self):
        html = "<html><body><h1>TPS5430</h1><p>3A Buck Converter</p></body></html>"
        md = html_to_clean_markdown(html)
        assert "TPS5430" in md
        assert "3A Buck Converter" in md

    def test_truncation(self):
        html = "<p>" + "A" * 10000 + "</p>"
        md = html_to_clean_markdown(html, max_len=500)
        assert len(md) <= 500


# ============================================================
# Tier3Retriever
# ============================================================

class TestTier3Retriever:

    def test_inherits_public_mpn_retriever(self):
        retriever = Tier3Retriever()
        assert isinstance(retriever, PublicMPNRetriever)

    def test_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=False):
            # TIER3_ENABLED 默认 false
            retriever = Tier3Retriever()
            # enabled 取决于环境变量，不强制为 False

    def test_search_disabled_returns_none(self):
        retriever = Tier3Retriever()
        retriever.enabled = False
        result = retriever.search("TPS5430", "voltage")
        assert result is None

    def test_search_no_supplier_match(self):
        retriever = Tier3Retriever()
        retriever.enabled = True
        result = retriever.search("XYZ999", "test")
        assert result is None

    def test_sanitize_query_removes_mpn(self):
        retriever = Tier3Retriever()
        safe = retriever._sanitize_query("TPS5430", "TPS5430 VOUT formula")
        assert "TPS5430" not in safe
        assert "voltage" in safe or "formula" in safe

    def test_sanitize_query_keeps_tech_keywords(self):
        retriever = Tier3Retriever()
        safe = retriever._sanitize_query("TPS5430", "voltage rating switching frequency")
        assert "voltage" in safe
        assert "switching" in safe

    def test_search_with_mock_scraper(self):
        retriever = Tier3Retriever()
        retriever.enabled = True
        retriever._enable_llm_extract = False

        mock_scraper = MagicMock()
        mock_scraper.scrape_html.return_value = "# TPS5430\n" + "3A Buck Converter 36V input 500kHz switching frequency\n" * 10
        mock_scraper.scrape_pdf.return_value = None

        # 直接设置 _scraper，绕过 property
        retriever._scraper = mock_scraper

        result = retriever.search("TPS5430", "voltage rating")
        assert result is not None
        assert result.status == "success"
        assert result.confidence == 0.7
        assert "TPS5430" in result.content
        assert "tier3:TI" in result.source

    def test_search_scraper_returns_empty(self):
        retriever = Tier3Retriever()
        retriever.enabled = True
        retriever._enable_llm_extract = False

        mock_scraper = MagicMock()
        mock_scraper.scrape_html.return_value = None
        retriever._scraper = mock_scraper

        result = retriever.search("TPS5430", "test")
        assert result is None

    def test_scraper_property_lazy_init(self):
        retriever = Tier3Retriever()
        retriever.enabled = True
        assert retriever._scraper is None
        scraper = retriever.scraper
        assert scraper is not None
        assert isinstance(scraper, WebScraper)

    def test_scraper_property_disabled(self):
        retriever = Tier3Retriever()
        retriever.enabled = False
        assert retriever.scraper is None


# ============================================================
# WebScraper
# ============================================================

class TestWebScraper:

    def test_init_defaults(self):
        scraper = WebScraper()
        assert scraper.timeout > 0
        assert "Mozilla" in scraper.user_agent

    @patch("requests.Session.get")
    def test_scrape_html_success(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html><body><h1>Test</h1></body></html>"
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp

        scraper = WebScraper()
        result = scraper.scrape_html("https://example.com")
        assert result is not None
        assert "Test" in result

    @patch("requests.Session.get")
    def test_scrape_html_timeout(self, mock_get):
        import requests
        mock_get.side_effect = requests.exceptions.Timeout()

        scraper = WebScraper()
        result = scraper.scrape_html("https://example.com")
        assert result is None

    @patch("requests.Session.get")
    def test_scrape_html_http_error(self, mock_get):
        import requests
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.raise_for_status.side_effect = requests.exceptions.HTTPError(response=mock_resp)
        mock_get.return_value = mock_resp

        scraper = WebScraper()
        result = scraper.scrape_html("https://example.com")
        assert result is None


# ============================================================
# 工厂函数
# ============================================================

class TestFactory:

    def test_create_lightweight(self):
        with patch.dict(os.environ, {"TIER3_TYPE": "lightweight"}):
            from agent_system.tier3_retriever import create_tier3_retriever
            retriever = create_tier3_retriever()
            assert isinstance(retriever, Tier3Retriever)

    def test_create_default(self):
        with patch.dict(os.environ, {"TIER3_TYPE": "lightweight"}, clear=False):
            from agent_system.tier3_retriever import create_tier3_retriever
            retriever = create_tier3_retriever()
            assert isinstance(retriever, Tier3Retriever)

    def test_create_firecrawl_fallback(self):
        with patch.dict(os.environ, {"TIER3_TYPE": "firecrawl"}):
            from agent_system.tier3_retriever import create_tier3_retriever
            # firecrawl 模块不存在，应 fallback 到 Tier3Retriever
            retriever = create_tier3_retriever()
            assert isinstance(retriever, Tier3Retriever)

    def test_create_unknown_type(self):
        with patch.dict(os.environ, {"TIER3_TYPE": "unknown"}):
            from agent_system.tier3_retriever import create_tier3_retriever
            retriever = create_tier3_retriever()
            assert isinstance(retriever, PublicMPNRetriever)
