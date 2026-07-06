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


# ── Pre-出圈 Wyckoff/VSA detection thresholds ─────────────────────────────
# These classify the period BEFORE chuquan fires (when we're still upstream /
# in-circle) into the 4 cold→hot lifecycle stages that mirror what smart-money
# players look for on-chain: forced-selling climax → quiet accumulation → spring
# retest → first markup. Each maps to a damp factor in cause_proximity.py:
#   capitulation 0.45 · dry_up 0.30 (lowest) · spring_test 0.35 · early_markup 0.50
# Thresholds are PROVISIONAL — same caveat as Seth's _SEASON_DAMP. Calibrate from
# 2018-12 / 2022-11 BTC bottoms + memecoin blow-offs once D3 + OHLCV history lands.
_PRE_MIN_HISTORY   = 14        # need ≥14d for MA30 (computed from available history) + 7d delta
_CAP_VOL_RATIO     = 2.5       # climax: vol_now / vol_MA30
_CAP_HOLDER_DROP7  = -0.05     # panic: holders down ≥5% over 7d
_CAP_STAGE_MAX     = 0.40      # climax happens while still concentrated
_DRYUP_VOL_RATIO   = 0.60      # quiet: vol_now / vol_MA30
_DRYUP_HOLDER_MIN  = -0.02     # holders stable (not fleeing, not flooding in)
_SPRING_VOL_RATIO  = 1.00      # low: vol_now / vol_MA30
_SPRING_STAGE_MAX  = 0.30      # spring happens at the bottom of diffusion
_EM_VOL_RATIO      = 0.80      # pickup: vol rising above dry baseline
_EM_HOLDER_RISE7   =  0.02     # first demand: holders up ≥2% over 7d
_EM_STAGE_MIN      = 0.25      # markup begins as stage rises from accumulation


def _classify_pre_chuquan(d: pd.DataFrame, idx: int) -> str:
    """Classify a pre-出圈 date into the Wyckoff lifecycle stage. Reads `volume`,
    `n_holders`, `stage` columns. Returns one of:
        capitulation  — climax volume + holders fleeing (panic sell, smart money still selling)
        dry_up        — quiet volume, holders stable (smart money accumulating in silence)
        spring_test   — low-volume retest of lows (last weak hands shaken, supply exhausting)
        early_markup  — volume picking up, holders starting to grow (first demand back)
        pre           — default fallback (no clear signal, still upstream / in-circle)

    Order of checks matters — capitulation FIRST (highest urgency), then dry_up vs
    spring_test (both at low stage but distinguishable by volume), then early_markup
    (rising stage), then pre.
    """
    if "volume" not in d.columns or idx < _PRE_MIN_HISTORY:
        return "pre"

    vol_now    = float(d["volume"].iloc[idx])
    vol_ma30   = float(d["volume"].iloc[max(0, idx - 30):idx].mean())
    holders    = float(d["n_holders"].iloc[idx])
    holders_7d = float(d["n_holders"].iloc[max(0, idx - 7)])
    stage_now  = float(d["stage"].iloc[idx])

    if vol_ma30 <= 0 or holders_7d <= 0:
        return "pre"

    vol_ratio = vol_now / vol_ma30
    holder_chg_7d = (holders - holders_7d) / max(1.0, holders_7d)

    # 1. Capitulation — forced-selling climax (loudest signal first)
    if vol_ratio > _CAP_VOL_RATIO and holder_chg_7d < _CAP_HOLDER_DROP7 \
            and stage_now < _CAP_STAGE_MAX:
        return "capitulation"

    # 2. Spring test — low-vol retest of lows (stage plateauing low AFTER capitulation,
    #    supply drying up). Detected by stage-low + low vol.
    if vol_ratio < _SPRING_VOL_RATIO and stage_now < _SPRING_STAGE_MAX:
        return "spring_test"

    # 3. Dry-up — quiet accumulation (low vol, holders NOT fleeing). Strict vol cutoff
    #    so we don't double-count spring_test (which has slightly higher vol_ratio <1.0).
    if vol_ratio < _DRYUP_VOL_RATIO and holder_chg_7d >= _DRYUP_HOLDER_MIN:
        return "dry_up"

    # 4. Early markup — vol rising from quiet baseline, holders starting to grow.
    if vol_ratio > _EM_VOL_RATIO and holder_chg_7d > _EM_HOLDER_RISE7 \
            and stage_now > _EM_STAGE_MIN:
        return "early_markup"

    return "pre"


# ── per-asset stage + 出圈 alert + season lifecycle (history of snapshots) ──
def stage_series(df: pd.DataFrame, momentum_window_days: int = 60,
                 ohlcv: "pd.DataFrame | None" = None) -> pd.DataFrame:
    """
    df indexed by date with columns: hhi, n_holders (+ optional top10/gini).
    Returns per-date:
      stage              ∈ [0,1] — self-referenced position on the asset's own diffusion curve
                          (1 = most dispersed/widely-held it has been = out-of-circle/late).
      disp_accel         — dispersion acceleration z-score (出圈 trigger when high & positive).
      chuquan            — boolean 出圈 EVENT alert (fires on the day mass retail arrives).
      days_since_chuquan — int; days since the most recent chuquan=True (-1 if never).
                          Each chuquan fire resets the clock (a new flood starts a fresh
                          window). This is the "time-into-season" clock.
      season             — full Wyckoff/VSA lifecycle (B-extension 2026-07-06):
                            pre-出圈 (Wyckoff): capitulation → dry_up → spring_test → early_markup → pre
                            post-出圈:        momentum → stale
                          Contract strings — consumer (cause_proximity.py) maps each to a
                          risk damp/floor:
                            capitulation ×0.45 · dry_up ×0.30 (LOWEST) · spring_test ×0.35
                            early_markup ×0.50 · pre (baseline) · momentum ×0.55
                            stale floor 0.72.
                          Back-compat: if `ohlcv` is None OR a row's history is too short
                          for the Wyckoff detector (<30d), pre-出圈 falls back to "pre"
                          (same string, identical to the 2026-07-06 3-season behavior).

    `ohlcv` (optional) — DataFrame indexed by date with a `volume` column (anything
    with the same DatetimeIndex works). Used ONLY for the pre-出圈 Wyckoff
    classification (volume climax, dry-up). If absent, the pre-出圈 window
    stays at "pre" (no degradation of post-出圈 behavior). The OHLCV pipeline
    is a separate P1 (MINIMAX_SYNC §11.8) — once it lands this parameter is
    wired in by the producer (fetch_holder_concentration.process_and_write).

    `momentum_window_days` defaults to 60 (upper bound of "1-2 months"). Tune via the
    parameter if your asset class trades a tighter window — e.g. memecoins might be 30,
    L1s might be 75. The right value is per-asset-class; for now one global default keeps
    the contract simple.
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
    # concentrated phase. The acceleration IS the event — the season is what comes after.
    d["chuquan"] = (d["disp_accel"] > 1.5) & (d["stage"] > 0.3)

    # ── OHLCV join (for pre-出圈 Wyckoff detection) ──────────────────────
    # If ohlcv is provided with a `volume` column, left-join onto d on the date index.
    # Rows in d without a matching OHLCV date → NaN volume → _classify_pre_chuquan
    # falls back to "pre" (safe default). Post-出圈 season logic is unaffected.
    has_ohlcv = False
    if ohlcv is not None and not ohlcv.empty and "volume" in ohlcv.columns:
        d = d.join(ohlcv[["volume"]], how="left")
        has_ohlcv = True

    # ── SEASON: full lifecycle (cold→hot) ────────────────────────────────
    # Pre-出圈 (chuquan never fired yet) → Wyckoff detector using volume + holders + stage.
    # Post-出圈 (chuquan fired)         → days_since vs momentum_window_days.
    # Each fire resets the clock. The Wyckoff detection is per-row and PIT (only uses
    # data at-or-before that date — see the slicing [max(0, idx-30):idx] / idx-7).
    last_fire_idx: int | None = None
    days_since: list[int] = []
    season: list[str] = []
    for i, _dt in enumerate(d.index):
        if bool(d["chuquan"].iloc[i]):
            last_fire_idx = i
        if last_fire_idx is None:
            # pre-出圈: Wyckoff if OHLCV, else "pre"
            days_since.append(-1)
            season.append(_classify_pre_chuquan(d, i) if has_ohlcv else "pre")
        else:
            ds = int((d.index[i] - d.index[last_fire_idx]).days)
            days_since.append(ds)
            season.append("momentum" if ds <= momentum_window_days else "stale")
    d["days_since_chuquan"] = days_since
    d["season"] = season

    return d[["stage", "disp_accel", "chuquan", "days_since_chuquan", "season"]]


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

    # ── B-extension selftest: synthetic OHLCV exercising every pre-出圈 stage ──
    # 80 weekly snapshots, 5 phases so each Wyckoff stage has room to settle:
    #   wk  0–14  steady accumulation (small organic growth, low vol) → "pre"
    #   wk 15–17  capitulation spike (vol ×3 MA, holders flee −7%)     → "capitulation"
    #   wk 18–25  dry-up (vol ×0.4 MA, holders stable)                 → "dry_up"
    #   wk 26–28  spring test (vol ×0.7 MA, holders flat, low stage)   → "spring_test"
    #   wk 29–34  early markup (vol rising, holders up +3% / wk)       → "early_markup"
    #   wk 35–44  quiet pre-flood                                      → "pre"
    #   wk 45     chuquan FIRES (sudden retail flood)                  → "momentum" starts
    #   wk 45–54  momentum window (post-出圈 tradeable)                 → "momentum"
    #   wk 55+    post-window                                          → "stale"
    dates2 = pd.date_range("2025-01-01", periods=80, freq="W")
    rows2 = []
    rng = np.random.default_rng(42)
    MA30_BASE = 1_000.0
    for i, dt in enumerate(dates2):
        if 0 <= i <= 14:    phase = "steady"
        elif 15 <= i <= 17: phase = "capitulation"
        elif 18 <= i <= 25: phase = "dry_up"
        elif 26 <= i <= 28: phase = "spring"
        elif 29 <= i <= 34: phase = "markup"
        elif 35 <= i <= 44: phase = "steady2"
        else:               phase = "post_chuquan"
        whales = [1000, 800, 600, 400, 300]
        # Phase-aware holder dynamics: capitulation makes holders FLEE (panic sell),
        # dry-up keeps them stable (smart money buying, no crowd), spring plateau,
        # markup back to growth. Without these, holder count is monotonically rising
        # and the Wyckoff detector can't distinguish the stages.
        base_growth = int(10 * 1.06 ** i)
        holder_mult = {
            "steady":       1.00, "capitulation": 0.55, "dry_up":  1.00,
            "spring":       0.98, "markup":       1.05, "steady2": 1.02,
            "post_chuquan": 1.10,
        }[phase]
        # Anchor holder count to a phase-aware baseline so the 7-day delta
        # direction matches the phase intent (capitulation ↓, markup ↑).
        anchored_base = max(5, int(base_growth * holder_mult))
        flood = 6000 if i == 45 else 0
        n_small = anchored_base + flood
        smalls = list(rng.exponential(2.0, n_small))
        m = snapshot_metrics(whales + smalls)
        # Volume profile per phase (vs MA30_BASE = 1000)
        vol_mult = {
            "steady":       1.0, "capitulation": 3.2, "dry_up":     0.4,
            "spring":       0.7, "markup":       1.2, "steady2":    0.9,
            "post_chuquan": 1.8,
        }[phase]
        m["volume"] = max(50.0, MA30_BASE * vol_mult + rng.normal(0, 80))
        m["date"] = dt
        rows2.append(m)
    df2 = pd.DataFrame(rows2).set_index("date")
    ohlcv2 = df2[["volume"]].copy()
    holder_df2 = df2.drop(columns=["volume"])      # holder-only frame for stage_series
    st2 = stage_series(holder_df2, ohlcv=ohlcv2)
    out2 = df2.join(st2)
    print("synthetic token with OHLCV — full lifecycle demo (capitulation → dry_up → "
          "spring_test → early_markup → pre → momentum → stale):\n")
    print(f"  {'date':12} {'n_holders':>10} {'vol_ratio':>10} {'stage':>6} "
          f"{'chuquan':>8} {'days':>5} {'season':>14}")
    # Sample 5 rows per phase window so all 7 seasons appear at least once.
    sample_idx = list(range(0, 15, 3)) + list(range(15, 18)) + list(range(18, 26, 2)) \
               + list(range(26, 29)) + list(range(29, 35, 2)) + [35, 40, 44, 45, 50, 54, 55, 60]
    sample_idx = sorted(set(sample_idx))
    for i in sample_idx:
        if i >= len(out2):
            continue
        d = out2.index[i]
        vol_now = float(out2["volume"].iloc[i])
        vol_ma30 = float(out2["volume"].iloc[max(0, i - 30):i].mean()) if i >= 1 else vol_now
        vr = vol_now / vol_ma30 if vol_ma30 > 0 else 1.0
        flag = "⚠ YES" if bool(out2["chuquan"].iloc[i]) else "  -  "
        days_since = int(out2["days_since_chuquan"].iloc[i])
        days_str = "  - " if days_since < 0 else f"{days_since:>4}d"
        print(f"  {d.strftime('%Y-%m-%d'):12} "
              f"{int(out2['n_holders'].iloc[i]):>10} "
              f"{vr:>10.2f} "
              f"{out2['stage'].iloc[i]:>6.3f} "
              f"{flag:>8} "
              f"{days_str:>5} "
              f"{out2['season'].iloc[i]:>14}")
    seasons_seen = set(out2["season"])
    expected_7 = {"capitulation", "dry_up", "spring_test", "early_markup",
                  "pre", "momentum", "stale"}
    missing = expected_7 - seasons_seen
    assert not missing, (
        f"selftest should exercise all 7 lifecycle stages; missing: {sorted(missing)}. "
        f"Seen: {sorted(seasons_seen)}"
    )
    print(f"\n✓ all 7 seasons observed in the synthetic lifecycle: "
          f"{sorted(seasons_seen)}")

    # ── Original selftest (no OHLCV → pre-出圈 collapses to "pre") ──
    st = stage_series(df)            # no ohlcv → back-compat path
    out = df.join(st)
    print("\nsynthetic token: concentrated (5 whales) → mass retail flood (NO OHLCV)\n")
    print(out[["n_holders", "hhi", "stage", "disp_accel", "chuquan", "season"]]
          .iloc[::8].round(3).to_string())
    first_alert = out[out["chuquan"]].index.min()
    print(f"\nstage: {out['stage'].iloc[0]:.2f} (early) → {out['stage'].iloc[-1]:.2f} (out-of-circle)")
    print(f"first 出圈 (dispersion-acceleration) alert: {first_alert.date() if pd.notna(first_alert) else 'none'}")
    # Back-compat: no OHLCV → pre-出圈 must be "pre" for every never-fired row.
    # (Rows where chuquan never fired have days_since_chuquan == -1 → season=='pre'.
    # Rows AFTER the first fire have days_since ≥ 0 → momentum/stale regardless of
    # OHLCV presence — that's the post-出圈 path, not the Wyckoff detector.)
    never_fired = out[out["days_since_chuquan"] == -1]
    assert (never_fired["season"] == "pre").all(), \
        "no-OHLCV back-compat path must keep never-fired rows at season='pre'"
    print(f"✓ back-compat: {len(never_fired)} never-fired rows all report season='pre'")
    assert out["stage"].iloc[-1] > out["stage"].iloc[0], "stage must rise as it disperses"
    print("\n✓ math checks: stage rises as holders disperse; 出圈 fires on the acceleration.")


if __name__ == "__main__":
    _selftest()
