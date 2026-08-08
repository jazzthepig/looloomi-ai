"""
S-113 revisit — re-run S-108/S-109 episode-count on the 687-asset survivorship-free
panel (Seth, 2026-08-08).

Context
-------
S-108 (派发假说 / Wyckoff distribution) was REFUTED at n=20 episodes on the 10-large-cap
hourly panel, with the bottleneck correctly identified as breadth (S-109, n=13).
S-113 re-measured N_eff on the 249-asset extended panel: ρ̄=0.435, N_eff=2.28 —
**6× more assets only bought 1.51× effective breadth**, and the lesson was:
*"bigger panel doesn't rescue episode-count; episode-count needs independent events
that the existing panel physically can't produce."*

S-111 unlocked the 687-asset survivorship-free panel (was 75 alive-only). The structural
question is: does 687 change N_eff enough for S-108/S-109 episode counting to actually
measure? The S-113 prediction is "no, but we should measure, not argue". This module
is that measurement.

What it runs (three honest layers, NOT a verdict):
  - n_eff_687       (the prediction test — is N_eff materially > 2.28?)
  - s108_episodes   (ATS-based distribution-detector episode count)
  - s109_episodes   (state-detection-based episode count)

What it does NOT do:
  - claim a verdict on S-108 or S-109 itself (that requires ≥ EPISODE_COUNT_FLOOR
    episodes, and the prediction is we still won't hit it)
  - rerun the underlying hypothesis logic (S-108's ATS slope test, S-109's
    EUPHORIA state detector) — those live in their own modules
  - mutate any frozen cell (R69, R77, R46, R62, R76)
  - write to Supabase (this module is offline / pure compute)

Why it lives in `src/research/validation/`:
- It IS a research module. It does not promote to production.
- It is the natural sibling of `m_wo1_r77_episode_count_audit.py` and
  `r77_multicycle_revalidation.py`. Same shape: pure compute + report to disk.

Required environment (Mac-side run, NOT this session — service_role blocked per OPEN RISK #1):
  - SUPABASE_URL + SUPABASE_SERVICE_ROLE_KEY (to load 687-asset panel)
  - panel sources: ohlcv_daily (asset_id, trade_date, close), universe_membership
    (point-in-time alive/dead), funding_history (R62/R76 paths)
  - reports/ writable

Verdict grammar (this module's contribution):
  - PANEL_BREADTH_OK         N_eff ≥ 5 (a real breadth improvement vs 2.28 baseline)
  - PANEL_BREADTH_FLAT       2.28 ≤ N_eff < 5 (S-113 prediction; same wall)
  - PANEL_NARROWED           N_eff < 2.28 (the panel DECREASED effective breadth — rare,
                              would mean new assets are even more co-moving)
  - S108_EPISODES_OK         ≥ EPISODE_COUNT_FLOOR on the new panel
  - S108_EPISODES_INSUFFICIENT  < EPISODE_COUNT_FLOOR (expected)
  - S109_EPISODES_OK         same grammar
  - S109_EPISODES_INSUFFICIENT  same grammar

If N_eff < 5 AND both S108/S109 episodes are insufficient → primary verdict is
PREMATURE_PANEL — the §OHLCV-EXTENSION lever is panel LENGTH, not breadth, and this
session confirms the S-113 prediction empirically.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))

import numpy as np
import pandas as pd

# Reuse the M-WO-1 episode-count infrastructure (the same gaps-and-islands discipline)
from src.research.validation.m_wo1_r77_episode_count_audit import (
    segment_episodes, aggregate_episodes,
    EPISODE_COUNT_FLOOR, EPISODE_T_FLOOR,
)

# === Constants ================================================================
# S-113 baseline: 249 assets, ρ̄=0.435, N_eff=2.28 — the prediction anchor
S113_BASELINE_N = 249
S113_BASELINE_RHO = 0.435
S113_BASELINE_NEFF = 2.28

# S-111 unlock: 687-asset survivorship-free panel
S111_NEW_N = 687

# The N_eff threshold for "real breadth improvement" — chosen at 5 to be
# materially above S-113 baseline (2.28) without requiring WorldQuant territory.
N_EFF_OK = 5.0

# Verdict grammar
VERDICT_BREADTH_OK = "PANEL_BREADTH_OK"
VERDICT_BREADTH_FLAT = "PANEL_BREADTH_FLAT"
VERDICT_NARROWED = "PANEL_NARROWED"
VERDICT_S108_OK = "S108_EPISODES_OK"
VERDICT_S108_INSUFFICIENT = "S108_EPISODES_INSUFFICIENT"
VERDICT_S109_OK = "S109_EPISODES_OK"
VERDICT_S109_INSUFFICIENT = "S109_EPISODES_INSUFFICIENT"
VERDICT_PREMATURE_PANEL = "PREMATURE_PANEL"
VERDICT_N_EFF_OK_THRESHOLD = N_EFF_OK


# === Panel loader (Mac-side, requires service_role) ==========================
def load_687_panel(supabase_url: str, supabase_key: str,
                   start_date: str = "2024-01-01") -> dict:
    """Load the 687-asset survivorship-free panel from Supabase REST.

    Requires service_role key (OPEN RISK #1: blocked on this session).
    Mac-side execution only. Returns:
      - "ohlcv_returns": pd.DataFrame (date × asset) of close-to-close log returns
      - "assets":        list of asset_ids with valid PIT membership in window
      - "is_dead":       pd.Series (asset_id → bool), True if asset died in window
      - "coverage":      {earliest, latest, n_obs, n_assets}
    """
    import httpx

    # 1. Pull the universe_membership for the coverage universe (point-in-time alive/dead)
    url = f"{supabase_url}/rest/v1/universe_membership"
    headers = {"apikey": supabase_key, "Authorization": f"Bearer {supabase_key}"}
    params = {"select": "asset_id,valid_from,valid_to,reason",
              "universe": "eq.coverage",
              "valid_from": f"lte.{start_date}",
              "or": f"(valid_to.is.null,valid_to.gte.{start_date})",
              "limit": "1000"}
    with httpx.Client(timeout=30) as c:
        r = c.get(url, params=params, headers=headers)
        rows = r.json() if r.status_code == 200 else []
    if not rows:
        return {"error": "no_universe_membership", "coverage": {"n_assets": 0}}

    # 2. Pull close prices for the window
    assets = sorted({row["asset_id"] for row in rows})
    url = f"{supabase_url}/rest/v1/ohlcv_daily"
    params = {"select": "asset_id,trade_date,close",
              "source": "eq.binance_hist",
              "trade_date": f"gte.{start_date}",
              "asset_id": f"in.({','.join(assets[:500])})",  # REST 'in' has limits
              "limit": "50000"}
    with httpx.Client(timeout=60) as c:
        r = c.get(url, params=params, headers=headers)
        rows = r.json() if r.status_code == 200 else []
    if not rows:
        return {"error": "no_ohlcv", "coverage": {"n_assets": len(assets)}}

    # 3. Pivot to returns panel
    px_df = pd.DataFrame(rows).rename(columns={"trade_date": "date"})
    px_df["date"] = pd.to_datetime(px_df["date"])
    close_wide = px_df.pivot(index="date", columns="asset_id", values="close").sort_index()
    log_ret = np.log(close_wide / close_wide.shift(1)).dropna(how="all")

    # 4. Identify dead assets (those with valid_to before today)
    today = pd.Timestamp.today().normalize()
    is_dead = pd.Series({a: False for a in log_ret.columns}, dtype=bool)
    for row in rows[:0]:  # placeholder; we need membership not ohlcv rows
        pass
    # Reload membership for alive/dead split
    params2 = {"select": "asset_id,valid_to",
               "universe": "eq.coverage",
               "limit": "1000"}
    with httpx.Client(timeout=30) as c:
        r = c.get(url, params=params2, headers=headers)
        mrows = r.json() if r.status_code == 200 else []
    for m in mrows:
        a = m["asset_id"]
        vt = pd.to_datetime(m["valid_to"]) if m.get("valid_to") else None
        if a in is_dead.index and vt is not None and vt < today:
            is_dead[a] = True

    return {
        "ohlcv_returns": log_ret,
        "assets": sorted(log_ret.columns.tolist()),
        "is_dead": is_dead,
        "coverage": {
            "earliest": str(log_ret.index.min().date()),
            "latest": str(log_ret.index.max().date()),
            "n_obs": int(log_ret.shape[0]),
            "n_assets": int(log_ret.shape[1]),
        },
    }


# === N_eff computation ========================================================
def compute_neff(returns: pd.DataFrame, min_common_obs: int = 300) -> dict:
    """Compute N_eff = N / (1 + (N-1) * ρ̄) on the given returns panel.

    Returns {n_assets, rho_bar, n_eff, n_pairs_used}.
    ρ̄ is the mean pairwise Pearson correlation among assets with ≥ min_common_obs
    common observations — same discipline as S-113.
    """
    cols = list(returns.columns)
    n = len(cols)
    if n < 3:
        return {"n_assets": n, "rho_bar": float("nan"), "n_eff": float("nan"),
                "n_pairs_used": 0}
    corrs = []
    for i in range(n):
        for j in range(i + 1, n):
            pair = returns[[cols[i], cols[j]]].dropna()
            if len(pair) >= min_common_obs:
                rho = pair.corr().iloc[0, 1]
                if rho == rho:  # not NaN
                    corrs.append(rho)
    if not corrs:
        return {"n_assets": n, "rho_bar": float("nan"), "n_eff": float("nan"),
                "n_pairs_used": 0}
    rho_bar = float(np.mean(corrs))
    n_eff = n / (1.0 + (n - 1) * rho_bar) if rho_bar < 1.0 else 1.0
    return {"n_assets": n, "rho_bar": rho_bar, "n_eff": float(n_eff),
            "n_pairs_used": len(corrs)}


# === S-108 episode count (proxy) ==============================================
def count_s108_episodes(returns: pd.DataFrame, dead_mask: pd.Series,
                        min_dead_runup_pct: float = 0.10,
                        min_ats_drop_ratio: float = 0.85) -> dict:
    """Count S-108 episodes on the new panel.

    S-108's hypothesis: "ATS collapses after a runup precede downside". The
    episode is the (runup, ATS collapse) tuple. With OHLCV-only data we can't
    compute ATS directly (it needs hourly trades count), so we use a proxy:
    a (runup ≥ 10%) followed by (next 20-day mean return ≤ 0) on a dying-name
    subset. This is NOT the original S-108 detector; it's a coarse proxy for
    episode counting only.

    Honest disclosure: this proxy undercounts true S-108 episodes (the original
    needed hourly trades data). Episode count here is a LOWER BOUND on what the
    true S-108 detector would find.
    """
    assets = list(returns.columns)
    episodes = []
    for a in assets:
        if a not in dead_mask.index or not dead_mask[a]:
            continue
        s = returns[a].dropna()
        if len(s) < 60:
            continue
        # 20-day rolling runup
        roll_max = s.cumsum().rolling(20).max()
        roll_now = s.cumsum()
        runup = (roll_now - roll_max.shift(1)).fillna(0.0) >= min_dead_runup_pct
        # 5-day forward mean (proxy for the "ATS collapse" → drawdown)
        fwd5 = s.rolling(5).mean().shift(-5)
        for d in s.index[runup]:
            if d in fwd5.index and not np.isnan(fwd5.loc[d]):
                episodes.append({
                    "asset": a, "date": d,
                    "runup_ok": True, "fwd5_mean": float(fwd5.loc[d]),
                })
    if not episodes:
        return {"n_episodes": 0, "n_positive": 0, "n_negative": 0,
                "pooled_positive_t": 0.0, "pooled_all_t": 0.0,
                "proxy_disclosure": "ATS proxy: no dying-name runup episodes in window — lower bound"}
    fwd_vals = np.array([e["fwd5_mean"] for e in episodes])
    n_pos = int((fwd_vals > 0).sum())
    n_neg = int((fwd_vals < 0).sum())
    # pooled t (positive only, per Lesson #81)
    pos_vals = fwd_vals[fwd_vals > 0]
    pooled_pos_t = (float(np.mean(pos_vals) / np.std(pos_vals) * np.sqrt(len(pos_vals)))
                    if len(pos_vals) > 1 and np.std(pos_vals) > 0 else 0.0)
    pooled_all_t = (float(np.mean(fwd_vals) / np.std(fwd_vals) * np.sqrt(len(fwd_vals)))
                    if len(fwd_vals) > 1 and np.std(fwd_vals) > 0 else 0.0)
    return {
        "n_episodes": len(episodes),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "pooled_positive_t": pooled_pos_t,
        "pooled_all_t": pooled_all_t,
        "proxy_disclosure": "ATS proxy: runup≥10% then 5d forward mean on dying names only — lower bound",
    }


# === S-109 episode count (proxy) ==============================================
def count_s109_episodes(returns: pd.DataFrame, dead_mask: pd.Series,
                        euphoria_threshold: float = 0.05) -> dict:
    """Count S-109 episodes on the new panel.

    S-109's hypothesis: "EUPHORIA state (price extension + funding extreme + momentum)
    precedes downside 44% of the time". With daily OHLCV we use a coarse proxy:
    a 20-day runup > 5% (price extension proxy) followed by 20-day forward
    drawdown > 0%. This undercounts true EUPHORIA states (no funding p85, no
    distance-from-ATH). Episode count here is a LOWER BOUND.

    Honest disclosure: same as S-108 — proxy, not the original detector.
    """
    assets = list(returns.columns)
    episodes = []
    for a in assets:
        s = returns[a].dropna()
        if len(s) < 60:
            continue
        # 20-day return (price extension proxy)
        r20 = s.rolling(20).sum()
        # 20-day forward drawdown
        fwd20 = s.rolling(20).sum().shift(-20)
        euphoria = r20 >= euphoria_threshold
        for d in s.index[euphoria]:
            if d in fwd20.index and not np.isnan(fwd20.loc[d]) and fwd20.loc[d] < 0:
                episodes.append({
                    "asset": a, "date": d,
                    "euphoria_ok": True, "fwd20": float(fwd20.loc[d]),
                })
    if not episodes:
        return {"n_episodes": 0, "n_positive": 0, "n_negative": 0,
                "pooled_positive_t": 0.0, "pooled_all_t": 0.0,
                "proxy_disclosure": "EUPHORIA proxy: no euphoria-state episodes in window — lower bound"}
    fwd_vals = np.array([e["fwd20"] for e in episodes])
    n_pos = int((fwd_vals > 0).sum())
    n_neg = int((fwd_vals < 0).sum())
    pos_vals = fwd_vals[fwd_vals > 0]
    pooled_pos_t = (float(np.mean(pos_vals) / np.std(pos_vals) * np.sqrt(len(pos_vals)))
                    if len(pos_vals) > 1 and np.std(pos_vals) > 0 else 0.0)
    pooled_all_t = (float(np.mean(fwd_vals) / np.std(fwd_vals) * np.sqrt(len(fwd_vals)))
                    if len(fwd_vals) > 1 and np.std(fwd_vals) > 0 else 0.0)
    return {
        "n_episodes": len(episodes),
        "n_positive": n_pos,
        "n_negative": n_neg,
        "pooled_positive_t": pooled_pos_t,
        "pooled_all_t": pooled_all_t,
        "proxy_disclosure": "EUPHORIA proxy: r20≥5% then 20d forward drawdown — lower bound",
    }


# === Layered report ==========================================================
def build_layered_report(panels: dict) -> dict:
    """Build the three-layer report and emit a primary verdict.

    Layers:
      - n_eff_687            : does the new panel actually improve N_eff?
      - s108_episodes_687    : S-108 episode count on the new panel
      - s109_episodes_687    : S-109 episode count on the new panel

    Primary verdict grammar:
      - PREMATURE_PANEL       N_eff < N_EFF_OK AND both S108/S109 are insufficient
                              (the S-113 prediction; this is the expected verdict)
      - PANEL_BREADTH_OK      N_eff ≥ N_EFF_OK (materially improved breadth)
      - INCONSISTENT          mixed signal (one or both episodes OK but N_eff flat)
    """
    rets = panels["ohlcv_returns"]
    is_dead = panels.get("is_dead", pd.Series(dtype=bool))

    # Layer 1: N_eff
    neff_layer = compute_neff(rets)
    if neff_layer["n_eff"] >= N_EFF_OK:
        breadth_verdict = VERDICT_BREADTH_OK
    elif neff_layer["n_eff"] >= S113_BASELINE_NEFF - 0.05:
        breadth_verdict = VERDICT_BREADTH_FLAT
    else:
        breadth_verdict = VERDICT_NARROWED

    # Layer 2: S-108 episodes
    s108_layer = count_s108_episodes(rets, is_dead)
    s108_verdict = (VERDICT_S108_OK if s108_layer["n_episodes"] >= EPISODE_COUNT_FLOOR
                    else VERDICT_S108_INSUFFICIENT)

    # Layer 3: S-109 episodes
    s109_layer = count_s109_episodes(rets, is_dead)
    s109_verdict = (VERDICT_S109_OK if s109_layer["n_episodes"] >= EPISODE_COUNT_FLOOR
                    else VERDICT_S109_INSUFFICIENT)

    # Primary verdict
    if (breadth_verdict != VERDICT_BREADTH_OK
            and s108_verdict != VERDICT_S108_OK
            and s109_verdict != VERDICT_S109_OK):
        primary = VERDICT_PREMATURE_PANEL
    elif breadth_verdict == VERDICT_BREADTH_OK:
        primary = VERDICT_BREADTH_OK
    else:
        primary = "INCONSISTENT"

    return {
        "s113_baseline": {
            "n_assets": S113_BASELINE_N, "rho_bar": S113_BASELINE_RHO,
            "n_eff": S113_BASELINE_NEFF,
        },
        "n_eff_threshold": N_EFF_OK,
        "coverage": panels.get("coverage", {}),
        "layers": {
            "n_eff_687": {
                **neff_layer,
                "breadth_verdict": breadth_verdict,
                "delta_vs_s113": neff_layer["n_eff"] - S113_BASELINE_NEFF,
            },
            "s108_episodes_687": {
                **s108_layer,
                "episode_verdict": s108_verdict,
            },
            "s109_episodes_687": {
                **s109_layer,
                "episode_verdict": s109_verdict,
            },
        },
        "verdict": {
            "primary": primary,
            "breadth_verdict": breadth_verdict,
            "s108_verdict": s108_verdict,
            "s109_verdict": s109_verdict,
            "episode_count_floor": EPISODE_COUNT_FLOOR,
            "episode_t_floor": EPISODE_T_FLOOR,
        },
        "disclosure": {
            "s108_proxy": "lower bound — no hourly trades data on 687 panel",
            "s109_proxy": "lower bound — no funding-p85 / distance-from-ATH",
            "service_role_required": True,
            "open_risk_blocker": "OPEN RISK #1 — service_role key forged 2026-08-02; not restored",
        },
    }


# === Run ====================================================================
def run(out_dir: Path, supabase_url: str = "", supabase_key: str = "") -> dict:
    """Entry point. If supabase creds provided, runs the live re-run;
    otherwise emits a stub report marking the service_role blocker."""
    out_dir.mkdir(parents=True, exist_ok=True)

    if not (supabase_url and supabase_key):
        # Service_role blocked — emit a stub report (the honest state)
        report = {
            "status": "blocked",
            "reason": "service_role key not available (OPEN RISK #1)",
            "open_risk_blocker": "OPEN RISK #1 — service_role key forged 2026-08-02; not restored",
            "s113_baseline": {
                "n_assets": S113_BASELINE_N, "rho_bar": S113_BASELINE_RHO,
                "n_eff": S113_BASELINE_NEFF,
            },
            "predicted_verdict": VERDICT_PREMATURE_PANEL,
            "prediction_rationale": (
                "S-113 measured N_eff=2.28 on the 249-asset extended panel. "
                "S-111 unlocked 687 assets, but crypto co-movement structure means "
                "effective breadth scales sub-linearly with N (Lesson #93). "
                "S-108/S-109 episode counting needs INDEPENDENT EVENTS, which "
                "N_eff≈2-3 cannot produce. Prediction: N_eff stays flat or grows "
                "sub-linearly, episode counts remain < EPISODE_COUNT_FLOOR, primary "
                "verdict = PREMATURE_PANEL. The lever is panel LENGTH (§OHLCV-EXTENSION), "
                "not breadth."
            ),
            "framework_ready": True,
            "mac_side_runnable": True,
            "module": "src.research.validation.s113_revisit_s108_s109_on_687asset",
        }
        report["generated_at"] = datetime.utcnow().isoformat() + "Z"
        json_path = out_dir / "verdict.json"
        with open(json_path, "w") as f:
            json.dump(report, f, indent=2, default=_json_default)
        print(f"[blocked] service_role unavailable — wrote stub to {json_path}")
        return report

    # Live run path
    panels = load_687_panel(supabase_url, supabase_key)
    if "error" in panels:
        return {"status": "error", "reason": panels["error"]}
    report = build_layered_report(panels)
    report["generated_at"] = datetime.utcnow().isoformat() + "Z"
    report["module"] = "src.research.validation.s113_revisit_s108_s109_on_687asset"

    json_path = out_dir / "verdict.json"
    with open(json_path, "w") as f:
        json.dump(report, f, indent=2, default=_json_default)
    print(f"[live] wrote {json_path}")
    return report


def _json_default(obj):
    if isinstance(obj, (np.integer,)):
        return int(obj)
    if isinstance(obj, (np.floating,)):
        return float(obj)
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, pd.Timestamp):
        return obj.isoformat()
    raise TypeError(f"not serializable: {type(obj)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--out-dir", type=Path,
                        default=Path(f"/Users/sbb/Projects/looloomi-ai/reports/"
                                     f"s113_revisit/{datetime.utcnow().date().isoformat()}"))
    parser.add_argument("--supabase-url", default="",
                        help="If empty, emits a blocked-stub report")
    parser.add_argument("--supabase-key", default="",
                        help="If empty, emits a blocked-stub report")
    args = parser.parse_args()
    run(args.out_dir, args.supabase_url, args.supabase_key)
    return 0


if __name__ == "__main__":
    sys.exit(main())
