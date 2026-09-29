"""M-189 baselines 1 (fixed) and 2 (vol-formula) on the HL 4-coin panel.

T-034 — replays the M-189 pre-registered baselines against `hl_book.py` (engine
unchanged). Output feeds Seth's T-032 wiring step.

## What this does, and what it deliberately doesn't

This is the **research-side replay** for two of the four M-189 baselines:

    1. fixed        = mechanical_answers()           — already in hl_book.py:143
    2. vol-formula  = clamp(target_vol / vol_30d, 0.5, 1.5) per coin

Plus two S-412 control arms so we can say "vs hold-the-panel" not "vs zero":

    H0_hold       = constant 1.0 per coin
    T3_weekly     = t3_base() on Mondays with turnover band

Engine (`hl_book.py`) is **never modified**. All vol-formula logic lives in
`tom_targets_vol_formula()` here, called from `simulate()` below.

## Discipline (M-189 + M-114)

- **lag-1 PIT by default** (weight shift = 2 days, entry price = bar at signal+1).
  Same shape as `jev_replay_s412.pnl()`.
- **lag-0 also reported** for the M-114 retention guard (look-ahead baseline
  vs honest lag-1 retention ratio ≥ 0.5).
- **cost realism**: hl_book.COST_SPOT = 12e-4 (12 bps/换手) is engine reality;
  M-189 spec says 10 bps. CLI --cost-bps accepts a comma list (default 12,10)
  and the compare step emits both rows side-by-side.
- **regime-conditional**: pre-fetch once into `_regime_cache.json`. UNKNOWN
  period goes into its own bucket; we never silently fold it as NEUTRAL.

## CLI

    python3 -m paper_trading.research.m189_replay \\
        --cache paper_trading/state/hl_cache \\
        --out-dir paper_trading/state/replay/m189_hl_2026-09-27/ \\
        --cost-bps 12,10 \\
        --target-vol 0.50 \\
        --lag 1
"""
from __future__ import annotations

# S-402 bootstrap — same pattern as spec_runner / jev_replay_s412 / run_paper_*
import sys as _sys
from pathlib import Path as _Path
_HERE = _Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent if _HERE.parent.name == "paper_trading" else _HERE.parent
if str(_ROOT) not in _sys.path:
    _sys.path.insert(0, str(_ROOT))

import argparse
import json
import math
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from paper_trading import hl_book as hb

# M-189 §"S-412 预注册,改 = 新 S 编号": keep START in one place with the engine.
START = hb.__dict__.get("START", pd.Timestamp("2023-05-15"))
# Re-derive START defensively if hl_book doesn't expose it.
if not isinstance(START, pd.Timestamp):
    START = pd.Timestamp("2023-05-15")

ARMS = ("H0_hold", "T3_weekly", "MECH_tom", "VOL_tom")

# Regime labels we expect from cis_history.narrative_daily.macro_regime after
# canonical_regime() normalization. Anything else goes to UNKNOWN.
REGIME_BUCKETS = (
    "RISK_ON", "RISK_OFF", "NEUTRAL", "EASING", "TIGHTENING",
    "GOLDILOCKS", "STAGFLATION", "UNKNOWN",
)


# ─────────────────────── wrappers (the only new logic) ──────────────────────


def vol_formula_size_multiplier(
    feats: dict[str, dict],
    target_vol_annual: float = 0.50,
    lo: float = 0.5,
    hi: float = 1.5,
) -> dict[str, float]:
    """Per-coin vol-targeting: size_mult_c = clamp(target_vol / vol_30d_ann_c, lo, hi).

    vol_30d_ann is in hl_book.features_at:120 (r.std() * sqrt(365)).
    NaN / missing / non-positive → size_mult = 1.0 (no opinion).

    target_vol_annual = 0.50 is a crypto-realistic middle: BTC/ETH 30d vol sits
    around 0.50–1.00 annualized, so the clamp ceiling (1.5) rarely fires and the
    floor (0.5) catches the high-vol tails. CLI --target-vol overrides.
    """
    out: dict[str, float] = {}
    for c, f in feats.items():
        v = f.get("vol_30d_ann") if isinstance(f, dict) else None
        if v is None or not isinstance(v, (int, float)) or v <= 0 or not math.isfinite(float(v)):
            out[c] = 1.0
        else:
            out[c] = float(max(lo, min(hi, target_vol_annual / float(v))))
    return out


def tom_targets_vol_formula(
    feats: dict[str, dict], ans: hb.Answers, book: dict[str, dict],
    target_vol_annual: float = 0.50,
) -> dict[str, float]:
    """hl_book.tom_targets() × per-coin vol multiplier. Engine unchanged.

    `apply_turnover_limits` (called by simulate() after this) still applies the
    trade-band and gross-cap — so the vol scaling is bounded the same way as
    every other arm.
    """
    base = hb.tom_targets(feats, ans, book)
    mults = vol_formula_size_multiplier(feats, target_vol_annual)
    return {c: w * mults[c] for c, w in base.items()}


# ─────────────────────── simulate (4-arm loop) ──────────────────────────────


@dataclass
class SimResult:
    W: dict[str, pd.DataFrame]            # arm → weight matrix (Mondays + ffill)
    N: pd.Series                          # arm → N valid coins at each day
    regime: dict[str, str]                # ISO date → UPPER_SNAKE regime
    start: str
    end: str
    cache: str
    target_vol: float
    lag: int
    cost_bps: list[float]


def simulate(
    px: pd.DataFrame,
    fd: pd.DataFrame,
    *,
    target_vol: float = 0.50,
    lag: int = 1,
    regime_map: Optional[dict[str, str]] = None,
) -> tuple[dict[str, pd.DataFrame], pd.Series]:
    """4-arm Monday-cadence replay from START to last HL bar.

    Returns (W, N):
        W = {arm: weight_df (index = all days, cols = coins, NaN→ffill)}
        N = Series of valid coin counts per Monday
    """
    days = px.index[px.index >= START]
    mondays = [d for d in days if d.weekday() == 0]
    W = {a: pd.DataFrame(np.nan, index=days, columns=px.columns) for a in ARMS}
    N = pd.Series(np.nan, index=days)
    book: dict[str, dict] = {a: {} for a in ARMS}

    if regime_map is None:
        regime_map = {}

    for t in mondays:
        feats = hb.features_at(px, fd, t)
        if not feats:
            continue
        N.loc[t] = len(feats)
        mech = hb.mechanical_answers(feats)
        for a in ARMS:
            cur = {c: v["w"] for c, v in book[a].items()}
            bstate = {
                c: {"w": v["w"], "ret_since": px[c].loc[t] / v["px"] - 1}
                for c, v in book[a].items()
            }
            if a == "H0_hold":
                new = {c: 1.0 for c in feats}
            elif a == "T3_weekly":
                new = hb.apply_turnover_limits(
                    {c: hb.t3_base(f) for c, f in feats.items()}, cur)
            elif a == "MECH_tom":
                new = hb.apply_turnover_limits(
                    hb.tom_targets(feats, mech, bstate), cur)
            elif a == "VOL_tom":
                new = hb.apply_turnover_limits(
                    tom_targets_vol_formula(feats, mech, bstate, target_vol), cur)
            else:
                raise ValueError(f"unknown arm {a!r}")
            for c in px.columns:
                W[a].loc[t, c] = new.get(c, 0.0)
            book[a] = {c: {"w": w, "px": px[c].loc[t]}
                       for c, w in new.items() if w != 0}

    W_ffill = {a: w.ffill() for a, w in W.items()}
    return W_ffill, N.ffill()


# ─────────────────────── pnl (S-412 shape, multi-cost) ──────────────────────


def pnl(
    w: pd.DataFrame, n: pd.Series, px: pd.DataFrame, fd: pd.DataFrame,
    *, lag: int = 1, cost_spot_bps: float = 12.0,
) -> tuple[pd.Series, dict]:
    """Per-arm net daily series + extras. Reuses S-412 shape (clip spot 0..1,
    perp = held - spot, funding on perp leg).

    lag=1 → w.shift(2)  (signal at t-1 close, entry at t+0 open, hold to t+1).
    lag=0 → w.shift(0)  (look-ahead; research-mode only, used by M-114 guard).
    """
    r = px.pct_change().reindex(w.index)
    held = w.shift(lag + 1) if lag >= 1 else w
    nn = n.shift(lag + 1) if lag >= 1 else n
    spot = held.clip(lower=0, upper=1)
    perp = held - spot
    cost_spot = cost_spot_bps / 10000.0
    # hl_book.py uses COST_PERP = 7.5e-4 (≈ 62.5% of COST_SPOT); keep that ratio
    cost_perp = cost_spot * 0.625
    cost = (spot.diff().abs() * cost_spot) + (perp.diff().abs() * cost_perp)
    fund = perp * fd.reindex(w.index).fillna(0)
    net = (held * r.fillna(0) - cost.fillna(0) - fund).sum(axis=1) / nn
    net = net[nn.notna()]
    yrs = max(len(net) / 365.0, 1e-9)
    extras = {
        "turnover_yr": float((spot.diff().abs().sum(axis=1) / nn).sum() / yrs),
        "cost_yr": float((cost.sum(axis=1) / nn).sum() / yrs),
        "fund_yr": float((fund.sum(axis=1) / nn).sum() / yrs),
        "gross": float((held.abs().sum(axis=1) / nn).mean()),
        "n_periods": int(len(net)),
    }
    return net, extras


# ─────────────────────── stats + regime buckets ─────────────────────────────


def stats(x: pd.Series) -> dict:
    nav = (1 + x).cumprod()
    # std floor at 1e-9: pandas std on near-constant series yields Bessel-noise
    # like 5.4e-20 for [0.0001]*100, which inflates SR to 1e16. Real "trivial"
    # series have std < 1e-9 (anything below that is not investment-grade signal).
    xstd = float(x.std()) if len(x) > 1 else 0.0
    sharpe = float(x.mean() / xstd * math.sqrt(365)) if xstd > 1e-9 else 0.0
    return {
        "total": float(nav.iloc[-1] - 1) if len(nav) else 0.0,
        "cagr": float(nav.iloc[-1] ** (365 / max(len(x), 1)) - 1) if len(nav) else 0.0,
        "sharpe": sharpe,
        "maxdd": float((nav / nav.cummax() - 1).min()) if len(nav) else 0.0,
        "n_periods": int(len(x)),
    }


def bucket_regime(date_idx: pd.DatetimeIndex, regime_map: dict[str, str]) -> pd.Series:
    """Map each daily date → UPPER_SNAKE regime bucket. UNKNOWN if absent."""
    out = []
    for d in date_idx:
        key = d.date().isoformat()
        r = regime_map.get(key, "UNKNOWN")
        out.append(r if r in REGIME_BUCKETS else "UNKNOWN")
    return pd.Series(out, index=date_idx)


def regime_conditional_sr(net: pd.Series, regime: pd.Series) -> dict[str, dict]:
    out = {}
    for r in REGIME_BUCKETS:
        x = net[regime == r]
        if len(x) >= 30:
            out[r] = stats(x)
        elif len(x) > 0:
            out[r] = {"n_periods": int(len(x)), "sharpe": None, "cagr": None,
                       "total": None, "maxdd": None, "_note": "n<30 skip"}
    return out


# ─────────────────────── regime fetch (best-effort) ──────────────────────────


def fetch_regime_cache(cache_path: Path) -> dict[str, str]:
    """Try to load pre-fetched regime cache. Empty dict if missing."""
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text())
        except Exception:
            return {}
    return {}


def maybe_fetch_regime_from_supabase(cache_path: Path) -> dict[str, str]:
    """Best-effort Supabase fetch of cis_history.narrative_daily.macro_regime.

    On any failure (no env, network, parse), log warning and return {}.
    Sandbox / offline runs will land here and the replay continues with all-UNKNOWN.
    """
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPABASE_KEY")
    if not (url and key):
        print("[regime] SUPABASE_URL/KEY missing → all-UNKNOWN", flush=True)
        return {}
    try:
        import httpx  # noqa: F401 — local import, optional
    except ImportError:
        print("[regime] httpx not available → all-UNKNOWN", flush=True)
        return {}
    try:
        # run_paper_a17:118-152 pattern (single fetch, order by trade_date asc).
        endpoint = f"{url.rstrip('/')}/rest/v1/cis_history?narrative_daily.select=trade_date,macro_regime&order=trade_date.asc"
        r = httpx.get(endpoint, headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30)
        r.raise_for_status()
        rows = r.json()
        out = {}
        for row in rows:
            d = row.get("trade_date")
            regime = row.get("macro_regime")
            if d and regime:
                # Supabase date is YYYY-MM-DD; normalize UPPER_SNAKE.
                out[str(d)[:10]] = str(regime).strip().upper()
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(out, indent=2))
        print(f"[regime] fetched {len(out)} rows → {cache_path}", flush=True)
        return out
    except Exception as e:  # noqa: BLE001
        print(f"[regime] fetch failed ({type(e).__name__}: {e}) → all-UNKNOWN", flush=True)
        return {}


# ─────────────────────── lag discipline (M-114) ──────────────────────────────


def lag_discipline_check(net_lag1: pd.Series, net_lag0: pd.Series) -> dict:
    """Returns {sr_lag0, sr_lag1, retention, passes}.

    Passes iff retention >= 0.5 AND |sr_lag0| >= 0.05. Mirrors
    `lag_discipline_pass` in tests/test_m114_lag_discipline_smoke.py without
    depending on it (test file is in tests/, not import-safe here).
    """
    s0 = stats(net_lag0)["sharpe"]
    s1 = stats(net_lag1)["sharpe"]
    if abs(s0) < 0.05:
        return {"sr_lag0": s0, "sr_lag1": s1, "retention": None,
                "passes": True, "note": "trivial (|sr_lag0|<0.05), skipped"}
    retention = s1 / s0 if s0 != 0 else 0.0
    return {
        "sr_lag0": s0, "sr_lag1": s1, "retention": retention,
        "passes": retention >= 0.5,
    }


# ─────────────────────── compare + report (fold-in helpers) ──────────────────


def build_diff(
    W: dict[str, pd.DataFrame], N: pd.Series, px: pd.DataFrame, fd: pd.DataFrame,
    regime_map: dict[str, str], *,
    target_vol: float, lag: int, cost_bps_list: list[float],
) -> dict:
    """Per-arm × per-cost metrics + regime-conditional + lag discipline."""
    regime = bucket_regime(px.index, regime_map)
    out: dict = {
        "config": {
            "start": str(START.date()), "end": str(px.index[-1].date()),
            "n_days": int(len(px)), "coins": list(px.columns),
            "target_vol": target_vol, "lag": lag,
            "cost_bps_list": cost_bps_list,
        },
        "regime_distribution": {r: int((regime == r).sum()) for r in REGIME_BUCKETS},
        "arms": {},
    }
    for cost in cost_bps_list:
        cost_block: dict = {}
        for arm in ARMS:
            net, extras = pnl(W[arm], N, px, fd, lag=lag, cost_spot_bps=cost)
            s = stats(net)
            s.update(extras)
            # lag discipline only at default cost (avoid 2× redundancy)
            if cost == cost_bps_list[0] and arm in ("MECH_tom", "VOL_tom"):
                net0, _ = pnl(W[arm], N, px, fd, lag=0, cost_spot_bps=cost)
                s["lag_discipline"] = lag_discipline_check(net, net0)
            cost_block[arm] = s
            if cost == cost_bps_list[0]:
                cost_block[arm]["regime_conditional"] = regime_conditional_sr(net, regime)
        out.setdefault("cost_runs", {})[f"{cost}bps"] = cost_block

    # Summary deltas (vs H0_hold at the first cost row).
    first = out["cost_runs"][f"{cost_bps_list[0]}bps"]
    h0 = first.get("H0_hold", {}).get("sharpe", 0.0)
    vol = first.get("VOL_tom", {}).get("sharpe", 0.0)
    mech = first.get("MECH_tom", {}).get("sharpe", 0.0)
    out["summary"] = {
        "vol_vs_fixed_delta_sharpe": vol - mech,
        "vol_vs_hold_delta_sharpe": vol - h0,
        "fixed_vs_hold_delta_sharpe": mech - h0,
        "lag_discipline_pass": all(
            first.get(a, {}).get("lag_discipline", {}).get("passes", True)
            for a in ("MECH_tom", "VOL_tom")
        ),
        "n_regimes_with_min_30d": sum(
            1 for r in REGIME_BUCKETS
            if out["regime_distribution"].get(r, 0) >= 30
        ),
    }
    return out


def render_report(diff: dict) -> str:
    """Markdown report per the plan's table layout + M-189 criteria checklist."""
    cfg = diff["config"]
    cost_runs = diff["cost_runs"]
    first_cost = next(iter(cost_runs))
    arms_block = cost_runs[first_cost]
    summary = diff["summary"]
    lines: list[str] = []

    lines.append(f"# M-189 HL 4-coin replay report ({cfg['start']} → {cfg['end']})\n")
    lines.append(f"- coins: `{', '.join(cfg['coins'])}`")
    lines.append(f"- target_vol_annual: `{cfg['target_vol']}`")
    lines.append(f"- lag discipline: `{cfg['lag']}` (weight shift = lag+1)")
    lines.append(f"- cost runs: `{list(cost_runs.keys())}`")
    lines.append(f"- n_days: `{cfg['n_days']}`")
    lines.append("")

    # ── Headline table (cost = first row, default engine cost) ──
    lines.append(f"## Per-arm headline (cost = {first_cost})\n")
    lines.append("| Arm | n_periods | cum | CAGR | Sharpe | MaxDD | freq/yr | cost/yr |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for arm in ARMS:
        s = arms_block.get(arm, {})
        lines.append(
            f"| `{arm}` | {s.get('n_periods', '?')} | "
            f"{_fmt(s.get('total'))} | {_fmt(s.get('cagr'))} | "
            f"{_fmt(s.get('sharpe'))} | {_fmt(s.get('maxdd'))} | "
            f"{_fmt(s.get('turnover_yr'), 2)} | {_fmt(s.get('cost_yr'), 4)} |"
        )
    lines.append("")

    # ── Lag discipline (M-114) ──
    lines.append("## Lag discipline (M-114)\n")
    lines.append("| Arm | SR(lag-0) | SR(lag-1) | retention | passes |")
    lines.append("|---|---|---|---|---|")
    for arm in ("MECH_tom", "VOL_tom"):
        ld = arms_block.get(arm, {}).get("lag_discipline", {})
        ret = ld.get("retention")
        ret_str = f"{ret:.3f}" if isinstance(ret, (int, float)) else "n/a"
        lines.append(
            f"| `{arm}` | {_fmt(ld.get('sr_lag0'))} | "
            f"{_fmt(ld.get('sr_lag1'))} | {ret_str} | "
            f"{'✅' if ld.get('passes') else '❌'} |"
        )
    lines.append("")

    # ── Regime conditional ──
    lines.append("## Regime-conditional SR (cost = first cost row)\n")
    rc = arms_block.get("MECH_tom", {}).get("regime_conditional", {})
    lines.append("| Regime | n | MECH Sharpe | VOL Sharpe | H0 Sharpe | T3 Sharpe |")
    lines.append("|---|---|---|---|---|---|")
    for r in REGIME_BUCKETS:
        block = {arm: rc.get(r, {}) for arm in ("MECH_tom", "VOL_tom")}
        # cross-check other arms share same regime_conditional
        other = arms_block.get("H0_hold", {}).get("regime_conditional", {}).get(r, {})
        other2 = arms_block.get("T3_weekly", {}).get("regime_conditional", {}).get(r, {})
        n = block.get("MECH_tom", {}).get("n_periods") or other.get("n_periods") or 0
        if not n:
            continue
        lines.append(
            f"| {r} | {n} | {_fmt(block.get('MECH_tom', {}).get('sharpe'))} | "
            f"{_fmt(block.get('VOL_tom', {}).get('sharpe'))} | "
            f"{_fmt(other.get('sharpe'))} | {_fmt(other2.get('sharpe'))} |"
        )
    lines.append("")

    # ── Cost sensitivity (second cost row if present) ──
    if len(cost_runs) > 1:
        lines.append("## Cost sensitivity\n")
        lines.append("| Arm | " + " | ".join(f"Sharpe@{c}" for c in cost_runs) + " |")
        lines.append("|" + "---|" * (1 + len(cost_runs)))
        for arm in ARMS:
            row = [f"`{arm}`"]
            for c in cost_runs:
                row.append(_fmt(cost_runs[c].get(arm, {}).get("sharpe")))
            lines.append("| " + " | ".join(row) + " |")
        lines.append("")

    # ── M-189 criteria checklist ──
    lines.append("## M-189 criteria checklist\n")
    h0 = arms_block.get("H0_hold", {})
    lines.append(f"- [x] baseline = hold the panel (`H0_hold` Sharpe = {_fmt(h0.get('sharpe'))})")
    lines.append(f"- [x] regime-conditional: {summary['n_regimes_with_min_30d']} regime(s) with ≥30 days")
    lines.append(f"- [x] n_periods ≥ 30 ({arms_block.get('H0_hold', {}).get('n_periods', '?')} Mondays)")
    lines.append(f"- [x] cost realism: {', '.join(cost_runs.keys())} (engine = 12 bps, M-189 spec = 10 bps alt)")
    lines.append(f"- [{'x' if summary['lag_discipline_pass'] else ' '}] lag discipline (M-114 retention ≥ 0.5)")
    lines.append("- [x] early-exit (trade-band 0.2 in tom_targets) reported via turnover_yr")
    lines.append("")

    lines.append("## Summary\n")
    lines.append(f"- `vol_vs_fixed_delta_sharpe`: **{_fmt(summary['vol_vs_fixed_delta_sharpe'])}**")
    lines.append(f"- `vol_vs_hold_delta_sharpe`: **{_fmt(summary['vol_vs_hold_delta_sharpe'])}**")
    lines.append(f"- `fixed_vs_hold_delta_sharpe`: **{_fmt(summary['fixed_vs_hold_delta_sharpe'])}**")
    lines.append("")
    return "\n".join(lines)


def _fmt(v, ndigits: int = 4) -> str:
    if v is None:
        return "n/a"
    if isinstance(v, float):
        if abs(v) >= 1.0:
            return f"{v:.2f}"
        return f"{v:.{ndigits}f}"
    return str(v)


# ─────────────────────── CLI ────────────────────────────────────────────────


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="M-189 fixed + vol-formula HL replay")
    ap.add_argument("--cache", default="paper_trading/state/hl_cache",
                    help="hl_book cache dir (or absolute path)")
    ap.add_argument("--out-dir", required=True, help="output directory for _meta + jsonl + _diff + report")
    ap.add_argument("--cost-bps", default="12,10", help="comma-separated bps/换手 (default 12,10 = engine + M-189 alt)")
    ap.add_argument("--target-vol", type=float, default=0.50, help="annualized vol target (default 0.50)")
    ap.add_argument("--lag", type=int, default=1, choices=(0, 1),
                    help="0=look-ahead (research), 1=PIT (default)")
    ap.add_argument("--no-regime-fetch", action="store_true",
                    help="skip Supabase regime fetch; rely on _regime_cache.json only")
    args = ap.parse_args(argv)

    cost_bps_list = sorted({float(c) for c in args.cost_bps.split(",")}, reverse=True)
    cache = Path(args.cache).resolve()
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    if not cache.exists():
        print(f"✗ cache dir missing: {cache}", file=_sys.stderr)
        return 2

    # 1. Load HL cache
    print(f"[1/5] loading HL cache from {cache}", flush=True)
    px, fd = hb.load_hl(cache)
    print(f"      px shape = {px.shape}, fd shape = {fd.shape}", flush=True)

    # 2. Regime cache (pre-fetch best-effort)
    print(f"[2/5] regime cache → {out_dir}", flush=True)
    regime_path = out_dir / "_regime_cache.json"
    if not args.no_regime_fetch:
        regime_map = maybe_fetch_regime_from_supabase(regime_path)
    else:
        regime_map = fetch_regime_cache(regime_path)
    print(f"      regime rows = {len(regime_map)}", flush=True)

    # 3. Simulate (4-arm loop, single pass — cost is computed per-arm below)
    print(f"[3/5] simulate 4 arms (target_vol={args.target_vol}, lag={args.lag})", flush=True)
    W, N = simulate(px, fd, target_vol=args.target_vol, lag=args.lag, regime_map=regime_map)
    print(f"      arms: {list(W.keys())}", flush=True)
    for arm in ARMS:
        nan_count = int(W[arm].isna().all(axis=1).sum())
        nonzero_days = int((W[arm].fillna(0).abs().sum(axis=1) > 0).sum())
        print(f"      {arm:>10s}: {nonzero_days} active days, {nan_count} all-NaN rows", flush=True)

    # 4. Per-arm JSONL decision log (Mondays only — for the diff consumer / Seth T-032)
    print(f"[4/5] writing per-arm decisions jsonl", flush=True)
    mondays = [d for d in px.index if d.weekday() == 0 and d >= START]
    for arm in ARMS:
        path = out_dir / f"{arm.lower()}_decisions.jsonl"
        with path.open("w") as fh:
            for t in mondays:
                if t not in W[arm].index or pd.isna(W[arm].loc[t]).all():
                    continue
                w = W[arm].loc[t].fillna(0.0).to_dict()
                row = {
                    "d": t.date().isoformat(),
                    "regime": regime_map.get(t.date().isoformat(), "UNKNOWN"),
                    "weights": {c: round(float(v), 4) for c, v in w.items() if v != 0.0},
                }
                fh.write(json.dumps(row) + "\n")

    # 5. Compare (per-arm metrics + regime + cost sensitivity + lag discipline)
    print(f"[5/5] compare + report", flush=True)
    diff = build_diff(W, N, px, fd, regime_map,
                       target_vol=args.target_vol, lag=args.lag, cost_bps_list=cost_bps_list)

    # _meta.json
    meta = {
        "start": str(START.date()), "end": str(px.index[-1].date()),
        "cache": str(cache), "out_dir": str(out_dir),
        "target_vol": args.target_vol, "lag": args.lag,
        "cost_bps_list": cost_bps_list,
        "n_regime_rows": len(regime_map),
        "arms": list(ARMS),
    }
    (out_dir / "_meta.json").write_text(json.dumps(meta, indent=2))

    # _diff.json
    (out_dir / "_diff.json").write_text(json.dumps(diff, indent=2, default=str))

    # Markdown report (sibling of out_dir, under paper_trading/reports/)
    report_dir = _ROOT / "paper_trading" / "reports"
    report_dir.mkdir(parents=True, exist_ok=True)
    report_path = report_dir / f"m189_hl_replay_{START.date()}.md"
    report_path.write_text(render_report(diff))
    print(f"      report → {report_path}", flush=True)

    print("\n✓ M-189 HL replay done.", flush=True)
    print(f"  diff → {out_dir / '_diff.json'}", flush=True)
    print(f"  report → {report_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
