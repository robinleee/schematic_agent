"""LLM 实体抽取器

从 Datasheet 文本中抽取硬件实体和关系。
v2: 健壮 JSON 解析 + 重试 + 结构化 prompt
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

【重要】仅输出合法 JSON，格式如下，不要输出任何其他文字、解释或 markdown：
{"entities":[{"type":"Component","name":"TPS7A47","properties":{"category":"LDO"}}],"relations":[{"source":"TPS7A47","source_type":"Component","target":"Input Voltage 5.5-36V","target_type":"Spec","relation":"HAS_SPEC"}]}

文档文本：
{text}
"""


class HardwareEntityExtractor:
    """从 Datasheet 文本抽取硬件实体"""

    MAX_RETRIES = 2

    def __init__(self, llm_client=None, config: Optional[GraphRAGConfig] = None):
        self.config = config or GraphRAGConfig()
        self._llm = llm_client

    def _get_llm(self):
        if self._llm is None:
            from agent_system.llm_client import LLMClient
            self._llm = LLMClient()
        return self._llm

    def extract(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        if len(text) > 2000:
            return self._extract_long_text(text)

        prompt = EXTRACTION_PROMPT.format(text=text[:1500])  # 截断过长文本

        for attempt in range(self.MAX_RETRIES):
            try:
                llm = self._get_llm()
                temp = 0.1 if attempt == 0 else 0.0
                response = llm.chat(prompt, temperature=temp)
                entities, relations = self._parse_response(response)

                if entities:
                    return entities, relations

                logger.debug(f"Attempt {attempt+1}: extracted 0 entities, retrying...")
            except Exception as e:
                logger.warning(f"LLM 实体抽取失败 (attempt {attempt+1}): {e}")

        # All retries failed, fallback to regex
        logger.info("LLM extraction failed after retries, using regex fallback")
        return self._regex_fallback(text)

    def _extract_long_text(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        all_entities = []
        all_relations = []

        paragraphs = [p.strip() for p in text.split("\n\n") if len(p.strip()) > 50]

        for para in paragraphs[:10]:
            try:
                entities, relations = self.extract(para)
                all_entities.extend(entities)
                all_relations.extend(relations)
            except Exception:
                continue

        seen = set()
        unique_entities = []
        for e in all_entities:
            key = (e.entity_type, e.name)
            if key not in seen:
                seen.add(key)
                unique_entities.append(e)

        return unique_entities, all_relations

    def _parse_response(self, response: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """解析 LLM JSON 响应 — 健壮版"""
        entities = []
        relations = []

        json_str = self._extract_json_string(response)
        if not json_str:
            return [], []

        data = self._safe_json_loads(json_str)
        if not data:
            return [], []

        # 解析实体
        for ent in data.get("entities", []):
            if not isinstance(ent, dict):
                continue
            entities.append(ExtractedEntity(
                entity_type=ent.get("type", "Unknown"),
                name=ent.get("name", ""),
                properties=ent.get("properties", {}),
            ))

        # 解析关系
        for rel in data.get("relations", []):
            if not isinstance(rel, dict):
                continue
            relations.append(ExtractedRelation(
                source=rel.get("source", ""),
                source_type=rel.get("source_type", ""),
                target=rel.get("target", ""),
                target_type=rel.get("target_type", ""),
                relation_type=rel.get("relation", "RELATED_TO"),
            ))

        return entities, relations

    @staticmethod
    def _extract_json_string(response: str) -> Optional[str]:
        """从 LLM 响应中提取 JSON 字符串，多层清理"""
        s = response.strip()

        # Step 1: 去掉 <think>...</think> 标签
        s = re.sub(r'<think>.*?</think>', '', s, flags=re.DOTALL)
        s = re.sub(r'<[^>]+>', '', s)

        # Step 2: 去掉 markdown 代码块
        if "```json" in s:
            s = s.split("```json", 1)[1]
            if "```" in s:
                s = s.split("```", 1)[0]
        elif "```" in s:
            parts = s.split("```")
            if len(parts) >= 2:
                s = parts[1]
                if s.startswith('\n'):
                    s = s[1:]

        s = s.strip()

        # Step 3: 定位首尾花括号
        first_brace = s.find('{')
        last_brace = s.rfind('}')
        if first_brace < 0 or last_brace <= first_brace:
            return None

        s = s[first_brace:last_brace + 1]

        # Step 4: 清理常见问题
        # 4a: 移除尾部逗号 (trailing comma before } or ])
        s = re.sub(r',\s*([}\]])', r'\1', s)
        # 4b: 修复单引号为双引号（如果整体用单引号）
        if '"' not in s and "'" in s:
            s = s.replace("'", '"')
        # 4c: 修复缺少引号的 key
        s = re.sub(r'(\{|,)\s*([a-zA-Z_]\w*)\s*:', r'\1"\2":', s)
        # 4d: 修复布尔值
        s = re.sub(r':\s*True\b', ': true', s)
        s = re.sub(r':\s*False\b', ': false', s)
        s = re.sub(r':\s*None\b', ': null', s)

        return s

    @staticmethod
    def _safe_json_loads(json_str: str) -> Optional[dict]:
        """安全的 JSON 加载，多层降级"""
        # 尝试 1: 直接解析
        try:
            return json.loads(json_str)
        except json.JSONDecodeError:
            pass

        # 尝试 2: 修复常见错误 — 转义字符
        try:
            fixed = json_str.replace('\\n', ' ').replace('\\t', ' ')
            return json.loads(fixed)
        except json.JSONDecodeError:
            pass

        # 尝试 3: 逐字符修复 — 找到最深的有效 JSON 对象
        try:
            # 尝试找到 "entities" key 并手动构建
            return HardwareEntityExtractor._manual_parse(json_str)
        except Exception:
            pass

        logger.debug(f"JSON 解析全部失败, 原文前100字: {json_str[:100]}")
        return None

    @staticmethod
    def _manual_parse(json_str: str) -> Optional[dict]:
        """手动从可能损坏的 JSON 中提取实体列表"""
        result = {"entities": [], "relations": []}

        # 尝试用正则提取 entities 数组中的每个对象
        # 匹配 {"type":"...", "name":"...", ...} 模式
        entity_pattern = r'\{\s*"type"\s*:\s*"([^"]+)"\s*,\s*"name"\s*:\s*"([^"]+)"'
        for match in re.finditer(entity_pattern, json_str):
            etype, name = match.group(1), match.group(2)
            result["entities"].append({
                "type": etype,
                "name": name,
                "properties": {},
            })

        # 匹配关系
        rel_pattern = r'\{\s*"source"\s*:\s*"([^"]+)"\s*,\s*"source_type"\s*:\s*"([^"]+)"\s*,\s*"target"\s*:\s*"([^"]+)"\s*,\s*"target_type"\s*:\s*"([^"]+)"\s*,\s*"relation"\s*:\s*"([^"]+)"'
        for match in re.finditer(rel_pattern, json_str):
            result["relations"].append({
                "source": match.group(1),
                "source_type": match.group(2),
                "target": match.group(3),
                "target_type": match.group(4),
                "relation": match.group(5),
            })

        return result if result["entities"] or result["relations"] else None

    def _regex_fallback(self, text: str) -> tuple[list[ExtractedEntity], list[ExtractedRelation]]:
        """正则表达式降级抽取（当 LLM 不可用时）"""
        entities = []
        relations = []

        # 抽取 MPN 模式 — 扩展覆盖
        mpn_patterns = [
            r'\b([A-Z]{2,4}\d[A-Z0-9\-]{3,})\b',  # TPS7A47, SN74LVC1G34, TLV733P
            r'\b(TLV|TPS|SN|LM|ADM|MAX|MIC|NCP|RT|GRM|CL)\d{2,}[A-Z0-9\-]*\b',
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
        voltage_pattern = r'(\d+\.?\d*)\s*V\s*(?:to|-|~)\s*(\d+\.?\d*)\s*V'
        for match in re.finditer(voltage_pattern, text, re.IGNORECASE):
            vmin, vmax = match.group(1), match.group(2)
            entities.append(ExtractedEntity(
                entity_type="Spec",
                name=f"Voltage {vmin}-{vmax}V",
                properties={"param": "voltage", "min": float(vmin), "max": float(vmax), "unit": "V"},
            ))

        # 抽取电流规格
        current_pattern = r'(\d+\.?\d*)\s*m?A\s*(?:to|-|~)\s*(\d+\.?\d*)\s*m?A'
        for match in re.finditer(current_pattern, text, re.IGNORECASE):
            entities.append(ExtractedEntity(
                entity_type="Spec",
                name=f"Current {match.group(1)}-{match.group(2)}A",
                properties={"param": "current", "unit": "A"},
            ))

        # 抽取电容推荐
        cap_pattern = r'(\d+\.?\d*)\s*(uF|nF|pF|µF)\s*(?:ceramic|capacitor|bypass|decoupling)?'
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
        for ent in entities:
            label = self._entity_type_to_label(ent.entity_type)
            props = {k: v for k, v in ent.properties.items() if isinstance(v, (str, int, float, bool))}
            props["name"] = ent.name

            set_clause = ", ".join([f"e.{k} = ${k}" for k in props.keys() if k != "name"])
            cypher = f"MERGE (e:{label} {{name: $name}})" + (f" SET {set_clause}" if set_clause else "")

            try:
                with driver.session() as session:
                    session.run(cypher, props)
            except Exception as e:
                logger.debug(f"写入实体失败: {e}")

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
