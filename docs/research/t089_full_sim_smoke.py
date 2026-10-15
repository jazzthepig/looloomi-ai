"""smoke test — verify modules import and key symbols exist."""
import sys
sys.path.insert(0, "docs/research")
import t089_full_sim as f
import t089_panel_loader as p
import t089_two_dimensions as t
print("OK full_sim; arms:", f.ARMS_NON_CORE, "caps:", f.SINGLE_BOOK_CAP_NON_TILT, f.TILT_CAP)
print("OK panel_loader; cols:", p.PANEL_COLS, "loaders:", list(p.LOADERS))
print("OK two_dimensions; candidates:", t.CANDIDATES, "exposures:", t.EXPOSURES)

# Test cs_halfwidth / shrink / evidence with synthetic data
import pandas as pd
import numpy as np
rng = np.random.default_rng(42)
n = 200
idx = pd.date_range("2023-01-02", periods=n, freq="D")
a = (1 + rng.normal(0.001, 0.02, n)).cumprod()
b = (1 + rng.normal(0.001, 0.02, n)).cumprod()
ser_a = pd.Series(a, index=idx)
ser_b = pd.Series(b, index=idx)
ev = f.evidence(ser_a, ser_b, idx[-1])
print("evidence n_days:", ev.get("n_days"), "mu:", ev.get("mu"), "sigma:", ev.get("sigma"),
      "mu_lo_cs:", ev.get("mu_lo_cs"), "mu_post:", ev.get("mu_post"))

# Test decide with synthesized arms
dec = f.decide(idx[-1], {"multiplier": ser_a, "portfolio_layer": ser_a, "cis_tilt": ser_a}, ser_b)
print("decide weights:", dec["weights"])

# Compose-nav integration smoke (§Seth-1015a #2):合成一个 5 列 panel,
# 跑一次 compose_nav + 两次 random(4-arm / 5-arm),确认两套分位能算出来。
panel = pd.DataFrame({
    "d":               idx,
    "core_u":          a,
    "multiplier":      b,
    "portfolio_layer": a * (1 + rng.normal(0, 0.005, n)),
    "cis_tilt":        b * (1 + rng.normal(0, 0.005, n)),
    "btc":             a * (1 + rng.normal(0, 0.003, n)),
})
# 把每列索引换成 d(否则 _evidence_window 接到的是 RangeIndex)
panel_ix = panel.set_index("d")
rds = f.rebalance_dates(panel)
fund_nav, decisions = f.compose_nav(panel_ix, rds)
rng2 = np.random.default_rng(7)
nav_4 = f.random_compose_nav_4arm(panel_ix, rds, rng2)
nav_5 = f.random_compose_nav_5arm(panel_ix, rds, rng2)
m_fund = f.metrics(fund_nav)
m_4 = f.metrics(nav_4)
m_5 = f.metrics(nav_5)
print(f"compose_nav fund: total={m_fund['total_return']:+.2%} maxDD={m_fund['max_dd']:+.2%} n_days={m_fund['n_days']}")
print(f"random 4-arm:      total={m_4['total_return']:+.2%} maxDD={m_4['max_dd']:+.2%}")
print(f"random 5-arm:      total={m_5['total_return']:+.2%} maxDD={m_5['max_dd']:+.2%}")
assert len(decisions) > 0, "compose_nav 没产出决策"
assert len(fund_nav) == len(panel), "fund_nav 长度应与 panel 一致"
assert m_4["n_days"] > 0 and m_5["n_days"] > 0, "random 4/5 臂应各产一条 NAV"
print("smoke OK")