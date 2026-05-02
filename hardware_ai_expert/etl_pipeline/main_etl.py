from etl_pipeline.chip_parser import CadenceChipParser
from etl_pipeline.prt_parser import CadencePrtParser
from etl_pipeline.net_parser import CadenceNetlistParser
from etl_pipeline.part_type_standardizer import PartTypeStandardizer
from etl_pipeline.quality_guard import QualityGuard, QualityGuardException
import os
import json

# 定位项目根目录 (hardware_ai_expert/)
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT_DIR, "data", "netlist_Beet7")
OUTPUT_DIR = os.path.join(ROOT_DIR, "data", "output")

# 1. 读取三大文件内容 (使用latin-1编码以兼容非UTF-8字符)
with open(os.path.join(DATA_DIR, "pstxnet.dat"), 'r', encoding='latin-1') as f:
    pstxnet_content = f.read()

with open(os.path.join(DATA_DIR, "pstxprt.dat"), 'r', encoding='latin-1') as f:
    pstxprt_content = f.read()

with open(os.path.join(DATA_DIR, "pstchip.dat"), 'r', encoding='latin-1') as f:
    pstchip_content = f.read()

# 2. 实例化解析器并解析三大文件
net_parser_inst = CadenceNetlistParser()
prt_parser_inst = CadencePrtParser()
chip_parser_inst = CadenceChipParser()

# 获取到最纯净的拓扑三元组列表
net_topology = net_parser_inst.parse_pstxnet(pstxnet_content)  
# 获取映射和底层库字典
ref_to_prim = prt_parser_inst.parse_pstxprt(pstxprt_content)
chip_library = chip_parser_inst.parse_pstchip(pstchip_content)

# 3. 融合：组装高维度的 Component 节点数据
# 3.1 初始化 PartType 标准化器（自动查找 BOM 文件）
bom_path = os.path.join(DATA_DIR, "BOM.csv")
if not os.path.exists(bom_path):
    bom_path = os.path.join(DATA_DIR, "BOM.xlsx")
if not os.path.exists(bom_path):
    bom_path = None

standardizer = PartTypeStandardizer(bom_path=bom_path)

graph_components = {}
for triplet in net_topology:
    refdes = triplet['Component_RefDes']

    # 防止重复处理同一个器件
    if refdes not in graph_components:
        # 顺藤摸瓜：位号 -> 库模型名 -> 库模型电气属性
        primitive_name = ref_to_prim.get(refdes)
        properties = chip_library.get(primitive_name, {}).get("Properties", {})
        raw_parttype = properties.get("PART_NAME", "N/A")
        value = properties.get("VALUE", None)

        # PartType 标准化（三层降级策略）
        part_type = standardizer.standardize(
            refdes=refdes,
            model=primitive_name,
            value=value
        )

        # 组装完整的器件节点数据
        graph_components[refdes] = {
            "RefDes": refdes,
            "Model": primitive_name,
            "Value": value if value else "N/A",
            "PartType": part_type,
            "RawPartType": raw_parttype,
        }

# 4. 将数据保存到独立文件 (节点 Nodes 与 关系 Edges 分离)
os.makedirs(OUTPUT_DIR, exist_ok=True)

# 输出一：保存 Component 节点属性数据
components_output_file = os.path.join(OUTPUT_DIR, "graph_components.json")
with open(components_output_file, 'w', encoding='utf-8') as f:
    json.dump(graph_components, f, ensure_ascii=False, indent=2)

print(f"Successfully saved {len(graph_components)} component nodes to: {components_output_file}")

# 输出二：保存拓扑连接关系数据
topology_output_file = os.path.join(OUTPUT_DIR, "topology_triplets.json")
with open(topology_output_file, 'w', encoding='utf-8') as f:
    json.dump(net_topology, f, ensure_ascii=False, indent=2)

print(f"Successfully saved {len(net_topology)} topology triplets to: {topology_output_file}")

# 5. 输出 PartType 标准化统计
standardizer.print_stats()

# ============================================
# 5.5 生成 Pin.Type 映射（用于 Neo4j 引脚类型注入）
# ============================================
print("\n[PinTypeMap] 正在生成引脚类型映射...")

PIN_TYPE_MAP = {}

for triplet in net_topology:
    refdes = triplet['Component_RefDes']
    pin_num = triplet['Pin_Number']
    net_name = triplet['Net_Name']
    key = f"{refdes}_{pin_num}"

    primitive_name = ref_to_prim.get(refdes)
    pin_data = chip_library.get(primitive_name, {}).get("Pins", {}).get(pin_num, {})
    comp_parttype = graph_components.get(refdes, {}).get("PartType", "UNKNOWN")

    pin_type = None

    # 规则1: PINUSE 直接映射
    pinuse = pin_data.get("PINUSE", "")
    if pinuse == "POWER":
        pin_type = "POWER"

    # 规则2: 网络名推断（GND/VSS → GROUND）
    if not pin_type:
        net_upper = net_name.upper()
        if "GND" in net_upper or "VSS" in net_upper:
            pin_type = "GROUND"

    # 规则3: 网络名推断（VCC/VDD/电压 → POWER）
    if not pin_type:
        import re
        if re.search(r'(?i)^(VCC|VDD|VIN|VOUT|VBAT|3V3|1V8|1V2|1V0|5V|12V)', net_name):
            pin_type = "POWER"

    # 规则4: BIDIRECTIONAL 属性
    if not pin_type:
        if pin_data.get("BIDIRECTIONAL") == "TRUE":
            pin_type = "BIDIRECTIONAL"

    # 规则5: INPUT/OUTPUT 属性
    if not pin_type:
        has_input = "INPUT_LOAD" in pin_data
        has_output = "OUTPUT_LOAD" in pin_data
        if has_input and has_output:
            pin_type = "BIDIRECTIONAL"
        elif has_output:
            pin_type = "OUTPUT"
        elif has_input:
            pin_type = "INPUT"

    # 规则6: 被动器件
    if not pin_type:
        if comp_parttype in ("CAPACITOR", "RESISTOR", "INDUCTOR"):
            pin_type = "PASSIVE"

    # 规则7: 默认值
    if not pin_type:
        pin_type = "SIGNAL"

    PIN_TYPE_MAP[key] = pin_type

# 统计
from collections import Counter
type_counts = Counter(PIN_TYPE_MAP.values())
print(f"[PinTypeMap] 共生成 {len(PIN_TYPE_MAP)} 个引脚类型映射:")
for pt, cnt in type_counts.most_common():
    print(f"  {pt}: {cnt}")

pin_type_output_file = os.path.join(OUTPUT_DIR, "pin_type_map.json")
with open(pin_type_output_file, 'w', encoding='utf-8') as f:
    json.dump(PIN_TYPE_MAP, f, ensure_ascii=False, indent=2)
print(f"[PinTypeMap] 已保存到: {pin_type_output_file}")

# 6. Quality Guard 质量检查（不达标则阻断）
print("\n[QualityGuard] 正在执行数据质量检查...")
guard = QualityGuard(components=graph_components, topology=net_topology)
try:
    guard.validate(raise_on_fail=True)
    guard.print_report()
    print("\n[QualityGuard] ✅ 数据质量检查通过，继续后续流程")
except QualityGuardException as e:
    print(f"\n{e}")
    print("\n[QualityGuard] ❌ 数据质量未达标，已阻断运行")
    print("[QualityGuard] 请检查 ETL 输出并修复数据问题后重试")
    exit(1)
