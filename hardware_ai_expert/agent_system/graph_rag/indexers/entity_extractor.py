"""LLM 实体抽取器

从 Datasheet 文本中抽取硬件实体和关系。
"""

from __future__ import annotations

import json
import logging
import re
from typing import Optional

from agent_system.graph_rag.schemas import ExtractedEntity, ExtractedRelation, GraphRAGConfig

logger = logging.getLogger(__name__)


EXTRACTION_PROMPT = """从以下硬件文档文本中抽取实体和关系。

实体类型：
- Component: 器件型号 (如 TPS7A47, SN74LVC1G34)
- Spec: 规格参数 (如 "Input Voltage 5.5-36V", "Output Current 1A")
- Pin: 引脚定义 (如 "Pin 1 VIN", "Pin 3 EN")
- Application: 应用建议 (如 "Decoupling: 10uF ceramic", "Add 0.1uF bypass cap")

关系类型：
- HAS_SPEC: Component → Spec
- HAS_PIN: Component → Pin
- RECOMMENDS: Component → Application

请以 JSON 格式输出：
{
  "entities": [
    {"type": "Component", "name": "TPS7A47", "properties": {"category": "LDO"}},
    {"type": "Spec", "name": "Input Voltage 5.5-36V", "properties": {"param": "vin", "min": 5.5, "max": 36, "unit": "V"}}
  ],
  "relations": [
    {"source": "TPS7A47", "source_type": "Component", "target": "Input Voltage 5.5-36V", "target_type": "Spec", "relation": "HAS_SPEC"}
  ]
}

仅输出 JSON，不要其他文字。

文档文本：
{text}
"""


class HardwareEntityExtractor:
    """从 Datasheet 文本抽取硬件实体"""

    def __init__(self, llm_client=None, config: Optional[GraphRAGConfig] = None):
        self.config = config or GraphRAGConfig()
        self._llm = llm_client

    def _get_llm(self):
        """获取 LLM 客户端"""
        if self._llm is None:
            from agent_system.llm_client import LLMClient
            self._llm = LLMClient()
        return self._llm

    def extract(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """
        从文本中抽取实体和关系

        Args:
            text: Datasheet 文本

        Returns:
            (entities, relations) 元组
        """
        # 如果文本太长，分段处理
        if len(text) > 2000:
            return self._extract_long_text(text)

        prompt = EXTRACTION_PROMPT.format(text=text)

        try:
            llm = self._get_llm()
            response = llm.chat(prompt, temperature=0.1)
            return self._parse_response(response)
        except Exception as e:
            logger.warning(f"LLM 实体抽取失败: {e}")
            return self._regex_fallback(text)

    def _extract_long_text(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """分段抽取长文本"""
        all_entities = []
        all_relations = []

        # 按段落分割
        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]

        for para in paragraphs[:10]:  # 最多处理 10 段
            try:
                entities, relations = self.extract(para)
                all_entities.extend(entities)
                all_relations.extend(relations)
            except Exception:
                continue

        # 去重
        seen = set()
        unique_entities = []
        for e in all_entities:
            key = (e.entity_type, e.name)
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return unique_entities, all_relations

    def _parse_response(self, response: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """解析 LLM JSON 响应"""
        entities = []
        relations = []

        # 尝试提取 JSON
        json_str = response.strip()
        # 去掉 markdown 代码块
        if "```json" in json_str:
            json_str = json_str.split("```json")[1].split("```")[0]
        elif "```" in json_str:
            json_str = json_str.split("```")[1].split("```")[0]

        # 去掉 <think>...</think> 等标签
        import re
        json_str = re.sub(r'<[^>]+>', '', json_str)

        # 清理常见格式问题
        json_str = json_str.strip()
        if not json_str.startswith('{'):
            # 找第一个 { 开始
            idx = json_str.find('{')
            if idx >= 0:
                json_str = json_str[idx:]
        if not json_str.rstrip().endswith('}'):
            # 找最后一个 }
            idx = json_str.rfind('}')
            if idx >= 0:
                json_str = json_str[:idx + 1]

        try:
            data = json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug(f"JSON 解析失败: {e}, 响应前80字: {json_str[:80]}")
            return [], []

        # 解析实体
        for ent in data.get("entities", []):
            entities.append(ExtractedEntity(
                entity_type=ent.get("type", "Unknown"),
                name=ent.get("name", ""),
                properties=ent.get("properties", {}),
            ))

        # 解析关系
        for rel in data.get("relations", []):
            relations.append(ExtractedRelation(
                source=rel.get("source", ""),
                source_type=rel.get("source_type", ""),
                target=rel.get("target", ""),
                target_type=rel.get("target_type", ""),
                relation_type=rel.get("relation", "RELATED_TO"),
            ))

        return entities, relations

    def _regex_fallback(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """正则表达式降级抽取（当 LLM 不可用时）"""
        entities = []
        relations = []

        # 抽取 MPN 模式
        mpn_patterns = [
            r'\b([A-Z]{2,}\d{2,}[A-Z0-9\-]*)\b',  # TPS7A47, SN74LVC1G34
            r'\b(TLV|TPS|SN|LM|ADM|MAX|MIC|NCP|RT)\d{4,}[A-Z0-9\-]*\b',
        ]

        seen_mpns = set()
        for pattern in mpn_patterns:
            for match in re.finditer(pattern, text):
                mpn = match.group(1) if match.lastindex else match.group(0)
                if mpn not in seen_mpns and len(mpn) >= 4:
                    seen_mpns.add(mpn)
                    entities.append(ExtractedEntity(
                        entity_type="Component",
                        name=mpn,
                        properties={"extraction_method": "regex"},
                    ))

        # 抽取电压规格
        voltage_pattern = r'(\d+\.?\d*)\s*V\s*(?:to|-)\s*(\d+\.?\d*)\s*V'
        for match in re.finditer(voltage_pattern, text, re.IGNORECASE):
            vmin, vmax = match.group(1), match.group(2)
            entities.append(ExtractedEntity(
                entity_type="Spec",
                name=f"Voltage {vmin}-{vmax}V",
                properties={"param": "voltage", "min": float(vmin), "max": float(vmax), "unit": "V"},
            ))

        # 抽取电容推荐
        cap_pattern = r'(\d+\.?\d*)\s*(uF|nF|pF)\s*(?:ceramic|capacitor|bypass|decoupling)'
        for match in re.finditer(cap_pattern, text, re.IGNORECASE):
            value, unit = match.group(1), match.group(2)
            entities.append(ExtractedEntity(
                entity_type="Application",
                name=f"Capacitor {value}{unit}",
                properties={"type": "decoupling", "value": value, "unit": unit},
            ))

        return entities, relations

    def write_to_neo4j(self, entities: list[ExtractedEntity],
                        relations: list[ExtractedRelation], driver):
        """将抽取的实体和关系写入 Neo4j"""
        # 写入实体
        for ent in entities:
            label = ent.entity_type
            if label == "Component":
                label = "ExtractedComponent"
            elif label == "Spec":
                label = "ExtractedSpec"
            elif label == "Pin":
                label = "ExtractedPin"
            elif label == "Application":
                label = "ExtractedApplication"

            props = {k: v for k, v in ent.properties.items() if isinstance(v, (str, int, float, bool))}
            props["name"] = ent.name
            props_str = ", ".join([f"{k}: ${k}" for k in props.keys()])

            cypher = f"""
            MERGE (e:{label} {{name: $name}})
            SET {', '.join([f'e.{k} = ${k}' for k in props.keys() if k != 'name'])}
            """

            try:
                with driver.session() as session:
                    session.run(cypher, props)
            except Exception as e:
                logger.debug(f"写入实体失败: {e}")

        # 写入关系
        for rel in relations:
            src_label = self._entity_type_to_label(rel.source_type)
            tgt_label = self._entity_type_to_label(rel.target_type)
            rel_type = rel.relation_type

            cypher = f"""
            MATCH (s:{src_label} {{name: $source}})
            MATCH (t:{tgt_label} {{name: $target}})
            MERGE (s)-[:{rel_type}]->(t)
            """

            try:
                with driver.session() as session:
                    session.run(cypher, {"source": rel.source, "target": rel.target})
            except Exception as e:
                logger.debug(f"写入关系失败: {e}")

    @staticmethod
    def _entity_type_to_label(entity_type: str) -> str:
        mapping = {
            "Component": "ExtractedComponent",
            "Spec": "ExtractedSpec",
            "Pin": "ExtractedPin",
            "Application": "ExtractedApplication",
        }
        return mapping.get(entity_type, "Entity")
