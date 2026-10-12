"""S-553:信号成绩单的 CAGR 不满一年不年化(GIPS)。之前下限是 0.05 年(约 18 天)。"""
from datetime import datetime, timedelta, timezone

from src.api.routers.signals import _compute_metrics


def _closed(days: int, n: int = 12, ret: float = 2.0):
    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    step = days / (n - 1)
    rows = [{"signal_date": (t0 + timedelta(days=i * step)).isoformat(), "return_pct": ret} for i in range(n)]
    return list(reversed(rows))                       # newest first, as the journal returns them


def test_weeks_of_signals_have_no_cagr_but_a_period_return():
    m = _compute_metrics(_closed(40), [])
    assert m["cagr_pct"] is None
    assert m["period_return_pct"] is not None and m["period_return_pct"] > 0
    assert 0.1 < m["period_years"] < 0.12
    assert m.get("calmar") is None


def test_a_full_year_is_annualised():
    m = _compute_metrics(_closed(400), [])
    assert m["cagr_pct"] is not None and m["period_years"] > 1.0
