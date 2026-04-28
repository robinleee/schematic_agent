import chip_parser
import prt_parser
import net_parser
import os
import json

# 获取脚本所在目录，构建数据文件的绝对路径
script_dir = os.path.dirname(os.path.abspath(__file__))
data_dir = os.path.join(script_dir, "netlist_Beet7")

# 1. 读取三大文件内容 (使用latin-1编码以兼容非UTF-8字符)
with open(os.path.join(data_dir, "pstxnet.dat"), 'r', encoding='latin-1') as f:
    pstxnet_content = f.read()

with open(os.path.join(data_dir, "pstxprt.dat"), 'r', encoding='latin-1') as f:
    pstxprt_content = f.read()

with open(os.path.join(data_dir, "pstchip.dat"), 'r', encoding='latin-1') as f:
    pstchip_content = f.read()

# 2. 实例化解析器并解析三大文件
net_parser_inst = net_parser.CadenceNetlistParser()
prt_parser_inst = prt_parser.CadencePrtParser()
chip_parser_inst = chip_parser.CadenceChipParser()

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
output_dir = "output"
os.makedirs(output_dir, exist_ok=True)

# 输出一：保存 Component 节点属性数据
components_output_file = os.path.join(output_dir, "graph_components.json")
with open(components_output_file, 'w', encoding='utf-8') as f:
    json.dump(graph_components, f, ensure_ascii=False, indent=2)

print(f"✓ 成功保存 {len(graph_components)} 个器件节点(Nodes)数据到: {components_output_file}")

# 输出二：保存拓扑连接关系数据 (新增的部分)
topology_output_file = os.path.join(output_dir, "topology_triplets.json")
with open(topology_output_file, 'w', encoding='utf-8') as f:
    json.dump(net_topology, f, ensure_ascii=False, indent=2)

print(f"✓ 成功保存 {len(net_topology)} 条拓扑关系(Relationships)数据到: {topology_output_file}")