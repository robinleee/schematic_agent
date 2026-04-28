# Design Guide 知识提取模块详细设计

## 1. 模块概述

**模块名称**: `agent_system/design_guide_processor.py`

**核心职责**:
- 支持用户上传芯片厂家 Design Guide PDF 文档
- 使用 Qianfan-OCR + LLM 自动提取设计规则和知识
- 将提取的规则转换为可执行的审查规则
- 管理 Design Guide 知识库

**设计目标**:
- 用户友好：简单的上传接口
- 自动化：最小人工干预
- 可追溯：保留原文引用
- 可扩展：支持多种文档格式

---

## 2. 架构设计

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Design Guide Processor 架构                           │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                      User Interface Layer                         │   │
│  │                                                                  │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐   │   │
│  │  │ DesignGuide │ │ DesignGuide │ │ DesignGuide             │   │   │
│  │  │ Upload UI   │ │ Library     │ │ Review History          │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│  ┌─────────────────────────────────┴─────────────────────────────────┐   │
│  │                      Processing Layer                             │   │
│  │                                                                  │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐   │   │
│  │  │ Qianfan-OCR │ │RuleExtractor│ │ RuleTransformer         │   │   │
│  │  │ Parser      │ │(LLM)        │ │                         │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│  ┌─────────────────────────────────┴─────────────────────────────────┐   │
│  │                      Storage Layer                                │   │
│  │                                                                  │   │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────────────────┐   │   │
│  │  │ Neo4j      │ │ ChromaDB   │ │ File Storage            │   │   │
│  │  │ (Rules)    │ │ (Vectors)  │ │ (Original PDFs)        │   │   │
│  │  └─────────────┘ └─────────────┘ └─────────────────────────┘   │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心实现

### 3.1 数据模型

```python
# agent_system/design_guide_processor/models.py

"""
Design Guide 相关数据模型
"""

from typing import Optional, Literal
from pydantic import BaseModel, Field
from datetime import datetime


class DesignGuide(BaseModel):
    """Design Guide 文档模型"""
    id: str = Field(description="文档唯一ID")
    name: str = Field(description="文档名称")
    manufacturer: str = Field(description="芯片厂商")
    mpn: str = Field(description="目标芯片型号")
    category: str = Field(description="文档类别: design_guide, app_note, datasheet")

    # 文件信息
    file_path: str = Field(description="原始文件路径")
    file_hash: str = Field(description="文件哈希值")
    page_count: int = Field(description="页数")

    # 解析状态
    status: Literal["uploaded", "parsing", "extracting", "completed", "failed"] = "uploaded"
    error_message: Optional[str] = None

    # 元数据
    uploaded_by: str = Field(description="上传人")
    uploaded_at: datetime = Field(default_factory=datetime.now)
    processed_at: Optional[datetime] = None

    # 关联
    rules_count: int = Field(default=0, description="提取的规则数量")
    knowledge_chunks_count: int = Field(default=0, description="知识切片数量")


class ExtractedRule(BaseModel):
    """从 Design Guide 提取的规则"""
    id: str = Field(description="规则ID")
    guide_id: str = Field(description="来源文档ID")
    guide_name: str = Field(description="来源文档名称")

    # 规则基本信息
    rule_type: Literal[
        "power_decoupling",
        "pullup_pulldown",
        "esd_protection",
        "power_sequencing",
        "impedance_matching",
        "bypass_capacitor",
        "termination",
        "routing",
        "other"
    ] = Field(description="规则类型")

    # 规则详情
    title: str = Field(description="规则标题")
    description: str = Field(description="规则描述")
    requirement: str = Field(description="具体要求")

    # 规则参数（用于生成 RuleConfig）
    template_id: str = Field(description="对应的规则模板")
    params: dict = Field(default_factory=dict, description="模板参数")
    severity: Literal["ERROR", "WARNING", "INFO"] = Field(default="WARNING")

    # 适用范围
    applicable_mpns: list[str] = Field(default_factory=list, description="适用的芯片型号")
    applicable_voltages: list[str] = Field(default_factory=list, description="适用的电压")
    applicable_nets: list[str] = Field(default_factory=list, description="适用的网络")

    # 原文引用
    source_page: int = Field(description="来源页码")
    source_quote: str = Field(description="原文引用")
    source_confidence: float = Field(ge=0.0, le=1.0, description="提取置信度")

    # 状态
    status: Literal["extracted", "validated", "approved", "rejected"] = "extracted"
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None
    review_notes: Optional[str] = None


class ExtractedKnowledge(BaseModel):
    """提取的设计知识（非规则类）"""
    id: str = Field(description="知识ID")
    guide_id: str = Field(description="来源文档ID")

    # 知识内容
    category: Literal[
        "pin_assignment",
        "power_supply",
        "clock_timing",
        "thermal",
        "layout",
        "testing",
        "troubleshooting",
        "general"
    ] = Field(description="知识类别")

    title: str = Field(description="知识标题")
    content: str = Field(description="知识内容（Markdown格式）")

    # 向量存储
    vector_id: Optional[str] = Field(None, description="ChromaDB 向量ID")

    # 原文引用
    source_page: int = Field(description="来源页码")
    source_section: Optional[str] = Field(None, description="来源章节")
    source_quote: str = Field(description="原文引用")


class ProcessingResult(BaseModel):
    """处理结果"""
    guide_id: str
    status: Literal["success", "partial", "failed"]

    # 统计
    total_pages: int
    pages_processed: int
    rules_extracted: int
    knowledge_extracted: int

    # 结果
    rules: list[ExtractedRule] = Field(default_factory=list)
    knowledge: list[ExtractedKnowledge] = Field(default_factory=list)

    # 错误
    errors: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
```

### 3.2 Design Guide 处理器

```python
# agent_system/design_guide_processor/processor.py

"""
Design Guide 处理器

核心功能：
1. 文档解析 (Qianfan-OCR)
2. 规则提取 (LLM)
3. 知识提取 (LLM)
4. 规则转换 (RuleConfig)
"""

import os
import hashlib
import json
from pathlib import Path
from typing import Optional, Callable
from datetime import datetime

# Pydantic
from pydantic import BaseModel

# Neo4j
from neo4j import GraphDatabase

# LLM
from langchain_openai import ChatOpenAI

# Qianfan-OCR
from agent_system.datasheet_processor import QianfanOCRProcessor

# 存储
import chromadb


class DesignGuideProcessor:
    """
    Design Guide 处理器

    处理 Design Guide PDF，提取规则和知识。
    """

    def __init__(
        self,
        neo4j_uri: str,
        neo4j_user: str,
        neo4j_password: str,
        llm_model: str = "qwen-max",
        storage_dir: str = "./data/design_guides",
    ):
        self.llm = ChatOpenAI(model=llm_model, temperature=0)

        # Neo4j 连接
        self.driver = GraphDatabase.driver(
            neo4j_uri,
            auth=(neo4j_user, neo4j_password)
        )

        # 文件存储
        self.storage_dir = Path(storage_dir)
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Qianfan-OCR
        self.ocr = QianfanOCRProcessor()

        # ChromaDB
        self.chroma_client = chromadb.PersistentClient(
            path=str(self.storage_dir / "vectors")
        )
        self.knowledge_collection = self.chroma_client.get_or_create_collection(
            name="design_guide_knowledge",
            metadata={"description": "Design Guide 知识库"}
        )

        # 规则提取提示模板
        self.rule_extraction_prompt = self._load_rule_prompt()
        self.knowledge_extraction_prompt = self._load_knowledge_prompt()

    def process(
        self,
        file_path: str,
        manufacturer: str,
        mpn: str,
        category: str = "design_guide",
        uploaded_by: str = "system",
        progress_callback: Optional[Callable] = None,
    ) -> ProcessingResult:
        """
        处理 Design Guide PDF

        Args:
            file_path: PDF 文件路径
            manufacturer: 芯片厂商
            mpn: 目标芯片型号
            category: 文档类别
            uploaded_by: 上传人
            progress_callback: 进度回调

        Returns:
            ProcessingResult 处理结果
        """
        guide_id = self._generate_id(file_path, mpn)

        # 1. 创建文档记录
        guide = self._create_guide_record(
            guide_id=guide_id,
            file_path=file_path,
            manufacturer=manufacturer,
            mpn=mpn,
            category=category,
            uploaded_by=uploaded_by,
        )

        try:
            # 2. 解析 PDF
            if progress_callback:
                progress_callback("正在解析 PDF...", 10)
            guide, pages = self._parse_pdf(guide)

            # 3. 提取规则
            if progress_callback:
                progress_callback("正在提取设计规则...", 40)
            rules = self._extract_rules(guide, pages)

            # 4. 提取知识
            if progress_callback:
                progress_callback("正在提取设计知识...", 70)
            knowledge = self._extract_knowledge(guide, pages)

            # 5. 存储结果
            if progress_callback:
                progress_callback("正在保存结果...", 90)
            self._save_results(guide, rules, knowledge)

            # 6. 更新状态
            guide.status = "completed"
            guide.processed_at = datetime.now()
            guide.rules_count = len(rules)
            guide.knowledge_chunks_count = len(knowledge)
            self._update_guide_status(guide)

            return ProcessingResult(
                guide_id=guide_id,
                status="success",
                total_pages=len(pages),
                pages_processed=len(pages),
                rules_extracted=len(rules),
                knowledge_extracted=len(knowledge),
                rules=rules,
                knowledge=knowledge,
            )

        except Exception as e:
            guide.status = "failed"
            guide.error_message = str(e)
            self._update_guide_status(guide)

            return ProcessingResult(
                guide_id=guide_id,
                status="failed",
                total_pages=0,
                pages_processed=0,
                rules_extracted=0,
                knowledge_extracted=0,
                errors=[str(e)],
            )

    def _parse_pdf(self, guide: DesignGuide) -> tuple[DesignGuide, list[str]]:
        """解析 PDF 为页面文本"""
        # 使用 Qianfan-OCR
        images = self.ocr.pdf_to_images(guide.file_path)
        guide.page_count = len(images)

        pages = []
        for i, image in enumerate(images):
            markdown = self.ocr.extract_page_content(image, i + 1)
            pages.append(markdown)

        return guide, pages

    def _extract_rules(
        self,
        guide: DesignGuide,
        pages: list[str]
    ) -> list[ExtractedRule]:
        """从页面内容中提取规则"""
        rules = []

        # 构建提取提示
        prompt = self.rule_extraction_prompt.format(
            manufacturer=guide.manufacturer,
            mpn=guide.mpn,
            content="\n\n".join([
                f"=== Page {i+1} ===\n{page}"
                for i, page in enumerate(pages)
            ])
        )

        # 调用 LLM
        response = self.llm.invoke(prompt)

        # 解析 JSON
        try:
            data = json.loads(response.content)
            rule_data_list = data.get("rules", [])

            for rule_data in rule_data_list:
                rule = ExtractedRule(
                    id=f"{guide.id}_rule_{len(rules) + 1}",
                    guide_id=guide.id,
                    guide_name=guide.name,
                    rule_type=rule_data.get("rule_type", "other"),
                    title=rule_data.get("title", ""),
                    description=rule_data.get("description", ""),
                    requirement=rule_data.get("requirement", ""),
                    template_id=self._map_rule_type_to_template(rule_data.get("rule_type", "other")),
                    params=rule_data.get("params", {}),
                    severity=rule_data.get("severity", "WARNING"),
                    source_page=rule_data.get("source_page", 1),
                    source_quote=rule_data.get("source_quote", ""),
                    source_confidence=rule_data.get("confidence", 0.8),
                )
                rules.append(rule)

        except json.JSONDecodeError as e:
            print(f"规则 JSON 解析失败: {e}")

        return rules

    def _extract_knowledge(
        self,
        guide: DesignGuide,
        pages: list[str]
    ) -> list[ExtractedKnowledge]:
        """从页面内容中提取设计知识"""
        knowledge_list = []

        # 构建提取提示
        prompt = self.knowledge_extraction_prompt.format(
            manufacturer=guide.manufacturer,
            mpn=guide.mpn,
            content="\n\n".join([
                f"=== Page {i+1} ===\n{page}"
                for i, page in enumerate(pages)
            ])
        )

        # 调用 LLM
        response = self.llm.invoke(prompt)

        # 解析 JSON
        try:
            data = json.loads(response.content)
            knowledge_data_list = data.get("knowledge", [])

            for i, kb_data in enumerate(knowledge_data_list):
                # 存储到 ChromaDB
                content = kb_data.get("content", "")
                vector_id = self._store_vector(
                    collection=self.knowledge_collection,
                    text=content,
                    metadata={
                        "guide_id": guide.id,
                        "guide_name": guide.name,
                        "mpn": guide.mpn,
                        "category": kb_data.get("category", "general"),
                        "source_page": kb_data.get("source_page", 1),
                    }
                )

                knowledge = ExtractedKnowledge(
                    id=f"{guide.id}_kb_{i + 1}",
                    guide_id=guide.id,
                    category=kb_data.get("category", "general"),
                    title=kb_data.get("title", ""),
                    content=content,
                    vector_id=vector_id,
                    source_page=kb_data.get("source_page", 1),
                    source_section=kb_data.get("source_section"),
                    source_quote=kb_data.get("source_quote", ""),
                )
                knowledge_list.append(knowledge)

        except json.JSONDecodeError as e:
            print(f"知识 JSON 解析失败: {e}")

        return knowledge_list

    def _map_rule_type_to_template(self, rule_type: str) -> str:
        """将规则类型映射到模板"""
        mapping = {
            "power_decoupling": "decap_check",
            "pullup_pulldown": "pullup_check",
            "esd_protection": "esd_check",
            "bypass_capacitor": "decap_check",
            "termination": "termination_check",
            "power_sequencing": "power_seq_check",
            "impedance_matching": "impedance_check",
            "routing": "routing_check",
            "other": "generic_check",
        }
        return mapping.get(rule_type, "generic_check")

    def _store_vector(
        self,
        collection,
        text: str,
        metadata: dict
    ) -> str:
        """存储向量到 ChromaDB"""
        vector_id = metadata.get("guide_id", "") + "_" + str(metadata.get("source_page", 0))

        # 生成向量（使用 LLM 的嵌入）
        # 这里简化处理，实际应使用 embedding model
        embedding = self._generate_embedding(text)

        collection.add(
            documents=[text],
            embeddings=[embedding],
            metadatas=[metadata],
            ids=[vector_id]
        )

        return vector_id

    def _generate_embedding(self, text: str) -> list[float]:
        """生成文本向量（简化实现）"""
        # TODO: 集成实际的 embedding model
        import hashlib
        # 使用文本哈希作为伪向量（仅用于测试）
        h = hashlib.md5(text.encode()).digest()
        return [float(b) / 255.0 for b in h[:32]]

    def _save_results(
        self,
        guide: DesignGuide,
        rules: list[ExtractedRule],
        knowledge: list[ExtractedKnowledge]
    ):
        """保存结果到 Neo4j"""
        # 保存 Design Guide 节点
        cypher = """
        MERGE (g:DesignGuide {id: $id})
        SET g.name = $name,
            g.manufacturer = $manufacturer,
            g.mpn = $mpn,
            g.category = $category,
            g.file_path = $file_path,
            g.page_count = $page_count,
            g.status = $status,
            g.uploaded_by = $uploaded_by,
            g.uploaded_at = datetime($uploaded_at),
            g.rules_count = $rules_count,
            g.knowledge_chunks_count = $knowledge_count
        """

        with self.driver.session() as session:
            session.run(cypher, {
                "id": guide.id,
                "name": guide.name,
                "manufacturer": guide.manufacturer,
                "mpn": guide.mpn,
                "category": guide.category,
                "file_path": guide.file_path,
                "page_count": guide.page_count,
                "status": guide.status,
                "uploaded_by": guide.uploaded_by,
                "uploaded_at": guide.uploaded_at.isoformat(),
                "rules_count": len(rules),
                "knowledge_count": len(knowledge),
            })

            # 保存规则节点
            for rule in rules:
                rule_cypher = """
                MERGE (r:ExtractedRule {id: $id})
                SET r.guide_id = $guide_id,
                    r.rule_type = $rule_type,
                    r.title = $title,
                    r.description = $description,
                    r.template_id = $template_id,
                    r.params = $params,
                    r.severity = $severity,
                    r.source_page = $source_page,
                    r.source_quote = $source_quote,
                    r.confidence = $confidence,
                    r.status = $status

                WITH r
                MATCH (g:DesignGuide {id: $guide_id})
                MERGE (g)-[:GENERATES]->(r)
                """

                session.run(rule_cypher, {
                    "id": rule.id,
                    "guide_id": rule.guide_id,
                    "rule_type": rule.rule_type.value if hasattr(rule.rule_type, 'value') else rule.rule_type,
                    "title": rule.title,
                    "description": rule.description,
                    "template_id": rule.template_id,
                    "params": json.dumps(rule.params),
                    "severity": rule.severity,
                    "source_page": rule.source_page,
                    "source_quote": rule.source_quote,
                    "confidence": rule.source_confidence,
                    "status": rule.status,
                })

    def _load_rule_prompt(self) -> str:
        """加载规则提取提示模板"""
        return """
你是电子芯片 Design Guide 规则提取专家。

请从以下 {manufacturer} {mpn} 的 Design Guide 文档中提取硬件设计规则。

提取要求：
1. 只提取可执行的硬件设计规则（如去耦电容、上拉电阻、ESD保护等）
2. 每个规则必须包含具体的技术参数和数值要求
3. 标注规则来源（页码）和置信度
4. 将规则参数化为可执行格式

支持的规则类型：
- power_decoupling: 电源去耦
- pullup_pulldown: 上下拉电阻
- esd_protection: ESD保护
- bypass_capacitor: 旁路电容
- termination: 端接电阻
- power_sequencing: 电源时序
- impedance_matching: 阻抗匹配

输出格式 (JSON):
{{
  "rules": [
    {{
      "rule_type": "power_decoupling",
      "title": "1.8V 电源去耦要求",
      "description": "每个1.8V电源引脚必须配置去耦电容",
      "requirement": "每个电源引脚至少2个0.1µF电容",
      "params": {{
        "voltage": "1V8",
        "min_count": 2,
        "capacitor_values": ["0.1uF"]
      }},
      "severity": "ERROR",
      "source_page": 15,
      "source_quote": "Each VCC pin should have at least 2 decoupling capacitors...",
      "confidence": 0.95
    }}
  ]
}}

只输出 JSON，不要有其他内容。

文档内容:
{content}
"""

    def _load_knowledge_prompt(self) -> str:
        """加载知识提取提示模板"""
        return """
你是电子芯片设计知识提取专家。

请从以下 {manufacturer} {mpn} 的 Design Guide 文档中提取设计知识。

提取要求：
1. 提取有价值的硬件设计知识（引脚分配、时钟时序、热设计、布局建议等）
2. 保留技术细节和推荐做法
3. 标注来源（页码、章节）

支持的知识类别：
- pin_assignment: 引脚分配
- power_supply: 电源设计
- clock_timing: 时钟时序
- thermal: 热设计
- layout: 布局布线
- testing: 测试建议
- troubleshooting: 故障排查
- general: 一般说明

输出格式 (JSON):
{{
  "knowledge": [
    {{
      "category": "power_supply",
      "title": "电源设计建议",
      "content": "1.8V 电源建议使用 LDO 供电...",
      "source_page": 12,
      "source_section": "Power Supply Design",
      "source_quote": "For 1.8V operation, an LDO regulator..."
    }}
  ]
}}

只输出 JSON，不要有其他内容。

文档内容:
{content}
"""

    def _generate_id(self, file_path: str, mpn: str) -> str:
        """生成文档唯一ID"""
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        hash_str = hashlib.md5(f"{file_path}{mpn}".encode()).hexdigest()[:8]
        return f"DG_{timestamp}_{hash_str}"

    def _create_guide_record(
        self,
        guide_id: str,
        file_path: str,
        manufacturer: str,
        mpn: str,
        category: str,
        uploaded_by: str,
    ) -> DesignGuide:
        """创建文档记录"""
        return DesignGuide(
            id=guide_id,
            name=Path(file_path).stem,
            manufacturer=manufacturer,
            mpn=mpn,
            category=category,
            file_path=file_path,
            file_hash=hashlib.md5(open(file_path, 'rb').read()).hexdigest(),
            page_count=0,
            status="uploaded",
            uploaded_by=uploaded_by,
        )

    def _update_guide_status(self, guide: DesignGuide):
        """更新文档状态"""
        cypher = """
        MATCH (g:DesignGuide {id: $id})
        SET g.status = $status,
            g.error_message = $error_message,
            g.processed_at = $processed_at,
            g.rules_count = $rules_count
        """

        with self.driver.session() as session:
            session.run(cypher, {
                "id": guide.id,
                "status": guide.status,
                "error_message": guide.error_message,
                "processed_at": guide.processed_at.isoformat() if guide.processed_at else None,
                "rules_count": guide.rules_count,
            })
```

### 3.3 规则转换器

```python
# agent_system/design_guide_processor/rule_transformer.py

"""
规则转换器

将 ExtractedRule 转换为可执行的 RuleConfig
"""

from typing import list
from agent_system.review_engine.config import RuleConfig
from agent_system.design_guide_processor.models import ExtractedRule


class RuleTransformer:
    """
    规则转换器

    将从 Design Guide 提取的规则转换为可执行的 RuleConfig
    """

    # 规则类型到模板的映射
    TYPE_TO_TEMPLATE = {
        "power_decoupling": "decap_check",
        "bypass_capacitor": "decap_check",
        "pullup_pulldown": "pullup_check",
        "esd_protection": "esd_check",
        "termination": "termination_check",
        "power_sequencing": "power_seq_check",
        "impedance_matching": "impedance_check",
        "routing": "routing_check",
        "other": "generic_check",
    }

    def transform(self, extracted_rule: ExtractedRule) -> RuleConfig:
        """
        将 ExtractedRule 转换为 RuleConfig

        Args:
            extracted_rule: 提取的规则

        Returns:
            RuleConfig 可执行的规则配置
        """
        # 生成规则 ID
        rule_id = f"KB_{extracted_rule.guide_id}_{extracted_rule.id}"

        # 确定模板
        template_id = self.TYPE_TO_TEMPLATE.get(
            extracted_rule.rule_type,
            "generic_check"
        )

        # 构建参数
        params = self._build_params(extracted_rule)

        # 创建 RuleConfig
        return RuleConfig(
            id=rule_id,
            template_id=template_id,
            name=extracted_rule.title,
            description=extracted_rule.description,
            severity=extracted_rule.severity,
            params=params,
            applicable_mpns=extracted_rule.applicable_mpns,
            applicable_voltages=extracted_rule.applicable_voltages,
            applicable_nets=extracted_rule.applicable_nets,
            tags=[extracted_rule.guide_name, extracted_rule.rule_type],
        )

    def _build_params(self, rule: ExtractedRule) -> dict:
        """根据规则类型构建参数"""
        params = rule.params.copy()

        # 如果没有预定义的参数，根据规则内容推断
        if not params and rule.requirement:
            params = self._infer_params(rule)

        return params

    def _infer_params(self, rule: ExtractedRule) -> dict:
        """从规则描述中推断参数"""
        import re

        params = {}
        requirement = rule.requirement.lower()

        if rule.rule_type in ["power_decoupling", "bypass_capacitor"]:
            # 提取电容数量
            count_match = re.search(r'(\d+)\s*(?:个|颗|pcs)?\s*(?:0?\.?\d+[uU]?[fF])', requirement)
            if count_match:
                params["min_count"] = int(count_match.group(1))

            # 提取电容值
            values = re.findall(r'0?\.?\d+[uU]?[fF]', requirement)
            if values:
                params["required_values"] = values

        elif rule.rule_type in ["pullup_pulldown"]:
            # 提取电阻值范围
            ohm_match = re.search(r'(\d+\.?\d*)\s*([kK]?)\s*Ω?', requirement)
            if ohm_match:
                value = float(ohm_match.group(1))
                unit = ohm_match.group(2)
                if unit.lower() == 'k':
                    value *= 1000
                params["min_ohm"] = value * 0.8  # 下浮 20%
                params["max_ohm"] = value * 1.2  # 上浮 20%

        return params

    def batch_transform(
        self,
        extracted_rules: list[ExtractedRule]
    ) -> list[RuleConfig]:
        """批量转换规则"""
        configs = []
        for rule in extracted_rules:
            if rule.status == "approved" or rule.status == "extracted":
                config = self.transform(rule)
                configs.append(config)
        return configs
```

### 3.4 Design Guide 知识库管理

```python
# agent_system/design_guide_processor/library.py

"""
Design Guide 知识库管理

管理用户上传的 Design Guide 和提取的规则
"""

from typing import Optional
from agent_system.design_guide_processor.models import DesignGuide, ExtractedRule, ExtractedKnowledge


class DesignGuideLibrary:
    """
    Design Guide 知识库

    管理 Design Guide 文档库和提取的规则知识
    """

    def __init__(self, neo4j_driver):
        self.driver = neo4j_driver

    def list_guides(
        self,
        manufacturer: Optional[str] = None,
        status: Optional[str] = None,
    ) -> list[DesignGuide]:
        """列出 Design Guide"""
        cypher = """
        MATCH (g:DesignGuide)
        WHERE ($manufacturer IS NULL OR g.manufacturer = $manufacturer)
          AND ($status IS NULL OR g.status = $status)
        RETURN g
        ORDER BY g.uploaded_at DESC
        """

        with self.driver.session() as session:
            results = session.run(cypher, {
                "manufacturer": manufacturer,
                "status": status,
            })

            guides = []
            for record in results:
                g = record["g"]
                guides.append(DesignGuide(
                    id=g.get("id", ""),
                    name=g.get("name", ""),
                    manufacturer=g.get("manufacturer", ""),
                    mpn=g.get("mpn", ""),
                    category=g.get("category", ""),
                    file_path=g.get("file_path", ""),
                    page_count=g.get("page_count", 0),
                    status=g.get("status", "uploaded"),
                    rules_count=g.get("rules_count", 0),
                    knowledge_chunks_count=g.get("knowledge_chunks_count", 0),
                ))

            return guides

    def get_guide_rules(
        self,
        guide_id: str,
        approved_only: bool = True
    ) -> list[ExtractedRule]:
        """获取 Design Guide 的规则"""
        status_filter = "AND r.status = 'approved'" if approved_only else ""

        cypher = f"""
        MATCH (g:DesignGuide {{id: $guide_id}})-[:GENERATES]->(r:ExtractedRule)
        WHERE true {status_filter}
        RETURN r
        ORDER BY r.confidence DESC
        """

        with self.driver.session() as session:
            results = session.run(cypher, {"guide_id": guide_id})

            rules = []
            for record in results:
                r = record["r"]
                rules.append(ExtractedRule(
                    id=r.get("id", ""),
                    guide_id=r.get("guide_id", ""),
                    guide_name="",
                    rule_type=r.get("rule_type", "other"),
                    title=r.get("title", ""),
                    description=r.get("description", ""),
                    requirement=r.get("requirement", ""),
                    template_id=r.get("template_id", "generic_check"),
                    severity=r.get("severity", "WARNING"),
                    source_page=r.get("source_page", 1),
                    source_quote=r.get("source_quote", ""),
                    source_confidence=r.get("confidence", 0.8),
                    status=r.get("status", "extracted"),
                ))

            return rules

    def approve_rule(
        self,
        rule_id: str,
        reviewed_by: str,
        notes: Optional[str] = None
    ):
        """审核通过规则"""
        cypher = """
        MATCH (r:ExtractedRule {id: $rule_id})
        SET r.status = 'approved',
            r.reviewed_by = $reviewed_by,
            r.reviewed_at = datetime(),
            r.review_notes = $notes
        """

        with self.driver.session() as session:
            session.run(cypher, {
                "rule_id": rule_id,
                "reviewed_by": reviewed_by,
                "notes": notes,
            })

    def reject_rule(
        self,
        rule_id: str,
        reviewed_by: str,
        reason: str
    ):
        """审核拒绝规则"""
        cypher = """
        MATCH (r:ExtractedRule {id: $rule_id})
        SET r.status = 'rejected',
            r.reviewed_by = $reviewed_by,
            r.reviewed_at = datetime(),
            r.review_notes = $reason
        """

        with self.driver.session() as session:
            session.run(cypher, {
                "rule_id": rule_id,
                "reviewed_by": reviewed_by,
                "reason": reason,
            })

    def get_rules_by_mpn(self, mpn: str) -> list[ExtractedRule]:
        """根据芯片型号获取规则"""
        cypher = """
        MATCH (g:DesignGuide {mpn: $mpn})-[:GENERATES]->(r:ExtractedRule)
        WHERE r.status IN ['approved', 'extracted']
        RETURN r
        ORDER BY r.confidence DESC
        """

        with self.driver.session() as session:
            results = session.run(cypher, {"mpn": mpn})

            rules = []
            for record in results:
                r = record["r"]
                rules.append(ExtractedRule(
                    id=r.get("id", ""),
                    guide_id=r.get("guide_id", ""),
                    guide_name="",
                    rule_type=r.get("rule_type", "other"),
                    title=r.get("title", ""),
                    description=r.get("description", ""),
                    template_id=r.get("template_id", "generic_check"),
                    severity=r.get("severity", "WARNING"),
                    params=json.loads(r.get("params", "{}")),
                    source_page=r.get("source_page", 1),
                    source_confidence=r.get("confidence", 0.8),
                    status=r.get("status", "extracted"),
                ))

            return rules

    def search_knowledge(
        self,
        query: str,
        mpn: Optional[str] = None,
        category: Optional[str] = None,
        limit: int = 5
    ) -> list[ExtractedKnowledge]:
        """搜索设计知识（向量检索）"""
        # 使用 ChromaDB 进行向量搜索
        # 此处简化实现
        pass

    def export_rules_to_config(
        self,
        guide_id: str,
        output_path: str
    ):
        """导出规则为 YAML 配置"""
        from agent_system.review_engine.config import RuleConfigManager
        from agent_system.design_guide_processor.rule_transformer import RuleTransformer

        # 获取规则
        rules = self.get_guide_rules(guide_id)

        # 转换
        transformer = RuleTransformer()
        configs = transformer.batch_transform(rules)

        # 导出
        manager = RuleConfigManager()
        for config in configs:
            manager.add_rule(config)
        manager.save_to_file(output_path)
```

---

## 4. Streamlit UI 集成

```python
# web_ui/design_guide_tab.py

"""
Design Guide 上传与管理界面
"""

import streamlit as st
from agent_system.design_guide_processor import (
    DesignGuideProcessor,
    DesignGuideLibrary,
)


def design_guide_tab():
    """Design Guide 管理标签页"""

    st.header("Design Guide 知识库")

    # 标签页
    tab1, tab2, tab3 = st.tabs(["上传文档", "规则审核", "知识搜索"])

    with tab1:
        upload_section()

    with tab2:
        review_section()

    with tab3:
        search_section()


def upload_section():
    """上传文档"""
    st.subheader("上传 Design Guide")

    with st.form("upload_form"):
        col1, col2 = st.columns(2)

        with col1:
            manufacturer = st.text_input("芯片厂商", placeholder="如: Micron, TI, NXP")
            mpn = st.text_input("芯片型号", placeholder="如: MT25QU256ABA8E12")

        with col2:
            category = st.selectbox(
                "文档类型",
                ["design_guide", "app_note", "datasheet"]
            )
            uploaded_by = st.text_input("上传人", value="user")

        uploaded_file = st.file_uploader(
            "选择 PDF 文件",
            type=["pdf"]
        )

        submitted = st.form_submit_button("上传并处理")

        if submitted and uploaded_file:
            # 保存文件
            save_path = f"./data/design_guides/{uploaded_file.name}"
            with open(save_path, "wb") as f:
                f.write(uploaded_file.getbuffer())

            # 处理
            processor = DesignGuideProcessor(
                neo4j_uri="bolt://localhost:7687",
                neo4j_user="neo4j",
                neo4j_password="password",
            )

            progress_bar = st.progress(0)
            status_text = st.empty()

            def progress_callback(message, percent):
                progress_bar.progress(percent / 100)
                status_text.text(message)

            result = processor.process(
                file_path=save_path,
                manufacturer=manufacturer,
                mpn=mpn,
                category=category,
                uploaded_by=uploaded_by,
                progress_callback=progress_callback,
            )

            if result.status == "success":
                st.success(f"处理完成！提取了 {result.rules_extracted} 条规则")
            else:
                st.error(f"处理失败: {result.errors}")


def review_section():
    """规则审核"""
    st.subheader("规则审核")

    library = DesignGuideLibrary(driver)

    # 选择 Design Guide
    guides = library.list_guides(status="completed")
    guide_options = {g.name: g.id for g in guides}
    selected_guide = st.selectbox("选择文档", list(guide_options.keys()))

    if selected_guide:
        guide_id = guide_options[selected_guide]
        rules = library.get_guide_rules(guide_id, approved_only=False)

        # 统计
        col1, col2, col3 = st.columns(3)
        col1.metric("总规则数", len(rules))
        col2.metric("已审核", len([r for r in rules if r.status == "approved"]))
        col3.metric("待审核", len([r for r in rules if r.status == "extracted"]))

        # 规则列表
        for rule in rules:
            with st.expander(f"[{rule.severity}] {rule.title}", expanded=False):
                st.write(f"**类型**: {rule.rule_type}")
                st.write(f"**描述**: {rule.description}")
                st.write(f"**要求**: {rule.requirement}")
                st.write(f"**来源**: 第 {rule.source_page} 页")
                st.write(f"**置信度**: {rule.source_confidence:.0%}")
                st.write(f"**状态**: {rule.status}")

                if rule.status == "extracted":
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("通过", key=f"approve_{rule.id}"):
                            library.approve_rule(rule.id, "user")
                            st.rerun()
                    with col2:
                        if st.button("拒绝", key=f"reject_{rule.id}"):
                            library.reject_rule(rule.id, "user", "不符合要求")
                            st.rerun()


def search_section():
    """知识搜索"""
    st.subheader("设计知识搜索")

    query = st.text_input("搜索关键词", placeholder="如: decoupling, pullup, ESD")

    if query:
        st.info("向量搜索功能开发中...")
        # TODO: 实现 ChromaDB 向量搜索
```

---

## 5. 工作流程总结

```
┌─────────────────────────────────────────────────────────────────────────┐
│                    Design Guide 知识提取完整流程                          │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  1. 用户上传 Design Guide PDF                                            │
│     └── Streamlit 上传界面                                              │
│                                                                          │
│  2. Qianfan-OCR 解析                                                    │
│     └── PDF → 页面图像 → Markdown                                        │
│                                                                          │
│  3. LLM 规则提取                                                        │
│     └── Prompt → 结构化 JSON 规则                                        │
│                                                                          │
│  4. LLM 知识提取                                                        │
│     └── Prompt → 设计知识切片                                            │
│                                                                          │
│  5. 规则审核 (可选)                                                     │
│     └── Human-in-the-Loop 审核                                          │
│                                                                          │
│  6. 规则转换                                                            │
│     └── ExtractedRule → RuleConfig                                     │
│                                                                          │
│  7. 规则应用                                                            │
│     └── 合并到审查规则库                                                 │
│                                                                          │
│  8. 知识检索                                                            │
│     └── RAG 问答支持                                                     │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## 6. 方案优势

| 特性 | 说明 |
|------|------|
| **用户自定义规则** | 用户可上传自己芯片的 Design Guide |
| **权威性** | 规则来源于厂家官方文档 |
| **自动化** | LLM 自动提取，最小人工干预 |
| **可审核** | 支持专家审核，确保规则质量 |
| **可追溯** | 保留原文引用，可追溯来源 |
| **可扩展** | 支持多种文档格式和规则类型 |

---

## 7. 待扩展功能

1. **批量上传**: 支持批量上传多个 Design Guide
2. **规则版本管理**: 跟踪规则变更历史
3. **规则分享**: 支持导出/导入规则配置
4. **知识问答**: 基于 Design Guide 内容的 RAG 问答
5. **规则冲突检测**: 检测规则之间的冲突
