"""t159.nav 的成本必须是扣钱,多空都一样(2026-10-25 发现:空单的 0.4% 来回成本被记成了收入)。

空单 units < 0,旧式 units × (出 − 进 − 0.004 × 进) 把成本翻成了 +0.4% 名义 —— 所有做空钱曲线都被抬高。
平价进出(出场价 = 进场价)的一张票,无论多空,权益都必须 < 1,且多空扣的钱一样多。
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "docs" / "research"))
import t159_bear_short as t159  # noqa: E402


def _bars(px=100.0, n=10, start="2022-01-01"):
    import datetime as dt
    d0 = dt.date.fromisoformat(start)
    return [((d0 + dt.timedelta(days=i)).isoformat(), px, px, px, px) for i in range(n)]


def _end_equity(stop_px):
    tk = [{"symbol": "X", "signal_d": "2022-01-01", "entry_d": "2022-01-02", "exit_d": "2022-01-06",
           "entry_px": 100.0, "stop_px": stop_px, "exit_px": 100.0}]
    curve = list(t159.nav(tk, {"X": _bars()}, 0.01, cap=10, d_to="2022-01-09"))
    return curve[-1]["equity"]


def test_flat_short_pays_cost_not_receives_it():
    eq = _end_equity(stop_px=120.0)                     # 空单:止损在进场上方
    assert eq < 1.0, f"平价空单权益 {eq} ≥ 1 ⇒ 成本被记成了收入"


def test_long_and_short_pay_the_same_cost():
    long_eq, short_eq = _end_equity(stop_px=80.0), _end_equity(stop_px=120.0)
    assert abs((1 - long_eq) - (1 - short_eq)) < 1e-12
    assert abs((1 - long_eq) - 0.01 / 0.20 * 0.004) < 1e-12, "名义 = f / 风险 = 5%,成本 0.4% ⇒ 0.02%"
