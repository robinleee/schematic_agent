import re
import json

class CadenceNetlistParser:
    def __init__(self):
        pass

    def parse_pstxnet(self, file_content):
        """
        专门解析 Cadence pstxnet.dat 文件
        提取 {Net_Name, Component_RefDes, Pin_Number} 三元组
        """
        triplets = []
        current_net = None
        lines = file_content.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 1. 捕捉网络名称块
            if line == 'NET_NAME':
                i += 1
                if i < len(lines):
                    # 下一行通常是被单引号包裹的网络名，例如: 'ND2' 或 '89581MT_JTAG_PIN7'
                    net_line = lines[i].strip()
                    net_match = re.search(r"'(.*?)'", net_line)
                    if net_match:
                        current_net = net_match.group(1)
            
            # 2. 捕捉引脚连接节点
            elif line.startswith('NODE_NAME'):
                # 示例: NODE_NAME    R30898 1
                # 使用 split() 自动处理中间的 Tab 或多个空格
                parts = line.split()
                if len(parts) >= 3 and current_net:
                    refdes = parts[1]
                    pin = parts[2]
                    
                    triplets.append({
                        'Net_Name': current_net,
                        'Component_RefDes': refdes,
                        'Pin_Number': pin
                    })
            
            i += 1
            
        return triplets

# ==========================================
# 测试您提供的真实片段
# ==========================================
if __name__ == "__main__":
    mock_pstxnet = """
FILE_TYPE = EXPANDEDNETLIST;
{ Using PSTWRITER 17.2.0 d001Feb-13-2026 at 16:44:32 }
NET_NAME
'ND2'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):ND2':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):nd2';
NODE_NAME	R30898 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26442702@RESISTORS.RES.NORMAL(CHIPS)':
 '1':;
NODE_NAME	U30004 C4
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS26446147@IC_BAIDU.MT25QL02GCBB8E12_TPBGA24.NORMAL(CHIPS)':
 'W#/DQ2':;
NET_NAME
'89581MT_JTAG_PIN7'
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):89581MT_JTAG_PIN7':
 C_SIGNAL='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):\\89581mt_jtag_pin7\\';
NODE_NAME	J70003 7
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS25246209@CON_HDR.HDR_2X5_M.NORMAL(CHIPS)':
 '7':;
NODE_NAME	R70229 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS25246236@RESISTORS.RES.NORMAL(CHIPS)':
 '1':;
    """
    
    parser = CadenceNetlistParser()
    result = parser.parse_pstxnet(mock_pstxnet)
    
    print(json.dumps(result, indent=4, ensure_ascii=False))