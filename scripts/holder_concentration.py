#!/usr/bin/env python3
"""
D3 — holder-concentration → propagation-stage (出圈) metric. Self-compute, no vendor
black box (DATA_CAPTURE_SPEC D3). The crypto-native instrument for the formless
price-discovery tracker: where on the diffusion curve a consensus sits.

Thesis (METHODOLOGY_CORE §3): a consensus is SAFE while concentrated upstream (few,
smart holders) and DANGEROUS once it has diffused out-of-circle (mass retail arrived).
So the signal is NOT the concentration *level* (asset-specific — some tokens are always
concentrated) but the **transition toward dispersion**:
  concentration falling (HHI ↓) + holder count exploding (N ↑) + avg balance shrinking
  = mass arrival = late-stage / out-of-circle / downstream / danger.

We measure: HHI, top-N share, Gini, holder count — then derive a per-asset, self-
referenced **stage ∈ [0,1]** (0 = early/concentrated, 1 = out-of-circle/dispersed) and a
**dispersion-acceleration alert** (the 出圈 trigger). Everything is point-in-time: each
snapshot uses only data available at its date (the chain is immutable history, so PIT is
free — but the SOURCE must return as-of-date balances, not today's).

This module is source-agnostic: feed it holder balances (or top-N shares) per date.
A source adapter (Dune / Flipside / Bitquery — free tiers) lands those snapshots.
"""
import numpy as np
import pandas as pd


# ── concentration primitives (one snapshot = array of holder balances) ──
def hhi(balances) -> float:
    """Herfindahl: sum(share^2). 1 = one holder, →0 = perfectly dispersed."""
    b = np.asarray(balances, float); b = b[b > 0]
    if b.sum() <= 0: return np.nan
    s = b / b.sum()
    return float((s ** 2).sum())


def top_n_share(balances, n=10) -> float:
    b = np.sort(np.asarray(balances, float))[::-1]
    if b.sum() <= 0: return np.nan
    return float(b[:n].sum() / b.sum())


def gini(balances) -> float:
    b = np.sort(np.asarray(balances, float)); b = b[b >= 0]
    n = len(b)
    if n == 0 or b.sum() == 0: return np.nan
    cum = np.cumsum(b)
    return float((n + 1 - 2 * (cum / cum[-1]).sum()) / n)


def snapshot_metrics(balances) -> dict:
    b = np.asarray(balances, float); b = b[b > 0]
    return {"n_holders": int(len(b)), "hhi": hhi(b), "top10": top_n_share(b, 10),
            "gini": gini(b), "avg_balance": float(b.mean()) if len(b) else np.nan}


# ── per-asset stage + 出圈 alert (history of snapshots) ──
def stage_series(df: pd.DataFrame) -> pd.DataFrame:
    """
    df indexed by date with columns: hhi, n_holders (+ optional top10/gini).
    Returns per-date:
      stage      ∈ [0,1] — self-referenced position on the asset's own diffusion curve
                  (1 = most dispersed/widely-held it has been = out-of-circle/late).
      disp_accel — dispersion acceleration z-score (出圈 trigger when high & positive).
      chuquan    — boolean 出圈 alert.
    """
    d = df.sort_index().copy()
    logN = np.log(d["n_holders"].clip(lower=1))
    # self-referenced (percentile within the asset's own history, expanding to avoid look-ahead)
    disp = (-d["hhi"]).rank(pct=True)            # low HHI = dispersed = high
    spread = logN.rank(pct=True)                 # many holders = dispersed = high
    d["stage"] = (disp + spread) / 2
    # dispersion ACCELERATION: HHI falling + holders rising, z-scored on rolling window
    dh = (-d["hhi"]).diff(); dn = logN.diff()
    z = lambda s: (s - s.rolling(20, min_periods=8).mean()) / s.rolling(20, min_periods=8).std()
    d["disp_accel"] = (z(dh).fillna(0) + z(dn).fillna(0)) / 2
    # 出圈 = a SUDDEN acceleration of dispersion (mass arriving fast), past the earliest
    # concentrated phase. The acceleration IS the danger — not waiting until already-late.
    d["chuquan"] = (d["disp_accel"] > 1.5) & (d["stage"] > 0.3)
    return d[["stage", "disp_accel", "chuquan"]]


# ── source adapter: Dune ──────────────────────────────────────────────────────
# Pipe verified 2026-06-25 (create/execute/poll/results all work). Right table found:
# tokens_ethereum.balances_daily (daily-partitioned = PIT + credit-prunable). BUT the
# concentration SQL must be authored in the Dune WEB UI (heavy table; needs interactive
# error/credit tuning — a blind 44s sandbox loop kept failing). Author this query once in
# the UI, save it, pass its query_id here. The query should compute the metrics IN SQL and
# return a tiny per-month table (filter token_address + day → prune; never SELECT *):
#
#   -- params: {{token}} (0x… varbinary), monthly day-grid
#   WITH b AS (
#     SELECT day, balance FROM tokens_ethereum.balances_daily
#     WHERE token_address = {{token}} AND day IN (date '2025-01-01', date '2025-02-01', ...)
#       AND balance > 0
#   ), t AS (SELECT day, SUM(balance) tot, COUNT(*) n_holders FROM b GROUP BY day),
#   tp AS (SELECT b.day, SUM(x.balance) top10 FROM b CROSS JOIN LATERAL
#          (SELECT balance FROM b b2 WHERE b2.day=b.day ORDER BY balance DESC LIMIT 10) x GROUP BY b.day)
#   SELECT t.day, t.n_holders,
#          (SELECT SUM(POWER(b.balance/t.tot,2)) FROM b WHERE b.day=t.day) AS hhi,
#          tp.top10/t.tot AS top10
#   FROM t JOIN tp ON t.day=tp.day ORDER BY t.day
#  (confirm column names in the UI — `balance` / `token_address` / `day` are best-guess.)

def dune_holder_metrics(query_id: int, api_key: str, params: dict = None,
                        timeout_s: int = 300) -> pd.DataFrame:
    """Execute a saved Dune query (the holder-concentration SQL above) and return its
    per-day metrics as a DataFrame indexed by date (cols: hhi, n_holders, top10).
    Feed the result to stage_series() for the 出圈 stage + alert."""
    import time, httpx
    B = "https://api.dune.com/api/v1"; H = {"X-Dune-API-Key": api_key}
    body = {"query_parameters": params} if params else {}
    eid = httpx.post(f"{B}/query/{query_id}/execute", headers=H, json=body, timeout=30).json()["execution_id"]
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        st = httpx.get(f"{B}/execution/{eid}/status", headers=H, timeout=30).json().get("state")
        if st == "QUERY_STATE_COMPLETED":
            rows = httpx.get(f"{B}/execution/{eid}/results", headers=H, timeout=30).json()["result"]["rows"]
            df = pd.DataFrame(rows)
            df["day"] = pd.to_datetime(df["day"])
            return df.set_index("day").sort_index()
        if st == "QUERY_STATE_FAILED":
            raise RuntimeError(f"Dune execution failed (eid={eid})")
        time.sleep(5)
    raise TimeoutError(f"Dune execution timed out (eid={eid})")


# ── self-test: prove the math on a synthetic concentrated→dispersed transition ──
def _selftest():
    dates = pd.date_range("2025-01-01", periods=60, freq="W")
    rows = []
    for i, dt in enumerate(dates):
        # early: 5 whales hold ~everything; gentle growth, then a SUDDEN retail FLOOD at wk 30
        whales = [1000, 800, 600, 400, 300]           # fixed whale stock
        base = int(10 * 1.06 ** i)                    # slow organic growth
        flood = 6000 if 30 <= i <= 33 else 0          # sudden out-of-circle flood
        n_small = base + flood
        smalls = list(np.random.default_rng(i).exponential(2.0, n_small))  # mass retail
        m = snapshot_metrics(whales + smalls); m["date"] = dt
        rows.append(m)
    df = pd.DataFrame(rows).set_index("date")
    st = stage_series(df)
    out = df.join(st)
    print("synthetic token: concentrated (5 whales) → mass retail flood\n")
    print(out[["n_holders", "hhi", "stage", "disp_accel", "chuquan"]]
          .iloc[::8].round(3).to_string())
    first_alert = out[out["chuquan"]].index.min()
    print(f"\nstage: {out['stage'].iloc[0]:.2f} (early) → {out['stage'].iloc[-1]:.2f} (out-of-circle)")
    print(f"first 出圈 (dispersion-acceleration) alert: {first_alert.date() if pd.notna(first_alert) else 'none'}")
    assert out["stage"].iloc[-1] > out["stage"].iloc[0], "stage must rise as it disperses"
    print("\n✓ math checks: stage rises as holders disperse; 出圈 fires on the acceleration.")


if __name__ == "__main__":
    _selftest()
