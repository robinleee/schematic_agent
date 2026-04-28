# 统一硬件 AI 专家系统 - 技术实现方案 (V2.0 最终交付版)

## 1. 系统架构与背景
本项目旨在构建一个 Agentic GraphRAG 硬件审查与诊断系统。系统通过解析 Cadence 格式的 EDA 网表建立 Neo4j 数字孪生图谱，并结合 Milvus/Chroma 本地向量库（Datasheet 规范），利用 LangGraph 状态机驱动大语言模型（LLM）实现自动化的原理图审查与硬件故障排查。

## 2. 项目目录结构定义
代码已按以下目录结构完成重构，所有开发均基于 `hardware_ai_expert/` 根目录：

```text
hardware_ai_expert/
├── data/
│   ├── netlist_Beet7/          # 原始 EDA 数据 (pstxnet.dat, pstchip.dat, pstxprt.dat)  [已就位]
│   ├── datasheets/             # 用于 RAG 向量化的 PDF 数据手册                          [待导入]
│   └── output/                 # ETL 产物 (graph_components.json, topology_triplets.json) [已生成]
├── etl_pipeline/               # 数据解析与注入层
│   ├── __init__.py             # Python 包标记
│   ├── chip_parser.py          # pstchip.dat 解析器 (CadenceChipParser)                  [已完成]
│   ├── prt_parser.py           # pstxprt.dat 解析器 (CadencePrtParser)                   [已完成]
│   ├── net_parser.py           # pstxnet.dat 解析器 (CadenceNetlistParser)               [已完成]
│   ├── main_etl.py             # 主解析融合脚本 (Pydantic 校验 + Neo4j 直接注入)         [已优化]
│   ├── load_to_neo4j.py        # 节点属性注入 (已集成到 main_etl.py)                      [已废弃]
│   ├── load_topology.py        # 拓扑关系注入 (已集成到 main_etl.py)                     [已废弃]
│   └── quality_checker.py       # 【新增】数据质量检查模块                                  [待开发]
├── agent_system/               # 核心 Agent 逻辑层
│   ├── __init__.py             # Python 包标记
│   ├── graph_tools.py          # Neo4j Cypher 查询工具箱 (带上下文防爆截断) 【详细设计: Graph_Tools_Design.md】
│   ├── knowledge_router.py     # Tier 1-3 分级 RAG 检索路由 【详细设计: Knowledge_Router_Design.md】
│   ├── agent_core.py           # LangGraph 状态机与 ReAct 节点编排 【详细设计: Agent_Core_Design.md】
│   ├── review_rules.py         # 审查规则引擎 (三层架构: 模板+配置+知识) 【详细设计: Review_Rules_Design.md】
│   ├── design_guide_processor.py # 用户 Design Guide 上传与知识提取 【详细设计: Design_Guide_Processor.md】
│   ├── datasheet_processor.py  # Qianfan-OCR Datasheet 解析                               [待开发]
│   ├── datasheet_linker.py     # Datasheet 与图谱关联                                      [待开发]
│   ├── schemas.py              # Pydantic 数据模型 【详细设计: Schemas_Design.md】
├── web_ui/
│   ├── __init__.py             # Python 包标记
│   └── app.py                  # Streamlit 交互界面与 HITL 专家反馈闭环                   [待开发]
├── requirements.txt            # 核心依赖清单                                             [已创建]
└── .env                        # 环境变量 (Neo4j URI/密码, LLM API Base 等)               [已创建]
## 3. 核心依赖栈
大模型底座: vllm, langchain, langgraph, openai (兼容接口)

数据库驱动: neo4j, chromadb (或 pymilvus)

数据处理与校验: pydantic, pandas

前端交互: streamlit

## 4. 核心模块开发规范与详细要求
4.1 数据底座层 (etl_pipeline/main_etl.py) - 【已优化】

#### 4.1.1 优化后的 ETL 流程

**原流程问题**: ETL → JSON 文件 → 手动导入 Neo4j，增加了环节且无法保证数据一致性。

**优化后的流程**:

```
┌─────────────────────────────────────────────────────────────────────┐
│                      优化后的 ETL 流程                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                      │
│  Cadence 文件 (pstxnet.dat, pstxprt.dat, pstchip.dat)             │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    ETL 解析层                                     │ │
│  │  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │ │
│  │  │ NetParser  │ │ PrtParser  │ │ ChipParser  │               │ │
│  │  └──────┬──────┘ └──────┬──────┘ └──────┬──────┘               │ │
│  │         │                │                │                      │ │
│  │         └────────────────┼────────────────┘                      │ │
│  │                          ▼                                       │ │
│  │              数据融合与属性补充                                    │ │
│  │              (Pin Type, Voltage Level)                           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    Pydantic 校验层                               │ │
│  │                                                                  │ │
│  │  1. ComponentNode.model_validate()  ← 验证必填字段              │ │
│  │  2. TopologyTriplet.model_validate()                            │ │
│  │  3. 缺失字段 → error.log + 拒绝入库                             │ │
│  │                                                                  │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                    ┌─────────┴─────────┐                            │
│                    ▼                   ▼                            │
│           ┌──────────────┐    ┌──────────────┐                     │
│           │  Valid Data  │    │ Invalid Data │                     │
│           │   (继续)     │    │ (写入日志)   │                     │
│           └──────┬───────┘    └──────────────┘                     │
│                  ▼                                                 │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    Neo4j 直接注入                                │ │
│  │                                                                  │ │
│  │  UNWIND + MERGE 批量注入                                         │ │
│  │  (与 ETL 同步完成，无需单独执行 load 脚本)                       │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                              │                                       │
│                              ▼                                       │
│  ┌─────────────────────────────────────────────────────────────────┐ │
│  │                    数据质量检查 (可选)                           │ │
│  │                                                                  │ │
│  │  1. 完整性检查: RefDes/Model/Value 是否完整                     │ │
│  │  2. 连通性检查: 是否存在孤立网络/器件                            │ │
│  │  3. 一致性检查: Pin 数量与定义是否匹配                           │ │
│  └─────────────────────────────────────────────────────────────────┘ │
│                                                                      │
└─────────────────────────────────────────────────────────────────────┘
```

#### 4.1.2 Pin Type 属性解析

**问题**: Pin 的 Type (POWER/SIGNAL/GND) 无法从 pstxnet.dat 直接获取。

**解决方案**: 从 pstchip.dat 的 PINUSE 属性解析:

```python
# Pin Type 映射规则
PIN_TYPE_MAPPING = {
    "POWER": "POWER",      # 电源引脚
    "INPUT": "SIGNAL",     # 输入信号
    "OUTPUT": "SIGNAL",    # 输出信号
    "BIDIR": "SIGNAL",     # 双向信号
    "GROUND": "GND",       # 地引脚
    "NC": "NC",           # 未连接
    "UNSPEC": "SIGNAL",    # 未指定默认为信号
}

# 从 pstchip.dat 解析 Pin Type
def parse_pin_type(pin_use: str) -> str:
    """将 PINUSE 转换为 Pin.Type"""
    return PIN_TYPE_MAPPING.get(pin_use.upper(), "SIGNAL")
```

#### 4.1.3 Net VoltageLevel 解析

**问题**: 网络电压等级无法直接获取，需要推断。

**解决方案**: 多策略电压等级推断:

```python
# 电压等级推断策略
VOLTAGE_PATTERNS = [
    # 显式模式匹配
    (r'\b1V8\b|\b1\.8V\b', "1V8"),
    (r'\b3V3\b|\b3\.3V\b', "3V3"),
    (r'\b5V0\b|\b5\.0V\b', "5V0"),
    (r'\b12V\b', "12V"),
    # 隐式推断（通过连接的 Power 引脚）
    # 当网络连接到已知电压的 IC 引脚时继承该电压
]

def infer_voltage_level(net_name: str, connected_components: list) -> str:
    """推断网络电压等级"""

    # 策略1: 网络名称模式匹配
    for pattern, voltage in VOLTAGE_PATTERNS:
        if re.search(pattern, net_name, re.IGNORECASE):
            return voltage

    # 策略2: 通过连接的器件推断
    # 如果网络连接到了已知电压的 IC (如 LDO 输出)，继承该电压
    for comp in connected_components:
        if comp.get("inferred_voltage"):
            return comp["inferred_voltage"]

    return "UNKNOWN"  # 无法推断
```

#### 4.1.4 Pydantic 校验与错误处理

```python
from pydantic import BaseModel, field_validator, ValidationError
import logging

logger = logging.getLogger(__name__)
error_log_path = "./data/output/etl_errors.log"

class ComponentNode(BaseModel):
    """器件节点模型"""
    RefDes: str
    Model: str | None = None
    Value: str | None = None
    PartType: str | None = None
    MPN: str | None = None
    VoltageRange: str | None = None

    @field_validator('RefDes')
    @classmethod
    def validate_refdes(cls, v: str) -> str:
        # 验证 RefDes 格式
        if not re.match(r'^[A-Z]+\d+', v):
            raise ValueError(f"Invalid RefDes format: {v}")
        return v

class TopologyTriplet(BaseModel):
    """拓扑三元组模型"""
    Net_Name: str
    Component_RefDes: str
    Pin_Number: str
    Pin_Type: str = "SIGNAL"
    VoltageLevel: str = "UNKNOWN"

    @field_validator('Component_RefDes')
    @classmethod
    def validate_refdes(cls, v: str) -> str:
        if not re.match(r'^[A-Z]+\d+', v):
            raise ValueError(f"Invalid Component_RefDes: {v}")
        return v

# 校验并记录错误
def validate_and_load(data: list, model_class: type) -> tuple[list, list]:
    """校验数据，返回有效数据和错误列表"""
    valid_data = []
    errors = []

    for idx, item in enumerate(data):
        try:
            validated = model_class.model_validate(item)
            valid_data.append(validated)
        except ValidationError as e:
            errors.append({
                "index": idx,
                "data": item,
                "errors": e.errors()
            })
            logger.error(f"Validation error at index {idx}: {e}")

    # 写入错误日志
    if errors:
        with open(error_log_path, "a") as f:
            f.write(json.dumps(errors, ensure_ascii=False, indent=2))

    return valid_data, errors
```

4.2 Neo4j 图谱 Schema 定义 - 【数据模型基础】

为实现 Datasheet 规范与原理图图谱的关联，必须定义清晰的图谱 Schema。以下为推荐的节点与关系类型定义：

```cypher
// ========== 节点类型定义 ==========

// 元件节点 (:Component)
// 核心属性：RefDes (唯一标识), Model (库模型), Value (值), PartType (类型)
// 关联属性：从 Datasheet 提取的规格参数
(:Component {
    RefDes: String,              // 位号，如 "U30004" (主键)
    Model: String,                // 库模型名
    Value: String,               // 器件值，如 "33Ω", "0.1uF"
    PartType: String,            // 器件类型，如 "RES", "CAP", "IC"
    MPN: String,                 // 厂商型号 (关键关联键，用于 RAG 检索)
    VoltageRange: String,        // 工作电压范围，如 "1.7V-2.0V"
    MaxCurrent_mA: Integer,      // 最大工作电流
    OperatingTemp: String,       // 工作温度范围
    Package: String,             // 封装类型，如 "BGA24"
    SpecSource: String           // 规格来源："Datasheet", "Manual", "Calculated"
})

// 引脚节点 (:Pin)
(:Pin {
    Number: String,              // 引脚编号
    Id: String,                  // 唯一标识：RefDes + "_" + Number
    Type: String                 // 引脚类型：POWER, SIGNAL, GND, NC
})

// 网络节点 (:Net)
(:Net {
    Name: String,                // 网络名称 (主键)
    VoltageLevel: String,        // 电压等级，如 "1V8", "3V3", "5V0"
    NetType: String              // 网络类型：POWER, SIGNAL, GND, NC
})

// 审查规则节点 (:ReviewRule)
(:ReviewRule {
    id: String,                  // 规则编号，如 "POWER_DECAP"
    description: String,         // 规则描述
    severity: String,             // 严重程度：ERROR, WARNING, INFO
    query_template: String       // Cypher 查询模板
})

// 白名单节点 (:ReviewWhitelist)
(:ReviewWhitelist {
    rule: String,                // 规则 ID
    refdes: String,              // 豁免的器件位号
    status: String,             // 状态：IGNORE, APPROVED
    reason: String,              // 豁免原因
    added_by: String,            // 添加人
    added_at: String             // 添加时间
})

// ========== 关系类型定义 ==========

// 器件拥有引脚
(:Component)-[:HAS_PIN]->(:Pin)

// 引脚连接到网络
(:Pin)-[:CONNECTS_TO]->(:Net)

// 器件关联审查规则
(:Component)-[:SUBJECT_TO]->(:ReviewRule)

// ========== 索引规范 ==========
CREATE CONSTRAINT refdes_unique IF NOT EXISTS FOR (c:Component) REQUIRE c.RefDes IS UNIQUE;
CREATE CONSTRAINT pin_id_unique IF NOT EXISTS FOR (p:Pin) REQUIRE p.Id IS UNIQUE;
CREATE CONSTRAINT net_name_unique IF NOT EXISTS FOR (n:Net) REQUIRE n.Name IS UNIQUE;
```

4.3 审查规则库 (agent_system/review_rules.py) - 【原理图审查规则定义】

**推荐方案**: 采用三层规则引擎架构 (Template + Config + Knowledge)

详细设计请参考: [Review_Rules_Design.md](./Review_Rules_Design.md)

#### 4.3.1 三层架构概览

```
┌─────────────────────────────────────────────────────────────────────────┐
│                        三层规则引擎架构                                    │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                          │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 1: 规则模板层 (Template)                  │   │
│  │  定义通用的检查逻辑模板，参数化配置                                 │   │
│  │  例: decap_check, pullup_check, esd_check                       │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 2: 规则配置层 (Config)                   │   │
│  │  YAML/JSON 定义规则实例，支持参数覆盖                              │   │
│  │  例: POWER_1V8_DECAP, I2C_PULLUP                                │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                    │                                    │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │                    Layer 3: 知识规则层 (Knowledge)                 │   │
│  │  从 Datasheet/Design Guide 自动提取规则（AI 驱动）                 │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                          │
└─────────────────────────────────────────────────────────────────────────┘
```

#### 4.3.2 快速参考 - 规则模板类型

| 模板 ID | 名称 | 典型参数 |
|---------|------|----------|
| decap_check | 电源去耦电容检查 | voltage_level, min_count, required_values |
| pullup_check | 上拉电阻检查 | net_patterns, min_ohm, max_ohm |
| esd_check | ESD 保护检查 | interface_types, max_capacitance_pf |
| voltage_check | 电压等级一致性检查 | voltage_levels |

#### 4.3.3 规则配置示例 (YAML)

```yaml
# config/rules/default_rules.yaml
rules:
  - id: POWER_1V8_DECAP
    template_id: decap_check
    severity: WARNING
    params:
      voltage_level: "1V8"
      min_count: 1
      required_values: ["0.1uF"]

  - id: I2C_STD_PULLUP
    template_id: pullup_check
    severity: ERROR
    params:
      net_patterns: ["I2C", "SCL", "SDA"]
      min_ohm: 2200
      max_ohm: 10000
```

详细模板定义、配置管理、AI 规则提取请参阅 [Review_Rules_Design.md](./Review_Rules_Design.md)

4.4 Datasheet 与原理图图谱的关联机制 - 【核心关联逻辑】

实现 Datasheet 规范与原理图图谱的深度关联，是系统实现自动审查与故障诊断的关键。

#### 4.4.1 数据准备阶段

```
┌─────────────────────────────────────────────────────────────────────┐
│                         数据准备阶段                                 │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  1. Datasheet PDF ──解析(PDFplumber/PyMuPDF)──→ 结构化文本          │
│                              │                                       │
│                              ▼                                       │
│  2. 文本切片 ──Embedding(Model: text2vec-base-chinese)──→ 向量      │
│                              │                                       │
│                              ▼                                       │
│  3. 向量 + 元数据 ──存储──→ ChromaDB                                 │
│                              │                                       │
│                              ▼                                       │
│  4. MPN/器件型号 ──关联──→ Neo4j Component 节点                     │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

#### 4.4.2 关联查询流程

```python
# agent_system/datasheet_linker.py

def link_datasheet_to_component(component_refdes: str) -> dict:
    """
    建立器件节点与 Datasheet 的关联
    核心关联键: MPN (Manufacturer Part Number)
    """
    # 1. 从 Neo4j 获取器件信息
    component_info = neo4j_query(f"""
        MATCH (c:Component {{RefDes: '{component_refdes}'}})
        RETURN c.RefDes, c.Model, c.Value, c.PartType, c.MPN
    """)
    
    if not component_info:
        return {"status": "NOT_FOUND"}
    
    mpn = component_info[0].get("c.MPN")
    
    # 2. 查询本地 ChromaDB 获取 Datasheet 片段
    datasheet_chunks = chromadb.query(
        collection_name="datasheets",
        query_texts=[f"{mpn} specifications pinout electrical characteristics"],
        n_results=5
    )
    
    # 3. 提取关键规格参数
    specs = extract_specs_from_chunks(datasheet_chunks)
    
    # 4. 更新 Neo4j 节点，补充规格属性
    neo4j_query(f"""
        MATCH (c:Component {{RefDes: '{component_refdes}'}})
        SET c.VoltageRange = '{specs.get('voltage_range')}',
            c.MaxCurrent_mA = {specs.get('max_current', 0)},
            c.OperatingTemp = '{specs.get('temp_range')}',
            c.SpecSource = 'Datasheet'
    """)
    
    return {
        "status": "LINKED",
        "mpn": mpn,
        "specs": specs
    }
```

#### 4.4.3 Qianfan-OCR Datasheet 解析方案

**Qianfan-OCR** 是百度千帆发布的端到端文档智能模型（4B 参数），在 OmniDocBench v1.5 上取得 93.12 分，端到端模型排名第一。该模型能够直接从 PDF 图像提取 Markdown 内容和结构化数据，非常适合用于 Datasheet 解析。

**模型特点**：
- 端到端 VLM 架构，统一文档解析、版面分析、文字识别、语义理解
- 支持表格提取、图表理解、文档问答（Document QA）
- 单张 A100 GPU, W8A8 量化, 吞吐量 1.024 页/秒
- 开源权重: `baidu/Qianfan-OCR` (HuggingFace)

##### 4.4.3.1 依赖安装

```bash
# 安装千帆 SDK
pip install qianfan

# 安装 vLLM 用于本地推理
pip install vllm

# 安装 PDF 处理依赖
pip install pymupdf pydantic
```

##### 4.4.3.2 目录结构更新

```text
agent_system/
├── __init__.py
├── graph_tools.py          # Neo4j Cypher 查询工具箱
├── knowledge_router.py     # Tier 1-3 分级 RAG 检索路由
├── datasheet_processor.py  # 【新增】Qianfan-OCR Datasheet 解析
├── datasheet_linker.py     # Datasheet 与图谱关联
├── review_rules.py         # 审查规则库
└── agent_core.py           # LangGraph 状态机
```

##### 4.4.3.3 核心代码实现

```python
# agent_system/datasheet_processor.py

import fitz  # PyMuPDF
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from vllm import LLM

class ComponentSpec(BaseModel):
    """元器件规格参数模型"""
    mpn: str = Field(description="厂商型号")
    voltage_range: Optional[str] = Field(None, description="工作电压范围")
    max_current_ma: Optional[int] = Field(None, description="最大电流(mA)")
    operating_temp: Optional[str] = Field(None, description="工作温度")
    package: Optional[str] = Field(None, description="封装")
    pin_count: Optional[int] = Field(None, description="引脚数")
    description: Optional[str] = Field(None, description="功能描述")


class PinDefinition(BaseModel):
    """引脚定义模型"""
    pin_number: str = Field(description="引脚编号")
    pin_name: str = Field(description="引脚名称")
    pin_function: str = Field(description="引脚功能")
    pin_type: str = Field(description="引脚类型: POWER/SIGNAL/GND/NC")


class QianfanOCRProcessor:
    """
    基于 Qianfan-OCR 的 Datasheet 解析器
    模型: baidu/Qianfan-OCR
    """

    def __init__(
        self,
        model_path: str = "baidu/Qianfan-OCR",
        tensor_parallel_size: int = 1,
        gpu_memory_utilization: float = 0.9
    ):
        self.llm = LLM(
            model=model_path,
            tensor_parallel_size=tensor_parallel_size,
            gpu_memory_utilization=gpu_memory_utilization,
            dtype="float16"
        )
        print(f"Qianfan-OCR 加载完成，模型路径: {model_path}")

    def pdf_to_images(self, pdf_path: str, dpi: int = 300) -> list:
        """
        将 PDF 页面渲染为图像

        Args:
            pdf_path: PDF 文件路径
            dpi: 渲染分辨率，默认 300 DPI

        Returns:
            页面图像列表 (PIL.Image)
        """
        from PIL import Image
        import io

        images = []
        doc = fitz.open(pdf_path)

        for page_num in range(len(doc)):
            page = doc.load_page(page_num)
            # 高分辨率渲染以保留细节
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            img_data = pix.tobytes("png")
            img = Image.open(io.BytesIO(img_data))
            images.append(img)

        doc.close()
        print(f"PDF 渲染完成: {pdf_path}, 共 {len(images)} 页")
        return images

    def extract_page_content(self, image, page_num: int) -> str:
        """
        使用 Qianfan-OCR 提取单页内容

        Args:
            image: 页面图像 (PIL.Image)
            page_num: 页码

        Returns:
            Markdown 格式的页面内容
        """
        # 构建多模态输入
        response = self.llm.chat([
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": """
你是电子元器件 Datasheet 解析专家。请将这张页面转换为 Markdown 格式，保留：
1. 标题和章节结构
2. 表格内容（转换为 Markdown 表格）
3. 列表和要点
4. 重要参数和规格值（保留原始数值和单位）

请直接输出 Markdown，不要添加解释。
"""}
                ]
            }
        ])

        return response

    def extract_specifications(self, image) -> ComponentSpec:
        """
        提取器件规格参数

        Args:
            image: 页面图像

        Returns:
            ComponentSpec 对象
        """
        response = self.llm.chat([
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": """
从这张 Datasheet 页面中提取器件的规格参数。以 JSON 格式输出：
{
    "mpn": "器件型号",
    "voltage_range": "工作电压范围，如 1.8V-3.6V",
    "max_current_ma": 最大工作电流(单位mA),
    "operating_temp": "工作温度范围",
    "package": "封装类型",
    "pin_count": 引脚数量,
    "description": "器件功能描述"
}
如果没有找到某项参数，设为 null。不要输出其他内容。
"""}
                ]
            }
        ])

        import json
        from pydantic import ValidationError

        try:
            data = json.loads(response)
            return ComponentSpec(**data)
        except (json.JSONDecodeError, ValidationError) as e:
            print(f"规格提取失败: {e}, 原始响应: {response}")
            return ComponentSpec(mpn="UNKNOWN")

    def extract_pinout_table(self, image) -> list[PinDefinition]:
        """
        提取引脚定义表

        Args:
            image: 页面图像

        Returns:
            引脚定义列表
        """
        response = self.llm.chat([
            {
                "role": "user",
                "content": [
                    {"type": "image", "image": image},
                    {"type": "text", "text": """
从这张 Datasheet 页面中提取引脚定义表。以 JSON 数组格式输出：
[
    {"pin_number": "引脚编号", "pin_name": "引脚名称", "pin_function": "功能描述", "pin_type": "POWER/SIGNAL/GND/NC"},
    ...
]
如果页面上没有引脚定义表，返回空数组 []。不要输出其他内容。
"""}
                ]
            }
        ])

        import json
        try:
            data = json.loads(response)
            if isinstance(data, list):
                return [PinDefinition(**item) for item in data]
            return []
        except (json.JSONDecodeError, Exception) as e:
            print(f"引脚定义提取失败: {e}")
            return []

    def process_datasheet(self, pdf_path: str) -> dict:
        """
        完整处理一个 Datasheet PDF

        Args:
            pdf_path: PDF 文件路径

        Returns:
            解析结果字典
        """
        print(f"开始处理 Datasheet: {pdf_path}")

        # 1. PDF 转图像
        images = self.pdf_to_images(pdf_path)

        results = {
            "file": pdf_path,
            "total_pages": len(images),
            "specifications": None,
            "pinout_tables": [],
            "markdown_content": []
        }

        # 2. 处理每一页
        for page_num, image in enumerate(images):
            print(f"  处理第 {page_num + 1}/{len(images)} 页...")

            # 提取 Markdown 内容（用于 RAG 向量化）
            markdown = self.extract_page_content(image, page_num)
            results["markdown_content"].append(markdown)

            # 尝试提取规格参数（通常在首页）
            if page_num == 0:
                specs = self.extract_specifications(image)
                results["specifications"] = specs.model_dump()

            # 尝试提取引脚定义表（通常在引脚定义页面）
            pinout = self.extract_pinout_table(image)
            if pinout:
                results["pinout_tables"].extend([
                    {"page": page_num + 1, **p.model_dump()}
                    for p in pinout
                ])

        print(f"Datasheet 处理完成: {results['total_pages']} 页")
        return results
```

##### 4.4.3.4 Datasheet 导入流水线

```python
# agent_system/datasheet_pipeline.py

from pathlib import Path
from agent_system.datasheet_processor import QianfanOCRProcessor
import chromadb
from neo4j import GraphDatabase

class DatasheetImportPipeline:
    """
    Datasheet 导入完整流水线：
    PDF → Qianfan-OCR 解析 → ChromaDB 向量存储 → Neo4j 规格关联
    """

    def __init__(self):
        self.ocr_processor = QianfanOCRProcessor()
        self.chroma_client = chromadb.Client()
        self.datasheet_collection = self.chroma_client.get_or_create_collection(
            name="datasheets",
            metadata={"description": "Datasheet 向量库"}
        )

    def import_directory(self, datasheet_dir: str):
        """
        批量导入目录下的所有 Datasheet PDF

        Args:
            datasheet_dir: Datasheet 目录路径
        """
        datasheet_path = Path(datasheet_dir)
        pdf_files = list(datasheet_path.glob("**/*.pdf"))

        print(f"找到 {len(pdf_files)} 个 PDF 文件")

        for pdf_file in pdf_files:
            try:
                self.import_single_pdf(str(pdf_file))
            except Exception as e:
                print(f"处理失败: {pdf_file}, 错误: {e}")

    def import_single_pdf(self, pdf_path: str):
        """
        导入单个 PDF 并关联到图谱
        """
        # 1. Qianfan-OCR 解析
        result = self.ocr_processor.process_datasheet(pdf_path)

        # 2. 提取 MPN 作为 ChromaDB 元数据
        mpn = result["specifications"]["mpn"] if result["specifications"] else Path(pdf_path).stem

        # 3. 向量存储到 ChromaDB（用于 RAG 检索）
        for page_num, markdown in enumerate(result["markdown_content"]):
            self.datasheet_collection.add(
                documents=[markdown],
                metadatas=[{
                    "source": pdf_path,
                    "page": page_num + 1,
                    "mpn": mpn
                }],
                ids=[f"{mpn}_page_{page_num + 1}"]
            )

        # 4. 提取规格参数（用于 Neo4j 节点更新）
        if result["specifications"]:
            self._update_neo4j_component(mpn, result["specifications"])

        # 5. 提取引脚定义（用于 Neo4j Pin 节点更新）
        if result["pinout_tables"]:
            self._update_neo4j_pins(mpn, result["pinout_tables"])

        print(f"导入完成: {mpn}")

    def _update_neo4j_component(self, mpn: str, specs: dict):
        """
        通过 MPN 匹配 Neo4j 节点并更新规格属性
        """
        # 注意：实际使用时需要连接 Neo4j
        # 此处仅示例逻辑
        pass

    def _update_neo4j_pins(self, mpn: str, pinout_tables: list):
        """
        更新引脚定义
        """
        pass
```

##### 4.4.3.5 资源需求与部署

| 配置项 | 要求 |
|--------|------|
| **GPU** | 单卡 A100 40GB 或等效显存 (≥20GB) |
| **内存** | ≥32GB CPU 内存 |
| **存储** | 模型权重约 8GB |
| **推理吞吐** | ~1 页/秒 (A100, W8A8 量化) |

**部署方式**：

```bash
# 方式1: 直接使用 vLLM
python -m vllm.entrypoints.openai.api_server \
    --model baidu/Qianfan-OCR \
    --dtype float16 \
    --gpu-memory-utilization 0.9

# 方式2: 通过千帆平台 API 调用
export QIANFAN_ACCESS_KEY="your_access_key"
export QIANFAN_SECRET_KEY="your_secret_key"
```

4.5 图谱工具层 (agent_system/graph_tools.py) - 【核心开发】
将复杂的 Cypher 查询封装为带有 Type Hint 的 Python 函数（LangChain Tools）。必须实现防爆截断机制。

截断装饰器 (@graph_result_truncator):
监控底层 Cypher 返回的数据条目数。若 count > 50，强制阻断并向 LLM 返回报错提示（如："查询结果过大，存在 OOM 风险，请修改 Cypher 增加 WHERE 限制条件后重试"），迫使 LLM 缩小检索范围。

核心 Tool 签名:

query_component_attributes(refdes: str) -> dict: 查询单颗器件的容值、阻值、耐压等参数。

trace_shortest_path(source: str, target: str, avoid_nets: list = ['GND', 'VCC']) -> list: 追踪两颗芯片间的物理信号链路（使用 shortestPath 算法，必须在 Cypher 中排除公共网络防止穿透）。

find_connected_peripherals(center_refdes: str, radius: int = 2) -> list: 查找特定 IC 周边的被动器件。

4.6 检索路由层 (agent_system/knowledge_router.py) - 【核心开发】
实现解决冷门芯片"知识盲区"的三级降级检索（Tiered Routing）。

工具签名: search_hardware_specs(mpn: str, query: str) -> str

内部执行逻辑:

Tier 1 (本地 RAG): 查询本地 ChromaDB/Milvus 中的 Datasheet 切片。若有高置信度结果，直接返回。

Tier 2 (内网 API - 预留): 若 Tier 1 未命中，请求公司内部 PLM 系统。

Tier 3 (脱敏公网 API): 仅携带型号（MPN），剥离所有电路网络上下文，调用外部 API（如 Octopart）获取引脚定义与极限参数，并自动缓存回本地 Tier 1 数据库。

4.7 Agent 编排层 (agent_system/agent_core.py) - 【核心开发】
放弃简单的 ReAct，强制使用 LangGraph 状态机来管理多轮复杂推理，避免死循环查询。

**详细设计文档**: 请参考 [Agent_Core_Design.md](./Agent_Core_Design.md)

AgentState 分层架构:

```
BaseAgentState (基础状态)
├── messages: 对话历史与动作记录
├── tool_call_count: 计数器
├── execution_trace: 执行轨迹
├── context: 共享上下文
└── error_message: 错误信息

        ↓

┌───────────────┬───────────────┬───────────────┐
│  ReviewState  │ DiagnosisState│  QueryState   │
│  (审查状态)    │ (诊断状态)     │ (查询状态)    │
├───────────────┼───────────────┼───────────────┤
│ violations[]  │ hypotheses[]  │ query_result  │
│ selected_rules│ visited_nodes  │ confidence    │
│ review_scope  │ test_results  │ sources[]     │
└───────────────┴───────────────┴───────────────┘
```

节点路由流转: 建立 Reasoning Node（大模型思考）与 Tool Execution Node，通过条件边判定是否输出最终诊断报告。

4.8 交互前端与反馈闭环 (web_ui/app.py) - 【核心开发】
基础界面: 左侧展示用户输入的报错日志或审查指令，右侧以折叠面板展示 Agent 的 Thought -> Action -> Observation 执行流。

Human-in-the-Loop 专家反馈闭环: 针对系统输出的"违规报错"，提供【忽略并加入白名单】按钮。触发后，前端调用接口将该规则（如 {"rule": "I2C_PULLUP", "refdes": "R30898", "status": "IGNORE"}）作为 (:ReviewWhitelist) 节点永久写入 Neo4j。Agent 下次调用查询工具前，强制在 Cypher 中联合过滤白名单。

4.9 原理图审查工作流 (Schema Review Workflow)

系统通过以下流程实现自动化原理图审查：

```
用户输入：审查指令（如 "检查所有 1.8V 电源网络的去耦电容配置"）
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│                          原理图审查流程                                 │
├───────────────────────────────────────────────────────────────────────┤
│  Step 1: 图谱定位 - 定位目标网络与器件                                 │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 1.1 查询所有 1.8V 相关网络                                        │  │
│  │     Cypher: MATCH (n:Net) WHERE n.Name CONTAINS '1V8'            │  │
│  │                                                                     │  │
│  │ 1.2 获取连接到这些网络的 IC 器件                                    │  │
│  │     Cypher: MATCH (ic:Component)-[:HAS_PIN]->(p)-[:CONNECTS_TO]-> │  │
│  │              (n:Net) WHERE n.Name CONTAINS '1V8'                  │  │
│  │              AND ic.PartType IN ['IC', 'MCU', 'FPGA']             │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                              ▼                                       │
│  Step 2: Datasheet 检索 - 获取规格要求                                 │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 2.1 提取 IC 型号 (MPN): "MT25QU256ABA8E12"                        │  │
│  │                                                                     │  │
│  │ 2.2 RAG 查询:                                                       │  │
│  │     search_hardware_specs(                                         │  │
│  │         mpn="MT25QU256ABA8E12",                                    │  │
│  │         query="decoupling capacitor requirements power supply"     │  │
│  │     )                                                              │  │
│  │     → 返回: "每个电源引脚至少需要 0.1µF + 可选 10µF 钽电容"         │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                              ▼                                       │
│  Step 3: 对比分析 - 检查实际配置                                       │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 3.1 查询每个电源引脚连接的去耦电容                                   │  │
│  │     Cypher: MATCH (p:Pin)-[:CONNECTS_TO]->(n:Net)<-[:CONNECTS_TO]- │  │
│  │              (cap:Component)                                      │  │
│  │     WHERE n.Name = 'VDA_CSIRX0_1_1V8'                             │  │
│  │       AND cap.PartType CONTAINS 'CAP'                             │  │
│  │                                                                     │  │
│  │ 3.2 对比分析                                                        │  │
│  │     - Datasheet 要求: 每个电源引脚 0.1µF × 1                       │  │
│  │     - 实际设计: 0.1µF × 2 (Pin AH28, AH27 共享)                    │  │
│  │                                                                     │  │
│  │ 3.3 输出审查结果                                                    │  │
│  │     ✅ 审查通过 或 ⚠️ 去耦电容数量/容值不符合要求                    │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

4.10 故障排查工作流 (Fault Diagnosis Workflow)

系统通过以下流程实现故障诊断：

```
用户输入：故障现象（如 "USB 接口无法识别设备"）
                │
                ▼
┌───────────────────────────────────────────────────────────────────────┐
│                         故障排查流程                                   │
├───────────────────────────────────────────────────────────────────────┤
│  Step 1: 信号路径追踪 - 定位故障相关器件                                │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 1.1 定位 USB 接口连接器                                           │  │
│  │     Cypher: MATCH (c:Component)                                  │  │
│  │     WHERE c.RefDes STARTS WITH 'J'                               │  │
│  │       AND c.PartType CONTAINS 'USB'                               │  │
│  │                                                                     │  │
│  │ 1.2 追踪信号路径 (USB_D+, USB_D-, VBUS, GND)                       │  │
│  │     Cypher: MATCH path = shortestPath(                           │  │
│  │              (c1:Component {RefDes: 'J60001'})                    │  │
│  │              -[:HAS_PIN|CONNECTS_TO*1..10]-                      │  │
│  │              (c2:Component {PartType: 'USB_HUB'})                 │  │
│  │             )                                                    │  │
│  │     RETURN path                                                 │  │
│  │                                                                     │  │
│  │ 1.3 提取路径上的关键器件 (ESD保护、限流电阻、共模电感)              │  │
│  │     分析: R60470 (限流), CR20001 (ESD二极管)                       │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                              ▼                                       │
│  Step 2: Datasheet 知识检索 - 获取器件规格与故障模式                     │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 2.1 提取路径器件 MPN                                              │  │
│  │     - CR20001: "1N4148WSQ-7-F"                                    │  │
│  │     - Datasheet 查询: "1N4148WS USB high speed compatibility"    │  │
│  │                                                                     │  │
│  │ 2.2 获取故障知识                                                  │  │
│  │     search_hardware_specs(                                       │  │
│  │         mpn="1N4148WSQ-7-F",                                     │  │
│  │         query="typical failure modes USB application             │  │
│  │               parasitic capacitance data sheet"                  │  │
│  │     )                                                            │  │
│  │     → 返回: "1N4148WS 结电容 2pF @ 1MHz，不适合 USB 3.0 高速信号"  │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                              │                                       │
│                              ▼                                       │
│  Step 3: 根因推理与诊断报告                                            │
│  ┌─────────────────────────────────────────────────────────────────┐  │
│  │ 3.1 综合分析                                                      │  │
│  │     - 信号路径: USB接口 → CR20001(ESD) → R60470(限流) → PHY芯片   │  │
│  │     - 规格分析: CR20001 结电容 2pF @ 1MHz                         │  │
│  │     - 问题判定: USB 3.0 高速信号(480Mbps) 要求电容 < 0.5pF         │  │
│  │                                                                     │  │
│  │ 3.2 输出诊断报告                                                   │  │
│  │     ┌─────────────────────────────────────────────────────────┐   │  │
│  │     │ 🔴 根因: CR20001 ESD 器件选型不当                          │   │  │
│  │     │ 📋 依据: 结电容 2pF 超出 USB 3.0 高速信号要求(<0.5pF)      │   │  │
│  │     │ 💡 建议: 替换为 USBLC6-2SC6 (电容 0.35pF) 或 RCLAMP0521P   │   │  │
│  │     └─────────────────────────────────────────────────────────┘   │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└───────────────────────────────────────────────────────────────────────┘
```

## 5. 安全与性能基线
Neo4j 权限隔离: 供 graph_tools.py（Agent 运行环境）使用的 Neo4j 账号必须为只读权限 (Read-Only)，防止 LLM 幻觉生成 DELETE 语句删库。ETL 注入脚本使用高权账号。

响应耗时要求: Neo4j 查询必须命中索引，单次 shortestPath 查询耗时需控制在 500ms 内。