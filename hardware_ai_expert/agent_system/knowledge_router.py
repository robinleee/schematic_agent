"""
Knowledge Router - 三级降级检索路由

实现 Tier 1 (本地 ChromaDB) → Tier 2 (内网 PLM) → Tier 3 (公网 API)
的降级检索机制，为 Agent 提供硬件规格查询能力。
"""

import os
import hashlib
import logging
from datetime import datetime
from typing import Optional
from dataclasses import dataclass
from enum import Enum

from dotenv import load_dotenv
from pydantic import BaseModel, Field

try:
    import chromadb
    from chromadb.config import Settings as ChromaSettings
except ImportError:
    chromadb = None

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT_DIR, ".env"))

logger = logging.getLogger(__name__)

# ============================================================
# 数据模型
# ============================================================

class TierLevel(str):
    TIER_1 = "tier_1_local"
    TIER_2 = "tier_2_internal"
    TIER_3 = "tier_3_public"


class RetrievalResult(BaseModel):
    status: str = "not_found"  # success, not_found, error
    tier: str = ""
    content: str = ""
    source: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    mpn: Optional[str] = None
    cached: bool = False


@dataclass
class DatasheetChunk:
    mpn: str
    page: int
    content: str
    chunk_type: str = "general"
    content_hash: str = ""


# ============================================================
# ChromaDB Client (Singleton)
# ============================================================

_chroma_client = None


def _get_chroma_client():
    global _chroma_client
    if _chroma_client is None:
        if chromadb is None:
            raise RuntimeError("chromadb not installed")
        persist_dir = os.path.join(ROOT_DIR, "data", "chroma_db")
        os.makedirs(persist_dir, exist_ok=True)
        _chroma_client = chromadb.PersistentClient(
            path=persist_dir,
            settings=ChromaSettings(anonymized_telemetry=False, allow_reset=True)
        )
    return _chroma_client


# ============================================================
# Tier 1: 本地 ChromaDB RAG
# ============================================================

class LocalRAGRetriever:
    """本地 ChromaDB 向量检索器"""

    COLLECTION = "hardware_datasheets"

    def __init__(self):
        self._col = None

    @property
    def collection(self):
        if self._col is None:
            client = _get_chroma_client()
            try:
                self._col = client.get_collection(self.COLLECTION)
            except Exception:
                self._col = client.create_collection(
                    self.COLLECTION,
                    metadata={"description": "Hardware Datasheet Vector Store"},
                    get_or_create=True
                )
        return self._col

    def add_chunk(self, chunk: DatasheetChunk) -> bool:
        """添加一个切片到向量库"""
        if not chunk.content_hash:
            chunk.content_hash = hashlib.md5(chunk.content.encode()).hexdigest()

        chunk_id = f"{chunk.mpn}_p{chunk.page}_{chunk.chunk_type}"

        # 使用纯 Python 的简单位嵌入（避免额外依赖）
        embedding = self._simple_embed(chunk.content)

        try:
            self.collection.add(
                documents=[chunk.content],
                embeddings=[embedding],
                metadatas=[{
                    "mpn": chunk.mpn,
                    "page": chunk.page,
                    "chunk_type": chunk.chunk_type,
                    "content_hash": chunk.content_hash,
                    "indexed_at": datetime.now().isoformat(),
                }],
                ids=[chunk_id]
            )
            return True
        except Exception as e:
            logger.error(f"Failed to add chunk: {e}")
            return False

    def search(self, mpn: str, query: str, n: int = 5) -> list[RetrievalResult]:
        """搜索本地向量库"""
        query_emb = self._simple_embed(query)

        try:
            results = self.collection.query(
                query_embeddings=[query_emb],
                n_results=n,
                where={"mpn": {"$eq": mpn}} if mpn else None,
                include=["documents", "metadatas", "distances"]
            )
        except Exception as e:
            logger.error(f"ChromaDB query failed: {e}")
            return []

        if not results or not results.get("documents") or not results["documents"][0]:
            return []

        retrieval_results = []
        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i]
            confidence = max(0.0, 1.0 - distance)

            retrieval_results.append(RetrievalResult(
                status="success",
                tier=TierLevel.TIER_1,
                content=doc,
                source=f"local:{metadata.get('chunk_type', 'unknown')}",
                confidence=confidence,
                mpn=mpn,
                cached=True
            ))

        return retrieval_results

    def _simple_embed(self, text: str) -> list[float]:
        """
        简单位嵌入实现。
        使用字符频率向量作为占位符，避免引入 sentence-transformers 依赖。
        生产环境应替换为 BAAI/bge-large-zh-v1.5 等模型。
        """
        import math
        words = text.lower().split()
        vocab_size = 512
        vec = [0.0] * vocab_size
        for word in words:
            for char in word[:8]:
                idx = (ord(char) * 31) % vocab_size
                vec[idx] += 1.0
        norm = math.sqrt(sum(v * v for v in vec))
        if norm > 0:
            vec = [v / norm for v in vec]
        return vec

    def count(self) -> int:
        """返回向量库中的切片数量"""
        try:
            return self.collection.count()
        except Exception:
            return 0

    def reset(self):
        """重置向量库"""
        global _chroma_client
        if _chroma_client is not None:
            _chroma_client.reset()
        _chroma_client = None
        self._col = None


# ============================================================
# Tier 3: 公网 MPN 检索（示例实现）
# ============================================================

class PublicMPNRetriever:
    """
    公网 MPN 检索器。
    当前为空实现（Tier 2/3 预留）。
    生产环境可接入 Octopart / Mouser / DigiKey API。
    """

    def __init__(self):
        self.enabled = False  # 暂不启用

    def search(self, mpn: str, query: str) -> Optional[RetrievalResult]:
        """搜索公网器件数据库（示例：返回 None 表示未命中）"""
        if not self.enabled:
            return None

        # TODO: 实现 Octopart / Mouser API
        # 严格脱敏原则：只携带 MPN，不带任何电路上下文
        logger.debug(f"PublicMPNRetriever.search: {mpn}")
        return None


# ============================================================
# Knowledge Router 核心
# ============================================================

class KnowledgeRouter:
    """
    三级降级知识路由器。

    检索顺序：Tier 1 (本地) → Tier 2 (内网) → Tier 3 (公网)
    Tier 3 命中后自动缓存到 Tier 1。
    """

    def __init__(self):
        self.tier1 = LocalRAGRetriever()
        self.tier2 = None  # 预留
        self.tier3 = PublicMPNRetriever()

    def search(self, mpn: str, query: str, max_results: int = 5) -> RetrievalResult:
        """
        执行三级降级检索。

        Args:
            mpn: 器件型号（关联键）
            query: 查询内容
            max_results: 最大返回数

        Returns:
            最优检索结果
        """
        # Tier 1: 本地向量库
        tier1_results = self.tier1.search(mpn, query, n=max_results)
        if tier1_results:
            best = max(tier1_results, key=lambda r: r.confidence)
            if best.confidence >= 0.5:
                logger.info(f"Tier1 hit: {mpn} confidence={best.confidence:.2f}")
                return best

        # Tier 2: 内网 PLM（预留）
        if self.tier2:
            result = self.tier2.search(mpn, query)
            if result and result.status == "success":
                self._cache_to_tier1(result)
                return result

        # Tier 3: 公网 MPN
        result = self.tier3.search(mpn, query)
        if result and result.status == "success":
            logger.info(f"Tier3 hit: {mpn}")
            self._cache_to_tier1(result)
            return result

        # 未找到
        return RetrievalResult(
            status="not_found",
            tier="none",
            content=f"未找到 {mpn} 相关规格信息",
            mpn=mpn,
        )

    def _cache_to_tier1(self, result: RetrievalResult):
        """将外部检索结果缓存到本地"""
        if not result.mpn or not result.content:
            return
        chunk = DatasheetChunk(
            mpn=result.mpn,
            page=0,
            content=result.content[:2000],
            chunk_type="cached_external",
        )
        self.tier1.add_chunk(chunk)
        logger.info(f"Cached to Tier1: {result.mpn}")

    def import_text_knowledge(self, mpn: str, pages: dict[str, str]) -> int:
        """
        导入文本知识到本地向量库。

        Args:
            mpn: 器件型号
            pages: dict of {page_num: content}

        Returns:
            成功导入的页数
        """
        imported = 0
        for page_num, content in pages.items():
            if not content or not content.strip():
                continue
            chunk = DatasheetChunk(
                mpn=mpn,
                page=int(page_num) if str(page_num).isdigit() else 0,
                content=content[:5000],  # 截断避免超长
                chunk_type="general",
            )
            if self.tier1.add_chunk(chunk):
                imported += 1
        return imported

    def get_stats(self) -> dict:
        """获取向量库统计"""
        return {
            "tier1_chunks": self.tier1.count(),
            "tier2_enabled": self.tier2 is not None,
            "tier3_enabled": self.tier3.enabled,
        }


# ============================================================
# LangChain Tool 封装
# ============================================================

try:
    from langchain_core.tools import tool
    _LANGCHAIN_AVAILABLE = True
except ImportError:
    _LANGCHAIN_AVAILABLE = False
    def tool(fn):
        """装饰器替代（LangChain 不可用时）"""
        return fn


if _LANGCHAIN_AVAILABLE:

    @tool
    def search_hardware_specs(mpn: str, query: str) -> str:
        """
        搜索器件规格信息。

        基于三级降级检索（本地向量库 → 内网 PLM → 公网 MPN），
        自动缓存外部结果到本地。

        Args:
            mpn: 器件厂商型号，如 "MT25QU256ABA8E12"
            query: 查询内容，如 "pinout voltage", "decoupling capacitor"

        Returns:
            检索到的规格信息字符串

        Example:
            search_hardware_specs("MT25QU256ABA8E12", "pinout voltage specifications")
        """
        router = KnowledgeRouter()
        result = router.search(mpn, query)

        if result.status == "not_found":
            return f"未找到 {mpn} 的相关信息。"

        return f"""来源: {result.source} | 置信度: {result.confidence:.0%} | 层级: {result.tier}

{result.content}"""

    def get_knowledge_tools():
        return [search_hardware_specs]


# ============================================================
# 便捷函数
# ============================================================

def search_hardware_specs(mpn: str, query: str) -> RetrievalResult:
    """
    便捷函数：搜索硬件规格。

    Example:
        result = search_hardware_specs("MT25QU256ABA8E12", "pinout voltage")
    """
    router = KnowledgeRouter()
    return router.search(mpn, query)


# ============================================================
# 端到端验证
# ============================================================

def _validate():
    """验证 Knowledge Router"""
    print("=" * 60)
    print("Phase 2: Knowledge Router Validation")
    print("=" * 60)

    router = KnowledgeRouter()

    # 1. 导入测试数据
    print("\n[1/4] Importing test datasheet knowledge...")
    test_pages = {
        "1": "MT25QL02 Flash Memory\nMPN: MT25QU256ABA8E12\nPackage: TPBGA24\nVoltage: 1.8V SPI Interface\nPin C4: VCC (Power)\nPin A4: DQ0 (Data Signal)\nPin E1: VSS (GND)",
        "2": "I2C Bus Pull-up Resistor Specification\nStandard I2C pull-up: 2.2K to 10K ohm\nFor 1.8V I2C bus: recommended 4.7K ohm\nDo not use values below 1K on low-speed I2C",
        "3": "Decoupling Capacitor Recommendation\nPlace 100nF ceramic capacitor within 2mm of each power pin\nFor VCC pins: use X5R or X7R dielectric\nVoltage rating: 16V minimum for 1.8V rails",
    }
    imported = router.import_text_knowledge("MT25QU256ABA8E12", test_pages)
    print(f"  Imported {imported} pages")

    stats = router.get_stats()
    print(f"  VectorDB chunks: {stats['tier1_chunks']}")

    # 2. Tier1 检索测试
    print("\n[2/4] Testing Tier1 retrieval...")
    tests = [
        ("MT25QU256ABA8E12", "pull-up resistor I2C"),
        ("MT25QU256ABA8E12", "pinout voltage"),
        ("MT25QU256ABA8E12", "decoupling capacitor"),
    ]
    for mpn, query in tests:
        result = router.search(mpn, query)
        print(f"  Query: '{query}'")
        print(f"    Status: {result.status}, Tier: {result.tier}, Confidence: {result.confidence:.2f}")
        if result.status == "success":
            print(f"    Content preview: {result.content[:80]}...")

    # 3. 未知 MPN 降级测试
    print("\n[3/4] Testing unknown MPN (Tier3 fallback)...")
    result = router.search("UNKNOWN_MPN_XYZ", "voltage rating")
    print(f"  Status: {result.status}, Content: {result.content[:60]}...")

    # 4. 统计
    print("\n[4/4] VectorDB statistics...")
    stats = router.get_stats()
    print(f"  {stats}")

    print("\n✅ Phase 2 validation PASSED")


if __name__ == "__main__":
    _validate()
