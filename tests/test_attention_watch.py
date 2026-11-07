"""S-769 B 的前向记录(11-07):尖峰口径与 t290 的 B 臂一致、到期才结算、没价不写 0。"""
import datetime as dt

from src.data.signals import attention_watch as aw


def _series(n=100, spike_at=95, base=100.0):
    d0 = dt.date(2026, 1, 1)
    ser = {}
    for i in range(n):
        ser[(d0 + dt.timedelta(days=i)).isoformat()] = base + (i % 5) + (500.0 if i in (spike_at, spike_at + 3) else 0.0)
    return ser


def test_spike_needs_60_prior_obs_and_dedupes_30_days():
    ev = aw.spikes({"X": _series()})
    assert len(ev) == 1 and ev[0][0] == "X" and ev[0][1] == "2026-04-06", ev
    assert aw.spikes({"Y": _series(n=50, spike_at=45)}) == [], "前 90 天不足 60 个观测不打分"


def test_excess_vs_equal_weight_basket_and_missing_prices():
    px = {"X": {"2026-04-07": (10.0, 1e8), "2026-04-14": (9.0, 1e8)},
          "A": {"2026-04-07": (1.0, 5e7), "2026-04-14": (1.1, 5e7)},
          "B": {"2026-04-07": (2.0, 1e7), "2026-04-14": (4.0, 1e7)}}
    by_date = {"2026-04-06": {"X": (10.0, 1e8), "A": (1.0, 5e7), "B": (2.0, 1e7)}}
    x, n = aw.excess("X", "2026-04-06", px, by_date, 7)
    assert n == 2 and abs(x - (-0.1 - 0.0)) < 1e-9, (x, n)          # B 市值 < 2,000 万不进篮子
    assert aw.excess("Z", "2026-04-06", px, by_date, 7) == (None, None)
    r = aw.rows([("X", "2026-04-06", 4.2)], px, by_date, dt.date(2026, 4, 20))
    assert r[0]["excess_7d"] is not None and r[0]["excess_30d"] is None and r[0]["cohort"] == "backfill"
