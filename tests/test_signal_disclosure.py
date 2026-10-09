"""S-529(Jazz 10-09):CIS 信号对外 = 根据过往表现展示,不是预测。

守三件事:① 信号面引用同一个口径常量,不各写一句;② 面向 agent / 用户的描述里没有「预测 / 该行动」措辞;
③ 方法论里不再有「Agent Action」(进场 / 止损 / 退出)那张表。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.api.contracts.disclosure import SIGNAL_DISCLOSURE, SIGNAL_DISCLOSURE_ZH  # noqa: E402

FORWARD = re.compile(r"expected to do|will (?:out|under)perform|expected to (?:out|under)perform|positive outlook|"
                     r"timed decision|what should I (?:actually )?do|highest-conviction long|act on the top signal|"
                     r"how much I should actually act", re.I)


def test_disclosure_says_not_a_forecast() -> None:
    assert "not forecasts" in SIGNAL_DISCLOSURE and "not investment advice" in SIGNAL_DISCLOSURE
    assert "past" in SIGNAL_DISCLOSURE and "historical outcomes" in SIGNAL_DISCLOSURE
    assert "不是对未来表现的预测" in SIGNAL_DISCLOSURE_ZH


def test_signal_routes_use_the_one_constant() -> None:
    src = (ROOT / "src/api/routers/signals.py").read_text(encoding="utf-8")
    assert "Positioning language only; not investment advice." not in src, "信号面另写了一句口径 —— 用 SIGNAL_DISCLOSURE"
    assert "SIGNAL_DISCLOSURE" in src
    assert "SIGNAL_DISCLOSURE" in (ROOT / "src/data/cis/provenance.py").read_text(encoding="utf-8")


def test_no_forward_looking_framing_on_signal_surfaces() -> None:
    for rel in ("src/mcp/cometcloud_mcp.py", "src/api/routers/signals.py", "CIS_METHODOLOGY.md",
                "dashboard/src/components/MethodologyPage.jsx", "dashboard/src/components/SignalAttribution.jsx",
                "dashboard/src/components/CISAssetDetail.jsx"):
        text = (ROOT / rel).read_text(encoding="utf-8")
        hits = [m.group(0) for m in FORWARD.finditer(text)]
        assert not hits, f"{rel} 有预测 / 该行动措辞:{hits[:5]}"


def test_methodology_has_no_agent_action_table() -> None:
    text = (ROOT / "CIS_METHODOLOGY.md").read_text(encoding="utf-8")
    assert "Agent Action" not in text and "set stop-loss" not in text and "Exit position" not in text
