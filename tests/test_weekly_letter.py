"""周信(11-03):周收益、面板对照、记分表按作者、文案合规、读不到的段写明。"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.ops import weekly_letter as wl  # noqa: E402


def test_live_and_panel_week():
    live = wl.live_week([{"d": "2026-11-03", "equity_usd": 630.0, "nav": 1.0}, {"d": "2026-11-08", "equity_usd": 640.0, "nav": 1.01}])
    assert live["ok"] and abs(live["ret"] - 0.01) < 1e-9 and live["days"] == 2
    assert wl.live_week([]) == {"ok": False, "why": "本周没有真钱快照"}
    assert abs(wl.panel_week([{"ret": 0.01}, {"ret": -0.01}]) - (1.01 * 0.99 - 1)) < 1e-9 and wl.panel_week([]) is None


def test_scorecard_groups_settled_by_author_and_counts_pending():
    entries = [{"id": "E53", "author": "seth:weekly", "statement": "BTC in band", "prob": 0.7},
               {"id": "E54", "author": "seth:weekly", "statement": "x", "prob": 0.3},
               {"id": "X-1-down", "author": "seth:exposure", "statement": "y", "prob": 0.2}]
    scores = [{"id": "E53", "scored_at": "2026-11-04T01:00:00+00:00", "outcome": True, "brier": 0.09, "observed": 80000},
              {"id": "E54", "scored_at": "2026-11-04T01:00:00+00:00", "outcome": False, "brier": 0.09, "observed": 1},
              {"id": "X-1-down", "scored_at": "2026-10-20T01:00:00+00:00", "outcome": True, "brier": 0.64}]
    c = wl.scorecard(entries, scores, "2026-11-02", "2026-11-08")
    assert c["settled"]["seth:weekly"]["n"] == 2 and c["settled"]["seth:weekly"]["hit_rate"] == 0.5
    assert abs(c["settled"]["seth:weekly"]["mean_brier"] - 0.09) < 1e-9 and "seth:exposure" not in c["settled"], "上周结的不进本周"
    assert c["pending"] == {}


def test_compose_is_compliant_and_names_unreadable_sections():
    live = {"ok": True, "d0": "2026-11-02", "d1": "2026-11-08", "equity0": 630.0, "equity1": 640.0, "ret": 0.016, "days": 7, "flows": False}
    decisions = [{"d": "2026-11-02", "rule_exposure": 0.0, "probs": {"down": 0.22, "flat": 0.45, "up": 0.33}, "bucket": "all", "n_bucket": 3334,
                  "flag": None, "inputs": {"probs_knn": {"down": 0.3, "flat": 0.4, "up": 0.3}}}]
    card = {"settled": {"seth:weekly": {"n": 2, "hits": 1, "hit_rate": 0.5, "mean_brier": 0.09,
                                        "items": [{"id": "E53", "statement": "BTC in band", "prob": 0.7, "outcome": True, "observed": 80000}]}},
            "pending": {"seth:exposure": 3}}
    md = wl.compose("2026-11-08", live, 0.01, decisions, card, {"counts": {"listing": 5}, "named": ["listing:FOO — Binance Will List Foo"]},
                    ["④ 套息 ❌:24 名等权资金费 ≈ 5%/yr,低于 8%"], note="本周切换 CIS v2。")
    assert md.startswith("# CometCloud 周信 · 2026-11-02 → 2026-11-08")
    assert "在场 0/1 天" in md and "+1.60%" in md and "30%/40%/30%" in md and "seth:weekly | 2 | 50%" in md and "等待结算:seth:exposure 3 条" in md
    assert "④ 套息 ❌" in md and "listing 5" in md and wl.COMPLIANCE in md
    assert not re.search(r"\b(buy|sell|accumulate|avoid|reduce)\b", md, re.I) and "买入" not in md and "卖出" not in md


def test_endpoint_and_migration_exist():
    src = (ROOT / "src/api/routers/admin.py").read_text(encoding="utf-8")
    assert '"/internal/weekly-letter"' in src
    mig = (ROOT / "migrations/2026-11-03_weekly_letters.sql").read_text(encoding="utf-8")
    for col in wl.WRITES_COLUMNS[wl.TABLE]:
        assert col in mig, col
