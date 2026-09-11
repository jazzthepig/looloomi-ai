"""
Strategy 4 — Cross-Asset Factor Tilt paper-trade loop (R-N + 33, Minimax-B, 2026-08-20).
========================================================================================

Spec: docs/STRATEGY_4_CROSS_ASSET_FACTOR_TILT.md §Live spec.

Architecture (mirror of fusion_paper.py §P1/§P2):
  1. Fetch live close for 41-asset crypto universe + 17 TradFi ETFs.
  2. Fetch live CIS pillar_O for crypto symbols (from Redis/Supabase).
  3. Compute composite z_quality + z_momentum + z_lowrisk per asset per day.
  4. Convert to long-only tilt weights (bottom quartile floored at 1/N).
  5. Apply H3.2 conviction-scaled sizing at each rebalance.
  6. Mark NAV using close[t]/close[t-1]−1, deduct turnover cost.
  7. Vol-target the aggregator at 12% annualized.
  8. Persist NAV row to Supabase `factor_tilt_nav` table.

§STRATEGY-DISCIPLINE gates:
  - ≥60 forward days before `validated: true`
  - Live Sharpe within tolerance of OOS Sharpe
  - W5 ann% positive (the L/S fragility fix claim)
  - Factor decomposition Sharpe attribution (no single factor > 70%)

Lane: Seth/Austin. Mac-side daily loop. Sandbox-safe.
Compliance: positioning language only (no BUY/SELL/ACCUMULATE).
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

# ── Constants (mirror cross_asset_factor_tilt.py — keep in sync) ─────────────
REBAL_DAYS = 5
COST_BPS = 5.0
VOL_TARGET_ANN = 0.12
H32_FLOOR = 0.5
H32_CAP = 1.75
PERIODS_PER_YEAR = 365
MOMENTUM_LOOKBACK = 30
VOL_LOOKBACK = 30
Z_CLIP = 3.0

VALIDATION_MIN_DAYS = 60
PAPER_NOTIONAL_USD = 1_000_000.0

# Live state persistence
from src.data.signals.nav_persist import NavWrite, write_nav_row

STATE_TABLE = "factor_tilt_state"
NAV_TABLE = "factor_tilt_nav"

# Endpoints (wired to src/api/main.py)
ENDPOINT_NAV = "/api/v1/signals/factor-tilt"
ENDPOINT_TRACKING = "/api/v1/signals/factor-tilt-tracking"

# 41-asset crypto + 17 TradFi ETF universe (mirror backtest rig)
from src.data.signals.fusion_paper import UNIVERSE as CRYPTO_UNIVERSE
from src.research.validation.cis_quality_tradfi import TRADFI_UNIVERSE
FULL_UNIVERSE = sorted(set(CRYPTO_UNIVERSE) | set(TRADFI_UNIVERSE))

_SB_URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
_SB_KEY = os.environ.get("SUPABASE_KEY", "")
_INTERNAL_TOKEN = os.environ.get("INTERNAL_TOKEN", "")

_logger = logging.getLogger("factor_tilt_paper")


# ── Live data fetchers ───────────────────────────────────────────────────────
#: TradFi 本地缓存目录 —— **Mac 侧数据根,不是「写死的错路径」**。
#:
#: ⚠️ S-323w 更正我自己在 S-323u 里写错的一条。我把
#: `/Volumes/CometCloudAI/...` 说成是「某台 Mac 的私有路径 / 硬编码债」,
#: **那是错的,而且是没看清工程结构就下的判断**。它是 CLAUDE.md
#: 第 52/117 行写明的 **Minimax lane 数据根**,是这套架构的固定件;
#: `src/research/paths.py`(P0-5, 2026-08-27)早就把它收成了唯一来源,
#: 并写着 lane 纪律:「These are READ paths into Minimax's lane.」
#: 我不但判错了,还差点用一条测试去禁止它 —— 那会把**正确的 Mac 侧代码**判红。
#:
#: **真正的缺陷不是这个路径,是 lane 不匹配**:本模块开头自己声明
#: 「Lane: Seth/Austin. **Mac-side daily loop.**」,而 `_factor_tilt_loop`
#: 是在 **Railway** 上跑它的。Railway 没有挂载那个卷 —— 这是对的,
#: 不是故障 —— 所以在 Railway 上这条读路必然落空,而落空被渲染成
#: 「这些资产没有数据」。**一个模块在它声明之外的 lane 里被执行,
#: 那是调度的问题,不是它所读的那个路径的问题。**
#:
#: 于是两条路都保留,按**运行在哪条 lane** 决定:
#:   Mac 侧(卷挂着)→ 读本地 EODHD 缓存,快且是同一份厂商数据
#:   Railway(卷不在)→ `panel_closes` 取库里已入库的 eodhd
#: 走 `paths.py` 而不是再写一个字面量 —— 重复那个字面量才是真正的债。
try:                                     # research/ 不在最小运行时里时降级
    from src.research.paths import MAC_ROOT as _MAC_ROOT
    _EODHD_DEFAULT = str(_MAC_ROOT / "_cache" / "eodhd_history")
except Exception:                                             # noqa: BLE001
    _EODHD_DEFAULT = ""
EODHD_CACHE_DIR = os.environ.get("EODHD_CACHE_DIR", _EODHD_DEFAULT)


@dataclass(frozen=True)
class FetchCoverage:
    """取回来的价格 + 【没取到的是谁、为什么】(S-240)。

    原来的 `_fetch_close_live` 只返回成功的那部分:TradFi 缓存文件不存在 → 跳过;
    Binance 非 200 → 跳过;任何异常 → `_logger.debug` 然后 `continue`。
    **debug 级日志在生产默认不可见**,而返回值里没有任何痕迹。

    于是调用方无法区分「这些资产没有数据」和「我一个都没取到」 —— 而这两件事
    会让同一本账要么缩小宇宙、要么记一条基于三个资产的曲线,两种都不报错。
    这是本 session 反复出现的形状:**丢失被表示成"更少",而不是"丢了"。**
    """

    prices: dict[str, list[float]]
    missing: dict[str, str]        # symbol → 为什么没有

    @property
    def coverage(self) -> float:
        n = len(self.prices) + len(self.missing)
        return round(len(self.prices) / n, 4) if n else 0.0

    def as_payload(self) -> dict[str, Any]:
        return {
            "priced": len(self.prices),
            "unpriced": len(self.missing),
            "coverage": self.coverage,
            # 只列前几个,但**原因分组**要全 —— 一百个符号同一个原因是一个事实,
            # 一百个符号一百个原因是另一个。
            "missing_reasons": _group(self.missing),
        }


def _group(missing: dict[str, str]) -> dict[str, int]:
    out: dict[str, int] = {}
    for reason in missing.values():
        out[reason] = out.get(reason, 0) + 1
    return dict(sorted(out.items(), key=lambda kv: -kv[1]))


async def _fetch_close_live(symbols: list[str],
                            lookback_days: int = 60) -> FetchCoverage:
    """Daily closes from the sources we PAY for. **One request, no fan-out.**

    ⚠️ S-323u。上一版是:crypto 逐个符号打 `fapi.binance.com`,
    TradFi 读一个写死的 Mac 路径 `/Volumes/CometCloudAI/.../eodhd_history`。

    Jazz(2026-09-09,而且这条他讲过很多次):
    **「不可以那么多资产打向免费 api。多资产重复调取要走付费 api。
      binance 和 hyperliquid 这些是进入交易之后才调取。」**

    实测后果:Railway 上那个 Mac 路径不存在 → 17 个 TradFi 每轮全部 missing
    → 只剩 28 个 crypto 对 >=20 的地板 → **这本账连续数周拒绝打标,
    而它要的价格一直就在我们自己的库里**(28/28 crypto 在 coingecko_pro_ohlc,
    11/17 tradfi 在 eodhd,都是付费源)。

    改为一次 `panel_closes` RPC:不扇出、单一来源每符号(S-106 口径不拼接)、
    缺失带原因回来。**取不到就报缺,绝不退回免费端点去补。**

    ⚠️ S-323w:TradFi 的本地 EODHD 缓存**保留**。它在 Mac 侧是对的
    (那是 Minimax lane 的数据根,见上方常量注释),只是本模块被调度到
    Railway 上跑,而那里没有挂载那个卷。所以按 lane 选路,不是二选一地
    否定其中一条:卷在就读本地(同一份厂商数据,更快),不在就走库里的
    eodhd。**两条路的数据同源,所以不存在 S-106 的口径拼接问题。**
    """
    from src.data.market.paid_close_loader import load_paid_closes

    local: dict[str, list[float]] = {}
    if EODHD_CACHE_DIR and Path(EODHD_CACHE_DIR).is_dir():
        for sym in [s for s in symbols if s in TRADFI_UNIVERSE]:
            try:
                hits = sorted(Path(EODHD_CACHE_DIR).glob(f"{sym}_*.json"))
                if not hits:
                    continue
                rows = json.loads(hits[-1].read_text())
                closes = [float(r["close"]) for r in rows[-lookback_days:]]
                if len(closes) >= 2:
                    local[sym] = closes
            except Exception as ex:                           # noqa: BLE001
                # 不再是 debug。少一个符号是这本账宇宙的变化,不是调试细节。
                _logger.warning("factor_tilt local EODHD read failed for %s: %s",
                                sym, ex)
        if local:
            _logger.info("[FACTOR-TILT] %s TradFi names from the Mac-side EODHD "
                         "cache (%s)", len(local), EODHD_CACHE_DIR)

    paid = await load_paid_closes(
        [s for s in symbols if s not in local], lookback_days=lookback_days)
    prices = {**paid.prices, **local}
    missing = {s: r for s, r in paid.missing.items() if s not in local}
    return FetchCoverage(prices, missing)


async def _fetch_cis_pillar_o_live(symbols: list[str]) -> pd.Series:
    """Fetch latest CIS pillar_O for crypto symbols (TradFi has no pillar_O)."""
    try:
        import httpx
    except ImportError:
        return pd.Series(dtype=float)
    try:
        import redis.asyncio as redis_async
        rc = redis_async.from_url(os.environ.get("REDIS_URL", ""))
        cis_payload = await rc.get("cis:local_scores")
        if cis_payload:
            data = json.loads(cis_payload)
            scores = {s["symbol"]: float(s.get("pillar_o", s.get("score", 0)))
                      for s in data.get("scores", [])
                      if s.get("symbol") in symbols}
            await rc.aclose()
            return pd.Series(scores)
    except Exception as ex:
        _logger.debug("Redis fetch failed: %s", ex)
    if _SB_URL and _SB_KEY:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_SB_URL}/rest/v1/cis_scores",
                    params={"select": "symbol,pillar_o", "order": "recorded_at.desc",
                            "limit": len(symbols) * 2},
                    headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
                if r.status_code == 200:
                    rows = r.json()
                    scores = {}
                    for row in rows:
                        sym = row.get("symbol")
                        if sym in symbols and sym not in scores:
                            scores[sym] = float(row.get("pillar_o", 0))
                    return pd.Series(scores)
        except Exception as ex:
            _logger.debug("Supabase fetch failed: %s", ex)
    return pd.Series(dtype=float)


# ── State persistence (mirror fusion_paper_state schema) ─────────────────────
async def _load_state() -> dict[str, Any]:
    try:
        import httpx
        if _SB_URL and _SB_KEY:
            async with httpx.AsyncClient(timeout=15) as client:
                r = await client.get(
                    f"{_SB_URL}/rest/v1/{STATE_TABLE}",
                    params={"select": "*", "order": "updated_at.desc", "limit": 1},
                    headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
                if r.status_code == 200 and r.json():
                    return json.loads(r.json()[0]["state_json"])
    except Exception as ex:
        _logger.debug("state load failed: %s", ex)
    return _default_state()


def _default_state() -> dict[str, Any]:
    return {
        "inception_date": str(dt.date.today()),
        "nav": 1.0,
        "last_mark_date": None,
        "n_days_marked": 0,
        "factor_sharpe_attribution": {},
    }


async def _save_state(state: dict[str, Any]) -> None:
    try:
        import httpx
        if _SB_URL and _SB_KEY:
            async with httpx.AsyncClient(timeout=15) as client:
                payload = {
                    "last_mark_date": state.get("last_mark_date"),
                    "state_json": json.dumps(state),
                    "nav": state.get("nav", 1.0),
                    "n_days_marked": state.get("n_days_marked", 0),
                }
                r = await client.post(
                    f"{_SB_URL}/rest/v1/{STATE_TABLE}",
                    json=payload,
                    headers={
                        "apikey": _SB_KEY,
                        "Authorization": f"Bearer {_SB_KEY}",
                        "Prefer": "resolution=merge-duplicates",
                    })
                if r.status_code not in (200, 201):
                    _logger.warning("state save returned HTTP %d", r.status_code)
    except Exception as ex:
        _logger.warning("state save failed (will retry next day): %s", ex)


# ── Daily mark (mirror fusion_paper.py mark_and_rebalance) ───────────────────
async def _row_exists_for(table: str, day: str) -> bool | None:
    """表里今天有没有行。**三值:True / False / None(读不到)** (S-321)。

    `already_marked_today` 原本只问 Redis state。而 state 与表可以不一致 ——
    实测 `factor_tilt_nav` / `pod_aggregator_nav` **0 行数周**,
    而每轮都返回 `skipped: already_marked_today`:
    **state 记得做过,表说从来没有。**

    > **「我记得我做过」和「它确实在那里」是两个状态。**
    > 跳过与否是关于后者的判断,所以要问后者。

    读不到时返回 `None`,调用方**不得当成「有」** —— 读不到 ≠ 已经写过。
    """
    try:
        import httpx
        from src.api.store import _SB_KEY, _SB_URL
        if not _SB_URL or not _SB_KEY:
            return None
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(
                f"{_SB_URL}/rest/v1/{table}?select=mark_date&mark_date=eq.{day}&limit=1",
                headers={"apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
        if r.status_code != 200:
            return None
        return bool(r.json())
    except Exception:                                           # noqa: BLE001
        return None

async def mark_and_rebalance(dry_run: bool = False) -> dict[str, Any]:
    """Daily mark of the cross-asset factor tilt paper book. Idempotent per day."""
    from src.research.validation.cross_asset_factor_tilt import (
        build_composite, tilt_weights, h32_size, vol_target, book_returns,
        hold_panel_benchmark,
    )

    today = dt.date.today()
    state = await _load_state()
    if state.get("last_mark_date") == str(today):
        # ⚠️ **state 说做过不算数,表说有才算** (S-321)。
        # 读不到(None)时**不跳过** —— 读不到 ≠ 已经写过,重跑是幂等的。
        _has = await _row_exists_for(NAV_TABLE, str(today))
        if _has:
            return {"status": "skipped", "reason": "already_marked_today",
                "date": str(today), "nav": state.get("nav", 1.0)}

    universe = FULL_UNIVERSE
    fetched = await _fetch_close_live(universe, lookback_days=60)
    data = fetched.prices
    if len(data) < 20:
        # ⚠️ 拒绝时把【谁缺、为什么】一起带出去 (S-240)。原来只报
        # `n_assets_with_data`,那个数字分不出"这些资产今天没交易"和
        # "价源整个不可达" —— 而两者的修法在不同的 lane。
        return {"status": "skipped", "reason": "insufficient_live_data",
                "n_assets_with_data": len(data),
                "universe_size": len(universe),
                **fetched.as_payload()}

    pillar_o = await _fetch_cis_pillar_o_live(
        [s for s in data.keys() if s in CRYPTO_UNIVERSE])

    # ⚠️ S-330:**空的 pillar_O 必须在这里拒绝,不能带着空表往下走。**
    #
    # 2026-09-11 实测:`_fetch_cis_pillar_o_live` 的查询写的是
    # `order=ts.desc`,而 `cis_scores` 根本没有 `ts` 列 —— PostgREST 每次
    # 回 400 `column cis_scores.ts does not exist`,而调用点把它
    # `_logger.debug` 掉了(生产默认不可见),于是返回一个空 Series。
    #
    # 空 Series 一路走到 `build_quality_score()` 的
    # `cis_long.pivot(index="date", ...)`,在一个**空 DataFrame** 上取不到
    # `date` 列,最后以 `KeyError: 'date'` 的形式炸在 pandas 里三层之外。
    #
    # > **一个「上游没有数据」的事实,被渲染成了一个「代码有 bug」的样子。**
    # > 前者要去查数据源,后者会让人去读 pandas 的调用栈 —— 修法完全不同。
    #
    # 数据是在的(实测 948 行 / 58 个标的 / pillar_o 全非空 / 10 分钟前)。
    # 所以这里拒绝,并且**说出是哪一个上游空了**。
    if pillar_o is None or len(pillar_o) == 0:
        return {"status": "skipped", "reason": "insufficient_data",
                "detail": ("CIS pillar_O came back empty — the book cannot "
                           "score quality without it. This is an UPSTREAM "
                           "emptiness, not a bug in the weighting: check "
                           "cis_scores freshness and the Redis key "
                           "`cis:local_scores` (S-330)."),
                "n_priced": len(data), "date": today.isoformat()}

    today_ts = pd.Timestamp(today)
    close_panel = pd.DataFrame(
        {sym: pd.Series(d, index=pd.date_range(
            end=today_ts, periods=len(d), freq="D"))
         for sym, d in data.items() if len(d) >= MOMENTUM_LOOKBACK + 2}
    ).sort_index()
    rets = close_panel.pct_change().fillna(0.0)

    # Synthesize cis_long from live pillar_o (constant per asset over the panel)
    cis_long_rows = []
    for sym in pillar_o.index:
        for d in close_panel.index:
            cis_long_rows.append({"date": d, "asset": sym, "O": float(pillar_o[sym])})
    cis_long = pd.DataFrame(cis_long_rows)

    # Build composite score
    score = build_composite(cis_long, rets, list(data.keys()), close_panel.index)
    # For TradFi (no pillar_O), composite reduces to (z_momentum + z_lowrisk) / 2
    from src.research.validation.cross_asset_factor_tilt import (
        build_momentum_score, build_lowrisk_score,
    )
    tradfi_in_data = [s for s in data.keys() if s in TRADFI_UNIVERSE]
    if tradfi_in_data:
        z_m = build_momentum_score(rets, tradfi_in_data, close_panel.index)
        z_l = build_lowrisk_score(rets, tradfi_in_data, close_panel.index)
        score[tradfi_in_data] = (z_m.fillna(0.0) + z_l.fillna(0.0)) / 2.0

    # Long-only tilt weights
    n = len(data)
    w = tilt_weights(score, min_weight=1.0 / max(n, 1))
    w = w.reindex(close_panel.index).ffill().fillna(0.0)
    w = w.div(w.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # H3.2 conviction scaling at each rebalance day
    size_scalar = pd.Series(1.0, index=close_panel.index)
    rebal_idx = list(range(0, len(close_panel.index), REBAL_DAYS))
    for i in rebal_idx:
        recent = rets.iloc[max(0, i - 30):i].mean(axis=1)
        size_scalar.iloc[i] = h32_size(recent)
    w_scaled = w.multiply(size_scalar.values, axis=0)
    w_scaled = w_scaled.clip(lower=0.0, upper=H32_CAP / n)
    w_scaled = w_scaled.div(w_scaled.sum(axis=1).replace(0, np.nan), axis=0).fillna(0.0)

    # Book returns + vol target
    raw_pnl = book_returns(w_scaled, rets)
    targeted_pnl = vol_target(raw_pnl, target_ann=VOL_TARGET_ANN)
    today_ret = float(targeted_pnl.iloc[-1]) if len(targeted_pnl) > 0 else 0.0

    # Hold-the-panel benchmark
    bench = hold_panel_benchmark(rets)

    # Excess return
    excess = today_ret - float(bench.iloc[-1])

    new_nav = float(state.get("nav", 1.0)) * (1.0 + today_ret)
    n_days_marked = int(state.get("n_days_marked", 0)) + 1
    inception = dt.date.fromisoformat(state["inception_date"])
    n_forward_days = (today - inception).days
    validated = n_forward_days >= VALIDATION_MIN_DAYS

    # Factor Sharpe attribution (single-factor book sharpes)
    factor_attribution = {}
    for fname, fbuilder in [
        ("quality", lambda a: (cis_long[cis_long["asset"].isin(a)]
                                .pivot(index="date", columns="asset", values="O")
                                .reindex(index=close_panel.index, columns=a))),
        ("momentum", lambda a: rets[a]),
        ("lowrisk", lambda a: rets[a]),
    ]:
        try:
            if fname == "quality":
                fz = (builder := fbuilder)(list(data.keys()))
                fz = (fz - fz.mean(axis=1).values[:, None]) / fz.std(axis=1).values[:, None]
                fz = fz.clip(-Z_CLIP, Z_CLIP)
            elif fname == "momentum":
                fz = (close_panel.shift(1) / close_panel.shift(MOMENTUM_LOOKBACK + 1) - 1)
            else:
                vol = rets.rolling(VOL_LOOKBACK, min_periods=10).std()
                fz = -vol
            fw = tilt_weights(fz, min_weight=1.0 / max(n, 1)).reindex(close_panel.index).ffill().fillna(0.0)
            fpnl = book_returns(fw, rets)
            if fpnl.std() > 0:
                factor_attribution[fname] = float(
                    fpnl.mean() / fpnl.std() * np.sqrt(PERIODS_PER_YEAR))
        except Exception as ex:
            _logger.debug("factor attribution failed for %s: %s", fname, ex)

    new_state = {
        **state,
        "nav": new_nav,
        "last_mark_date": str(today),
        "n_days_marked": n_days_marked,
        "factor_sharpe_attribution": factor_attribution,
    }
    max_share = max(
        (abs(s) / max(sum(abs(v) for v in factor_attribution.values()), 1e-9))
        for s in factor_attribution.values()) if factor_attribution else 0.0

    # NAV_TABLE was declared at line 56 and never written to — same defect as
    # pod_aggregator (S-214). Both books marked into their state row only.
    nav_write = NavWrite(True, NAV_TABLE, "dry_run")
    if not dry_run:
        # ⚠️ **先写行,再存 state** (S-321)。原来的顺序是反的:state 先被标成
        # 「今天已 mark」,而 `write_nav_row` 随后失败 —— 于是 state 声称成功、
        # 表里 0 行,**而当天任何一次重跑都会撞上 `already_marked_today` 并
        # 返回 skipped**,把真正的失败盖掉。部署一天好几次,重跑是常态。
        #
        # 「我记得我做过」和「它确实在那里」是两个状态,而这里让前者
        # 覆盖了后者。state 是给自己看的,表是给所有人看的 —— **以表为准。**
        nav_write = await write_nav_row(NAV_TABLE, {
            "mark_date": str(today),
            "nav": new_nav,
            "daily_return": today_ret,
            "excess_vs_bench": excess,
            "n_days_marked": n_days_marked,
            "validated": validated,
            "factor_attribution": factor_attribution,
            "max_single_factor_sharpe_share": max_share,
        })

        # 只有真的写进去了才记「今天做过」。写失败时**不存 state**,
        # 下一轮会重试 —— 而这正是我们要的。
        if nav_write.ok:
            await _save_state(new_state)

    return {
        "status": "ok" if nav_write.ok else "degraded",
        "date": str(today),
        "nav": new_nav,
        "today_return": today_ret,
        "today_excess_vs_bench": excess,
        "n_days_marked": n_days_marked,
        "validated": validated,
        "factor_attribution": factor_attribution,
        "max_single_factor_sharpe_share": max_share,
        **fetched.as_payload(),
        **nav_write.as_payload(),
    }


# ── API: NAV curve ───────────────────────────────────────────────────────────
async def get_curve(limit: int = 400) -> dict[str, Any]:
    state = await _load_state()
    inception = dt.date.fromisoformat(state["inception_date"])
    n_days = (dt.date.today() - inception).days
    return {
        "endpoint": ENDPOINT_NAV,
        "strategy": "cross_asset_factor_tilt",
        "spec": "docs/STRATEGY_4_CROSS_ASSET_FACTOR_TILT.md",
        "inception_date": state["inception_date"],
        "as_of": str(dt.date.today()),
        "current_nav": state.get("nav", 1.0),
        "n_days_marked": state.get("n_days_marked", 0),
        "n_forward_days": n_days,
        "validated": n_days >= VALIDATION_MIN_DAYS,
        "validation_min_days": VALIDATION_MIN_DAYS,
        "universe_size": len(FULL_UNIVERSE),
        "n_crypto": len([s for s in FULL_UNIVERSE if s in CRYPTO_UNIVERSE]),
        "n_tradfi": len([s for s in FULL_UNIVERSE if s in TRADFI_UNIVERSE]),
        "factor_sharpe_attribution": state.get("factor_sharpe_attribution", {}),
        "compliance": "positioning language only — no investment advice",
    }


# ── Background loop ───────────────────────────────────────────────────────────
async def daily_loop(interval_hours: int = 24) -> None:
    while True:
        try:
            result = await mark_and_rebalance(dry_run=False)
            _logger.info("factor_tilt mark: %s", result.get("status"))
        except Exception as ex:
            _logger.exception("factor_tilt loop error: %s", ex)
        await asyncio.sleep(interval_hours * 3600)


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--once", action="store_true")
    p.add_argument("--loop", action="store_true")
    args = p.parse_args()
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(name)s] %(message)s")
    if args.loop:
        asyncio.run(daily_loop())
    else:
        print(json.dumps(asyncio.run(mark_and_rebalance(dry_run=args.dry_run)),
                          indent=2, default=str))