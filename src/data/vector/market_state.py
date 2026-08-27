"""
market_state_vectors — the 24-dim daily environment vector.

Spec: docs/VDB_MINING_SCHEMA.md §2. This is item #2 of §7 ("历史回算 … 能算多少算
多少, 缺失记 NaN").

WHY THIS SHAPE — the constraint that is easy to violate and fatal to violate:

    Price occupies 5 of 24 dims and enters ONLY through second moments and
    trend phase. Never through direction.

    "价格是高维信号的映射" — so we reconstruct the high-dimensional cause and
    refuse to consume the projection. A state vector built out of price is a
    rear-view mirror wearing a navigation costume: Shadow's vector_mine Round 6
    clustered 1206 dates on 5 price-derived dims (BTC vol, BTC/ETH ratio z,
    correlation, dispersion, drawdown) and its own notes record the symptom —
    "the 8 clusters all share HIGH_VOL + RISK_ON + HIGH_DISP, differentiated
    mainly by V2 and V7". Eight slices of one environment, because the inputs
    were eight views of one price series over one macro regime.

DEPTH — why 11 years and not 3.5:

    ohlcv_daily holds 2015-07 → 2026-07, 75 symbols, spanning 2017 mania /
    2018 bear / 2020 crash+recovery / 2021 mania / 2022 bear / 2023-24
    recovery / 2025-26 drawdown. Round 6 used 1296 days (2023-01 → 2026-07),
    which is essentially ONE macro environment — kNN over it can only answer
    "which recent day looked like today". Three cycles is the minimum for
    `similar_market_states` to return something a mediocre trader could not
    have guessed.

MISSINGNESS IS FIRST-CLASS (I1):

    CIS scores start 2025-05; funding/OI start later still; on-chain stablecoin
    supply is not wired at all. Early years therefore have genuinely missing
    dims. We do NOT impute them to zero — a zero is a measurement claim and a
    false one. `vec_full` keeps nulls, `vec` carries a neutral fill purely so
    pgvector can index it, and `source_completeness` reports what fraction was
    really measured. A caller that ignores source_completeness will compare a
    5-dim-real 2016 day against a 24-dim-real 2026 day and get nonsense; the
    field exists so that is a visible choice rather than a silent one.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional, Sequence

log = logging.getLogger(__name__)

# ── The 24 dims, in vector order. Order is a contract: changing it invalidates
#    every stored vector and every HNSW neighbour. Append only; never reorder.
DIMS: tuple[str, ...] = (
    # 横截面质量 — 池子整体质量与分化度 (cis_scores)
    "cis_mean", "cis_disp", "cis_skew", "pct_grade_A",
    # 风险偏好 — 边际资金愿不愿承担额外风险 (面板横截面)
    "alt_btc_spread", "breadth_200ma", "disp_return", "corr_mean",
    # 流动性 — 边际买方的燃料
    "stable_supply_chg", "volume_trend", "adv_concentration",
    # 杠杆/情绪 — 拥挤度与脆弱性 (衍生品)
    "funding_mean", "funding_disp", "fng", "oi_mcap",
    # 波动结构 — 环境的二阶矩 (价格, 1/2)
    "vol_mkt", "vol_of_vol", "downside_ratio",
    # 趋势相位 — 相位位置, 不是方向预测 (价格, 2/2)
    "trend_strength", "trend_age_days",
    # CIS 动态 — R63b 稳定性溢价
    "d_cis_mean", "stability_OS",
    # 预留 — 保持 24 维契约; 填 None 直到定义确定
    "_reserved_1", "_reserved_2",
)
assert len(DIMS) == 24, f"spec fixes the vector at 24 dims, got {len(DIMS)}"

# Dims derived from price. The spec caps this at 5 and the cap is the point.
PRICE_DIMS: frozenset[str] = frozenset({
    "vol_mkt", "vol_of_vol", "downside_ratio", "trend_strength", "trend_age_days",
})
assert len(PRICE_DIMS) == 5, "price must occupy exactly 5 of 24 dims"
assert PRICE_DIMS <= set(DIMS)

# Neutral fill for the indexed copy. Vectors are z-scored per dim before
# storage, so 0.0 means "at the historical mean of this dim" — the least
# informative value, not a fabricated measurement. vec_full keeps the null.
NEUTRAL_FILL = 0.0


@dataclass
class StateVector:
    d: str                                   # ISO date
    values: dict[str, Optional[float]] = field(default_factory=dict)
    regime_label: Optional[str] = None

    @property
    def source_completeness(self) -> float:
        """Fraction of the 24 dims actually measured. Reserved dims are excluded
        from the denominator so they cannot silently depress every day's score."""
        live = [k for k in DIMS if not k.startswith("_reserved")]
        got = sum(1 for k in live if self.values.get(k) is not None)
        return round(got / len(live), 4)

    @property
    def price_share(self) -> float:
        """Fraction of MEASURED dims that came from price. The spec's 5/24 cap is
        on the definition; this reports the realised share, which drifts upward
        whenever non-price sources are missing. A day where price is most of what
        we know is a day the vector is closer to a rear-view mirror — surfacing
        it is the whole point."""
        measured = [k for k in DIMS if self.values.get(k) is not None]
        if not measured:
            return 0.0
        return round(sum(1 for k in measured if k in PRICE_DIMS) / len(measured), 4)

    def to_vec(self) -> list[float]:
        """Indexed copy — nulls become NEUTRAL_FILL so pgvector can build HNSW."""
        return [
            NEUTRAL_FILL if self.values.get(k) is None else float(self.values[k])
            for k in DIMS
        ]

    def to_vec_full(self) -> dict[str, Optional[float]]:
        """Honest copy — nulls preserved (I1)."""
        return {k: self.values.get(k) for k in DIMS}


# ── Primitives ────────────────────────────────────────────────────────────────

def _finite(xs: Sequence[Optional[float]]) -> list[float]:
    return [float(x) for x in xs
            if x is not None and isinstance(x, (int, float)) and math.isfinite(float(x))]


def mean(xs: Sequence[Optional[float]]) -> Optional[float]:
    v = _finite(xs)
    return sum(v) / len(v) if v else None


def stdev(xs: Sequence[Optional[float]]) -> Optional[float]:
    v = _finite(xs)
    if len(v) < 2:
        return None
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1))


def skew(xs: Sequence[Optional[float]]) -> Optional[float]:
    v = _finite(xs)
    if len(v) < 3:
        return None
    m = sum(v) / len(v)
    s = math.sqrt(sum((x - m) ** 2 for x in v) / len(v))
    if s == 0:
        return 0.0
    return sum(((x - m) / s) ** 3 for x in v) / len(v)


def pct_change(series: Sequence[float], lag: int = 1) -> Optional[float]:
    v = _finite(series)
    if len(v) <= lag or v[-1 - lag] == 0:
        return None
    return v[-1] / v[-1 - lag] - 1.0


def realized_vol(returns: Sequence[Optional[float]], annualize: bool = True) -> Optional[float]:
    s = stdev(returns)
    if s is None:
        return None
    return s * math.sqrt(365) if annualize else s


def downside_ratio(returns: Sequence[Optional[float]]) -> Optional[float]:
    """Downside semi-deviation / total deviation — a fragility read, not a
    direction call.

    Both legs divide by the SAME denominator (the full sample), which is what
    makes the ratio comparable: semi-deviation over negatives-only-count is a
    different statistic and can exceed 1, silently inflating this dim relative
    to the other 23 once everything is z-scored. For a symmetric distribution
    the ratio sits near 1/sqrt(2) ~= 0.707; above that, dispersion is carried by
    the losing tail.
    """
    v = _finite(returns)
    if len(v) < 5:
        return None
    n = len(v)
    m = sum(v) / n
    total = math.sqrt(sum((x - m) ** 2 for x in v) / n)
    if total == 0:
        return None
    neg = [x for x in v if x < m]
    if not neg:
        return 0.0
    down = math.sqrt(sum((x - m) ** 2 for x in neg) / n)
    return down / total


def trend_phase(closes: Sequence[float], ma_window: int = 200) -> tuple[Optional[float], Optional[float]]:
    """(strength, age_days) — WHERE in a trend we are, never which way it goes next.

    strength : (last - MA) / MA, sign carries position relative to the mean, not
               a forecast.
    age_days : consecutive days on the current side of the MA. Phase position is
               the input the response surface conditions on; a 300-day-old trend
               and a 3-day-old one are different environments even at identical
               strength.
    """
    v = _finite(closes)
    if len(v) < ma_window + 1:
        return None, None
    ma = sum(v[-ma_window:]) / ma_window
    if ma == 0:
        return None, None
    strength = v[-1] / ma - 1.0
    above = v[-1] >= ma
    age = 0
    for i in range(len(v) - 1, ma_window - 2, -1):
        w = v[i - ma_window + 1:i + 1]
        if len(w) < ma_window:
            break
        if (v[i] >= sum(w) / ma_window) != above:
            break
        age += 1
    return strength, float(age)


def breadth_above_ma(closes_by_symbol: dict[str, Sequence[float]],
                     ma_window: int = 200) -> Optional[float]:
    """Share of the panel trading above its own long MA. Participation is a
    risk-appetite read: a rally carried by three names is a different environment
    from the same index level carried by fifty."""
    ok = tot = 0
    for _s, closes in closes_by_symbol.items():
        v = _finite(closes)
        if len(v) < ma_window:
            continue
        tot += 1
        if v[-1] >= sum(v[-ma_window:]) / ma_window:
            ok += 1
    return round(ok / tot, 6) if tot >= 5 else None


def mean_pairwise_corr(returns_by_symbol: dict[str, Sequence[float]],
                       min_overlap: int = 30, max_symbols: int = 40) -> Optional[float]:
    """Average pairwise correlation across the panel — how much of the market is
    one trade. High corr means diversification has evaporated; that is a state of
    the world, not a property of any strategy."""
    syms = [s for s, r in list(returns_by_symbol.items())[:max_symbols]
            if len(_finite(r)) >= min_overlap]
    if len(syms) < 3:
        return None
    cors: list[float] = []
    for i in range(len(syms)):
        for j in range(i + 1, len(syms)):
            a, b = _finite(returns_by_symbol[syms[i]]), _finite(returns_by_symbol[syms[j]])
            n = min(len(a), len(b))
            if n < min_overlap:
                continue
            a, b = a[-n:], b[-n:]
            ma, mb = sum(a) / n, sum(b) / n
            va = math.sqrt(sum((x - ma) ** 2 for x in a))
            vb = math.sqrt(sum((x - mb) ** 2 for x in b))
            if va == 0 or vb == 0:
                continue
            cors.append(sum((a[k] - ma) * (b[k] - mb) for k in range(n)) / (va * vb))
    return round(sum(cors) / len(cors), 6) if cors else None


def herfindahl(weights: Sequence[Optional[float]]) -> Optional[float]:
    """HHI on shares. Used for adv_concentration: is the panel's tradeable volume
    one venue/asset deep, or genuinely broad."""
    v = [x for x in _finite(weights) if x > 0]
    if not v:
        return None
    tot = sum(v)
    return round(sum((x / tot) ** 2 for x in v), 6) if tot > 0 else None


def zscore_columns(rows: list[StateVector], min_obs: int = 60) -> list[StateVector]:
    """Z-score each dim across the whole history, ignoring nulls.

    Cosine distance over raw units would let vol_mkt (order 1.0) and
    trend_age_days (order 100) contribute wildly unequally — the neighbour set
    would be decided by whichever dim happens to have the largest natural scale.
    Standardising first is what makes "similar environment" mean similar in all
    24 respects rather than similar in trend_age_days.
    """
    for k in DIMS:
        col = [r.values.get(k) for r in rows]
        v = _finite(col)
        if len(v) < min_obs:
            continue
        m = sum(v) / len(v)
        s = math.sqrt(sum((x - m) ** 2 for x in v) / (len(v) - 1)) if len(v) > 1 else 0.0
        if s == 0:
            continue
        for r in rows:
            x = r.values.get(k)
            if x is not None and math.isfinite(float(x)):
                r.values[k] = (float(x) - m) / s
    return rows


def to_vec_full_array(sv: "StateVector") -> list[Optional[float]]:
    """`vec_full` as the DB actually stores it: a POSITIONAL array (S-233).

    ⚠️ `similar_market_states()` reads this column with
    `jsonb_array_elements_text(vec_full) with ordinality` and joins the target
    day's array **by index**. So the column is an ordered array, and the order is
    `DIMS`. The stored 582 rows are arrays; `to_vec_full()` returns a **dict**.

    `build_rows_for_upsert` was handing the dict straight to the column. Nothing
    had caught it because the function has no callers — the table was written
    once by something outside this repo. The first writer to use this helper
    would have written 24 dicts into a column the RPC indexes positionally, and
    the neighbour query would have degraded without raising.

    Two shapes of one vector, one of which the only consumer cannot read: that is
    S-214 (a constant naming a table nobody wrote) with the arrow reversed —
    a writer nobody had run, pointed at a contract nobody had checked.
    """
    return [sv.values.get(k) for k in DIMS]


def build_rows_for_upsert(vectors: list[StateVector],
                          zscore_pass: Optional[str] = None) -> list[dict]:
    """Shape for market_state_vectors. Assumes z-scoring already applied.

    `zscore_pass` identifies the standardisation batch (S-232). Rows from two
    passes are not in one coordinate system, and the RPC's cosine will not say
    so — it returns a number either way. Stamping it is what makes a mixed table
    detectable instead of quietly wrong.
    """
    return [
        {
            "d": sv.d,
            "vec": sv.to_vec(),
            "vec_full": to_vec_full_array(sv),
            "regime_label": sv.regime_label,
            "source_completeness": sv.source_completeness,
            "measured_dims": sum(1 for k in DIMS if sv.values.get(k) is not None),
            "zscore_pass": zscore_pass,
        }
        for sv in vectors
    ]
