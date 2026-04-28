import re
import json

class CadencePrtParser:
    def __init__(self):
        # 匹配原理图位号与底层库模型的映射关系
        # 示例 1: BT6E1 'SKYLAKE_CAP_BAT-HLD-2032-TE_CR2':;
        # 示例 2: C0J1 'CAP_PPG_C0402_DISCRETE_0.1UF_11':
        self.part_pattern = re.compile(r"([A-Za-z0-9_]+)\s+'([^']+)'")

    def parse_pstxprt(self, file_content):
        """
        专门解析 Cadence pstxprt.dat 文件
        提取 {位号 (RefDes) : 库模型名称 (Primitive)} 的映射字典
        """
        part_mapping = {}
        lines = file_content.strip().split('\n')
        
        i = 0
        while i < len(lines):
            line = lines[i].strip()
            
            # 寻找 PART_NAME 块的开始
            if line == 'PART_NAME':
                i += 1
                if i < len(lines):
                    # 下一行通常包含位号和模型名称
                    part_line = lines[i].strip()
                    match = self.part_pattern.search(part_line)
                    if match:
                        refdes = match.group(1)       # 如: BT6E1
                        primitive = match.group(2)    # 如: SKYLAKE_CAP_BAT-HLD-2032-TE_CR2
                        part_mapping[refdes] = primitive
            i += 1
            
        return part_mapping

# ==========================================
# 测试您提供的 pstxprt.dat 真实片段
# ==========================================
if __name__ == "__main__":
    mock_pstxprt = """
FILE_TYPE = EXPANDEDPARTLIST;
{ Using PSTWRITER 17.2.0 d001Feb-13-2026 at 16:44:52 }
DIRECTIVES
 PST_VERSION='PST_HDL_CENTRIC_VERSION_0';
 ROOT_DRAWING='700-00700-00_ADS7_V1_20260213I';
 POST_TIME='Mar  2 2016 00:37:24';
 SOURCE_TOOL='CAPTURE_WRITER';
END_DIRECTIVES;

PART_NAME
 BT6E1 'SKYLAKE_CAP_BAT-HLD-2032-TE_CR2':;

SECTION_NUMBER 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS19154872@INTEL_RES_CAP.SKYLAKE_CAP.NORMAL(CHIPS)':
 C_PATH='@\\700-00700-00_ads7_v1_20260213i\\.ads7_sch(sch_1):ins19154872@intel_res_cap.\\skylake_cap.normal\\(chips)',
 PRIM_FILE='.\\pstchip.dat',
 SECTION='';

PART_NAME
 C0J1 'CAP_PPG_C0402_DISCRETE_0.1UF_11':
 ROOM='CONFIG_JUMPERS';

SECTION_NUMBER 1
 '@700-00700-00_ADS7_V1_20260213I.ADS7_SCH(SCH_1):INS20645513@MSTR_DISCRETE.CAP_PPG.NORMAL(CHIPS)':
 PRIM_FILE='.\\pstchip.dat',
 SECTION='';
    """
    
    parser = CadencePrtParser()
    result = parser.parse_pstxprt(mock_pstxprt)
    
    print(json.dumps(result, indent=4, ensure_ascii=False))