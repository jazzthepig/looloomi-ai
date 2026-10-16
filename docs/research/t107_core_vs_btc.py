"""T-107 / M-584:① (cap_uncapped) 重建到数据最早 + 与持有 BTC 同区间分周期比较。

按 M-584 §1–§5 预注册;不引入 src/ 改动 —— 读 core_variants ① 臂 + core_cap panel_universe 照搬。
数据来源:CoinGecko Pro /coins/{id}/market_chart 全历史(由 t107_cg_fetch.py 拉到
/Volumes/CometCloudAI/cometcloud-local/research/t107_cg_cache/<SYMBOL>.json)。

用法(Mac 侧跑):
    python3 docs/research/t107_core_vs_btc.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import ab_test, block_permute  # noqa: E402
import src.data.signals.core_variants as cv  # noqa: E402
from src.data.signals.core_variants import _norm, target_weights, simulate  # noqa: E402
from src.data.signals.core_cap import panel_universe  # noqa: E402

# M-584 §2 主判据写死:mean_block=3, days_per_year=365。
# acceptance「成本 = 0」:把 COST_BPS 临时覆盖,跑完恢复。
cv.COST_BPS = 0.0

TARGET_START = pd.Timestamp("2018-01-01")
REBAL_FREQ = "MS"  # 月初 UTC
DOMINANCE_LOOKBACK = 90
BLOCK_DAYS = 180   # 6 个月块
SHUFFLE_N = 1000

CACHE = Path('/Volumes/CometCloudAI/cometcloud-local/research/t107_cg_cache')
STABLE_KEYWORDS = ("usd", "busd", "dai", "tusd", "usdc", "usdt", "wbtc",
                   "weth", "steth", "cbeth")


def load_one(symbol: str) -> pd.DataFrame | None:
    p = CACHE / f'{symbol}.json'
    if not p.exists():
        return None
    d = json.loads(p.read_text())
    if 'prices' not in d or 'market_caps' not in d:
        return None
    p_ts = pd.to_datetime([r[0] for r in d['prices']], unit='ms', utc=True).tz_convert(None)
    p_px = [r[1] for r in d['prices']]
    m_ts = pd.to_datetime([r[0] for r in d['market_caps']], unit='ms', utc=True).tz_convert(None)
    m_mc = [r[1] for r in d['market_caps']]
    # reindex to daily
    df = pd.DataFrame({'price': p_px, 'mcap': m_mc}, index=p_ts)
    df = df[~df.index.duplicated(keep='last')].sort_index()
    daily_idx = pd.date_range(df.index.min().normalize(), df.index.max().normalize(), freq='D')
    df = df.reindex(daily_idx).ffill(limit=3)
    return df


def filter_panel(panel: list[str]) -> list[str]:
    keep = []
    for c in panel:
        if any(k in c.lower() for k in STABLE_KEYWORDS):
            continue
        keep.append(c)
    return keep


def build_panels(panel: list[str], start: pd.Timestamp, end: pd.Timestamp):
    px_dict, mc_dict = {}, {}
    for s in panel:
        d = load_one(s)
        if d is None or d.empty:
            continue
        d = d.loc[start:end]
        if d['price'].notna().sum() < 30:
            continue
        px_dict[s] = d['price']
        mc_dict[s] = d['mcap']
    px = pd.DataFrame(px_dict)
    mc = pd.DataFrame(mc_dict)
    days = pd.date_range(start, end, freq='D')
    px = px.reindex(days).ffill(limit=3)
    mc = mc.reindex(days).ffill(limit=3)
    return px, mc


def make_targets(arm: str, days: pd.DatetimeIndex, px: pd.DataFrame,
                 mcap_prev: pd.DataFrame) -> dict[pd.Timestamp, dict[str, float]]:
    rebal = [d for d in days if d == days[0] or (d.day == 1)]
    quoted = {}
    for d in rebal:
        y = d - pd.Timedelta(days=1)
        quoted[d] = [s for s in px.columns
                     if y in px.index and pd.notna(px.at[y, s])] if y in px.index else []
    out = {}
    for d in rebal:
        if not quoted[d]:
            continue
        try:
            out[d] = target_weights(arm, d, px, mcap_prev, quoted[d])
        except Exception:
            out[d] = {}
    return out


def make_btc_targets(days: pd.DatetimeIndex) -> dict[pd.Timestamp, dict[str, float]]:
    return {days[0]: {"BTC": 1.0}}


def run_arm(arm: str, px: pd.DataFrame, mcap_prev: pd.DataFrame) -> pd.Series:
    days = px.index
    rets = (px / px.shift(1) - 1).loc[days].fillna(0.0)
    if arm == "btc":
        targets = make_btc_targets(days)
    else:
        targets = make_targets(arm, days, px, mcap_prev)
    return simulate(rets, targets)


def dominance(mcap_panel: pd.DataFrame, btc_id: str = "BTC") -> pd.Series:
    if btc_id not in mcap_panel.columns:
        return pd.Series(np.nan, index=mcap_panel.index)
    tot = mcap_panel.sum(axis=1, min_count=1)
    return mcap_panel[btc_id] / tot


def regime_split(core_ret: pd.Series, btc_px: pd.Series,
                 mcap_panel: pd.DataFrame, lookback: int) -> pd.DataFrame:
    dom = dominance(mcap_panel)
    dom_look = dom / dom.shift(lookback) - 1.0
    aligned = pd.concat([
        core_ret.rename("core"),
        btc_px.rename("btc_px"),
        dom_look.rename("dom_90d_change"),
    ], axis=1).dropna(subset=["core", "btc_px"])
    aligned["log_diff"] = (np.log1p(aligned["core"])
                            - np.log1p(aligned["btc_px"].pct_change().fillna(0.0)))
    aligned["regime"] = np.where(aligned["dom_90d_change"] > 0, "up", "down")
    return aligned


def shuffle_diff_test(aligned: pd.DataFrame, n: int = SHUFFLE_N,
                      block_days: int = BLOCK_DAYS) -> dict:
    rng = np.random.default_rng(584)
    regimes = aligned["regime"].to_numpy()
    diffs = aligned.groupby("regime")["log_diff"].mean()
    actual = diffs.get("up", 0.0) - diffs.get("down", 0.0)
    null = []
    for _ in range(n):
        shuf = block_permute(list(regimes), block_days, rng)
        df = pd.DataFrame({"log_diff": aligned["log_diff"].to_numpy(), "regime": shuf})
        d = df.groupby("regime")["log_diff"].mean()
        null.append(d.get("up", 0.0) - d.get("down", 0.0))
    null = np.array(null)
    p = float((np.abs(null) >= abs(actual)).mean())
    return {"actual": float(actual), "p_two_sided": p,
            "null_mean": float(null.mean()),
            "null_std": float(null.std()),
            "null_p05": float(np.quantile(null, 0.05)),
            "null_p95": float(np.quantile(null, 0.95)),
            "n": n}


def main() -> None:
    panel = filter_panel(list(panel_universe()))
    print(f"[panel] {len(panel)} names; sample: {panel[:6]}")

    # 重建起点 = 「全 panel 中最早币上市日」(尊重不修幸存者偏差)
    earliest = {}
    for s in panel:
        d = load_one(s)
        if d is not None and not d.empty:
            earliest[s] = d.index.min()
    print(f"[earliest] min={min(earliest.values()).date()}  "
          f"max_of_earliest={max(earliest.values()).date()}  (面板 24 名齐 = 2023-05 起)")

    # 起点 = 全 panel 都齐(SUI 2023-05-03);如想往前,可用 min(max_of_earliest, TARGET_START)
    start = pd.Timestamp("2018-01-01")
    end = pd.Timestamp("2026-10-15")
    if min(earliest.values()) > start:
        # 最早币(BTC) 在 2013 起,所以 start 可达 2018
        pass
    px, mc = build_panels(panel, start, end)
    print(f"[shape] px={px.shape}, mc={mc.shape}, "
          f"days={len(px)}, last={px.index[-1].date()}")

    # 各臂收益
    arms = ("cap_uncapped", "cap_c40", "mom90", "btc")
    rets_core = {}
    for arm in arms:
        if arm == "btc":
            days = px.index
            r = pd.Series(px["BTC"].pct_change().fillna(0.0), index=days) \
                if "BTC" in px.columns else pd.Series(0.0, index=days)
        else:
            try:
                r = run_arm(arm, px, mc)
            except Exception as e:
                print(f"[{arm}] sim FAIL: {e}")
                continue
        rets_core[arm] = r
        nav = (1 + r).cumprod()
        print(f"[{arm:12s}] days={len(r)}  total={(nav.iloc[-1] - 1):+.3f}  "
              f"maxdd={(nav / nav.cummax() - 1).min():+.3f}")

    # §2 主判据
    align = pd.concat([rets_core["btc"].rename("btc"),
                       rets_core["cap_uncapped"].rename("one")], axis=1).dropna()
    res = ab_test(align["btc"].tolist(), align["one"].tolist(),
                  mean_block=3, days_per_year=365, seed=584)
    print(f"\n[verdict] 全样本 BTC vs ①:\n"
          f"  verdict={res['verdict']}  p(BTC≤one) {res['p_b_le_a']:.4f}  "
          f"p(BTC≥one) {res['p_b_ge_a']:.4f}\n"
          f"  ratio_b/a={res['ratio_b_over_a']:.4f}  n_days={res['n_days']}  "
          f"underpowered={res['underpowered']}\n"
          f"  ci95_log_diff={res['ci95_log_diff']}")

    # 背景:cap_c40 / mom90 vs BTC
    bg = {}
    for arm in ("cap_c40", "mom90"):
        if arm not in rets_core:
            continue
        a = pd.concat([rets_core["btc"].rename("btc"),
                       rets_core[arm].rename("one")], axis=1).dropna()
        bg[arm] = ab_test(a["btc"].tolist(), a["one"].tolist(),
                          mean_block=3, days_per_year=365, seed=584)
        print(f"[bg {arm}] verdict={bg[arm]['verdict']}  "
              f"p(BTC≤one) {bg[arm]['p_b_le_a']:.4f}  ratio_b/a={bg[arm]['ratio_b_over_a']:.4f}")

    # §3 分状态
    aligned = regime_split(rets_core["cap_uncapped"], px["BTC"], mc, DOMINANCE_LOOKBACK)
    grp = aligned.groupby("regime")["log_diff"].agg(["count", "mean", "std"])
    print(f"\n[dominance split]\n{grp}")
    shuf = shuffle_diff_test(aligned)
    print(f"\n[shuffle 6mo×{SHUFFLE_N}] actual=up−down={shuf['actual']:+.5f}  "
          f"p_two_sided={shuf['p_two_sided']:.3f}  "
          f"null_p05={shuf['null_p05']:+.5f}  null_p95={shuf['null_p95']:+.5f}")

    # §4 探索
    by_year = {}
    for yr in range(int(start.year), int(end.year)+1):
        s = rets_core["cap_uncapped"].loc[f"{yr}-01-01":f"{yr}-12-31"]
        b = rets_core["btc"].loc[f"{yr}-01-01":f"{yr}-12-31"]
        if len(s) < 5:
            continue
        nav_c = (1 + s).cumprod()
        nav_b = (1 + b).cumprod()
        by_year[yr] = {
            "core_total": float(nav_c.iloc[-1] - 1),
            "btc_total": float(nav_b.iloc[-1] - 1),
            "core_maxdd": float((nav_c / nav_c.cummax() - 1).min()),
            "btc_maxdd": float((nav_b / nav_b.cummax() - 1).min()),
        }
    alt_season = rets_core["cap_uncapped"].loc["2020-06":"2021-12"]
    alt_season_b = rets_core["btc"].loc["2020-06":"2021-12"]
    if len(alt_season) > 5:
        alt_diff = float((alt_season - alt_season_b).sum())
    else:
        alt_diff = None

    payload = {
        "panel_size": len(panel),
        "earliest_per_symbol": {s: str(d.date()) for s, d in earliest.items()},
        "data_start": str(start.date()),
        "data_end": str(end.date()),
        "arm_totals": {a: float(((1 + rets_core[a]).cumprod().iloc[-1] - 1))
                       for a in rets_core},
        "arm_maxdd": {a: float(((1 + rets_core[a]).cumprod() /
                                  (1 + rets_core[a]).cumprod().cummax() - 1).min())
                      for a in rets_core},
        "verdict_full": res,
        "bg": bg,
        "regime_split": grp.to_dict(),
        "shuffle_6mo": shuf,
        "by_year": by_year,
        "alt_season_diff_2020_06_to_2021_12": alt_diff,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    out = ROOT / "docs" / "research" / "t107_results.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=1, default=str))
    print(f"\n[wrote] {out}")


if __name__ == "__main__":
    main()