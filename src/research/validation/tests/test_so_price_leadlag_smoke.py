"""
Smoke tests — so_price_leadlag. Sandbox-safe (pure python + random, no network/DB).
Validates the tester reproduces the two shapes it must distinguish: a price-COINCIDENT pillar
(big lead-0, ~0 lead-1 → the empirical S/O result) vs a genuinely price-LEADING pillar
(big lead-1). Run: python3 -m src.research.validation.tests.test_so_price_leadlag_smoke
"""
import os
import random
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "..")))

from src.research.validation.so_price_leadlag import (  # noqa: E402
    returns, pillar_deltas, lead_lag_profile, pooled_profile, verdict, _corr_t,
)


def _iid_returns(n, seed=7):
    r = random.Random(seed)
    return [r.gauss(0, 0.05) for _ in range(n)]


def test_returns_and_deltas():
    r = returns([100, 110, 99])
    assert r[0] is None and abs(r[1] - 0.1) < 1e-9 and abs(r[2] - (-0.1)) < 1e-9
    s = [50.0, 52.0, 51.0, 55.0]
    assert pillar_deltas(s, lead=0)[1] == 2.0            # s[1]-s[0]
    assert pillar_deltas(s, lead=1)[1] == -1.0           # s[2]-s[1]
    assert pillar_deltas(s, lead=0)[0] is None           # no prior


def test_corr_t_basic():
    r, t, n = _corr_t([1, 2, 3, 4, 5], [1, 2, 3, 4, 5])
    assert abs(r - 1.0) < 1e-3 and n == 5 and t > 5   # r clamped to 0.999999 to keep t finite


def test_coincident_pillar_is_detected():
    """Δpillar over (t-1,t] = 0.5·ret[t] ⇒ lead-0 corr ~1, lead-1 ~0 (the empirical S/O shape)."""
    ret = _iid_returns(600)
    pillar = [50.0]
    for t in range(1, len(ret)):
        pillar.append(pillar[-1] + 0.5 * ret[t])          # increment IS today's return
    prof = lead_lag_profile(ret, pillar, max_lead=2)
    assert prof[0]["rho"] > 0.9, f"contemporaneous should be strong, got {prof[0]}"
    assert abs(prof[1]["rho"]) < 0.2, f"lead+1 should be ~0, got {prof[1]}"
    assert "COINCIDENT" in verdict(prof)


def test_leading_pillar_is_detected():
    """Δpillar over (t,t+1] = 0.5·ret[t] ⇒ pillar LAGS price ⇒ lead-1 corr ~1 (nowcast justified)."""
    ret = _iid_returns(600, seed=11)
    n = len(ret)
    pillar = [50.0] * n
    for t in range(1, n - 1):
        pillar[t + 1] = pillar[t] + 0.5 * ret[t]          # tomorrow's pillar reacts to today's ret
    prof = lead_lag_profile(ret, pillar, max_lead=2)
    assert prof[1]["rho"] > 0.9 and prof[1]["t"] > 2, f"lead+1 should be strong, got {prof[1]}"
    assert "LEADS" in verdict(prof)


def test_independent_pillar():
    ret = _iid_returns(600, seed=3)
    rng = random.Random(99)
    pillar = [rng.gauss(50, 5) for _ in ret]
    prof = lead_lag_profile(ret, pillar, max_lead=2)
    assert abs(prof[0]["rho"]) < 0.2 and "INDEPENDENT" in verdict(prof)


def test_pooled_matches_single_asset():
    ret = _iid_returns(400)
    pillar = [50.0]
    for t in range(1, len(ret)):
        pillar.append(pillar[-1] + 0.5 * ret[t])
    single = lead_lag_profile(ret, pillar, max_lead=1)
    pooled = pooled_profile([(ret, pillar)], max_lead=1)
    assert abs(single[0]["rho"] - pooled[0]["rho"]) < 1e-9, "pool of one == single asset"


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} so_price_leadlag smoke tests passed")
