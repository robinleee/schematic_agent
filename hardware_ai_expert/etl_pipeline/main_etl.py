from etl_pipeline.chip_parser import CadenceChipParser
from etl_pipeline.prt_parser import CadencePrtParser
from etl_pipeline.net_parser import CadenceNetlistParser
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
graph_components = {}
for triplet in net_topology:
    refdes = triplet['Component_RefDes']
    
    # 防止重复处理同一个器件
    if refdes not in graph_components:
        # 顺藤摸瓜：位号 -> 库模型名 -> 库模型电气属性
        primitive_name = ref_to_prim.get(refdes)
        properties = chip_library.get(primitive_name, {}).get("Properties", {})
        
        # 组装完整的器件节点数据
        graph_components[refdes] = {
            "RefDes": refdes,
            "Model": primitive_name,
            "Value": properties.get("VALUE", "N/A"),
            "PartType": properties.get("PART_NAME", "N/A")
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
