"""
差分对信号完整性检查模板

检查高速差分对的完整性和信号完整性：
  1. P/N 网络匹配验证
  2. 走线对称性检查（连接器件数量一致）
  3. 端接电阻 / AC coupling 检查
  4. 共模电感检查（USB/ETH）
"""

from __future__ import annotations

import re
from typing import Any

from agent_system.review_engine.templates.base import RuleTemplate, RuleContext, TemplateRegistry
from agent_system.schemas import Violation


# ============================================
# 差分对命名模式
# ============================================

DIFF_PATTERNS = [
    # (正端模式, 负端模式, 基础名提取)
    (r'(.*)_P$', r'\1_N$', 'suffix_PN'),
    (r'(.*)_POS$', r'\1_NEG$', 'suffix_POS_NEG'),
    (r'(.*)\+$', r'\1-$', 'suffix_plus_minus'),
    # CLKP/CLKN, D0P/D0N 等嵌入式
    (r'(.*)CLKP$', r'\1CLKN$', 'embedded_CLKPN'),
    (r'(.*)DP$', r'\1DN$', 'embedded_DPN'),
    (r'(.*)TXP$', r'\1TXN$', 'embedded_TXPN'),
    (r'(.*)RXP$', r'\1RXN$', 'embedded_RXPN'),
]

SIGNAL_STANDARDS = [
    (r'(?i)PCIE', 'PCIe'),
    (r'(?i)(CSI|DSI|MIPI|DPHY|CPHY)', 'MIPI'),
    (r'(?i)(USB[_]?3|SSRX|SSTX|USB_SS)', 'USB3'),
    (r'(?i)USB', 'USB2'),
    (r'(?i)LVDS', 'LVDS'),
    (r'(?i)(ETH|ETHERNET|RGMII|GMII|SGMII|SERDES)', 'Ethernet'),
    (r'(?i)(HDMI|TMDS)', 'HDMI'),
    (r'(?i)SATA', 'SATA'),
    (r'(?i)(JESD|JESD204)', 'JESD204'),
    (r'(?i)(TXP|TXN|RXP|RXN)', 'SerDes'),
]


def infer_signal_standard(name: str) -> str:
    """推断信号标准"""
    for pattern, std in SIGNAL_STANDARDS:
        if re.search(pattern, name):
            return std
    return 'Unknown'


def find_diff_pair(net_name: str) -> tuple[str | None, str | None]:
    """
    给定一个网络名，尝试找到其差分对伙伴和基础名。
    返回 (complement_name, base_name) 或 (None, None)
    """
    # 嵌入式差分对模式 (CLKP/CLKN, DP/DN, TXP/TXN, RXP/RXN)
    # 也支持 D0P/D0N, D1P/D1N 等带数字编号的模式
    embedded_patterns = [
        ('CLKP', 'CLKN'),
        ('TXP', 'TXN'),
        ('RXP', 'RXN'),
        ('DP', 'DN'),
    ]
    embedded_patterns.sort(key=lambda x: len(x[0]), reverse=True)

    # 1. 先尝试嵌入式后缀 (TXP, RXP, CLKP, DP)
    for suffix, comp_suffix in embedded_patterns:
        if net_name.endswith(suffix):
            base = net_name[:-len(suffix)]
            complement = base + comp_suffix
            return complement, base

    # 2. 尝试数字编号差分对: D0P→D0N, D1P→D1N, TX0P→TX0N 等
    m = re.search(r'([A-Z]+)(\d+)P$', net_name)
    if m:
        prefix, num = m.group(1), m.group(2)
        base = net_name[:-1]  # remove trailing P
        complement = base + 'N'
        return complement, base

    # 后缀模式 (_P/_N, _POS/_NEG)
    suffix_pairs = [
        ('_P', '_N'),
        ('_POS', '_NEG'),
    ]
    for p_suffix, n_suffix in suffix_pairs:
        if net_name.endswith(p_suffix):
            base = net_name[:-len(p_suffix)]
            complement = base + n_suffix
            return complement, base
        if net_name.endswith(n_suffix):
            base = net_name[:-len(n_suffix)]
            complement = base + p_suffix
            return complement, base

    # +/- 后缀
    if net_name.endswith('+'):
        return net_name[:-1] + '-', net_name[:-1]
    if net_name.endswith('-'):
        return net_name[:-1] + '+', net_name[:-1]

    return None, None


# ============================================
# DiffPairCheckTemplate
# ============================================

class DiffPairCheckTemplate(RuleTemplate):
    """
    差分对信号完整性检查模板

    参数:
        signal_standards: list  要检查的信号标准（空=全部）
        check_type: str     检查类型
            - "matching": P/N 配对匹配
            - "termination": 端接检查
            - "cmc": 共模电感检查
            - "all": 全部检查（默认）
        require_ac_coupling: list  需要 AC coupling 的信号标准
        require_cmc: list          需要共模电感的信号标准
    """

    template_id = "diff_pair_check"
    name = "差分对信号完整性检查"
    description = "检查高速差分对的匹配、端接和共模电感配置"
    default_severity = "WARNING"

    def check(self, params: dict, context: RuleContext) -> list[Violation]:
        violations = []
        check_type = params.get("check_type", "all")
        signal_standards = params.get("signal_standards", [])
        rule_id = params.get("rule_id", self.template_id)
        severity = params.get("severity", self.default_severity)
        require_ac_coupling = params.get("require_ac_coupling", ["PCIe", "USB3"])
        require_cmc = params.get("require_cmc", ["USB2", "USB3", "Ethernet"])

        driver = context.neo4j_driver

        if check_type in ("matching", "all"):
            violations.extend(self._check_matching(
                driver, rule_id, severity, signal_standards, params
            ))

        if check_type in ("termination", "all"):
            violations.extend(self._check_termination(
                driver, rule_id, severity, signal_standards,
                require_ac_coupling, params
            ))

        if check_type in ("cmc", "all"):
            violations.extend(self._check_cmc(
                driver, rule_id, severity, signal_standards,
                require_cmc, params
            ))

        return violations

    # --------------------------------------------------------
    # 匹配检查
    # --------------------------------------------------------

    def _check_matching(self, driver, rule_id, severity, signal_standards, params) -> list[Violation]:
        """检查 P/N 差分对匹配"""
        violations = []

        # 查找所有可能是差分对 P 端的网络
        cypher = """
        MATCH (n:Net)
        WHERE n.Name =~ '.*_P$' OR n.Name =~ '.*CLKP$' OR n.Name =~ '.*DP$'
           OR n.Name =~ '.*TXP$' OR n.Name =~ '.*RXP$'
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            p_nets = [r["net_name"] for r in session.run(cypher)]

        for p_name in p_nets:
            complement, base_name = find_diff_pair(p_name)
            if not complement:
                continue

            signal_std = infer_signal_standard(p_name)

            # 如果指定了信号标准过滤，跳过不匹配的
            if signal_standards and signal_std not in signal_standards and signal_std != 'Unknown':
                continue
            # 如果指定了信号标准且当前是 Unknown，也跳过（不在关注范围内）
            if signal_standards and signal_std == 'Unknown':
                continue

            # 检查 N 端是否存在
            cypher_check = "MATCH (n:Net {Name: $name}) RETURN n.Name AS name"
            with driver.session() as session:
                n_result = list(session.run(cypher_check, {"name": complement}))

            if not n_result:
                violations.append(Violation(
                    id=f"{rule_id}_{p_name}_unmatched",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=self._find_driver_component(driver, p_name),
                    net_name=p_name,
                    description=f"差分对 P 端 '{p_name}' 缺少对应的 N 端 '{complement}' ({signal_std})",
                    severity=severity,
                    expected=f"P/N 配对完整: {p_name} ↔ {complement}",
                    actual=f"P 端存在，N 端 '{complement}' 不存在",
                ))
                continue

            # 检查 P/N 连接器件数量对称性
            cypher_count = """
            MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $name})
            RETURN count(DISTINCT c) AS cnt
            """
            with driver.session() as session:
                p_cnt = session.run(cypher_count, {"name": p_name}).single()["cnt"]
                n_cnt = session.run(cypher_count, {"name": complement}).single()["cnt"]

            if p_cnt != n_cnt:
                violations.append(Violation(
                    id=f"{rule_id}_{base_name}_asymmetric",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=self._find_driver_component(driver, p_name),
                    net_name=f"{p_name}/{complement}",
                    description=f"差分对 '{base_name}' ({signal_std}) P/N 连接器件数量不对称",
                    severity="INFO",
                    expected=f"P/N 连接器件数相同",
                    actual=f"P端: {p_cnt} 个器件, N端: {n_cnt} 个器件",
                ))

        return violations

    # --------------------------------------------------------
    # 端接检查
    # --------------------------------------------------------

    def _check_termination(self, driver, rule_id, severity, signal_standards,
                           require_ac_coupling, params) -> list[Violation]:
        """检查差分对端接（AC coupling cap / 端接电阻）"""
        violations = []

        if not require_ac_coupling:
            return violations

        # 构建信号标准过滤
        std_filter = "|".join(require_ac_coupling)
        cypher = f"""
        MATCH (n:Net)
        WHERE (n.Name =~ '.*_P$' OR n.Name =~ '.*DP$' OR n.Name =~ '.*TXP$')
          AND n.Name =~ '(?i)({std_filter})'
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            p_nets = [r["net_name"] for r in session.run(cypher)]

        for p_name in p_nets:
            complement, base_name = find_diff_pair(p_name)
            if not complement:
                continue

            signal_std = infer_signal_standard(p_name)
            if signal_std not in require_ac_coupling:
                continue

            # 检查差分对上是否有串联电容（AC coupling）
            # AC cap 通常在 TX 端差分线上串联
            cypher_caps = """
            MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
            WHERE c.PartType CONTAINS 'CAP'
            RETURN c.RefDes AS refdes, c.Value AS value
            """
            with driver.session() as session:
                p_caps = list(session.run(cypher_caps, {"net_name": p_name}))
                n_caps = list(session.run(cypher_caps, {"net_name": complement}))

            has_ac_cap = len(p_caps) > 0 or len(n_caps) > 0

            # PCIe REFCLK 不需要 AC cap，只需要端接
            if "REFCLK" in p_name.upper():
                # 检查端接电阻
                cypler_res = """
                MATCH (n:Net {Name: $net_name})<-[:CONNECTS_TO]-(p:Pin)<-[:HAS_PIN]-(c:Component)
                WHERE c.PartType CONTAINS 'RES'
                RETURN c.RefDes AS refdes, c.Value AS value
                """
                with driver.session() as session:
                    p_res = list(session.run(cypler_res, {"net_name": p_name}))

                if not p_res:
                    violations.append(Violation(
                        id=f"{rule_id}_{base_name}_refclk_term",
                        rule_id=rule_id,
                        rule_name=params.get("rule_name", self.name),
                        refdes=self._find_driver_component(driver, p_name),
                        net_name=p_name,
                        description=f"PCIe REFCLK '{base_name}' 缺少端接电阻",
                        severity=severity,
                        expected="REFCLK 差分对应有端接电阻",
                        actual="未找到端接电阻",
                    ))
                continue

            if not has_ac_cap:
                violations.append(Violation(
                    id=f"{rule_id}_{base_name}_no_ac_cap",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=self._find_driver_component(driver, p_name),
                    net_name=f"{p_name}/{complement}",
                    description=f"{signal_std} 差分对 '{base_name}' 缺少 AC coupling 电容",
                    severity=severity,
                    expected=f"{signal_std} TX 应有 AC coupling 电容",
                    actual="差分线上未发现串联电容",
                ))

        return violations

    # --------------------------------------------------------
    # 共模电感检查
    # --------------------------------------------------------

    def _check_cmc(self, driver, rule_id, severity, signal_standards,
                   require_cmc, params) -> list[Violation]:
        """检查 USB/ETH 差分对是否有共模电感"""
        violations = []

        if not require_cmc:
            return violations

        # 查找 USB/ETH 差分对
        std_filter = "|".join(require_cmc)
        cypher = f"""
        MATCH (n:Net)
        WHERE (n.Name =~ '.*_P$' OR n.Name =~ '.*DP$')
          AND n.Name =~ '(?i)({std_filter})'
        RETURN n.Name AS net_name
        """

        with driver.session() as session:
            p_nets = [r["net_name"] for r in session.run(cypher)]

        for p_name in p_nets:
            signal_std = infer_signal_standard(p_name)
            if signal_std not in require_cmc:
                continue

            complement, base_name = find_diff_pair(p_name)
            if not complement:
                continue

            # 检查差分对路径上是否有共模电感
            # CMC 在原理图中通常表现为连接 P/N 两线的电感/滤波器
            # 搜索策略：找 P 网络和 N 网络的共同邻居中的 INDUCTOR/FILTER
            cypher_cmc = """
            MATCH (c:Component)-[:HAS_PIN]->(p1:Pin)-[:CONNECTS_TO]->(n1:Net {Name: $p_name})
            WHERE c.PartType CONTAINS 'IND' OR c.PartType CONTAINS 'FILTER'
                  OR c.Model =~ '(?i).*CMC.*' OR c.Model =~ '(?i).*common.*mode.*'
            RETURN c.RefDes AS refdes, c.Model AS model, c.PartType AS pt
            """

            with driver.session() as session:
                cmcs = list(session.run(cypher_cmc, {"p_name": p_name}))

            if not cmcs:
                # 也检查 N 端
                with driver.session() as session:
                    cmcs = list(session.run(cypher_cmc, {"p_name": complement}))

            if not cmcs:
                violations.append(Violation(
                    id=f"{rule_id}_{base_name}_no_cmc",
                    rule_id=rule_id,
                    rule_name=params.get("rule_name", self.name),
                    refdes=self._find_driver_component(driver, p_name),
                    net_name=f"{p_name}/{complement}",
                    description=f"{signal_std} 差分对 '{base_name}' 缺少共模电感(CMC)",
                    severity="INFO",
                    expected=f"{signal_std} 差分对应有共模电感滤波",
                    actual="未发现 CMC / 共模滤波器",
                ))

        return violations

    # --------------------------------------------------------
    # 辅助方法
    # --------------------------------------------------------

    @staticmethod
    def _find_driver_component(driver, net_name: str) -> str:
        """找到网络上的驱动器件（IC/PMIC/MCU）"""
        cypher = """
        MATCH (c:Component)-[:HAS_PIN]->(p:Pin)-[:CONNECTS_TO]->(n:Net {Name: $name})
        WHERE c.PartType IN ['IC', 'PMIC', 'MCU', 'FPGA', 'SOC', 'CONNECTOR']
        RETURN c.RefDes AS refdes
        LIMIT 1
        """
        try:
            with driver.session() as session:
                result = session.run(cypher, {"name": net_name}).single()
                return result["refdes"] if result else net_name
        except Exception:
            return net_name


# 注册模板
TemplateRegistry.register(DiffPairCheckTemplate())
