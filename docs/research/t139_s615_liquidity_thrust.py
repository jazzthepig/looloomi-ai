"""T-139 / S-615 — ③ 推力的「平静」换成「流动性 × 趋势」(Fed / 稳定币)。

预注册在 REFUTATION_LEDGER §S-285(S-615 已固定),脚本只算不改规则。

第一步(任务 acceptance 强制):用库里 mult_v2_replay 的状态与底仓在 Python 里**完整复现**逐日 NAV,
与库里存的 NAV 逐行对比,差 < 1e-6 ⇒ 通过 ⇒ 继续;对不上先停下报差异。

第二步:按 S-615 算臂 L(美联储净流动性 28d 变化)与臂 S(USDT+USDC 边际流动性 S-285 口径)各算一次,
随机择时 1,000 次(同 ③ 预注册的 20 天块随机重排),两个窗口(2023–2024 语境 / 2025-01-01 → 2026-10-18 判定段)分报。

报告写 Mac 数据根 _reports/absorb_input/T-139_s615.md(S-501 private)。
"""
from __future__ import annotations

import asyncio
import math
import os
import sys
from pathlib import Path

# 加载 .env(仓库显式声明「没有代码加载 .env」,这里手动塞)
_env = Path("/Users/sbb/Projects/looloomi-ai/.env")
if _env.exists():
    for line in _env.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k, v)

# 让 src.* 可导入
sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai")

import numpy as np
import pandas as pd

from src.data.style.header import _read_all
from src.data.signals.multiplier import (LEVELS, VOL_CUT, CASH_ANN, FUNDING_FALLBACK_ANN, SWITCH_COST_BPS,
                                          multiplier, apply_multiplier, _stats, random_timing_pct)

REPLAY_START = pd.Timestamp("2023-01-02")
HOLDOUT_START = pd.Timestamp("2025-01-01")
FORWARD_END = pd.Timestamp("2026-10-18")  # S-615 写的判定段终点(2026-10-19 14:35 UTC)


# ──────────────────────────────────────────────────────────────────────────────
# 第一步:复现 mult_v2_replay 的逐日 NAV
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_mult_v2_replay() -> pd.DataFrame:
    rows = await _read_all("multiplier_daily",
                           {"select": "d,arm,m,ret,nav,cost,dist_200,vol_pct_3y",
                            "arm": "eq.mult_v2_replay", "order": "d.asc"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    return df.set_index("d").sort_index()


async def fetch_state() -> pd.DataFrame:
    rows = await _read_all("state_daily",
                           {"select": "d,feature,value", "entity": "eq.panel",
                            "feature": "in.(dist_200,vol_pct_3y,funding_7d_ann)",
                            "d": f"gte.{REPLAY_START.date().isoformat()}", "order": "d.asc"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    return df.pivot_table(index="d", columns="feature", values="value")


async def fetch_core_u_replay() -> pd.Series:
    rows = await _read_all("multiplier_daily",
                           {"select": "d,ret,nav", "arm": "eq.core_u_replay", "order": "d.asc"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    return pd.Series({pd.Timestamp(r["d"]): float(r["ret"]) for r in df.to_dict("records")}).sort_index()


def reproduce_mult_v2_replay(core_ret: pd.Series, state: pd.DataFrame) -> pd.DataFrame:
    m_at = pd.Series({d: multiplier(_f(row.get("dist_200")), _f(row.get("vol_pct_3y")))
                      for d, row in state.iterrows()}, dtype=float)
    m_prev = m_at.shift(1, freq="D")
    funding = state.get("funding_7d_ann", pd.Series(dtype=float)).astype(float)
    book = apply_multiplier(core_ret, m_prev, funding)
    return book


def _f(v):
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


# ──────────────────────────────────────────────────────────────────────────────
# 第二步:算臂 L / 臂 S
# ──────────────────────────────────────────────────────────────────────────────

async def fetch_fed_net_liquidity() -> pd.Series:
    rows = await _read_all("macro_daily", {"select": "d,value", "series": "eq.fed_net_liquidity",
                                            "order": "d.asc"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    return pd.Series({pd.Timestamp(r["d"]): float(r["value"]) for r in df.to_dict("records")}).sort_index()


async def fetch_stable_supply() -> pd.Series:
    rows = await _read_all("cg_coin_mcap_daily",
                           {"select": "d,mcap,coin_id",
                            "coin_id": "in.(tether,usd-coin)", "order": "d.asc"})
    df = pd.DataFrame(rows)
    df["d"] = pd.to_datetime(df["d"])
    pv = df.pivot_table(index="d", columns="coin_id", values="mcap").astype(float)
    # USDT + USDC 总额
    return pv.sum(axis=1).sort_index()


def stable_marginal(supply_series: pd.Series, d: pd.Timestamp) -> Optional[float]:
    """S-285 口径:USDT+USDC 市值 30 日增速 − 30 天前的 30 日增速。d−1 取值。"""
    # 取 d-1 的符号(改善/变差);S-285 用 d-1
    p = supply_series
    d_used = d - pd.Timedelta(days=1)
    g_now = _pct_change(p, d_used, 30)
    if g_now is None:
        return None
    g_prev = _pct_change(p, d_used - pd.Timedelta(days=30), 30)
    if g_prev is None:
        return None
    return g_now - g_prev


def _pct_change(s: pd.Series, d: pd.Timestamp, lookback: int) -> Optional[float]:
    if d not in s.index:
        return None
    d_prev = d - pd.Timedelta(days=lookback)
    if d_prev not in s.index:
        # 找 d_prev 之前最近的一个值
        prev = s.loc[:d_prev]
        if len(prev) < 2:
            return None
        d_prev = prev.index[-1]
        if (d - d_prev).days < lookback - 5:
            return None
    a = float(s.loc[d])
    b = float(s.loc[d_prev])
    if b <= 0 or not math.isfinite(a) or not math.isfinite(b):
        return None
    return a / b - 1


def feed_liq_up(liq: pd.Series, d: pd.Timestamp) -> Optional[bool]:
    """Fed 净流动性 d-1 > d-29 ⇒ 上升。"""
    if (d - pd.Timedelta(days=1)) not in liq.index or (d - pd.Timedelta(days=29)) not in liq.index:
        return None
    return float(liq.loc[d - pd.Timedelta(days=1)]) > float(liq.loc[d - pd.Timedelta(days=29)])


def liq_arm_m(dist_200: Optional[float], liq_up: Optional[bool]) -> float:
    """S-615 臂 L / 臂 S 共用规则:dist_200 > 0 且 liq_up ⇒ 1.3;dist_200 ≤ 0 且 not liq_up ⇒ 0.7;其余 1.0。"""
    if dist_200 is None or liq_up is None:
        return 1.0
    up = dist_200 > 0
    if up and liq_up:
        return LEVELS[2]
    if (not up) and (not liq_up):
        return LEVELS[0]
    return LEVELS[1]


def evaluate_arm(core_ret: pd.Series, m_prev: pd.Series, funding: pd.Series,
                 end: pd.Timestamp = FORWARD_END) -> dict:
    """S-615 规则:两个窗口 = (2023-01-02 → 2024-12-31) + (2025-01-01 → 2026-10-18)。"""
    windows = {"2023_2024_context": (REPLAY_START, HOLDOUT_START - pd.Timedelta(days=1)),
               "2025_2026_judge": (HOLDOUT_START, FORWARD_END)}
    out: dict = {}
    for name, (lo, hi) in windows.items():
        sel = (core_ret.index >= lo) & (core_ret.index <= hi)
        r1 = core_ret[sel]
        if len(r1) < 2:
            out[name] = {"n": int(len(r1))}
            continue
        book = apply_multiplier(r1, m_prev, funding)
        mm = book["m"]
        out[name] = {"core": _stats(r1), "arm": _stats(book["ret"]),
                     "share_days": {str(lv): round(float((mm == lv).mean()), 3) for lv in LEVELS},
                     **random_timing_pct(r1, m_prev, funding, n=1000, block=20, seed=63)}
    return out


# ──────────────────────────────────────────────────────────────────────────────
# main
# ──────────────────────────────────────────────────────────────────────────────

async def main():
    print("─" * 80)
    print("T-139 / S-615 — ③ 推力的「平静」条件换成 Fed / 稳定币边际流动性")
    print("─" * 80)

    # ── 第一步:复现 mult_v2_replay ────────────────────────────────────────
    print("\n[step 1] 复现 mult_v2_replay 逐日 NAV")
    v2_db = await fetch_mult_v2_replay()
    state = await fetch_state()
    core_u_ret = await fetch_core_u_replay()

    print(f"  库内 mult_v2_replay: {len(v2_db)} 行 {v2_db.index.min().date()} → {v2_db.index.max().date()}")
    print(f"  库内 state_daily(dist_200/vol_pct_3y/funding_7d_ann): {len(state)} 行")
    print(f"  库内 core_u_replay: {len(core_u_ret)} 行")

    rep = reproduce_mult_v2_replay(core_u_ret, state)
    common = v2_db.index.intersection(rep.index)
    diff_nav = (v2_db.loc[common, "nav"].astype(float) - rep.loc[common, "nav"]).abs()
    diff_ret = (v2_db.loc[common, "ret"].astype(float) - rep.loc[common, "ret"]).abs()
    max_diff_nav = float(diff_nav.max()) if len(diff_nav) else float("nan")
    max_diff_ret = float(diff_ret.max()) if len(diff_ret) else float("nan")
    print(f"  复现 vs 库内 mult_v2_replay NAV:max|Δ| = {max_diff_nav:.2e}  ({len(common)} 行)")
    print(f"  复现 vs 库内 mult_v2_replay ret:max|Δ| = {max_diff_ret:.2e}")

    if max_diff_nav > 1e-6:
        raise RuntimeError(f"❌ mult_v2_replay 复现与库内差 {max_diff_nav:.4e} > 1e-6 —— 停下,先报差异")
    print(f"✅ 复现通过(差 < 1e-6)")

    # 把复现出的 m_prev 与 funding 拿出来供臂 L / 臂 S 用
    m_prev_v2 = rep["m"].copy()
    funding = state.get("funding_7d_ann", pd.Series(dtype=float)).astype(float)

    # ── 第二步:算臂 L / 臂 S ───────────────────────────────────────────────
    print("\n[step 2] 算臂 L / 臂 S")
    fed = await fetch_fed_net_liquidity()
    stable = await fetch_stable_supply()
    print(f"  fed_net_liquidity: {len(fed)} 行 {fed.index.min().date() if len(fed) else 'EMPTY'} → {fed.index.max().date() if len(fed) else ''}")
    print(f"  stable_supply(tether+usd-coin 总市值): {len(stable)} 行 {stable.index.min().date() if len(stable) else 'EMPTY'} → {stable.index.max().date() if len(stable) else ''}")

    # dist_200 来自 state
    dist_200 = state["dist_200"].astype(float) if "dist_200" in state.columns else pd.Series(dtype=float)

    # 臂 L
    m_L = pd.Series(index=core_u_ret.index, dtype=float)
    for d in core_u_ret.index:
        d200 = float(dist_200.loc[d]) if d in dist_200.index and pd.notna(dist_200.loc[d]) else None
        lup = feed_liq_up(fed, d)
        m_L.loc[d] = liq_arm_m(d200, lup)

    # 臂 S
    m_S = pd.Series(index=core_u_ret.index, dtype=float)
    for d in core_u_ret.index:
        d200 = float(dist_200.loc[d]) if d in dist_200.index and pd.notna(dist_200.loc[d]) else None
        smarg = stable_marginal(stable, d)
        lup = None if smarg is None else smarg > 0
        m_S.loc[d] = liq_arm_m(d200, lup)

    # m_prev(d) = d-1 收盘定的敞口作用于 d
    m_L_prev = m_L.shift(1, freq="D")
    m_S_prev = m_S.shift(1, freq="D")

    # v2 复现的 m_prev 也只用于对齐窗口
    m_v2_prev = m_prev_v2.shift(1, freq="D")

    ev_v2 = evaluate_arm(core_u_ret, m_v2_prev, funding)
    ev_L = evaluate_arm(core_u_ret, m_L_prev, funding)
    ev_S = evaluate_arm(core_u_ret, m_S_prev, funding)

    # ── 输出汇总表 ─────────────────────────────────────────────────────────
    print("\n[result] 逐臂 × 逐窗口:")
    def fmt(ev, arm):
        return {w: {"core_total": ev[w]["core"]["total"], "arm_total": ev[w]["arm"]["total"],
                    "arm_maxdd": ev[w]["arm"]["maxdd"], "arm_sharpe": ev[w]["arm"]["sharpe"],
                    "pct_vs_random": ev[w]["pct_vs_random"],
                    "rand_p50": ev[w]["random_p50"], "rand_p95": ev[w]["random_p95"]}
                for w in ev}

    result = {
        "mult_v2_replay_reproduce": {"max_abs_diff_nav": max_diff_nav, "max_abs_diff_ret": max_diff_ret,
                                     "n_common": int(len(common)),
                                     "first_d": common.min().date().isoformat() if len(common) else None,
                                     "last_d": common.max().date().isoformat() if len(common) else None},
        "data_coverage": {
            "fed_net_liquidity": {"n": int(len(fed)),
                                  "first": fed.index.min().date().isoformat() if len(fed) else None,
                                  "last": fed.index.max().date().isoformat() if len(fed) else None},
            "stable_supply": {"n": int(len(stable)),
                              "first": stable.index.min().date().isoformat() if len(stable) else None,
                              "last": stable.index.max().date().isoformat() if len(stable) else None},
        },
        "evaluations": {
            "mult_v2_replay": fmt(ev_v2, "v2"),
            "arm_L_fed": fmt(ev_L, "L"),
            "arm_S_stablecoin": fmt(ev_S, "S"),
        },
    }

    import json
    out_json = Path("/Users/sbb/Projects/looloomi-ai-lane-b/docs/research/t139_s615_result.json")
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(result, indent=2, default=str))
    print(f"\n[write] {out_json}")

    # 简短报告到 _reports/absorb_input(Mac 数据根,private)
    rep_md = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-139_s615.md")
    rep_md.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# T-139 / S-615 — ③ 推力的「平静」换成 Fed / 稳定币边际流动性",
             "",
             f"**预注册:** REFUTATION_LEDGER §S-615(2026-03-19 14:35 UTC),本脚本只算不改规则。",
             "",
             "## 第一步:mult_v2_replay 复现",
             "",
             f"- 库内行数:{len(v2_db)};复现共用 {len(common)} 行公共索引",
             f"- max|Δnav| = **{max_diff_nav:.2e}**(阈值 1e-6)⇒ {'✅ 通过' if max_diff_nav <= 1e-6 else '❌ 未通过'}",
             f"- max|Δret| = {max_diff_ret:.2e}",
             "",
             "## 数据覆盖",
             "",
             f"- fed_net_liquidity:{result['data_coverage']['fed_net_liquidity']}",
             f"- stable_supply(tether+usd-coin 总市值):{result['data_coverage']['stable_supply']}",
             "",
             "## 逐臂 × 逐窗口",
             "",
             "| 臂 | 窗口 | ① 总收益 | 臂总收益 | 臂 maxDD | 臂 Sharpe | pct_vs_random | rand_p50 | rand_p95 |",
             "|---|---|---|---|---|---|---|---|---|"]
    for arm_name, data in result["evaluations"].items():
        for w, row in data.items():
            lines.append(f"| {arm_name} | {w} | {row['core_total']} | {row['arm_total']} | "
                         f"{row['arm_maxdd']} | {row['arm_sharpe']} | {row['pct_vs_random']} | "
                         f"{row['rand_p50']} | {row['rand_p95']} |")
    lines += ["",
              "## 过关判定(每臂单独判,试验数 = 2)",
              "",
              "- 判定段(2025-01-01 → 2026-10-18)总收益 > ③ v2",
              "- 最大回撤不比 ③ v2 深 2pp 以上",
              "- 「臂 − ①」总收益差在随机择时分布 ≥ 95 分位",
              ""]
    rep_md.write_text("\n".join(lines))
    print(f"[write] {rep_md}")

    print("\n[done] 跑完了,数据写盘。")


if __name__ == "__main__":
    asyncio.run(main())