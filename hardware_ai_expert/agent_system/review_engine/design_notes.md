# Review Engine 设计笔记

## 架构概述

三层架构：
- **Layer 1 (Template)**: 通用检查逻辑模板，Python 类实现
- **Layer 2 (Config)**: YAML/JSON 规则配置实例化，按电压等级/接口类型/产品线参数化
- **Layer 3 (Knowledge)**: 从 Datasheet 自动提取规则（AI 驱动，后续实现）

## 已实现的模板

| template_id | 类名 | 功能 |
|-------------|------|------|
| `decap_check` | DecapCheckTemplate | 电源去耦电容数量/容值检查 |
| `pullup_check` | PullupCheckTemplate | 总线上拉/终端电阻阻值检查 |
| `esd_check` | ESDCheckTemplate | 外部接口 ESD/TVS 保护检查 |
| `amr_check` | AMRCheckTemplate | AMR 降额检查（电阻功率/电容耐压）|

## 规则配置格式

规则在 `config/default_rules.yaml` 中定义，每个规则包含：

```yaml
- id: POWER_3V3_DECAP          # 规则唯一ID
  template_id: decap_check     # 关联的模板ID
  name: "3.3V 电源去耦检查"     # 规则名称
  severity: ERROR              # ERROR/WARNING/INFO
  enabled: true                # 是否启用
  params:                      # 模板参数
    voltage_level: "3.3"       # 电压等级
    min_count: 2               # 最少电容数量
    required_values: [...]      # 所需容值列表
    applicable_parts: [...]     # 适用器件类型
    net_patterns: [...]         # 网络名匹配模式
```

## Neo4j 数据质量说明

### Pin.Type 字段全为 NULL

ETL 解析 `pstchip.dat` 时 PINUSE 属性未能正确映射到 Pin.Type，导致所有 Pin 节点的 Type 字段为 NULL。

**影响**：依赖 `p.Type = 'POWER'` 的检查逻辑会失效。

**应对策略**：
- decap_check 先尝试 POWER 引脚查找，失败后兜底用无 Pin.Type 限制的查询
- ESD 检查已完全切换为按网络名模式匹配，不再依赖连接器引脚类型

### VoltageLevel 已标注

`VoltageLevelExtractor` 从网络名自动推断电压（如 VDD_3V3 → 3.3V）。
当前 Neo4j 中 **1811 个网络**已标注 VoltageLevel，可直接用于 decap_check。

### 网络名模式匹配作为补充策略

由于 Pin.Type 不可用，检查逻辑采用网络名模式匹配作为主要策略：
- 含 "3V3" → 3.3V 网络
- 含 "1V8" → 1.8V 网络
- 含 "I2C_SCL/SDA" → I2C 总线网络

## 白名单机制

存储在 Neo4j 节点 `ReviewWhitelist`，属性：

| 属性 | 说明 |
|------|------|
| `rule` | 规则 ID |
| `refdes` | 豁免的器件位号 |
| `status` | IGNORE / APPROVED |
| `reason` | 豁免原因 |
| `added_by` | 添加人 |
| `added_at` | 添加时间 |

> 注意：属性名与 Violation 的 rule_id/refdes 字段不同，需要映射。

## 已知误报情况

| 场景 | 原因 | 建议 |
|------|------|------|
| NC 网络被报告为"缺少 ESD" | NC 网络名称不含电源/地关键字 | 已修复：_is_power_or_gnd 跳过 "NC" |
| 连接器内部走线被报告 | 连接器外壳引脚连接到内部信号 | 需按 PartType 区分（如 CON_* 系列可能为内部连接器）|
| 网络名含电压字符但非电源网络 | 如 "BUF_3V3_BOOTMODE4" 是 GPIO 而非电源 | 需引入更精确的电源网络识别逻辑 |

## 规则数量与结果统计

当前配置 10 条规则，以 Beet7 数据为例运行结果：

| 规则 | 违规数 | 严重度 |
|------|--------|--------|
| POWER_3V3_DECAP | 184 | ERROR |
| POWER_1V8_DECAP | 145 | ERROR |
| POWER_5V0_DECAP | 105 | WARNING |
| I2C_STD_PULLUP | 266 | ERROR |
| USB_DP_DM_PULLUP | 1 | WARNING |
| USB_ESD_PROTECTION | 1 | WARNING |
| ETHERNET_ESD_PROTECTION | 163 | WARNING |
| EXTERNAL_IO_ESD | 438 | INFO |
| CAN_BUS_TERMINATION | 0 | - |
| HDMI_ESD_PROTECTION | 0 | - |

注：CAN/HDMI 违规为 0 是因为板子上没有 CAN 总线和 HDMI 接口。

## 下一步扩展方向

1. **PinMuxCheckTemplate**：引脚悬空、OpenDrain 漏接上拉检查
2. **PowerSequenceCheckTemplate**：多电源上电时序检查
3. **Layer 3 知识提取**：从 Datasheet PDF 自动提取规则（需对接 datasheet_processor）
4. **规则优先级/分组**：支持规则分组执行、增量检查
5. **与 Agent Core 集成**：在 agent_core.py 的 REVIEW_SPECIFIC 节点中调用 ReviewRuleEngine