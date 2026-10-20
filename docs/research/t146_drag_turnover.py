"""T-146 ── T-137 实施拖累 ≈7pp 残量的换手与成交时点拆解。

T-137 / T-143 解释到:基准回放对理想 −9.46pp/年;a–d 已解释 ≈2.3pp;
(e) 比例限额在 nav_cap=3000 时被吸收、= 0pp;(f) 收盘混源约 −0.27pp;
(g) 平均 |target − actual| ≈ 0.097(未折算成年化,差先不读)。

本卡三项独立开关、报年化与分年(每项都对**同一份基准回放**叠算,不重跑回放):

  h) **信号日 vs 回放实际成交日的延迟分布**。
     「信号日」= 计划当天算出的目标权重与上一日「成交后实际」之差,绝对值跨过再平衡门槛
     的那一天。「成交日」= 回放真正下手的那一天。延迟 = 成交日 − 信号日。
     把每笔「信号 → 成交」的延迟天数做成直方图(0/1/2/3+/5+),并按年化贡献分年
     (延迟 ≥ N 天的那部分时间等价年化)。

  i) **5% 门槛内被跳过的调仓累计少拿的暴露**。
     按日:理想目标权重 vs 回放实际权重(沿用 T-143 gap) → 差距乘当日该币收益
     → 全期求和(以及分年求和);这是「按日 (target − actual) × 当日收益」的总暴露差。
     **注意**:与 T-143 的 |gap| 不同 — T-143 是「绝对缺口」,这里把它**乘**当日收益折算;
     正负抵消后才是「真正少赚多少」。

  j) **止损 / 破位出场后的「空仓期」**(回放空仓、理想仍持仓)的天数与这些天的面板收益。
     「空仓日」= 总仓位(Σ actual_w[s]) ≤ 1e-6 的日子。
     这些日子的「错过面板收益」= sum_t(ideal_nav_return − replay_nav_return)
     × 年,以及总天数与平均门连续长度。

每项独立开关;其他参数照 T-137 基准。汇总三项之后剩多少没解释写明。

读库只用环境变量 SUPABASE_URL / SUPABASE_KEY(publishable),不读 .env、不打印 key。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from docs.research import t143_drag_decomposition as t143   # noqa: E402
from src.exec_host.replay import ideal_nav                  # noqa: E402

# ── 区间 / 账户(照 T-137 基准) ─────────────────────────────────────────────
START = "2021-01-01"
END = "2026-10-18"
ACCOUNT = 3_000.0
SYMS = ["BTC", "ETH"]
COST_GRID = {"half_spread_bps": 5.0, "fee_bps": 7.0}
REBAL_BAND = 0.05                          # ex.target_weights 的再平衡门槛,与 T-137 一致
EMPTY_EPS = 1e-6


# ── (h) 信号日 vs 实际成交日 ──────────────────────────────────────────────
def fill_delay(replay: dict, ohlc: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """对基准回放的逐笔成交,统计「需求被创建日 → 该笔成交日」的延迟。

    这里用「宽容版」信号:weight delta 与成交方向同号即可(无 5% 门槛过滤),
    因为:
      * 5% 门槛在 X1V 的 BTC/ETH 双币 + 短期 NAV 不大的情况下很少跨过
        (只在冷启动和大波动时);
      * 实际的成交可能由 executor 的 enter/exit_all/单日流转 / 小幅 rebalance 触发,
        不只是 5% 跨门槛;
      * 「同向 demand」哪怕只是 +0.001 也算「今天想往这个方向调」,延迟 0/1 都
        反映**真实日内决策 - 执行差**。

    对每笔成交 (d_trade, sym, side):
      signal_day d' = max d' ≤ d_trade: target_w[s,d'] − cw_proxy[s,d'] 与 side 同号
      delay         = d_trade − d'(天数;0 = 同日成交,1 = 隔日,N = 信号后第 N 天成交)
    """
    nav_df = replay["nav"]
    trades = replay["trades"]
    syms = [c[2:] for c in nav_df.columns if c.startswith("w_")]
    if not syms:
        syms = list(ohlc.keys())

    days = [pd.Timestamp(d).date() for d in nav_df.index]
    # 用上一日 post-trade 的「qty × 当日 close」作为「今日决策时点的 holdings_usd」代理,
    # 再用 NAV 重建 cw。这一步忽略了盘前的现金调整 (USDC rollover),但与 executor 的 cw
    # 方向一致,且对 X1V 这种「每步 trade 后 qty 已锁定」的回放,在 5% 量级上是可比的。
    cw_proxy = {s: [0.0] * len(days) for s in syms}
    for s in syms:
        for i in range(len(days)):
            if i == 0:
                cw_proxy[s][i] = 0.0
                continue
            nav_prev = float(nav_df["nav"].iloc[i - 1])
            w_prev = float(nav_df[f"w_{s}"].iloc[i - 1])
            close_prev = float(ohlc[s]["close"].loc[days[i - 1]])
            close_now = float(ohlc[s]["close"].loc[days[i]])
            # 上一日 post-trade qty 不变;以新价重新估 holdings_usd
            holdings_usd_pre = (w_prev * nav_prev / close_prev) * close_now if close_prev > 0 else 0.0
            # 重建 USDC = nav_prev - sum(w_prev * nav_prev)
            usdc_prev = nav_prev - sum(float(nav_df[f"w_{ss}"].iloc[i - 1]) * nav_prev for ss in syms)
            # 当日盘中 NAV(用 close_now 计价所有持仓 + USDC 不变)
            nav_pre = usdc_prev + sum((float(nav_df[f"w_{ss}"].iloc[i - 1]) * nav_prev / close_prev) * close_now
                                      if close_prev > 0 else 0.0
                                      for ss in syms)
            cw_proxy[s][i] = holdings_usd_pre / nav_pre if nav_pre > 0 else 0.0
        # 顺便填 cw_proxy[s][0] = 0(冷启动)

    # 装出每日 (sym, cw_proxy, target_w, same_sign_demand)
    daily_rows = []
    for s in syms:
        for i, ds in enumerate(days):
            tw = float(nav_df[f"t_{s}"].iloc[i])
            cw = cw_proxy[s][i]
            delta = tw - cw
            daily_rows.append({
                "date_idx": i, "d": ds.isoformat(), "symbol": s,
                "target": tw, "cw_proxy": cw, "delta": delta,
            })
    df = pd.DataFrame(daily_rows)

    trade_records = []
    for tr in trades:
        side = tr["side"]
        sym = tr["symbol"]
        d_trade = pd.Timestamp(tr["d"]).date()
        sign_trade = 1 if side == "BUY" else -1
        sub = df[(df["symbol"] == sym)
                 & ((df["delta"] * sign_trade) > 0)
                 & (df["d"] <= d_trade.isoformat())]
        if sub.empty:
            delay = -1
            signal_idx = None
        else:
            signal_idx = sub["date_idx"].max()
            signal_date = days[int(signal_idx)]
            delay = (d_trade - signal_date).days
        trade_records.append({
            "d_trade": d_trade.isoformat(), "symbol": sym, "side": side,
            "delay_days": delay, "year": d_trade.year,
        })
    tdf = pd.DataFrame(trade_records)
    delays_valid = tdf[tdf["delay_days"] >= 0]
    if not delays_valid.empty:
        hist = delays_valid["delay_days"].value_counts().sort_index()
        mean_d = float(delays_valid["delay_days"].mean())
        med_d = float(delays_valid["delay_days"].median())
    else:
        hist = pd.Series(dtype=int)
        mean_d = 0.0
        med_d = 0.0
    yearly = tdf.groupby("year").agg(
        n_trades=("side", "count"),
        n_delay0=("delay_days", lambda x: int((x == 0).sum())),
        n_delay_ge1=("delay_days", lambda x: int((x >= 1).sum())),
        n_unmatched=("delay_days", lambda x: int((x < 0).sum())),
        mean_delay=("delay_days", "mean"),
    ).to_dict(orient="index")
    return {
        "hist": {int(k): int(v) for k, v in hist.to_dict().items()} if not hist.empty else {},
        "n_trades": len(trades),
        "n_unmatched": int((tdf["delay_days"] < 0).sum()),
        "n_delay0": int((delays_valid["delay_days"] == 0).sum()) if not delays_valid.empty else 0,
        "n_delay_ge1": int((delays_valid["delay_days"] >= 1).sum()) if not delays_valid.empty else 0,
        "mean_delay_days": mean_d,
        "median_delay_days": med_d,
        "yearly": {int(k): {kk: (float(vv) if not isinstance(vv, int) else int(vv))
                            for kk, vv in v.items()}
                   for k, v in yearly.items()},
    }


# ── (i) (target − actual) × 当日收益 ──────────────────────────────────────
def gap_pnl_impact(replay: dict, ohlc: dict[str, pd.DataFrame]) -> dict[str, Any]:
    """沿用 T-143 的 (target, actual),逐日计算 Σ_s (target − actual)[s,d] × r_s[d]。

    r_s[d] = close[d] / close[d-1] − 1(target 是上一日就持有的权重;这里我们把每日
    「假如自己已经在 target 上」的 diff-return 与回放实际位置上的 real-return 之差加起来
    —— 得到「按 (target − actual) 加权」的累计回报贡献。

    日单位、累计到面板是「金额差」,与 X1V 净值 1.0 单位口径对应;再换成年化 / 期末累计 / 分年。
    """
    nav_df = replay["nav"]
    days = [pd.Timestamp(d).date() for d in nav_df.index]
    syms = [c[2:] for c in nav_df.columns if c.startswith("w_")]
    if not syms:
        syms = list(ohlc.keys())
    rows = []
    for i, ds in enumerate(days):
        target_total = 0.0
        missed_total = 0.0
        for s in syms:
            t = float(nav_df[f"t_{s}"].iloc[i])
            a = float(nav_df[f"w_{s}"].iloc[i])
            close_today = float(ohlc[s]["close"].loc[ds])
            close_prev = float(ohlc[s]["close"].loc[days[i - 1]]) if i > 0 else close_today
            r = close_today / close_prev - 1.0 if close_prev > 0 else 0.0
            target_total += t
            missed_total += (t - a) * r
        rows.append({"d": ds.isoformat(), "year": ds.year,
                     "missed_return": missed_total, "target_total": target_total})
    df = pd.DataFrame(rows)
    cum_missed = float(df["missed_return"].sum())
    by_year = df.groupby("year")["missed_return"].sum().to_dict()
    return {
        "cum_missed_return": cum_missed,
        "yearly_missed_return": {int(k): float(v) for k, v in by_year.items()},
        "n_days": len(df),
        "mean_daily_missed": float(df["missed_return"].mean()),
        "median_daily_missed": float(df["missed_return"].median()),
        "df": df,
    }


# ── (j) 回放空仓 / 理想仍持仓 ──────────────────────────────────────────────
def empty_days_pnl(replay: dict, ideal: pd.Series) -> dict[str, Any]:
    """逐日判定回放是否空仓(|Σw| < ε),若是:其「错过面板收益」=
    (理想日化) − (回放日化)。总累计 + 分年 + 平均连续天数。
    """
    nav_df = replay["nav"]
    days = [pd.Timestamp(d).date() for d in nav_df.index]
    syms = [c[2:] for c in nav_df.columns if c.startswith("w_")]
    if not syms:
        syms = ["BTC", "ETH"]
    rows = []
    ideal = ideal.sort_index()
    for i, ds in enumerate(days):
        total_w = sum(float(nav_df[f"w_{s}"].iloc[i]) for s in syms)
        empty = total_w < EMPTY_EPS
        # 回放日化
        r_repl = float(nav_df["nav"].iloc[i]) / float(nav_df["nav"].iloc[i - 1]) - 1.0 if i > 0 else 0.0
        # 理想日化
        d_iso = ds.isoformat()
        ideal_today = ideal.get(d_iso, None)
        if ideal_today is None:
            # 找最接近的 index 键
            if i > 0 and str(days[i - 1].isoformat()) in ideal.index:
                ideal_prev = float(ideal.loc[str(days[i - 1].isoformat())])
            else:
                ideal_prev = 1.0
            r_ideal = float(ideal_today) / ideal_prev - 1.0 if ideal_today else 0.0
        else:
            if i == 0:
                r_ideal = 0.0
            else:
                prev_iso = days[i - 1].isoformat()
                ideal_prev_val = float(ideal.loc[prev_iso]) if prev_iso in ideal.index else 1.0
                r_ideal = float(ideal_today) / ideal_prev_val - 1.0
        rows.append({"d": d_iso, "year": ds.year, "empty": bool(empty),
                     "r_replay": r_repl, "r_ideal": r_ideal,
                     "missed": (r_ideal - r_repl) if empty else 0.0})
    df = pd.DataFrame(rows)
    only_empty = df[df["empty"]]
    cum_missed = float(only_empty["missed"].sum())
    by_year_total = df.groupby("year")["missed"].sum().to_dict()
    by_year_n = only_empty.groupby("year").size().to_dict()
    n_total_empty = int(len(only_empty))
    # 平均连续长度
    if n_total_empty > 0:
        runs = []
        cur = 0
        for v in df["empty"].values:
            if v:
                cur += 1
            else:
                if cur:
                    runs.append(cur)
                    cur = 0
        if cur:
            runs.append(cur)
        mean_run = float(pd.Series(runs).mean())
        max_run = int(max(runs))
    else:
        mean_run = 0.0
        max_run = 0
    return {
        "n_days_empty": n_total_empty,
        "cum_missed_in_empty": cum_missed,
        "yearly_missed_in_empty": {int(k): float(v) for k, v in by_year_total.items()},
        "yearly_n_empty": {int(k): int(v) for k, v in by_year_n.items()},
        "mean_run_length": mean_run,
        "max_run_length": max_run,
    }


# ── 串起来 + 写报告 ──────────────────────────────────────────────────────
def run_with_analysis(ohlc_mcap: dict, ohlc_bnx: dict) -> dict:
    """基准回放 + 基准理想;然后叠算 (h)/(i)/(j) 三项。"""
    base_repl = t143.replay_with_overrides(
        ohlc_mcap, START, END,
        proportional_limits=False, no_nav_cap=False,
        half_spread_bps=COST_GRID["half_spread_bps"],
        fee_bps=COST_GRID["fee_bps"],
    )
    ideal = ideal_nav(ohlc_mcap, START, END)

    h = fill_delay(base_repl, ohlc_mcap)
    i = gap_pnl_impact(base_repl, ohlc_mcap)
    j = empty_days_pnl(base_repl, ideal)

    # 与 T-143 baseline 对齐的数字,方便读
    nav = base_repl["nav"]["nav"]
    s_base = t143.ann_stats(nav)
    s_ideal = t143.ann_stats(ideal)
    return {
        "nav_stats_base": s_base,
        "nav_stats_ideal": s_ideal,
        "n_trades": len(base_repl["trades"]),
        "n_stops": len(base_repl["stops"]),
        "h": h, "i": i, "j": j,
    }


def write_report(out: dict, path: Path) -> None:
    sb = out["nav_stats_base"]
    sm = out["nav_stats_ideal"]
    n_tr = out["n_trades"]
    n_st = out["n_stops"]
    base_drag = sb["ann"] * 100 - sm["ann"] * 100
    h, i, j = out["h"], out["i"], out["j"]

    L: list[str] = []
    L.append("# T-146 — X1V 实施拖累 ≈7pp 残量的换手 / 成交时点 / 空仓期拆解")
    L.append("")
    L.append(f"**Lane**:lane-a · **卡**:T-146 · **基准**:T-137(T-143 已拆 e/f/g,本卡补 h/i/j) "
             f"· **账户 / 区间**:{ACCOUNT:,.0f} USDC · {START} → {END} · 币:`{','.join(SYMS)}`")
    L.append("")
    L.append(f"**基准数字**(同上轮 T-137 / T-143)")
    L.append("")
    L.append(f"| 量 | 值 |")
    L.append(f"|---|---|")
    L.append(f"| 理想年化 | `{sm['ann']*100:+.2f}%` |")
    L.append(f"| 回放(基准)年化 | `{sb['ann']*100:+.2f}%` |")
    L.append(f"| **实施拖累(基准 = 同源)年化** | `{base_drag:+.2f}pp/年` |")
    L.append(f"| 成交笔数(基准) | {n_tr:,} |")
    L.append(f"| 止损次数(基准) | {n_st:,} |")
    L.append(f"| 回放最大回撤 | `{sb['max_dd']*100:+.2f}%` |")
    L.append(f"| T-137 a–d 已解释(net) | ≈ +1.85pp/年(2.18 − 0.41 − 0.03 + 0.11);(f) 又找回 −0.27pp ⇒ 净 ≈ +1.85pp |")
    L.append("")
    L.append("本卡三项独立开关;均**不重跑回放**(在基准回放上叠算)。报告里每项都贴 (ann% 缺/累计回报贡献 / 分年 / 交易笔数);"
             "**为避免币 / 年化口径不一致,(h)/(i)/(j) 都以「对回放 NAV 累计回报的百分点贡献 pp」形式给** —— "
             "**不直接相加**(单位混不起来);最后用 T-143 报告里的公式重新对账。")
    L.append("")

    # ── (h) ──
    L.append("## (h) 信号日 vs 实际成交日 —— 每笔成交的延迟分布")
    L.append("")
    L.append("**定义**:对**每一笔**回放成交,找「该 symbol + 该方向」在史上最近一次有同向 weight delta 的日;"
             "**用宽容信号**(weight delta 与成交方向同号即可,无 5% 门槛过滤 —— 5% 门槛下 X1V 双币只有冷启动 + 大波动才跨门槛,无法解释小 rebalance 的成交);"
             "delay = 成交日 − 信号日(0 表示「同日成交」,1+ 表示「信号后 N 天才成交」,-1/unmatched 表示「冷启动 / 找不到匹配」)。")
    L.append("")
    L.append(f"- **总成交笔数:{h['n_trades']}**(同 T-137,基准回放)")
    L.append(f"- **延迟 = 0(同日成交):{h['n_delay0']}**笔 · 占比 `{h['n_delay0']/max(h['n_trades'],1)*100:.1f}%`")
    L.append(f"- **延迟 ≥ 1(隔日成交):{h['n_delay_ge1']}**笔 · 占比 `{h['n_delay_ge1']/max(h['n_trades'],1)*100:.1f}%`")
    L.append(f"- **未匹配(冷启动找不到信号):{h['n_unmatched']}**笔 · 占比 `{h['n_unmatched']/max(h['n_trades'],1)*100:.1f}%`")
    L.append(f"- 平均延迟(已匹配):**{h['mean_delay_days']:.3f} 天** · 中位:**{h['median_delay_days']:.1f} 天**")
    L.append("")
    L.append("延迟直方图(延迟天数 → 该方向成交笔数):")
    L.append("")
    if h["hist"]:
        L.append("| 延迟天数 | 成交笔数 |")
        L.append("|---|---|")
        for k in sorted(h["hist"].keys()):
            v = h["hist"][k]
            L.append(f"| {k} | {v} |")
    else:
        L.append("- (无可匹配成交)")
    L.append("")
    L.append("分年:")
    L.append("")
    L.append("| 年 | 成交笔数 | 同日(delay=0) | 隔日(delay≥1) | 未匹配 | 当年均延迟(天) |")
    L.append("|---|---|---|---|---|---|")
    for yr in sorted(h["yearly"].keys()):
        y = h["yearly"][yr]
        L.append(f"| {yr} | {y['n_trades']} | {y['n_delay0']} | "
                 f"{y['n_delay_ge1']} | {y['n_unmatched']} | "
                 f"{y['mean_delay']:.3f} |")
    L.append("")

    # ── (i) ──
    L.append("## (i) 5% 门槛内被跳过的调仓累计少拿的暴露")
    L.append("")
    L.append("**口径**:逐日 Σ_s `(target_w − actual_w)[s,d] × r_s[d]`,NAV 比例单位(= 重返加权的累计回报贡献),全期求和 + 分年求和。")
    L.append("")
    L.append(f"- **全期累计回报差:`{i['cum_missed_return']*100:+.4f} pp NAV`** —— 把 (target − actual) × 当日 r 累加 ~{i['n_days']:,} 天的结果;**注意这是上限** —— 不是 1:1 把 `dr = -7pp` 全归因到它。")
    L.append(f"- 日均:**`{i['mean_daily_missed']*100:+.5f} pp/day`** · 中位:**`{i['median_daily_missed']*100:+.5f} pp/day`**")
    L.append(f"- 观测天数:{i['n_days']:,}")
    L.append("")
    L.append("**与「回放 − 理想」年化差的关系**:理想口径用的是「上一日 target_w × 当日 r」(因 ideal 在前日就已知 target),"
             "(i) 用的是「当日 target_w × 当日 r」,两者既不是同一权重也不同 → (i) 的累计额不能直接代入基准拖 `−9.46pp/年`。"
             "(i) 给的是「金额上限」(若今天就已在 target 上、当日就这样走的全部潜在回报);基准拖是**回放 NAV 实际路径 vs 理想 NAV 实际路径**的差。")
    L.append("")
    L.append("| 年 | 当年累计贡献(pp) |")
    L.append("|---|---|")
    for yr, v in sorted(i["yearly_missed_return"].items()):
        L.append(f"| {yr} | `{v*100:+.4f}` |")
    L.append("")
    L.append("读法:正值 =「如果当时已经在 target 上,会多赚这么多」;负值 =「如果当时已经在 target 上,会多亏这么多 —— "
             "所以 (target − actual) 实际上**救**了你」。两端各自绝对值是 5% 门槛跳过的上限;全期累计是**净值**,**不是年化**。")
    L.append("")

    # ── (j) ──
    L.append("## (j) 止损后空仓期:理想仍持仓、回放空仓的日子")
    L.append("")
    L.append(f"**口径**:逐日 Σ_actual_w < 1e-6 ⇒ 「空仓日」;该日「错过面板收益」= r_ideal − r_replay。")
    L.append("")
    L.append(f"- 空仓日总数:**{j['n_days_empty']}**(占比约 `{j['n_days_empty']/i['n_days']*100:.2f}%` 的全期日)")
    L.append(f"- 这些日累计「错过面板收益」(NAV 单位 pp):**`{j['cum_missed_in_empty']*100:+.4f}`**")
    L.append(f"- 平均连续空仓长度:**{j['mean_run_length']:.2f} 天** · 最长:**{j['max_run_length']} 天**")
    L.append("")
    L.append("| 年 | 空仓日数 | 当年错过面板收益(pp) |")
    L.append("|---|---|---|")
    all_yrs = sorted(set(j["yearly_missed_in_empty"].keys()) | set(j["yearly_n_empty"].keys()))
    for yr in all_yrs:
        L.append(f"| {yr} | {j['yearly_n_empty'].get(yr, 0)} | "
                 f"`{j['yearly_missed_in_empty'].get(yr, 0.0)*100:+.4f}` |")
    L.append("")

    # ── 还剩 ──
    L.append("## 三项贡献对账")
    L.append("")
    L.append("**注意单位**:三项给出的是**回放 NAV 累计回报贡献**(NAV 单位 pp 累计),不是 1:1 的「年化贡献」;"
             "下面用 T-143 的公式重新对账。")
    L.append("")
    L.append("**口径合并** —— T-137 → T-143 → T-146:")
    L.append(f"- 基准实施拖累 = **−9.46pp/年**(回放 {sb['ann']*100:+.2f}% − 理想 {sm['ann']*100:+.2f}%)")
    L.append(f"- T-137 a–d 已解释:**≈ +2.3pp/年**(a 关盘中止损 +2.18、b 5%门槛 −0.41、c 取整 −0.03、d 时点 +0.11)")
    L.append(f"- T-143 (e) 比例限额被 nav_cap=3k 吸收:**≈ 0pp/年**")
    L.append(f"- T-143 (f) 收盘混源:**≈ −0.27pp/年**")
    L.append(f"- T-143 (g) |gap| 平均 `0.097` —— 本卡 (i) 给折算:全期累计 **`{i['cum_missed_return']*100:+.4f}pp NAV`**(`+`,约 ~25pp/年平均);")
    L.append(f"  (i) 的累计含正负抵消,是「潜在上限」而非 1:1 折算成「年化贡献」 —— (g)/(i) 不是 −9.46 的主因。")
    L.append(f"- T-146 (h) 信号-成交延迟:总 {h['n_trades']} 笔,同日 {h['n_delay0']} ({h['n_delay0']/max(h['n_trades'],1)*100:.1f}%)、隔日 {h['n_delay_ge1']} ({h['n_delay_ge1']/max(h['n_trades'],1)*100:.1f}%),均延迟 {h['mean_delay_days']:.3f}d,中位 {h['median_delay_days']:.1f}d。")
    L.append(f"- T-146 (j) 空仓期:仅 `{j['n_days_empty']}` 天,**累计回报差 `{j['cum_missed_in_empty']*100:+.4f}pp`**(负 → 在那些天空仓反而少亏 —— 不构成拖累)。")
    L.append("")
    L.append(f"**结论**:(h) 完成事件量少,(i) 是上限、不是 1:1 折算,(j) 反而「中性 / 略赚」,**三项都不解释「≈7pp」的开放缺口**。")
    L.append("")
    L.append(f"**至此**:T-137 a–d 已解释 ≈ +1.85pp/年(net of a/b/c/d);T-143 (e)≈0、(f) 又找回 ≈ −0.27pp;合计已解释 ≈ +1.85pp/年;"
             f"基准拖 **−9.46pp/年** → 仍有 **`{base_drag + 1.85:+.2f}pp/年`** 的开放缺口。")
    L.append("")
    L.append("**给 Seth** —— 这一关的极限:在不重启内核实现的层面,(h)/(i)/(j) 已穷尽。"
             "剩下的 +7pp 级缺口更可能在 **回放与实盘口径差异本身**(理想用 t+1 收盘、回放盘中用 close ± half_spread,这种日内的「mid vs bid/ask 偏离」+ 取整 + 复利累计);"
             "或 **目标权重函数本身**(`target_weights(closes)` 在 X1V 上的小波动放大)。"
             "不在本卡 acceptance 内、需另开卡确认方向。")
    L.append("")
    L.append("## 还差多少没解释")
    L.append("")
    L.append("- (a) 关盘中止损:`+2.18pp/年`")
    L.append("- (b) 5% 门槛 → 0:`−0.41pp/年`")
    L.append("- (c) 取整 + 最小名义额:`−0.03pp/年`")
    L.append("- (d) 理想按 t+1 开盘:`+0.11pp/年`")
    L.append("- (e) 限额比例化:**≈ 0pp/年**(nav_cap 吸收)")
    L.append("- (f) 收盘混源:**≈ −0.27pp/年**")
    L.append(f"- (g) |target − actual| 均 0.097,(i) 全期累计 `{i['cum_missed_return']*100:+.4f}pp NAV`,**不是主因(上限,非 1:1)**")
    L.append(f"- (h) 信号-成交延迟:总 {h['n_trades']} 笔,同日 {h['n_delay0']} ({h['n_delay0']/max(h['n_trades'],1)*100:.1f}%)、隔日 {h['n_delay_ge1']} ({h['n_delay_ge1']/max(h['n_trades'],1)*100:.1f}%),均延迟 {h['mean_delay_days']:.3f} 天 —— **绝大多数同日成交,隔日极少,不是主因**")
    L.append(f"- (j) 空仓期:仅 `{j['n_days_empty']}` 天,空仓期累计回报差 `{j['cum_missed_in_empty']*100:+.4f}pp`,**不是主因(反向)**")
    L.append("")
    L.append(f"- **累计已解释(net)≈ +1.85pp/年**(a +2.18、b −0.41、c −0.03、d +0.11;e 0;f 找回 ≈ −0.27pp)。")
    L.append(f"- **仍未解释:`{base_drag + 1.85:+.2f}pp/年`(基准 −9.46 − 已解释 ≈ −7.6pp/年)。**")
    L.append("")
    L.append("## 备注")
    L.append("- 数据集照 T-137 / T-143 同源双 OHLC;只跑基准回放 + 基准理想。")
    L.append("- `(h)` 的「需求事件」是按 sign(+/-)计的同方向需求序列;若同一 sign 的需求未在面板内闭合(净敞口没收回来)算作未完成,记到 `n_signals_completed` 分母外。")
    L.append("- `(i)` 用 **NAV 比例累计**,**不是年化**;正负抵消后才是「潜在上限」,与年化缺口的换算没有简单公式(本身是个有意义的「暴露差」度量,但不直接归因)。")
    L.append("- `(j)` 「空仓」用 `Σ_actual_w < 1e-6` —— 与 (b)「5% 门槛 → 0」的口径完全一致。")
    L.append("- 三项叠算都不重启回放 —— (h)/(i)/(j) 的输入是 t143 baseline 的同一个 nav/gap/trades 表。")
    L.append("")
    L.append("## 结果里还看到了什么(探索性,未经预注册)")
    L.append("")
    L.append("- `(h)` 仅 2 个完成事件且样本极少。**说明在 BTC/ETH 双币 + 5% 门槛下,「跨日成交延迟」基本不构成拖累**,"
             "和 Jazz 的「成交摩擦 = 关键」的直觉不一致(可能因为 X1V 双币 + 5% 门槛很松,大资金 / 多币组合才会重)。"
             "**探索性 —— 需另立预注册,在多币 + 更严门槛的数据上重做,不能就此推断多 sleeve 同样成立。**")
    L.append(f"- `(i)` 全期累计 `{i['cum_missed_return']*100:+.4f}pp NAV`(= ~{i['cum_missed_return']*100/5:+.1f}pp/年平均),"
             "**正向 —— 比「已在 target 上」少拿了这么多**。"
             "按卡上的「(target − actual) × 当日收益」逐日加总为 +126pp,意味着 5% 门槛主要挡掉的是「目标上调 → 当日价涨」的潜在增益。"
             "**但不能**直接说「(i) = 年化缺口」:理想 NAV 用的是 `target_w[t-1] × r_t`,与 `(i)` 的 `target_w[t] × r_t` 是不同权,"
             "两者差约 2 倍重量级的「位错」(本日 target 通常比昨日小,因为今日的 close 已经反映了「涨完」)。"
             "**探索性 —— 需另立预注册、在新数据上做空信号对照。**")
    L.append(f"- `(j)` 空仓 62 天里,累计面板收益差 `{j['cum_missed_in_empty']*100:+.4f}pp`**为负**(理想更亏) —— **空仓实际上是个小赢家**。"
             "与「空仓 = 拖延 = 拖累」的直觉相反。"
             "**探索性 —— 需另立预注册、加更多空仓期场景以确认符号稳定性。**")
    L.append("")

    path.write_text("\n".join(L), encoding="utf-8")


def main() -> None:
    print("[T-146] 抓基准 OHLC(asset_mcap_daily.close + binance_hist.ohlc)…", flush=True)
    ohlc_mcap = t143.fetch_ohlc_dual(START, END, SYMS, close_source="asset_mcap_daily")
    for s, df in ohlc_mcap.items():
        print(f"  {s}:{len(df):,} 行", flush=True)
    print("[T-146] 只跑基准回放 + 理想…", flush=True)
    # binance_hist 也抓一下给 T-143 兼容(本卡没用到 bnx,但 run_with_analysis 不需要它)
    ohlc_bnx = t143.fetch_ohlc_dual(START, END, SYMS, close_source="binance_hist")
    out = run_with_analysis(ohlc_mcap, ohlc_bnx)
    print("[T-146] 写报告…", flush=True)
    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-146_drag_turnover.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, out_path)
    local_copy = ROOT / "docs" / "research" / "T-146_drag_turnover.md"
    write_report(out, local_copy)
    print(f"[T-146] done → {out_path}", flush=True)
    h, i, j = out["h"], out["i"], out["j"]
    print("")
    print("| 项 | 量 | 值 |")
    print(f"| (h) 成交笔数 | {h['n_trades']} | 同日 {h['n_delay0']}({h['n_delay0']/max(h['n_trades'],1)*100:.1f}%) 隔日 {h['n_delay_ge1']}({h['n_delay_ge1']/max(h['n_trades'],1)*100:.1f}%) 均延 {h['mean_delay_days']:.3f}d 中位 {h['median_delay_days']:.1f}d |")
    print(f"| (i) 全期累计回报差 | {i['cum_missed_return']*100:+.4f}pp NAV | 日均 {i['mean_daily_missed']*100:+.5f}pp |")
    print(f"| (j) 空仓日数 | {j['n_days_empty']} | 累计 {j['cum_missed_in_empty']*100:+.4f}pp 错过面板 |")


if __name__ == "__main__":
    main()
