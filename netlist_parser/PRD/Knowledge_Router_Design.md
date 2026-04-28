# Knowledge Router 模块详细设计

## 1. 模块概述

**模块名称**: `agent_system/knowledge_router.py`

**核心职责**:
- 实现三级降级检索机制（Tiered Routing）
- 解决冷门芯片"知识盲区"问题
- 管理本地 RAG 与外部 API 的协同
- 提供 Datasheet 规格的语义检索能力

**设计目标**:
- Tier 1 优先本地向量库，降低延迟和成本
- Tier 2/3 作为降级策略，确保知识可用性
- 自动缓存外部检索结果到本地
- 严格遵守数据脱敏要求（Tier 3）

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                     Knowledge Router Architecture                        │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│                         User Request                                      │
│                              │                                            │
│                              ▼                                            │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Knowledge Router (路由入口)                     │   │
│  │                                                                  │   │
│  │  search_hardware_specs(mpn, query)                              │   │
│  │       │                                                         │   │
│  │       ▼                                                         │   │
│  │  ┌─────────────────────────────────────────────────────────────┐ │   │
│  │  │              Tier Selection (自动判断)                       │ │   │
│  │  │  ┌─────────┐  ┌─────────┐  ┌─────────┐                     │ │   │
│  │  │  │Tier 1?  │─▶│Tier 2?  │─▶│Tier 3?  │                     │ │   │
│  │  │  └─────────┘  └─────────┘  └─────────┘                     │ │   │
│  │  └─────────────────────────────────────────────────────────────┘ │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                              │                                            │
│  ┌───────────────────────────┼───────────────────────────────────┐   │
│  │                           ▼                                    │   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │                    TIER 1: Local RAG                   │   │   │
│  │  │                                                          │   │   │
│  │  │  ChromaDB / Milvus Vector Store                         │   │   │
│  │  │       │                                                  │   │   │
│  │  │       ▼                                                  │   │   │
│  │  │  Embedding Search (MPN + Query)                          │   │   │
│  │  │       │                                                  │   │   │
│  │  │       ▼                                                  │   │   │
│  │  │  Relevance Filter (score > threshold)                    │   │   │
│  │  │       │                                                  │   │   │
│  │  │       ├──▶ HIT ──▶ Return Result                        │   │   │
│  │  │       │                                                   │   │   │
│  │  │       └──▶ MISS ──▶ Fallback to Tier 2                  │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                           │                                    │   │
│  │                           ▼                                    │   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │              TIER 2: Internal PLM API (Reserved)         │   │   │
│  │  │                                                          │   │   │
│  │  │  Company PLM / PDM System                                │   │   │
│  │  │       │                                                  │   │   │
│  │  │       ├──▶ HIT ──▶ Cache to Tier 1 ──▶ Return           │   │   │
│  │  │       │                                                   │   │   │
│  │  │       └──▶ MISS ──▶ Fallback to Tier 3                  │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  │                           │                                    │   │
│  │                           ▼                                    │   │
│  │  ┌─────────────────────────────────────────────────────────┐   │   │
│  │  │            TIER 3: Public API (Sanitized)               │   │   │
│  │  │                                                          │   │   │
│  │  │  Octopart / DigiKey / Mouser APIs                       │   │   │
│  │  │       │                                                  │   │   │
│  │  │       ├──▶ HIT ──▶ Cache to Tier 1 ──▶ Return           │   │   │
│  │  │       │                                                   │   │   │
│  │  │       └──▶ MISS ──▶ Return "Not Found"                  │   │   │
│  │  └─────────────────────────────────────────────────────────┘   │   │
│  └────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心实现

### 3.1 模块初始化与配置

```python
# agent_system/knowledge_router.py

"""
Knowledge Router - 三级降级检索路由

实现冷门芯片"知识盲区"问题的三级降级检索机制：
- Tier 1: 本地 ChromaDB/Milvus 向量库
- Tier 2: 公司内网 PLM 系统 (预留)
- Tier 3: 脱敏公网 API (Octopart 等)

Usage:
    from agent_system.knowledge_router import KnowledgeRouter, search_hardware_specs

    router = KnowledgeRouter()

    # 搜索器件规格
    result = router.search("MT25QU256ABA8E12", "pinout voltage specifications")

    # 批量导入 Datasheet
    router.import_datasheet("datasheets/MX25L25673G.pdf")
"""

import os
import json
import hashlib
import logging
from datetime import datetime
from typing import Optional, Any
from dataclasses import dataclass, field
from enum import Enum

# LangChain
from langchain_core.tools import tool

# Embedding
from langchain_community.embeddings import HuggingFaceBgeEmbeddings

# Vector Store
import chromadb
from chromadb.config import Settings as ChromaSettings

# HTTP Client
import requests

# Pydantic
from pydantic import BaseModel, Field

# ============================================
# 日志配置
# ============================================

logger = logging.getLogger(__name__)

# ============================================
# 数据模型
# ============================================

class TierLevel(Enum):
    """检索层级枚举"""
    TIER_1_LOCAL = "tier_1_local"
    TIER_2_INTERNAL = "tier_2_internal"
    TIER_3_PUBLIC = "tier_3_public"


class RetrievalResult(BaseModel):
    """检索结果模型"""
    status: Literal["success", "not_found", "error"]
    tier: TierLevel
    content: str = ""
    source: str = ""  # 来源标识
    confidence: float = Field(ge=0.0, le=1.0, default=0.0)
    mpn: Optional[str] = None
    metadata: dict = Field(default_factory=dict)
    cached: bool = False  # 是否从缓存返回


class DatasheetChunk(BaseModel):
    """Datasheet 切片模型"""
    mpn: str
    page: int
    content: str
    content_hash: str
    chunk_type: Literal["spec_table", "pinout", "description", "general"] = "general"
    embedding: Optional[list[float]] = None


# ============================================
# 配置类
# ============================================

class KnowledgeRouterConfig:
    """Knowledge Router 全局配置"""

    _instance: Optional["KnowledgeRouterConfig"] = None
    _chroma_client: Optional[chromadb.Client] = None
    _embedding_model = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def init(
        self,
        chroma_persist_dir: str = "./data/chromadb",
        embedding_model_name: str = "BAAI/bge-large-zh-v1.5",
        embedding_device: str = "cpu",
        octopart_api_key: str = None,
        plm_api_base: str = None,
    ) -> None:
        """初始化 Knowledge Router"""

        if self._initialized:
            logger.warning("Knowledge Router 已初始化，忽略重复初始化")
            return

        # 初始化 ChromaDB
        os.makedirs(chroma_persist_dir, exist_ok=True)
        self._chroma_client = chromadb.PersistentClient(
            path=chroma_persist_dir,
            settings=ChromaSettings(
                anonymized_telemetry=False,
                allow_reset=True,
            )
        )

        # 初始化 Embedding 模型
        self._embedding_model = HuggingFaceBgeEmbeddings(
            model_name=embedding_model_name,
            model_kwargs={"device": embedding_device},
            encode_kwargs={"normalize_embeddings": True},
        )

        # 保存 API 配置
        self._octopart_api_key = octopart_api_key or os.getenv("OCTOPART_API_KEY")
        self._plm_api_base = plm_api_base or os.getenv("PLM_API_BASE")

        self._initialized = True
        logger.info("Knowledge Router 初始化完成")

    @property
    def chroma_client(self) -> chromadb.Client:
        if not self._initialized or self._chroma_client is None:
            raise RuntimeError("Knowledge Router 未初始化")
        return self._chroma_client

    @property
    def embedding_model(self):
        if not self._initialized or self._embedding_model is None:
            raise RuntimeError("Knowledge Router 未初始化")
        return self._embedding_model

    @property
    def octopart_api_key(self) -> Optional[str]:
        return self._octopart_api_key

    @property
    def plm_api_base(self) -> Optional[str]:
        return self._plm_api_base

    def reset(self) -> None:
        """重置配置（主要用于测试）"""
        if self._chroma_client:
            self._chroma_client.reset()
        self._initialized = False
        logger.info("Knowledge Router 已重置")


# 全局配置实例
_config = KnowledgeRouterConfig()


def init_knowledge_router(**kwargs) -> None:
    """初始化 Knowledge Router"""
    _config.init(**kwargs)
```

### 3.2 Tier 1: 本地 RAG 实现

```python
# ============================================
# Tier 1: 本地向量库检索
# ============================================

class LocalRAGRetriever:
    """本地 ChromaDB RAG 检索器"""

    COLLECTION_NAME = "hardware_datasheets"
    COLLECTION_METADATA = {
        "description": "硬件 Datasheet 向量库",
        "version": "1.0"
    }

    def __init__(self):
        self.config = _config
        self.collection = self._get_or_create_collection()

    def _get_or_create_collection(self):
        """获取或创建向量集合"""
        try:
            return self.config.chroma_client.get_collection(
                name=self.COLLECTION_NAME
            )
        except Exception:
            return self.config.chroma_client.create_collection(
                name=self.COLLECTION_NAME,
                metadata=self.COLLECTION_METADATA,
                get_or_create=True
            )

    def add_datasheet_chunk(
        self,
        chunk: DatasheetChunk,
        overwrite: bool = True
    ) -> str:
        """
        添加 Datasheet 切片到向量库

        Args:
            chunk: Datasheet 切片
            overwrite: 是否覆盖已存在的记录

        Returns:
            切片 ID
        """
        # 生成 embedding
        embedding = self.config.embedding_model.embed_documents([chunk.content])[0]

        doc_id = f"{chunk.mpn}_page_{chunk.page}_{chunk.chunk_type}"

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
            ids=[doc_id]
        )

        logger.info(f"添加切片: {doc_id}")
        return doc_id

    def search(
        self,
        mpn: str,
        query: str,
        n_results: int = 5,
        confidence_threshold: float = 0.5,
        chunk_types: list[str] = None
    ) -> list[RetrievalResult]:
        """
        搜索本地向量库

        Args:
            mpn: 器件型号
            query: 查询文本
            n_results: 返回结果数量
            confidence_threshold: 置信度阈值
            chunk_types: 切片类型过滤

        Returns:
            检索结果列表
        """
        # 构建查询文本
        search_query = f"{mpn} {query}"

        # 生成 query embedding
        query_embedding = self.config.embedding_model.embed_documents([search_query])[0]

        # 执行相似度搜索
        results = self.collection.query(
            query_embeddings=[query_embedding],
            n_results=n_results,
            where={"mpn": {"$eq": mpn}} if mpn else None,
            include=["documents", "metadatas", "distances"]
        )

        # 解析结果
        retrieval_results = []

        if not results["documents"] or not results["documents"][0]:
            return []

        for i, doc in enumerate(results["documents"][0]):
            metadata = results["metadatas"][0][i]
            distance = results["distances"][0][i]

            # 将距离转换为置信度 (余弦距离越小越相似)
            confidence = 1.0 - distance

            # 过滤低置信度结果
            if confidence < confidence_threshold:
                continue

            # 过滤切片类型
            if chunk_types and metadata.get("chunk_type") not in chunk_types:
                continue

            retrieval_results.append(RetrievalResult(
                status="success",
                tier=TierLevel.TIER_1_LOCAL,
                content=doc,
                source=f"local_chroma:{metadata.get('chunk_type', 'unknown')}",
                confidence=confidence,
                mpn=mpn,
                metadata={
                    "page": metadata.get("page"),
                    "chunk_type": metadata.get("chunk_type"),
                    "distance": distance,
                },
                cached=False
            ))

        return retrieval_results

    def get_by_mpn(self, mpn: str) -> list[RetrievalResult]:
        """
        获取指定 MPN 的所有切片

        Args:
            mpn: 器件型号

        Returns:
            该 MPN 的所有切片
        """
        results = self.collection.get(
            where={"mpn": {"$eq": mpn}},
            include=["documents", "metadatas"]
        )

        retrieval_results = []
        for i, doc in enumerate(results["documents"]):
            metadata = results["metadatas"][i]
            retrieval_results.append(RetrievalResult(
                status="success",
                tier=TierLevel.TIER_1_LOCAL,
                content=doc,
                source=f"local_chroma:{metadata.get('chunk_type', 'unknown')}",
                confidence=1.0,
                mpn=mpn,
                metadata={
                    "page": metadata.get("page"),
                    "chunk_type": metadata.get("chunk_type"),
                },
                cached=True
            ))

        return retrieval_results

    def delete_by_mpn(self, mpn: str) -> int:
        """
        删除指定 MPN 的所有切片

        Args:
            mpn: 器件型号

        Returns:
            删除的切片数量
        """
        existing = self.collection.get(
            where={"mpn": {"$eq": mpn}},
            include=["ids"]
        )

        if existing["ids"]:
            self.collection.delete(ids=existing["ids"])
            logger.info(f"删除 MPN {mpn} 的 {len(existing['ids'])} 个切片")

        return len(existing["ids"])

    def get_statistics(self) -> dict:
        """获取向量库统计信息"""
        count = self.collection.count()

        # 按 MPN 分组统计
        all_data = self.collection.get(include=["metadastas"])

        mpn_counts = {}
        for metadata in all_data.get("metadatas", []):
            mpn = metadata.get("mpn", "unknown")
            mpn_counts[mpn] = mpn_counts.get(mpn, 0) + 1

        return {
            "total_chunks": count,
            "unique_mpns": len(mpn_counts),
            "top_mpns": sorted(mpn_counts.items(), key=lambda x: x[1], reverse=True)[:10],
        }
```

### 3.3 Tier 2: 内网 PLM API (预留)

```python
# ============================================
# Tier 2: 内网 PLM API (预留实现)
# ============================================

class InternalPLMRetriever:
    """
    内网 PLM 系统检索器

    预留接口，用于对接公司内部的 PLM/PDM 系统。
    需要根据实际 PLM 系统 API 进行实现。
    """

    def __init__(self):
        self.config = _config
        self.api_base = self.config.plm_api_base
        self.enabled = self.api_base is not None

    def search(self, mpn: str, query: str) -> Optional[RetrievalResult]:
        """
        搜索内网 PLM 系统

        Args:
            mpn: 器件型号
            query: 查询文本

        Returns:
            检索结果，None 表示未命中
        """
        if not self.enabled:
            logger.debug("Tier 2 (PLM) 未启用")
            return None

        try:
            # TODO: 根据实际 PLM API 实现
            # 示例 API 调用
            # response = requests.get(
            #     f"{self.api_base}/api/parts/search",
            #     params={"mpn": mpn, "query": query},
            #     headers={"Authorization": f"Bearer {plm_token}"},
            #     timeout=10
            # )

            logger.warning("Tier 2 PLM API 未实现")
            return None

        except requests.RequestException as e:
            logger.error(f"Tier 2 PLM API 调用失败: {e}")
            return None

    def get_part_details(self, part_id: str) -> Optional[dict]:
        """
        获取器件详细信息

        Args:
            part_id: PLM 系统中的器件 ID

        Returns:
            器件详情字典
        """
        if not self.enabled:
            return None

        # TODO: 实现详情查询
        return None
```

### 3.4 Tier 3: 脱敏公网 API

```python
# ============================================
# Tier 3: 脱敏公网 API
# ============================================

class PublicAPIRetriever:
    """
    公网器件 API 检索器

    仅携带 MPN（型号）进行查询，不携带任何电路上下文。
    严格遵守数据脱敏要求。

    支持的 API:
    - Octopart (https://octopart.com)
    - DigiKey API
    - Mouser API
    """

    def __init__(self):
        self.config = _config
        self.api_key = self.config.octopart_api_key
        self.enabled = self.api_key is not None

    def search(self, mpn: str, query: str) -> Optional[RetrievalResult]:
        """
        搜索公网器件数据库

        Args:
            mpn: 器件型号（唯一参数，严格脱敏）
            query: 查询内容（仅用于补充描述）

        Returns:
            检索结果
        """
        if not self.enabled:
            logger.debug("Tier 3 (Public API) 未启用")
            return None

        # 优先使用 MPN 精确匹配
        result = self._search_octopart(mpn)

        if result:
            return result

        # 备选：使用 Mouser API
        result = self._search_mouser(mpn)

        return result

    def _search_octopart(self, mpn: str) -> Optional[RetrievalResult]:
        """
        Octopart API 搜索

        注意：Octopart 已停止开放 API，此处为备选方案
        """
        try:
            # Octopart 内置于 Digi-Key，示例代码仅供参考
            # response = requests.get(
            #     "https://api.digikey.com/products/v4",
            #     headers={
            #         "X-DIGIKEY-Client-Id": self.api_key,
            #         "X-DIGIKEY-Client-Secret": self.api_secret,
            #     },
            #     params={"keywords": mpn},
            #     timeout=15
            # )

            logger.debug(f"Octopart API 搜索: {mpn}")
            return None

        except requests.RequestException as e:
            logger.error(f"Octopart API 调用失败: {e}")
            return None

    def _search_mouser(self, mpn: str) -> Optional[RetrievalResult]:
        """
        Mouser API 搜索

        Mouser 提供部分免费 API 访问
        """
        try:
            # Mouser Search API 示例
            # response = requests.get(
            #     "https://api.mouser.com/api/v1.0/search",
            #     headers={"Authorization": f"Bearer {self.api_key}"},
            #     params={
            #         "SearchByPartNumber": mpn,
            #         "recordsRequested": 1
            #     },
            #     timeout=15
            # )

            logger.debug(f"Mouser API 搜索: {mpn}")
            return None

        except requests.RequestException as e:
            logger.error(f"Mouser API 调用失败: {e}")
            return None

    def _format_result(
        self,
        mpn: str,
        data: dict
    ) -> RetrievalResult:
        """
        格式化 API 返回结果

        Args:
            mpn: 器件型号
            data: API 返回的原始数据

        Returns:
            格式化后的检索结果
        """
        # 提取关键信息（严格脱敏，只保留规格参数）
        content_parts = []

        # 基本信息
        if "mpn" in data:
            content_parts.append(f"型号: {data['mpn']}")

        if "description" in data:
            content_parts.append(f"描述: {data['description']}")

        # 技术规格
        if "specs" in data:
            specs = data["specs"]
            content_parts.append("技术规格:")
            for spec_name, spec_value in specs.items():
                content_parts.append(f"  - {spec_name}: {spec_value}")

        # 封装格式
        content = "\n".join(content_parts)

        return RetrievalResult(
            status="success",
            tier=TierLevel.TIER_3_PUBLIC,
            content=content,
            source="public_api",
            confidence=0.8,
            mpn=mpn,
            metadata=data,
            cached=False
        )


class OctopartClient:
    """
    Octopart API 客户端

    Octopart 提供器件搜索、价格对比等功能。
    官网: https://octopart.com
    API 文档: https://octopart.com/api/v4/home
    """

    BASE_URL = "https://core.nexar.com/graphql"

    def __init__(self, access_token: str = None):
        self.access_token = access_token or os.getenv("OCTOPART_ACCESS_TOKEN")
        self.enabled = self.access_token is not None

    def search_parts(self, mpn: str, limit: int = 5) -> list[dict]:
        """
        搜索器件

        GraphQL 查询示例:
        ```graphql
        query PartSearch($query: String!, $limit: Int!) {
            supSearch(q: $query, limit: $limit) {
                results {
                    part {
                        mpn
                        manufacturer { name }
                        short_description
                        specs {
                            attribute { name }
                            display_value
                        }
                    }
                }
            }
        }
        ```
        """
        if not self.enabled:
            return []

        query = """
        query PartSearch($query: String!, $limit: Int!) {
            supSearch(q: $query, limit: $limit) {
                results {
                    part {
                        mpn
                        manufacturer { name }
                        short_description
                        specs {
                            attribute { name }
                            display_value
                        }
                    }
                }
            }
        }
        """

        try:
            response = requests.post(
                self.BASE_URL,
                json={
                    "query": query,
                    "variables": {"query": mpn, "limit": limit}
                },
                headers={
                    "Authorization": f"Bearer {self.access_token}",
                    "Content-Type": "application/json"
                },
                timeout=30
            )

            response.raise_for_status()
            data = response.json()

            results = data.get("data", {}).get("supSearch", {}).get("results", [])
            return [r["part"] for r in results]

        except Exception as e:
            logger.error(f"Octopart API 错误: {e}")
            return []

    def get_part_specs(self, mpn: str) -> Optional[dict]:
        """
        获取器件详细规格

        Args:
            mpn: 器件型号

        Returns:
            器件规格字典
        """
        parts = self.search_parts(mpn, limit=1)

        if not parts:
            return None

        part = parts[0]

        # 格式化规格
        specs = {}
        for spec in part.get("specs", []):
            attr_name = spec["attribute"]["name"]
            display_value = spec.get("display_value", "N/A")
            specs[attr_name] = display_value

        return {
            "mpn": part.get("mpn"),
            "manufacturer": part.get("manufacturer", {}).get("name"),
            "description": part.get("short_description"),
            "specs": specs,
        }
```

### 3.5 知识路由器核心

```python
# ============================================
# 知识路由器核心
# ============================================

class KnowledgeRouter:
    """
    三级降级知识路由器

    实现 Tier 1 → Tier 2 → Tier 3 的降级检索机制。
    自动缓存外部检索结果到本地向量库。
    """

    def __init__(self):
        self.config = _config

        # 初始化各层级检索器
        self.tier1 = LocalRAGRetriever()
        self.tier2 = InternalPLMRetriever()
        self.tier3 = PublicAPIRetriever()

    def search(
        self,
        mpn: str,
        query: str,
        tier_preference: list[TierLevel] = None,
        confidence_threshold: float = 0.5,
        max_results: int = 5
    ) -> RetrievalResult:
        """
        执行三级降级检索

        Args:
            mpn: 器件型号（关键关联键）
            query: 查询内容
            tier_preference: 检索层级偏好，默认 [TIER_1, TIER_2, TIER_3]
            confidence_threshold: 置信度阈值
            max_results: 最大返回结果数

        Returns:
            检索结果（最优匹配）

        Example:
            >>> router = KnowledgeRouter()
            >>> result = router.search(
            ...     mpn="MT25QU256ABA8E12",
            ...     query="decoupling capacitor pinout voltage"
            ... )
            >>> print(result.content)
        """
        tier_preference = tier_preference or [
            TierLevel.TIER_1_LOCAL,
            TierLevel.TIER_2_INTERNAL,
            TierLevel.TIER_3_PUBLIC,
        ]

        all_results = []

        for tier in tier_preference:
            if tier == TierLevel.TIER_1_LOCAL:
                results = self._search_tier1(mpn, query, max_results)
            elif tier == TierLevel.TIER_2_INTERNAL:
                results = self._search_tier2(mpn, query)
            elif tier == TierLevel.TIER_3_PUBLIC:
                results = self._search_tier3(mpn, query)
            else:
                continue

            all_results.extend(results)

            # 如果 Tier 1 命中且置信度足够，停止搜索
            if tier == TierLevel.TIER_1_LOCAL and results:
                high_confidence = [r for r in results if r.confidence >= confidence_threshold]
                if high_confidence:
                    logger.info(f"Tier 1 命中，置信度 {high_confidence[0].confidence:.2f}")
                    return high_confidence[0]

        # 返回最优结果
        if all_results:
            best_result = max(all_results, key=lambda r: r.confidence)
            logger.info(f"返回最优结果: tier={best_result.tier.value}, confidence={best_result.confidence:.2f}")
            return best_result

        # 未找到任何结果
        return RetrievalResult(
            status="not_found",
            tier=TierLevel.TIER_3_PUBLIC,  # 最后一个尝试的层级
            content="",
            source="",
            confidence=0.0,
            mpn=mpn,
        )

    def _search_tier1(
        self,
        mpn: str,
        query: str,
        max_results: int
    ) -> list[RetrievalResult]:
        """Tier 1 搜索"""
        try:
            return self.tier1.search(
                mpn=mpn,
                query=query,
                n_results=max_results
            )
        except Exception as e:
            logger.error(f"Tier 1 搜索失败: {e}")
            return []

    def _search_tier2(
        self,
        mpn: str,
        query: str
    ) -> list[RetrievalResult]:
        """Tier 2 搜索"""
        try:
            result = self.tier2.search(mpn, query)
            return [result] if result else []
        except Exception as e:
            logger.error(f"Tier 2 搜索失败: {e}")
            return []

    def _search_tier3(
        self,
        mpn: str,
        query: str
    ) -> list[RetrievalResult]:
        """Tier 3 搜索"""
        try:
            result = self.tier3.search(mpn, query)

            if result and result.status == "success":
                # 自动缓存到 Tier 1
                self._cache_to_tier1(result)

            return [result] if result else []
        except Exception as e:
            logger.error(f"Tier 3 搜索失败: {e}")
            return []

    def _cache_to_tier1(self, result: RetrievalResult) -> None:
        """将结果缓存到本地向量库"""
        if not result.mpn or not result.content:
            return

        try:
            chunk = DatasheetChunk(
                mpn=result.mpn,
                page=result.metadata.get("page", 0),
                content=result.content,
                content_hash=hashlib.md5(result.content.encode()).hexdigest(),
                chunk_type="cached_external",
            )
            self.tier1.add_datasheet_chunk(chunk)
            logger.info(f"已缓存到 Tier 1: {result.mpn}")

        except Exception as e:
            logger.error(f"缓存失败: {e}")

    def import_datasheet(
        self,
        pdf_path: str,
        mpn: str = None
    ) -> dict:
        """
        导入 Datasheet PDF 到本地向量库

        Args:
            pdf_path: PDF 文件路径
            mpn: 器件型号（从文件名提取或手动指定）

        Returns:
            导入统计
        """
        from agent_system.datasheet_processor import QianfanOCRProcessor

        if not mpn:
            # 从文件名提取 MPN
            mpn = os.path.splitext(os.path.basename(pdf_path))[0]

        # 使用 Qianfan-OCR 解析
        processor = QianfanOCRProcessor()
        result = processor.process_datasheet(pdf_path)

        # 提取规格和内容
        specs = result.get("specifications", {})
        markdown_pages = result.get("markdown_content", [])

        imported_count = 0

        for page_num, content in enumerate(markdown_pages, 1):
            if not content.strip():
                continue

            chunk = DatasheetChunk(
                mpn=mpn,
                page=page_num,
                content=content,
                content_hash=hashlib.md5(content.encode()).hexdigest(),
                chunk_type="general",
            )

            try:
                self.tier1.add_datasheet_chunk(chunk)
                imported_count += 1
            except Exception as e:
                logger.error(f"导入失败 (page {page_num}): {e}")

        return {
            "mpn": mpn,
            "total_pages": len(markdown_pages),
            "imported_pages": imported_count,
            "specs": specs,
        }

    def get_statistics(self) -> dict:
        """获取检索统计"""
        return {
            "tier1": self.tier1.get_statistics(),
            "tier2_enabled": self.tier2.enabled,
            "tier3_enabled": self.tier3.enabled,
        }


# ============================================
# 全局便捷函数
# ============================================

def search_hardware_specs(mpn: str, query: str) -> str:
    """
    便捷函数：搜索硬件规格

    Args:
        mpn: 器件型号
        query: 查询内容

    Returns:
        格式化的检索结果字符串

    Example:
        >>> result = search_hardware_specs("MT25QU256ABA8E12", "pinout voltage")
        >>> print(result)
    """
    router = KnowledgeRouter()
    result = router.search(mpn, query)

    if result.status == "not_found":
        return f"未找到 {mpn} 的相关信息。"

    return f"""
来源: {result.source}
置信度: {result.confidence:.0%}
层级: {result.tier.value}

内容:
{result.content}
""".strip()
```

---

## 4. LangChain Tool 封装

```python
# ============================================
# LangChain Tool
# ============================================

@tool
def search_hardware_specs_tool(mpn: str, query: str) -> str:
    """
    搜索硬件器件规格信息。

    基于三级降级检索机制：
    1. 首先查询本地 Datasheet 向量库
    2. 其次查询公司内网 PLM 系统 (如已配置)
    3. 最后调用公网器件 API (如已配置)

    Args:
        mpn: 器件厂商型号，例如 "MT25QU256ABA8E12", "1N4148WSQ-7-F"
        query: 查询内容，例如 "pinout", "voltage range", "decoupling capacitor"

    Returns:
        检索到的规格信息

    使用示例:
        search_hardware_specs_tool(
            mpn="MT25QU256ABA8E12",
            query="pinout voltage specifications"
        )
    """
    result = search_hardware_specs(mpn, query)

    if not result:
        return f"未找到 {mpn} 的相关信息"

    return result


def get_knowledge_tools() -> list:
    """获取知识检索相关的 LangChain Tools"""
    return [search_hardware_specs_tool]
```

---

## 5. 完整模块代码

```python
# agent_system/knowledge_router.py

"""
Knowledge Router - 三级降级检索路由

实现 Tier 1 (本地 RAG) → Tier 2 (内网 PLM) → Tier 3 (公网 API) 的降级检索机制。

Author: Hardware AI Team
Version: 1.0.0
"""

__version__ = "1.0.0"

__all__ = [
    # 初始化
    "init_knowledge_router",
    "KnowledgeRouterConfig",
    # 核心类
    "KnowledgeRouter",
    "LocalRAGRetriever",
    "RetrievalResult",
    "DatasheetChunk",
    "TierLevel",
    # 便捷函数
    "search_hardware_specs",
    # LangChain Tools
    "get_knowledge_tools",
    "search_hardware_specs_tool",
]
```

---

## 6. 使用示例

### 6.1 基础使用

```python
# 1. 初始化
from agent_system.knowledge_router import init_knowledge_router, KnowledgeRouter

init_knowledge_router(
    chroma_persist_dir="./data/chromadb",
    embedding_model_name="BAAI/bge-large-zh-v1.5",
    octopart_api_key="your_api_key"  # 可选
)

# 2. 搜索规格
router = KnowledgeRouter()
result = router.search(
    mpn="MT25QU256ABA8E12",
    query="decoupling capacitor pinout voltage"
)

print(f"来源: {result.source}")
print(f"置信度: {result.confidence:.0%}")
print(f"内容: {result.content}")

# 3. 导入 Datasheet
router.import_datasheet("datasheets/MX25L25673G.pdf")
```

### 6.2 与 Agent 集成

```python
from agent_system.knowledge_router import get_knowledge_tools
from agent_system.graph_tools import get_graph_tools

# 合并所有 Tools
all_tools = get_graph_tools() + get_knowledge_tools()

# 创建 Agent
agent = create_react_agent(llm, all_tools)
```

---

## 7. 配置与环境变量

```bash
# .env 文件配置

# ChromaDB
CHROMADB_PERSIST_DIR=./data/chromadb

# Embedding 模型
EMBEDDING_MODEL=BAAI/bge-large-zh-v1.5
EMBEDDING_DEVICE=cpu  # 或 cuda

# Tier 2: PLM API (可选)
PLM_API_BASE=https://plm.internal.company.com/api

# Tier 3: 公网 API (可选)
OCTOPART_ACCESS_TOKEN=your_token
```

---

## 8. 安全与隐私

### 8.1 数据脱敏原则

1. **Tier 3 严格脱敏**：只携带 MPN，不携带任何电路上下文
2. **查询内容最小化**：只传递与规格相关的查询词
3. **缓存隔离**：本地向量库仅存储 Datasheet 内容

### 8.2 API 安全

1. API Key 通过环境变量配置，不硬编码
2. 请求超时限制（15秒）
3. 错误处理，不暴露内部信息
