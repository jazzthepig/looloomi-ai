"""S-814 周期位置空间:按时点、不补 0、近邻只取结果已出的日子、按独立段数收缩;回路 = 每周三条情景进记分账。"""
import asyncio
import datetime as dt
import math

import pytest

from src.data.state import cycle_space as cs


def _series(n=2600, seed=814):
    import random
    rng = random.Random(seed)
    d0 = dt.date(2012, 1, 1)
    days = [(d0 + dt.timedelta(days=i)).isoformat() for i in range(n)]
    price, p = {}, 10.0
    for i, d in enumerate(days):
        p *= math.exp(0.004 * math.sin(i / 200.0) + rng.gauss(0, 0.03))      # 有周期的价格
        price[d] = p
    mvrv = {d: 1.0 + 1.5 * (0.5 + 0.5 * math.sin(i / 200.0)) + rng.random() * 0.05 for i, d in enumerate(days)}
    puell = {d: 1.0 + 0.8 * math.sin(i / 200.0) + 1.0 for i, d in enumerate(days)}
    hash30 = {d: 0.05 * math.cos(i / 90.0) for i, d in enumerate(days)}
    fng = {d: 50 + 30 * math.sin(i / 200.0) for i, d in enumerate(days) if i >= 1500}      # 恐惧贪婪后来才有
    return days, price, mvrv, puell, hash30, fng


def test_features_and_vectors_are_point_in_time_and_missing_stays_missing():
    days, price, mvrv, puell, hash30, fng = _series()
    feats = cs.features(price, mvrv, puell, hash30, fng)
    vec = cs.pit_vectors(feats)
    cut = days[2000]
    feats2 = cs.features({d: v for d, v in price.items() if d <= cut}, mvrv, puell, hash30, fng)
    vec2 = cs.pit_vectors(feats2)
    assert vec[cut] == vec2[cut], "删掉 cut 之后的价格,cut 当天的向量逐位不变"
    i_f = cs.DIMS.index("fng_30")
    assert feats[days[1000]][i_f] is None and vec[days[1000]][i_f] is None, "恐惧贪婪还没有的年份:这一维不存在,不是 0"
    assert vec[days[100]] == [None] * len(cs.DIMS), "历史不足 MIN_HIST ⇒ 全 None"
    assert feats[days[150]][cs.DIMS.index("dist_200")] is None and feats[days[199]][cs.DIMS.index("dist_200")] is not None


def test_a_gap_in_the_calendar_resets_rolling_windows():
    days, price, mvrv, puell, hash30, fng = _series(600)
    del price[days[300]]
    feats = cs.features(price, mvrv, puell, hash30, fng)
    assert feats[days[301 + 50]][cs.DIMS.index("dist_200")] is None, "缺口之后 200 日窗口重来"
    assert feats[days[301 + 199]][cs.DIMS.index("dist_200")] is not None


def test_distance_uses_shared_dims_only_and_refuses_thin_overlap():
    a = [0.0, 1.0, None, 2.0, 0.0, 0.0, None, None]
    b = [0.0, 0.0, 5.0, 2.0, 0.0, 0.0, 9.0, None]
    assert cs.distance(a, b) == pytest.approx(math.sqrt(1.0 * 8 / 5))
    assert cs.distance([1.0] * 4 + [None] * 4, [1.0] * 8) is None


def test_analogs_only_use_days_whose_outcome_is_known_and_episodes_collapse_clusters():
    days, price, mvrv, puell, hash30, fng = _series()
    vec = cs.pit_vectors(cs.features(price, mvrv, puell, hash30, fng))
    d = days[2500]
    near = cs.analogs(vec, d)
    assert near and max(s for _, s in near) <= days[2500 - 181]
    assert [x for x, _ in near] == sorted(x for x, _ in near)
    assert cs.episodes(["2020-01-01", "2020-01-05", "2020-02-01", "2020-06-01", "2021-01-01"]) == 3
    r = cs.read(vec, price, d)
    assert r["ok"] and abs(sum(r["probs"].values()) - 1.0) < 1e-9 and 1 <= r["episodes"] <= r["n"] <= cs.K
    w = r["episodes"] / (r["episodes"] + cs.SHRINK_M)
    assert r["probs"]["up"] == pytest.approx(w * r["raw"]["up"] + (1 - w) * r["base"]["up"]), "按独立段数向无条件频率收缩"


def test_stance_needs_both_a_tilt_and_independent_history():
    base = {"ok": True, "episodes": 5, "tilt_excess": 0.30}
    assert cs.stance(base) == "add" and cs.target_weight("add") == 1.0
    assert cs.stance({**base, "tilt_excess": -0.30}) == "trim" and cs.target_weight("trim") == 0.35
    assert cs.stance({**base, "tilt_excess": 0.10}) == "hold" and cs.target_weight("hold") == 0.70
    assert cs.stance({**base, "episodes": 2}) == "hold", "近邻全挤在一两段历史里 ⇒ 不表态"
    assert cs.stance({"ok": False}) == "hold"


def test_weekly_scenarios_pass_the_ledger_validator_and_are_written_once_a_week(monkeypatch):
    from src.data.evaluation import scenario_ledger as sl
    import src.api.store as store
    days, price, mvrv, puell, hash30, fng = _series()
    rows = [{"series": s, "d": d, "value": v} for s, m in (("btc_price_usd", price), ("btc_mvrv", mvrv), ("btc_puell", puell),
                                                            ("btc_hash_30d", hash30), ("fng", fng)) for d, v in m.items()]

    async def read_all(table, params):
        assert table == "macro_daily" and "order" in params
        return rows
    v = asyncio.run(cs.view(read_all))
    today = dt.date.fromisoformat(v["d"])
    es = cs.scenario_entries(v["d"], v["close"], v["probs"])
    assert [sl.validate({**e, "author": cs.AUTHOR}, today) for e in es] == [[], [], []]
    assert es[0]["op"] == "lt" and "hi" in es[0] and es[2]["op"] == "gt" and "lo" in es[2]
    kv, wrote = {}, []

    async def kget(k):
        return kv.get(k), None

    async def kset(k, val, ttl=None):
        kv[k] = val
        return True

    async def submit(entries, author, now=None):
        wrote.append((author, [e["id"] for e in entries]))
        return {"ok": True}

    async def fake_view(read_all=None):
        return v
    monkeypatch.setattr(store, "redis_get_key_status", kget)
    monkeypatch.setattr(store, "redis_set_key", kset)
    monkeypatch.setattr(sl, "submit", submit)
    monkeypatch.setattr(cs, "view", fake_view)
    r1 = asyncio.run(cs.run_once())
    r2 = asyncio.run(cs.run_once())
    assert r1["written"] == 3 and r2["written"] == 0 and len(wrote) == 1 and wrote[0][0] == "seth:cycle-space"
