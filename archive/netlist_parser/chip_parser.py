import re
import json

class CadenceChipParser:
    def __init__(self):
        # 匹配 primitive 声明，例如: primitive 'SKYLAKE_CAP_BAT-HLD-2032-TE_CR2';
        self.primitive_pattern = re.compile(r"primitive\s+'([^']+)'")
        # 匹配属性赋值，例如: VALUE='CR2032_BATT_HOLDER';
        self.prop_pattern = re.compile(r"([A-Z_0-9]+)\s*=\s*'([^']+)'")
        # 匹配引脚名声明，例如: '1P':
        self.pin_name_pattern = re.compile(r"'([^']+)'\s*:")

    def parse_pstchip(self, file_content):
        """
        专门解析 Cadence pstchip.dat 文件
        提取器件属性 (VALUE, PART_NAME 等) 和引脚属性 (PINUSE)
        """
        library_parts = {}
        
        current_primitive = None
        current_section = None # 记录当前是在 'body' 还是 'pin' 块
        current_pin_name = None
        
        lines = file_content.strip().split('\n')
        
        for line in lines:
            line = line.strip()
            if not line or line.startswith('{'):
                continue
                
            # 1. 匹配新的 primitive (器件模型)
            prim_match = self.primitive_pattern.match(line)
            if prim_match:
                current_primitive = prim_match.group(1)
                library_parts[current_primitive] = {
                    "Properties": {},
                    "Pins": {}
                }
                continue
                
            # 如果不在任何 primitive 块内，跳过
            if not current_primitive:
                continue
                
            # 2. 状态机切换：进入 body 或 pin 块
            if line == 'body':
                current_section = 'body'
                continue
            elif line == 'pin':
                current_section = 'pin'
                continue
            elif line == 'end_body' or line == 'end_pin':
                current_section = None
                current_pin_name = None
                continue
            elif line == 'end_primitive':
                current_primitive = None
                continue
                
            # 3. 解析 body 块内的属性 (如 VALUE, PART_NUMBER)
            if current_section == 'body':
                prop_match = self.prop_pattern.search(line)
                if prop_match:
                    key = prop_match.group(1)
                    val = prop_match.group(2)
                    library_parts[current_primitive]["Properties"][key] = val
                    
            # 4. 解析 pin 块内的引脚定义 (如 PINUSE, PIN_NUMBER)
            elif current_section == 'pin':
                # 检查是否是新的引脚名定义，例如 '1P':
                pin_name_match = self.pin_name_pattern.match(line)
                if pin_name_match:
                    current_pin_name = pin_name_match.group(1)
                    library_parts[current_primitive]["Pins"][current_pin_name] = {}
                    continue
                
                # 如果当前正在解析某个具体引脚，提取其属性，例如 PIN_NUMBER='(1)';
                if current_pin_name:
                    prop_match = self.prop_pattern.search(line)
                    if prop_match:
                        key = prop_match.group(1)
                        # 去掉可能包含的括号，如 '(1)' -> '1'
                        val = prop_match.group(2).replace('(', '').replace(')', '')
                        library_parts[current_primitive]["Pins"][current_pin_name][key] = val

        return library_parts

# ==========================================
# 测试您提供的 pstchip.dat 真实片段
# ==========================================
if __name__ == "__main__":
    mock_pstchip = """
FILE_TYPE=LIBRARY_PARTS;
{ Using PSTWRITER 17.2.0 d001Feb-13-2026 at 16:44:52}
primitive 'SKYLAKE_CAP_BAT-HLD-2032-TE_CR2';
  pin
    '1P':
      PIN_NUMBER='(1)';
      PINUSE='UNSPEC';
    '2P':
      PIN_NUMBER='(2)';
      PINUSE='UNSPEC';
    '3P':
      PIN_NUMBER='(3)';
      PINUSE='UNSPEC';
  end_pin;
  body
    PART_NAME='SKYLAKE_CAP';
    JEDEC_TYPE='BAT-HLD-2032-TE';
    VALUE='CR2032_BATT_HOLDER';
    PART_NUMBER='390-00054-00';
  end_body;
end_primitive;
    """
    
    parser = CadenceChipParser()
    result = parser.parse_pstchip(mock_pstchip)
    
    print(json.dumps(result, indent=4, ensure_ascii=False))