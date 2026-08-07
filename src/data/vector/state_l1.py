"""
L1 — the data collection layer of the two-layer market-state vector.

    L1 (this file)  raw daily observations · ragged · nulls preserved · UNBOUNDED
    L2 (next)       latent factor state · fixed dim · HNSW-indexed · joins strategy

The split exists because dimensionality must never reach the similarity metric.
If a day's vector is "whatever we measured that day", then cosine distance over
neutral-filled slots clusters days by DATA AVAILABILITY rather than by market
environment — a spurious, confident, and completely invisible failure. The
macro-nowcasting literature calls this the ragged-edge problem and solves it the
same way we will: the measurement equation absorbs the varying observation set,
the latent state stays fixed-dimensional and therefore comparable across time
(Giannone-Reichlin-Small 2008; ECB WP1189).

The payoff is operational, not aesthetic: L1 can grow forever without
invalidating history. Open interest arrives next week, on-chain the month after,
a new venue after that — each enters as an additional observation series. The
2022 state is not recomputed and no table is rebuilt. That is the property that
stops this schema from needing to be re-decided every time a source appears,
which is the failure this whole codebase has been paying for.

Start date is 2022-01-01 by decision (Jazz, 2026-08-02): the current regime is a
tightening drawdown, and 2022 is the nearest regime-analogous history. kNN is
supposed to retrieve days like today; a sample that omits the last real bear
market cannot.

Coverage reality, measured 2026-08-02 — NOT assumed:
    panel (ohlcv_daily)      2015+, but crypto cross-section is 3 names in 2015,
                             32 by 2022. Cross-sectional stats before ~2020 are
                             arithmetic on noise.
    CIS (local cis_history)  162,693 rows, 4 assets in 2015 -> 26 by 2022
    funding (hyperliquid)    2023-05 onward only
    stablecoin supply (CG)   2022-03-17 onward, 1601 daily points
    global mcap (CG)         2013-04-29 onward
    OPEN INTEREST            no free historical source. CoinGecko serves a
                             current snapshot only (/derivatives), no history
                             endpoint. Vendor purchase pending. Recorded live
                             from today so the gap stops growing.
"""
from __future__ import annotations

import json
import logging
import os
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

log = logging.getLogger(__name__)

START_DATE = "2022-01-01"

# Local artifact. L1 will be reshaped repeatedly while dims are settled; writing
# to the production table on every iteration would churn a system-of-record for
# no reason, and ingest belongs to the Mac lane anyway (MINIMAX_SYNC D1/D2).
DEFAULT_OUT = Path("_data/market_state/l1_observations.db")


# ── Observation registry ──────────────────────────────────────────────────────
#
# One row per raw series L1 collects. `available_from` is MEASURED, not assumed —
# every value here was verified against the source on 2026-08-02. A series whose
# real start is later than claimed silently produces zeros at the boundary, which
# is the same class of bug as a wrong ticker: a populated, plausible, wrong value.

@dataclass(frozen=True)
class Series:
    key: str
    block: str                  # which L2 conceptual block it informs
    source: str
    available_from: Optional[str]   # None = not yet sourced
    unit: str
    note: str = ""

    @property
    def is_sourced(self) -> bool:
        return self.available_from is not None


REGISTRY: tuple[Series, ...] = (
    # 横截面质量 — pool quality and its dispersion
    Series("cis_mean", "cross_quality", "cis_history.db", "2022-01-01", "score"),
    Series("cis_disp", "cross_quality", "cis_history.db", "2022-01-01", "score"),
    Series("cis_skew", "cross_quality", "cis_history.db", "2022-01-01", "unitless"),
    Series("pct_grade_A", "cross_quality", "cis_history.db", "2022-01-01", "share"),
    Series("d_cis_mean", "cross_quality", "cis_history.db", "2022-01-01", "score/day"),
    Series("stability_OS", "cross_quality", "cis_history.db", "2022-01-01", "unitless",
           "R63b stability premium; needs pillar_o/pillar_s, 62.5% row coverage"),

    # 风险偏好 — whether marginal capital will carry extra risk
    Series("alt_btc_spread", "risk_appetite", "ohlcv_daily", "2022-01-01", "ret diff"),
    Series("breadth_200ma", "risk_appetite", "ohlcv_daily", "2022-01-01", "share"),
    Series("disp_return", "risk_appetite", "ohlcv_daily", "2022-01-01", "stdev"),
    Series("corr_mean", "risk_appetite", "ohlcv_daily", "2022-01-01", "corr"),
    Series("defi_eth_ratio", "risk_appetite", "coingecko /global/defi", None, "ratio",
           "current snapshot only; accumulate forward"),

    # 流动性 — fuel available to the marginal buyer
    Series("stable_supply_chg", "liquidity", "coingecko USDT+USDC market_chart",
           "2022-03-17", "pct", "stablecoin mcap ~= supply; 1601 daily points verified"),
    Series("volume_trend", "liquidity", "ohlcv_daily", "2022-01-01", "ratio"),
    Series("adv_concentration", "liquidity", "ohlcv_daily", "2022-01-01", "HHI"),

    # 杠杆/情绪 — crowding and fragility
    Series("funding_mean", "leverage", "hyperliquid_funding", "2023-05-12", "rate/8h"),
    Series("funding_disp", "leverage", "hyperliquid_funding", "2023-05-12", "stdev"),
    Series("fng", "leverage", "alternative.me", "2018-02-01", "index 0-100"),
    Series("oi_mcap", "leverage", "VENDOR PENDING", None, "ratio",
           "no free historical source; CoinGecko /derivatives is snapshot-only. "
           "This is the crowding-scale dim and cannot be proxied by funding, "
           "which carries direction but not size."),

    # 波动结构 + 趋势相位 — the ONLY price-derived block, 5 series, second
    # moments and phase only. Never direction.
    Series("vol_mkt", "vol_structure", "ohlcv_daily", "2022-01-01", "annualized"),
    Series("vol_of_vol", "vol_structure", "ohlcv_daily", "2022-01-01", "annualized"),
    Series("downside_ratio", "vol_structure", "ohlcv_daily", "2022-01-01", "ratio"),
    Series("trend_strength", "trend_phase", "ohlcv_daily", "2022-01-01", "pct vs MA"),
    Series("trend_age_days", "trend_phase", "ohlcv_daily", "2022-01-01", "days"),
)

PRICE_BLOCKS = frozenset({"vol_structure", "trend_phase"})


def sourced() -> list[Series]:
    return [s for s in REGISTRY if s.is_sourced]


def unsourced() -> list[Series]:
    return [s for s in REGISTRY if not s.is_sourced]


def price_share_of_registry() -> float:
    """Share of SOURCED series that are price-derived.

    The spec caps price at 5 of 24 by definition. This measures the realised
    share, which rises whenever non-price sources are missing. It is the single
    number that tells us whether L1 is drifting back into being a rear-view
    mirror: Shadow's Round 6 clustered on 5 price dims out of 5 and its own
    notes recorded the consequence, eight clusters that were all the same
    environment.
    """
    s = sourced()
    if not s:
        return 0.0
    return round(sum(1 for x in s if x.block in PRICE_BLOCKS) / len(s), 4)


def coverage_report(as_of: Optional[str] = None) -> dict[str, Any]:
    """What L1 can actually deliver. Run before trusting any downstream state."""
    as_of = as_of or date.today().isoformat()
    by_block: dict[str, dict[str, int]] = {}
    for s in REGISTRY:
        b = by_block.setdefault(s.block, {"total": 0, "sourced": 0})
        b["total"] += 1
        b["sourced"] += 1 if s.is_sourced else 0

    starts = [s.available_from for s in sourced() if s.available_from]
    return {
        "as_of": as_of,
        "start_date": START_DATE,
        "series_total": len(REGISTRY),
        "series_sourced": len(sourced()),
        "series_pending": [s.key for s in unsourced()],
        "price_share_of_sourced": price_share_of_registry(),
        "by_block": by_block,
        # The date from which EVERY sourced series exists. Before it, the
        # observation set is genuinely ragged — which L2 handles, but which must
        # not be mistaken for full coverage.
        "all_sourced_from": max(starts) if starts else None,
    }


# ── Storage ───────────────────────────────────────────────────────────────────

SCHEMA = """
create table if not exists l1_observations (
  d           text not null,
  series      text not null,
  value       real,              -- NULL means not measured. Never 0-filled.
  source      text,
  primary key (d, series)
);
create index if not exists l1_obs_d   on l1_observations(d);
create index if not exists l1_obs_ser on l1_observations(series);

-- Provenance of each build, so a state can always be traced to the L1 snapshot
-- it was estimated from. Re-estimating L2 without knowing which L1 produced it
-- is how two incomparable vectors end up in the same index.
create table if not exists l1_builds (
  build_id    text primary key,
  built_at    text,
  start_date  text,
  end_date    text,
  n_days      int,
  n_series    int,
  coverage    text               -- coverage_report() as json
);
"""


def open_db(path: Path = DEFAULT_OUT) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    return con


def write_observations(con: sqlite3.Connection,
                       rows: Iterable[tuple[str, str, Optional[float], str]]) -> int:
    """rows = (d, series, value, source). value=None is stored as NULL and stays
    NULL — imputation, if it ever happens, is L2's explicit and visible job."""
    cur = con.executemany(
        "insert or replace into l1_observations(d, series, value, source) values (?,?,?,?)",
        list(rows),
    )
    con.commit()
    return cur.rowcount


def record_build(con: sqlite3.Connection, start: str, end: str,
                 n_days: int, n_series: int) -> str:
    build_id = f"l1_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')}"
    con.execute(
        "insert into l1_builds(build_id, built_at, start_date, end_date, n_days, n_series, coverage)"
        " values (?,?,?,?,?,?,?)",
        (build_id, datetime.now(timezone.utc).isoformat(), start, end, n_days, n_series,
         json.dumps(coverage_report())),
    )
    con.commit()
    return build_id


def panel_from_db(con: sqlite3.Connection, start: str = START_DATE
                  ) -> dict[str, dict[str, Optional[float]]]:
    """{date: {series: value|None}} — the ragged panel L2 consumes.

    Missing pairs are returned as explicit None rather than omitted, so a
    consumer iterating series sees the hole instead of silently shortening its
    own feature list.
    """
    keys = [s.key for s in REGISTRY]
    out: dict[str, dict[str, Optional[float]]] = {}
    for d, series, value in con.execute(
        "select d, series, value from l1_observations where d >= ? order by d", (start,)
    ):
        out.setdefault(d, {k: None for k in keys})[series] = value
    return out
