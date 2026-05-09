# -*- coding: utf-8 -*-
"""
ETL Web Bridge 端到端测试

验证 ETL Web 封装模块的正确性。
"""

import os
import sys

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(ROOT_DIR, "hardware_ai_expert"))

from agent_system.etl_web_bridge import ETLWebExecutor


def test_preview_only():
    """测试预览功能（不入库）"""
    print("=" * 60)
    print("[Test 1] ETL Preview (No DB Write)")
    print("=" * 60)

    data_dir = os.path.join(ROOT_DIR, "hardware_ai_expert", "data", "netlist_Beet7")
    if not os.path.exists(data_dir):
        print(f"❌ 测试数据目录不存在: {data_dir}")
        return False

    files = {
        "pstxnet": os.path.join(data_dir, "pstxnet.dat"),
        "pstxprt": os.path.join(data_dir, "pstxprt.dat"),
        "pstchip": os.path.join(data_dir, "pstchip.dat"),
    }

    # 检查文件存在
    for key, path in files.items():
        if not os.path.exists(path):
            print(f"❌ 文件不存在: {path}")
            return False
        print(f"  ✅ {key}: {os.path.basename(path)} ({os.path.getsize(path)/1024:.1f} KB)")

    executor = ETLWebExecutor()
    preview = executor.get_preview_stats(files)

    if not preview.get("success"):
        print(f"❌ 预览失败: {preview.get('error')}")
        return False

    print(f"\n  解析结果:")
    print(f"    器件数: {preview['components_count']}")
    print(f"    拓扑连接: {preview['topology_count']}")
    print(f"    网络数: {preview['unique_nets']}")
    print(f"    PartType 覆盖率: {preview['parttype_coverage']:.1f}%")
    print(f"    电源网络: {preview['power_nets_count']}")
    print(f"    地网络: {preview['ground_nets_count']}")

    # 验证基本指标
    assert preview['components_count'] > 0, "应有器件"
    assert preview['topology_count'] > 0, "应有拓扑连接"
    assert preview['unique_nets'] > 0, "应有网络"

    print("\n✅ 预览测试通过")
    return True


def test_parttype_distribution():
    """测试 PartType 分布"""
    print("\n" + "=" * 60)
    print("[Test 2] PartType Distribution")
    print("=" * 60)

    data_dir = os.path.join(ROOT_DIR, "hardware_ai_expert", "data", "netlist_Beet7")
    files = {
        "pstxnet": os.path.join(data_dir, "pstxnet.dat"),
        "pstxprt": os.path.join(data_dir, "pstxprt.dat"),
        "pstchip": os.path.join(data_dir, "pstchip.dat"),
    }

    executor = ETLWebExecutor()
    preview = executor.get_preview_stats(files)

    parttype_dist = preview.get("parttype_distribution", {})
    print(f"  PartType 分布:")
    for pt, count in list(parttype_dist.items())[:10]:
        print(f"    {pt}: {count}")

    assert len(parttype_dist) > 0, "应有 PartType 分布"
    print("\n✅ PartType 分布测试通过")
    return True


def test_quality_thresholds():
    """测试质量阈值计算"""
    print("\n" + "=" * 60)
    print("[Test 3] Quality Thresholds")
    print("=" * 60)

    data_dir = os.path.join(ROOT_DIR, "hardware_ai_expert", "data", "netlist_Beet7")
    files = {
        "pstxnet": os.path.join(data_dir, "pstxnet.dat"),
        "pstxprt": os.path.join(data_dir, "pstxprt.dat"),
        "pstchip": os.path.join(data_dir, "pstchip.dat"),
    }

    executor = ETLWebExecutor()

    # 解析文件
    components, topology = executor._parse_files(files)

    # 运行质量检查
    quality = executor._run_quality_check(components, topology)

    print(f"  PartType 覆盖率: {quality['parttype_coverage']:.1f}%")
    print(f"  质量检查通过: {quality['passed']}")

    # 覆盖率应在合理范围
    assert 0 <= quality['parttype_coverage'] <= 100, "覆盖率应在 0-100% 之间"

    print("\n✅ 质量阈值测试通过")
    return True


def main():
    print("\n" + "=" * 60)
    print("ETL Web Bridge 测试开始")
    print("=" * 60 + "\n")

    results = []
    results.append(test_preview_only())
    results.append(test_parttype_distribution())
    results.append(test_quality_thresholds())

    print("\n" + "=" * 60)
    if all(results):
        print("🎉 所有 ETL Web Bridge 测试通过！")
        print("=" * 60)
        return 0
    else:
        print("❌ 部分测试失败")
        print("=" * 60)
        return 1


if __name__ == "__main__":
    sys.exit(main())
