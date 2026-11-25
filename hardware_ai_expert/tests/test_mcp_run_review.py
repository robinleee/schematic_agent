"""run_review must show samples from every rule, with real descriptions."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent_system.schemas.review import Violation  # noqa: E402
from mcp_server import tools  # noqa: E402


def _v(rule, refdes, net, sev="ERROR"):
    return Violation(id=f"{rule}-{refdes}-{net}", rule_id=rule, rule_name=rule, refdes=refdes,
                     net_name=net, description=f"{rule} 在 {net} 上的问题", severity=sev)


def test_full_review_samples_every_rule_with_descriptions(monkeypatch):
    monkeypatch.setenv("SCHEMATIC_PROJECT_ID", "testproj")
    # 12 hits of one rule come first: the old output showed only those 10 rows, all blank.
    vs = [_v("DECAP", f"U{i}", f"N{i}") for i in range(12)]
    vs += [_v("DECAP", "U0", "N0")]  # duplicate
    vs += [_v("ESD", "J1", "USB_DP", "INFO"), _v("PULLUP", "U9", "SCL", "WARNING")]
    monkeypatch.setattr(tools, "_run_review_cached", lambda *a, **k: vs)
    monkeypatch.setattr(tools.graph_tools, "_get_driver", lambda: None)

    out = tools.run_review()

    sample_lines = [line for line in out.splitlines() if line.startswith("- [")]
    assert [line.split(" | ")[0] for line in sample_lines] == [
        "- [ERROR] DECAP", "- [ERROR] DECAP", "- [INFO] ESD", "- [WARNING] PULLUP"]
    assert "U0 @ N0 | DECAP 在 N0 上的问题" in out
    assert "J1 @ USB_DP | ESD 在 USB_DP 上的问题" in out
    assert "DECAP:13" in out


def test_rule_subset_shows_more_samples_per_rule(monkeypatch):
    monkeypatch.setenv("SCHEMATIC_PROJECT_ID", "testproj")
    vs = [_v("DECAP", f"U{i}", f"N{i}") for i in range(5)] + [_v("ESD", "J1", "X")]
    monkeypatch.setattr(tools, "_run_review_cached", lambda *a, **k: vs)
    monkeypatch.setattr(tools.graph_tools, "_get_driver", lambda: None)

    out = tools.run_review(rule_ids=["DECAP"])

    assert out.count("- [ERROR] DECAP") == 3
    assert "ESD" not in out
