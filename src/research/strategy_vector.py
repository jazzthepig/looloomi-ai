"""
Strategy Vector — strategies as first-class, located objects (Seth, 2026-07-21).
================================================================================

⚠️ DEPRECATED (2026-07-22, build-order #3). The CANONICAL strategy-vector stack is
`src/data/vector/{strategy_schema,strategy_embedder,strategy_store}.py` (30-dim, Redis-backed,
router-wired). As of the #3 convergence it now carries everything this module pioneered:
NaN-honesty (I1), the binary validity floor (`is_disqualified`, I4), `coverage_gaps()`, `redundancy()`,
NaN-aware cosine. Do NOT build new work against this file.

This module is retained ONLY because `src/research/embed_graveyard.py` still imports
`build/save/format_library` from it, and a lossless port is blocked on two canonical-schema gaps
(both touch MECHANISM_SPEC §3, a Minimax-owned contract — coordinate before changing):
  1. cost representation — this module stores a `cost_slope` (d(perf)/d(bps)); the canonical schema
     stores absolute Sharpe at 0/2/5/10 bps. No lossless conversion without a base Sharpe.
  2. tri-state validity — here `leakage_clean=None` means UNVERIFIED (≠ leaky, does not disqualify,
     e.g. swing_overlay_v9). Canonical `pit_clean` is a bool; None→False would FALSELY disqualify.
Once canonical gains (1) a cost-slope field and (2) a tri-state/`pit_verified` flag, migrate
embed_graveyard and `git rm` this file (Mac-side). Tracked as build-order #3b.

Implements `docs/MECHANISM_SPEC.md` §3. Extends the pattern of `src/data/vector/embedder.py`
(an 18-dim *asset* embedding) to **strategies**, so a sleeve stops being a pass/fail verdict and
becomes a point in a space we can search, compare and find holes in.

WHY THIS EXISTS — three problems, one build:

1. **The gauntlet was throwing away the library.** `regime_robustness` *killed* anything that worked
   in some regimes and not others. That is what killed vol carry ("CALM-REGIME"), the crowding book
   ("MECHANISM REAL, F1 regime flip"), R33 ("β on a friendly window"), V5c. Each of those is a
   **sleeve with a domain**, not a failure. Our doctrine says `library beats hero`; our practice was
   enforcing hero. Here, regime behaviour becomes **coordinates** instead of a death sentence.
2. **Parallel agents collide in prose.** Minimax A/B/C + Seth writing findings into shared markdown
   loses work (the ledger was overwritten mid-session 2026-07-21). Emitting *vectors into a common
   space* is append-only and merge-safe by construction.
3. **We had no map of what we don't have.** Coverage gaps in this space tell us which sleeve to build
   next, instead of guessing.

THE VALIDITY/DURABILITY SPLIT (MECHANISM_SPEC §3) — the guardrail that keeps this honest:
  · **Binary, permanently disqualifying:** PIT/look-ahead leakage; cost-infeasibility at declared
    capacity. A leaky backtest is not "in a different lifecycle phase" — it is wrong. Capacity is a
    fact, not a season. These set `disqualified=True` and no amount of good coordinates overrides it.
  · **Dimensional, never binary:** regime fit, decay, crowding, correlation. Coordinates only.
Without the floor, "it's just a different phase" explains every bad result and nothing is falsifiable.
Without the dimensional half, we delete the library chasing an all-weather hero that does not exist.

⚠️ ALL performance inputs must be **β-adjusted and net of realistic costs** (R62: raw `a_ret − b_ret`
measured leveraged beta at β 1.4–2.4 and made a good signal look inverted). Feeding raw alpha into
this space produces a confidently wrong map.

Compliance: internal research tooling. Any surfaced output uses positioning language only.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field, asdict

import numpy as np

SCHEMA_VERSION = "sv1"

# ── the space ────────────────────────────────────────────────────────────────
# Six blocks (MECHANISM_SPEC §3). Order is the vector order; changing it bumps SCHEMA_VERSION.
DIMS: list[tuple[str, str]] = [
    # regime domain — where it works (from regime_robustness, repurposed as coordinates)
    ("regime_calm",        "risk-adj perf in calm-vol regime"),
    ("regime_stormy",      "risk-adj perf in high-vol regime"),
    ("regime_risk_on",     "risk-adj perf in risk-on"),
    ("regime_risk_off",    "risk-adj perf in risk-off"),
    ("regime_trend",       "risk-adj perf in trending tape"),
    ("regime_chop",        "risk-adj perf in chop"),
    # factor exposure — what it IS (from factor_absorption)
    ("beta_market",        "market β"),
    ("beta_momentum",      "momentum/TSMOM β"),
    ("beta_carry",         "carry/funding β"),
    ("beta_quality",       "CIS-quality β"),
    ("alpha_residual_t",   "residual α t-stat after factors"),
    # mechanics — how it trades
    ("holding_days",       "median holding period (days, log-scaled)"),
    ("turnover_yr",        "annual turnover (log-scaled)"),
    ("time_in_market",     "fraction of bars with exposure"),
    ("directionality",     "-1 short-only … 0 neutral … +1 long-only"),
    # capacity — the ceiling (P2)
    ("capacity_usd_log",   "declared capacity, log10 USD"),
    ("adv_fraction",       "per-clip size as fraction of ADV"),
    # lifecycle — where it is in its life (P3)
    ("age_days",           "days since discovery (log-scaled)"),
    ("perf_slope",         "rolling-performance slope (decay//growth)"),
    ("crowding",           "crowding proxy in its instruments"),
    # cost sensitivity — the slope, not a point
    ("cost_slope",         "d(perf)/d(bps) — how fast costs kill it"),
]
DIM_NAMES = [d[0] for d in DIMS]
NDIM = len(DIMS)


@dataclass
class StrategyVector:
    """One located strategy. `coords` is the NDIM-vector; the rest is provenance + the binary floor."""
    name: str
    coords: np.ndarray
    # ── binary validity floor — NOT coordinates ──
    disqualified: bool = False
    disqualified_reason: str = ""
    # ── provenance ──
    ledger_ref: str = ""
    status: str = "candidate"        # candidate | live | retired | refuted
    notes: str = ""
    schema: str = SCHEMA_VERSION

    def as_dict(self) -> dict:
        d = asdict(self)
        d["coords"] = {k: (None if np.isnan(v) else round(float(v), 4))
                       for k, v in zip(DIM_NAMES, self.coords)}
        return d


# ── construction ─────────────────────────────────────────────────────────────
def _sq(x, lo, hi):
    """Squash to [-1,1] over an expected range; NaN passes through as NaN (unknown ≠ zero)."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return float("nan")
    return float(np.clip(2 * (float(x) - lo) / (hi - lo) - 1, -1, 1))


def _log_sq(x, lo_log, hi_log):
    if x is None or (isinstance(x, float) and math.isnan(x)) or float(x) <= 0:
        return float("nan")
    return _sq(math.log10(float(x)), lo_log, hi_log)


def build(name: str, *, regime: dict | None = None, factors: dict | None = None,
          mechanics: dict | None = None, capacity: dict | None = None,
          lifecycle: dict | None = None, cost_slope: float | None = None,
          leakage_clean: bool | None = None, cost_feasible: bool | None = None,
          ledger_ref: str = "", status: str = "candidate", notes: str = "") -> StrategyVector:
    """Build a StrategyVector from measured inputs. Unknown dimensions stay NaN — an unmeasured
    dimension is NOT zero, and similarity must skip it rather than pretend it's average.

    Binary floor: `leakage_clean is False` OR `cost_feasible is False` ⇒ disqualified. These are the
    only two conditions that disqualify. Everything else is coordinates.
    """
    regime, factors = regime or {}, factors or {}
    mechanics, capacity = mechanics or {}, capacity or {}
    lifecycle = lifecycle or {}
    n = float("nan")
    c = np.array([
        _sq(regime.get("calm", n), -2, 3),
        _sq(regime.get("stormy", n), -2, 3),
        _sq(regime.get("risk_on", n), -2, 3),
        _sq(regime.get("risk_off", n), -2, 3),
        _sq(regime.get("trend", n), -2, 3),
        _sq(regime.get("chop", n), -2, 3),
        _sq(factors.get("beta_market", n), -1.5, 1.5),
        _sq(factors.get("beta_momentum", n), -1.5, 1.5),
        _sq(factors.get("beta_carry", n), -1.5, 1.5),
        _sq(factors.get("beta_quality", n), -1.5, 1.5),
        _sq(factors.get("alpha_t", n), -4, 4),
        _log_sq(mechanics.get("holding_days", n), -1, 2.5),     # 0.1d … ~316d
        _log_sq(mechanics.get("turnover_yr", n), 0, 3),         # 1 … 1000x/yr
        _sq(mechanics.get("time_in_market", n), 0, 1),
        _sq(mechanics.get("directionality", n), -1, 1),
        _log_sq(capacity.get("usd", n), 5, 9),                  # $100k … $1B
        _sq(capacity.get("adv_fraction", n), 0, 0.2),
        _log_sq(lifecycle.get("age_days", n), 0, 3.5),          # 1d … ~10y
        _sq(lifecycle.get("perf_slope", n), -1, 1),
        _sq(lifecycle.get("crowding", n), 0, 1),
        _sq(cost_slope, -1, 0),
    ], dtype=float)

    dq, why = False, ""
    if leakage_clean is False:
        dq, why = True, "PIT/look-ahead leakage — invalid, not a lifecycle phase"
    elif cost_feasible is False:
        dq, why = True, "cost-infeasible at declared capacity"
    return StrategyVector(name=name, coords=c, disqualified=dq, disqualified_reason=why,
                          ledger_ref=ledger_ref, status=status, notes=notes)


# ── search over the space ────────────────────────────────────────────────────
def similarity(a: StrategyVector, b: StrategyVector) -> float:
    """Cosine similarity over dimensions BOTH have measured. Returns NaN if <4 shared dims —
    a confident similarity from 2 dimensions is noise, and should not be reported as a number."""
    m = ~np.isnan(a.coords) & ~np.isnan(b.coords)
    if m.sum() < 4:
        return float("nan")
    x, y = a.coords[m], b.coords[m]
    nx, ny = np.linalg.norm(x), np.linalg.norm(y)
    if nx < 1e-9 or ny < 1e-9:
        return float("nan")
    return float(np.dot(x, y) / (nx * ny))


def neighbours(target: StrategyVector, pool: list[StrategyVector], k: int = 5) -> list[tuple[str, float]]:
    """Nearest strategies — 'is this candidate just something we already hold?'"""
    out = [(p.name, similarity(target, p)) for p in pool if p.name != target.name]
    out = [(nm, s) for nm, s in out if not math.isnan(s)]
    return sorted(out, key=lambda t: -t[1])[:k]


def coverage_gaps(pool: list[StrategyVector], threshold: float = 0.25) -> list[dict]:
    """Which regimes does the CURRENT library not cover? This is the output that tells us what to
    build next, instead of guessing. Disqualified sleeves are excluded — they are not inventory."""
    live = [p for p in pool if not p.disqualified]
    gaps = []
    for i, (dim, desc) in enumerate(DIMS[:6]):          # regime block only
        vals = np.array([p.coords[i] for p in live])
        vals = vals[~np.isnan(vals)]
        best = float(vals.max()) if len(vals) else float("nan")
        covered = len(vals) and best >= threshold
        gaps.append({"regime": dim, "description": desc, "n_measured": int(len(vals)),
                     "best_in_library": None if math.isnan(best) else round(best, 3),
                     "covered": bool(covered)})
    return gaps


def redundancy(pool: list[StrategyVector], thresh: float = 0.85) -> list[tuple[str, str, float]]:
    """Pairs that are near-duplicates — breadth we think we have but don't (R20: effective breadth
    was 6.74 of 17 strategies). Correlated sleeves are one sleeve wearing several names."""
    live = [p for p in pool if not p.disqualified]
    out = []
    for i in range(len(live)):
        for j in range(i + 1, len(live)):
            s = similarity(live[i], live[j])
            if not math.isnan(s) and s >= thresh:
                out.append((live[i].name, live[j].name, round(s, 3)))
    return sorted(out, key=lambda t: -t[2])


# ── persistence ──────────────────────────────────────────────────────────────
def save(pool: list[StrategyVector], path: str) -> int:
    """Append-only JSONL — merge-safe for parallel agents (the collision fix)."""
    with open(path, "w") as f:
        for p in pool:
            f.write(json.dumps(p.as_dict(), ensure_ascii=False) + "\n")
    return len(pool)


def load(path: str) -> list[StrategyVector]:
    out = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            coords = np.array([d["coords"].get(k) if d["coords"].get(k) is not None else np.nan
                               for k in DIM_NAMES], dtype=float)
            out.append(StrategyVector(
                name=d["name"], coords=coords, disqualified=d.get("disqualified", False),
                disqualified_reason=d.get("disqualified_reason", ""),
                ledger_ref=d.get("ledger_ref", ""), status=d.get("status", "candidate"),
                notes=d.get("notes", ""), schema=d.get("schema", SCHEMA_VERSION)))
    return out


def format_library(pool: list[StrategyVector]) -> str:
    live = [p for p in pool if not p.disqualified]
    dq = [p for p in pool if p.disqualified]
    L = [f"STRATEGY LIBRARY — {len(live)} located, {len(dq)} disqualified", "=" * 62]
    for p in sorted(live, key=lambda x: x.name):
        known = int((~np.isnan(p.coords)).sum())
        L.append(f"  {p.name:28s} {p.status:9s} {known:2d}/{NDIM} dims  {p.ledger_ref}")
    if dq:
        L.append("\nDISQUALIFIED (validity floor — not lifecycle):")
        for p in dq:
            L.append(f"  {p.name:28s} {p.disqualified_reason}")
    g = [x for x in coverage_gaps(pool) if not x["covered"]]
    L.append(f"\nUNCOVERED REGIMES ({len(g)}) — build here next:")
    for x in g:
        L.append(f"  {x['regime']:18s} best={x['best_in_library']} (n={x['n_measured']})")
    r = redundancy(pool)
    if r:
        L.append(f"\nNEAR-DUPLICATES (breadth we think we have but don't):")
        for a, b, s in r[:5]:
            L.append(f"  {a} ≈ {b}  ({s})")
    return "\n".join(L)
