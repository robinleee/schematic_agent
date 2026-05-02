# PartType 标准化器规格说明

## 任务概述

实现 `etl_pipeline/part_type_standardizer.py`，将 ETL 提取的原始 PartType（如 `"SKYLAKE_CAP"`、`"CAP_PPG"`、`"RES_PPG"`）标准化为 PRD V5.0 定义的枚举类型：

```python
[MCU, PMIC, FPGA, LDO, BUCK, CONNECTOR, PASSIVE, IC, SOC, CPU, FLASH, DRAM, SENSOR, CRYSTAL, INDUCTOR, DIODE, TRANSISTOR, MOSFET, ESD, TVS, UNKNOWN]
```

## 输入

1. **BOM 文件**（可选）：CSV/Excel 格式，包含 `Description` 字段
2. **器件 Model 名**（必选）：来自 pstchip.dat 的 `PART_NAME` 或 primitive 名
3. **器件 Value**（可选）：如 `"0.1UF"`、`"10K"`

## 输出

标准化后的 `PartType` 字符串，写入 `graph_components.json`。

## 核心策略（三层降级）

### Layer 1: BOM Description 匹配（最高优先级）

如果提供了 BOM 文件，读取 `Description` 字段，通过关键词匹配映射：

```python
BOM_KEYWORDS = {
    "MCU": ["MCU", "MICROCONTROLLER", "ARM CORTEX"],
    "PMIC": ["PMIC", "POWER MANAGEMENT", "POWER IC"],
    "FPGA": ["FPGA", "FIELD PROGRAMMABLE"],
    "LDO": ["LDO", "LOW DROPOUT", "LINEAR REGULATOR"],
    "BUCK": ["BUCK", "DC-DC", "STEP DOWN", "SWITCHING REGULATOR"],
    "CONNECTOR": ["CONNECTOR", "HEADER", "CON HDR", "RECEPTACLE", "JACK"],
    "PASSIVE": ["CAPACITOR", "RESISTOR", "CAP", "RES "],  # 注意空格避免误匹配
    "FLASH": ["FLASH", "NOR FLASH", "NAND FLASH", "EEPROM"],
    "DRAM": ["DRAM", "DDR", "LPDDR", "SDRAM"],
    "CRYSTAL": ["CRYSTAL", "OSCILLATOR", "TCXO", "XTAL"],
    "INDUCTOR": ["INDUCTOR", "FERRITE BEAD", "CHOKE"],
    "DIODE": ["DIODE", "SCHOTTKY", "RECTIFIER"],
    "TRANSISTOR": ["TRANSISTOR", "BJT", "NPN", "PNP"],
    "MOSFET": ["MOSFET", "POWER MOSFET"],
    "ESD": ["ESD", "TVS", "TRANSIENT"],
    "SENSOR": ["SENSOR", "TEMPERATURE SENSOR", "ACCELEROMETER"],
}
```

匹配规则：Description（不区分大小写）包含任一关键词即可命中。

### Layer 2: Model 名规则匹配（BOM 缺失时降级）

从 Model/Primitive 名中提取特征：

```python
MODEL_PATTERNS = {
    "MCU": [r'MCU', r'MICRO', r'ARM', r'CORTEX'],
    "FPGA": [r'FPGA', r'LATTICE', r'XILINX', r'ALTERA'],
    "PMIC": [r'PMIC', r'POWER', r'TPS[0-9]', r'ACT[0-9]'],
    "LDO": [r'LDO', r'LD[0-9]', r'XC6206', r'RT9193'],
    "BUCK": [r'BUCK', r'TPS54', r'MP[0-9]', r'SY[0-9]'],
    "CONNECTOR": [r'CONN', r'HDR', r'HEADER', r'RECEPTACLE', r'JACK', r'BAT-HLD'],
    "PASSIVE": [r'^CAP[_-]', r'^RES[_-]', r'C[0-9]{4}', r'R[0-9]{4}', r'PPG_'],
    "FLASH": [r'FLASH', r'NOR', r'MT25', r'W25', r'SPI_FLASH'],
    "DRAM": [r'DDR', r'LPDDR', r'SDRAM'],
    "CRYSTAL": [r'XTAL', r'CRYSTAL', r'OSCI'],
    "ESD": [r'ESD', r'TVS'],
    "MOSFET": [r'MOSFET', r'SI[0-9]'],
}
```

注意：PASSIVE 的匹配要精确，避免把 `CAP_PPG` 误判为 CAP（电容），实际上它还是 PASSIVE。

实际上 PASSIVE 应该是兜底类型。当匹配不到其他类型时，如果 Model 名包含 CAP/RES/IND 等被动器件特征，则归类为 PASSIVE。

### Layer 3: Value 推断兜底

如果 Model 名也匹配不到，通过 Value 字段推断：

```python
VALUE_PATTERNS = {
    "PASSIVE": {
        "CAP": [r'[0-9.]+[PNUF]F', r'[0-9.]+PF', r'[0-9.]+NF', r'[0-9.]+UF'],
        "RES": [r'[0-9.]+[KMG]?$', r'[0-9.]+K$', r'[0-9.]+M$'],
        "IND": [r'[0-9.]+[UN]?H', r'[0-9.]+UH', r'[0-9.]+NH'],
    }
}
```

如果 Value 匹配电容/电阻/电感格式，归类为 PASSIVE。

## 具体实现要求

### 1. 类定义

```python
class PartTypeStandardizer:
    def __init__(self, bom_path: str = None):
        self.bom_data = self._load_bom(bom_path) if bom_path else {}
        self.stats = {"bom_hits": 0, "model_hits": 0, "value_hits": 0, "unknown": 0}
    
    def standardize(self, refdes: str, model: str, value: str = None) -> str:
        """三层降级标准化"""
        
    def get_stats(self) -> dict:
        """返回标准化统计"""
        
    def _load_bom(self, path: str) -> dict:
        """加载 BOM 文件，返回 {refdes: description} 字典"""
```

### 2. BOM 加载器

支持 CSV 和 Excel 格式：
- CSV：读取 `RefDes` 和 `Description` 列
- Excel：读取 `RefDes` 和 `Description` 列
- 如果列名不匹配，尝试常见变体：`Description`/`Desc`/`Part Description`，`RefDes`/`Ref`/`Designator`

### 3. 集成到 main_etl.py

修改 `main_etl.py`，在组装 `graph_components` 时调用标准化器：

```python
from etl_pipeline.part_type_standardizer import PartTypeStandardizer

standardizer = PartTypeStandardizer(bom_path="data/bom/BOM.csv")  # 可选

for triplet in net_topology:
    refdes = triplet['Component_RefDes']
    if refdes not in graph_components:
        primitive_name = ref_to_prim.get(refdes)
        properties = chip_library.get(primitive_name, {}).get("Properties", {})
        raw_parttype = properties.get("PART_NAME", "N/A")
        
        # 标准化 PartType
        part_type = standardizer.standardize(
            refdes=refdes,
            model=primitive_name,
            value=properties.get("VALUE", None)
        )
        
        graph_components[refdes] = {
            "RefDes": refdes,
            "Model": primitive_name,
            "Value": properties.get("VALUE", "N/A"),
            "PartType": part_type,
            "RawPartType": raw_parttype,  # 保留原始值用于调试
        }

# 输出标准化统计
print(f"PartType 标准化统计: {standardizer.get_stats()}")
```

### 4. 输出格式

`graph_components.json` 中每个器件增加：
- `PartType`: 标准化后的类型
- `RawPartType`: 原始 PART_NAME（保留用于追溯）

### 5. 单元测试

在 `part_type_standardizer.py` 底部添加 self-test：

```python
if __name__ == "__main__":
    standardizer = PartTypeStandardizer()
    
    test_cases = [
        ("C30001", "CAP_PPG_C0402_DISCRETE_0.1UF_11", "0.1UF", "PASSIVE"),
        ("R30002", "RES_PPG_R0402_DISCRETE_10K_", "10K", "PASSIVE"),
        ("U30004", "MT25QL02GCBB8E12_TPBGA24", None, "FLASH"),
        ("J70003", "HDR_2X5_M", None, "CONNECTOR"),
        ("BT6E1", "SKYLAKE_CAP_BAT-HLD-2032-TE_CR2", None, "CONNECTOR"),  # 电池座
    ]
    
    for refdes, model, value, expected in test_cases:
        result = standardizer.standardize(refdes, model, value)
        status = "✅" if result == expected else "❌"
        print(f"{status} {refdes}: {model} → {result} (expected: {expected})")
```

## 验收标准

1. **所有测试用例通过**：至少 20 个不同 Model 名的标准化测试
2. **覆盖率达标**：标准类型覆盖率 >= 90%（即 90% 的器件能被标准化为已知类型）
3. **BOM 集成可用**：如果提供 BOM 文件，优先使用 BOM Description 做匹配
4. **向后兼容**：`main_etl.py` 修改后，原有输出格式不变，只是增加 `PartType` 和 `RawPartType`
5. **统计输出**：运行后打印标准化统计，便于 Quality Guard 后续接入

## 注意事项

1. **大小写不敏感**：所有匹配逻辑都不区分大小写
2. **优先级严格**：BOM > Model > Value，一旦某层命中就不再降级
3. **UNKNOWN 兜底**：三层都匹配不到时返回 `"UNKNOWN"`，而不是原始 PART_NAME
4. **不要过度匹配**：`CAP` 作为 PASSIVE 的关键词时，要避免把 `CAPTURE` 这种词也匹配上
5. **电池座**：如 `BAT-HLD-2032-TE` 是电池座/连接器，不是被动器件

## 参考数据

项目中已有的 Model 名样例（来自真实网表）：

```
SKYLAKE_CAP_BAT-HLD-2032-TE_CR2          → CONNECTOR (电池座)
CAP_PPG_C0402_DISCRETE_0.1UF_11          → PASSIVE (电容)
RES_PPG_R0402_DISCRETE_10K_              → PASSIVE (电阻)
MT25QL02GCBB8E12_TPBGA24                 → FLASH
HDR_2X5_M                                → CONNECTOR
```

## 交付物

1. `etl_pipeline/part_type_standardizer.py`（主文件）
2. `etl_pipeline/main_etl.py` 的修改（集成标准化器）
3. 单元测试通过截图/输出
