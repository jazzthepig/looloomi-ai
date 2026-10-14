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
print("smoke OK")