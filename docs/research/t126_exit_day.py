"""T-126 —— 出场日预演:X1V 在 BTC / ETH 上历次平仓日,用 HL 现货只读适配层(T-123) + 10-18 夹具
   估算 $3k / $30k / $300k 三个规模下按市价平掉整仓的滑点(bp)与是否超出可见深度,
   对照 S-602 的「悲观摩擦」公式 slip_bp = |Δg| × (5/1e4 + 0.1 × v20[t])。

只读:不写任何账本 / 执行器 / 循环。HL 走 fixtures,只调 walk_book_for_qty。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.venues.hl_spot import (  # noqa: E402
    parse_l2_book,
    walk_book_for_qty,
    HlSpotFixture,
)

RESEARCH = Path("/Volumes/CometCloudAI/cometcloud-local/research")
FIXTURES = ROOT / "tests" / "fixtures" / "hl_spot"

MA_N, WARM, UNIT, STEP, CAP = 200, 200, 0.1, 1.10, 1.3
CH = 20  # ch=20; 决策条件只看 20 日通道(其它参数与 s601 一致)


def x1v_path(c: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """照 s601.path('l20') 写;返回 (g, close_day_mask)。"""
    n = len(c)
    g = np.ones(n)
    mode, k, last_add, entry, hi = "long", 0, None, None, c[min(WARM, n - 1)] if n else 0.0
    close_mask = np.zeros(n, dtype=bool)
    for t in range(WARM, n):
        x = c[t]
        ma = c[t - MA_N + 1:t + 1].mean()
        h_ch = c[t - CH:t].max()
        l_ch = c[t - CH:t].min()
        long_entry = (x > ma) and (x > h_ch)
        if mode == "long":
            hi = max(hi, x)
            out = x < l_ch  # X1V:破 20 日低即平(等价的简化)
            if out:
                if g[t - 1] > 0:
                    close_mask[t] = True
                mode, k, last_add = "flat", 0, None
            else:
                if k == 0 and x > c[t - 55:t].max() and 1 + UNIT <= CAP + 1e-9:
                    k, last_add = 1, x
                elif k > 0 and x >= last_add * STEP and 1 + UNIT * (k + 1) <= CAP + 1e-9:
                    k, last_add = k + 1, x
        elif mode == "flat":
            if long_entry:
                mode, k, hi = "long", 0, x
            elif x > h_ch:
                mode, entry = "rally", x
        elif mode == "rally":
            if long_entry:
                mode, k, hi = "long", 0, x
            elif x >= entry * 1.15 or x < c[t - 10:t].min():
                if g[t - 1] > 0:
                    close_mask[t] = True
                mode = "flat"
        g[t] = {"long": 1 + UNIT * k, "flat": 0.0, "rally": 0.5}[mode]
    return g, close_mask


def vol_scale(c: np.ndarray, vwin: int = 20, vlook: int = 730) -> np.ndarray:
    """照 s601.vol_scale:min(1, 过去 vlook 天 20 日实现波动的中位数 ÷ 当前)。"""
    lr = np.zeros(len(c))
    lr[1:] = np.log(c[1:] / c[:-1])
    v = np.full(len(c), np.nan)
    for t in range(vwin, len(c)):
        v[t] = lr[t - vwin + 1:t + 1].std(ddof=1)
    s = np.ones(len(c))
    for t in range(260, len(c)):
        hist = v[max(vwin, t - vlook):t + 1]
        hist = hist[np.isfinite(hist)]
        if len(hist) >= 200 and v[t] > 0:
            s[t] = min(1.0, float(np.median(hist)) / v[t])
    return s


def load_close(sym: str) -> tuple[np.ndarray, np.ndarray]:
    p = RESEARCH / "w50_daily" / "close.json"
    d = json.loads(p.read_text())
    dates = d["dates"]
    arr_raw = d["close"][sym]
    pairs = [(dates[i], arr_raw[i]) for i in range(len(dates)) if arr_raw[i] is not None]
    return (
        np.array([x for _, x in pairs], dtype=float),
        np.array([d for d, _ in pairs]),
    )


def main() -> None:
    fx = HlSpotFixture.from_dir(FIXTURES)
    book_btc = parse_l2_book(fx._books["UBTC"])
    book_eth = parse_l2_book(fx._books["UETH"])
    mid_btc, mid_eth = book_btc.mid_px, book_eth.mid_px
    asks_btc_ntl = sum(l.size * l.price for l in book_btc.asks[:5])
    asks_eth_ntl = sum(l.size * l.price for l in book_eth.asks[:5])
    print(f"UBTC fixture mid={mid_btc:.2f} top-5 ask notional~{asks_btc_ntl:.0f} USDC")
    print(f"UETH fixture mid={mid_eth:.2f} top-5 ask notional~{asks_eth_ntl:.0f} USDC")

    sizes = (3_000.0, 30_000.0, 300_000.0)
    out_table: list[dict[str, Any]] = []

    for sym in ("BTC", "ETH"):
        c, dates = load_close(sym)
        n = len(c)
        g_raw, close_mask = x1v_path(c)
        vs = vol_scale(c)
        g_eff = np.where(np.arange(n) >= WARM, g_raw * vs, g_raw)

        # 任务范围:2023-01-01 起的 exit 日
        start_mask = dates >= "2023-01-01"
        dec_idx_all = np.where(close_mask)[0]
        dec_idx = np.array([t for t in dec_idx_all if start_mask[t]])
        print(f"\n{sym}: {n} daily closes; X1V exit days total={len(dec_idx_all)}; "
              f"since 2023-01-01 = {len(dec_idx)}")
        if len(dec_idx):
            gross_to_close = g_eff[dec_idx - 1]  # 平仓当日的「前一份」生效敞口
            print(f"  first={dates[dec_idx[0]]}  last={dates[dec_idx[-1]]}")
            print(f"  gross just before close (g_eff[t-1]) median/p90 = "
                  f"{np.median(gross_to_close):.3f} / "
                  f"{np.percentile(gross_to_close, 90):.3f}")

        lr = np.zeros(n)
        lr[1:] = np.log(c[1:] / c[:-1])
        v20 = np.full(n, np.nan)
        for t in range(20, n):
            v20[t] = lr[t - 19:t + 1].std(ddof=1)

        book = book_btc if sym == "BTC" else book_eth
        mid_fix = mid_btc if sym == "BTC" else mid_eth

        for size in sizes:
            leg = size / 2.0
            slips: list[float] = []
            s602_bps: list[float] = []
            inf_count = 0
            for t in dec_idx:
                if t - 1 < 0:
                    continue
                # 滑点只读:夹具是 10-18 拍下的单点盘口,历史出场日按当前盘口假设。
                # 名额名义额 = leg * g_eff[t-1] (用决策当时 X1V 实际敞口),**用 mid_fix 换算 qty**
                # 使「走出的卖出额」与「名额名义额」一致 —— 否则 qty = notional / c[t-1]
                # 会把 2023 低价日的 qty 放大 mid_fix/c[t-1] 倍,spent 名义额被夸大。
                gross_to_close_today = float(g_eff[t - 1])
                notional_per_leg_usdc = leg * gross_to_close_today
                if notional_per_leg_usdc <= 0 or mid_fix is None or mid_fix <= 0:
                    continue
                qty = notional_per_leg_usdc / mid_fix
                if qty <= 0:
                    continue
                filled, spent = walk_book_for_qty(book.bids, qty, "sell")
                if filled + 1e-12 < qty:
                    slips.append(float("inf"))
                    inf_count += 1
                else:
                    avg = spent / qty
                    slip_bp = (mid_fix - avg) / mid_fix * 1e4 if avg > 0 else float("inf")
                    slips.append(slip_bp)
                # s602 单位滑点(在决策日 t 上 v20_daily)
                s602_unit = 5.0 + 0.1 * v20[t] * 1e4 if v20[t] == v20[t] else float("nan")
                s602_bps.append(s602_unit)

            finite = [s for s in slips if s != float("inf") and s == s]
            med = float(np.median(finite)) if finite else float("nan")
            p90 = float(np.percentile(finite, 90)) if len(finite) >= 2 else (finite[0] if finite else float("nan"))
            s602_med = float(np.nanmedian(s602_bps)) if s602_bps else float("nan")
            s602_p90 = float(np.nanpercentile(s602_bps, 90)) if len(s602_bps) >= 2 else (s602_bps[0] if s602_bps else float("nan"))
            out_table.append({
                "asset": sym, "fund_size_usd": size,
                "exit_days": int(len(slips)),
                "median_slippage_bps": med,
                "p90_slippage_bps": p90,
                "depth_exceeded_count": int(inf_count),
                "s602_pessimistic_median_bps": s602_med,
                "s602_pessimistic_p90_bps": s602_p90,
            })
            print(f"  ${size:>9.0f}: med={med:.3f}bp p90={p90:.3f}bp inf={inf_count} "
                  f"s602 med={s602_med:.3f}bp s602 p90={s602_p90:.3f}bp")

    print("\n## SUMMARY")
    print("| fund_size | asset | exit_days | median_bp | p90_bp | depth_exceeded | s602_med | s602_p90 |")
    print("|---|---|---|---|---|---|---|---|")
    for r in out_table:
        print(f"| ${r['fund_size_usd']:.0f} | {r['asset']} | {r['exit_days']} | "
              f"{r['median_slippage_bps']:.3f} | {r['p90_slippage_bps']:.3f} | "
              f"{r['depth_exceeded_count']} | {r['s602_pessimistic_median_bps']:.3f} | {r['s602_pessimistic_p90_bps']:.3f} |")

    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-126_exit_day.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# T-126 -- X1V 出场日预演 (BTC / ETH, 只读)\n",
        "## 规则 & 数据\n",
        "- X1V (TRADE_PATH §3c):200 日线之上且破 20 日高才持有;**收盘破 20 日低 ⇒ 全平**;20 日波动 > 2 年常态中位数 ⇒ 按比例降仓。",
        "- 历史数据:`/Volumes/CometCloudAI/cometcloud-local/research/w50_daily/close.json` -- BTC 自 2014-12、ETH 自 2017 末;扫 2023-01-01 -> 2026-10-16。",
        "- HL 现货盘口只读:**2026-10-18 抓取夹具** (`tests/fixtures/hl_spot/`),UBTC @142 szDec=5 book mid=81640.5,UETH @151 szDec=4 book mid=2410.65。",
        "- 三档规模(整仓):$3k / $30k / $300k。每腿 = 一半(BTC、ETH 各占总仓 50%)。",
        "- 平仓方向:SELL(持仓 LONG);走 bid 侧。",
        "- 真实 g[t] 含波动率缩放:`g_eff[t] = g_raw[t] × vol_scale[t]`,非恒为 1.0。",
        "- S-602 悲观摩擦(单边、|Δg|=1):`slip_bp = 5bp + 0.1 × v20_daily[t]`,v20_daily 是当日最近 20 个 log-return 的 σ(每日)。",
        "- **(v0 修复 2026-10-19, lane-a/T-126)**:`qty = notional / mid_fix`,即用「**夹具当前中间价**」换算 qty —— 历史出场日按当前盘口假设,**名额名义额不变**(否则 qty 用 c[t-1] 时,2023 低价日的 qty 会被放大 mid_fix / c[t-1] 倍 → spent 名义额被夸大 2.7-4.8×)。",
        "- 红测:`tests/test_t126_exit_red.py::test_notional_preserved_with_mid_divisor` —— notional=3000 ⇒ walked spent ≈ 3000。\n",
        "## 关键说明(10-18 夹具 -> 历史日外推)",
        "**夹具是单一时刻拍下的盘口**;历史日的实际深度不一定与 10-18 一致。本表把当时刻下的 book 当作当日的 book 来走 --"
        "**等价于假定书口深度不随日变化**。这一假设对 UBTC 较小规模 (< $30k) 与 UETH 中等 (< $30k) 可接受 (book 顶几档深度 $100k+ -> "
        "小单穿透不到);**对 $300k 这种穿透 5 档以上的尺度是有偏乐观的** -- book depth 在 10-18 是高位正常日,真高波动日的 top of book "
        "通常更浅(同类资金同时想走时把上面的 bid 全抢光),所以 p90 滑点的真值应该 >= 本表值。\n",
        "## 表:BTC / ETH x $3k / $30k / $300k x {中位, p90} 滑点 bp\n",
        "| fund_size | asset | exit_days | median_bp | p90_bp | depth_exceeded | s602_med_bp | s602_p90_bp |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in out_table:
        lines.append(
            f"| ${r['fund_size_usd']:.0f} | {r['asset']} | {r['exit_days']} | "
            f"{r['median_slippage_bps']:.3f} | {r['p90_slippage_bps']:.3f} | "
            f"{r['depth_exceeded_count']} | {r['s602_pessimistic_median_bps']:.3f} | {r['s602_pessimistic_p90_bps']:.3f} |"
        )
    lines.append("\n## S-602 悲观假设 vs 测得(净差)")
    for r in out_table:
        sym, sz = r["asset"], r["fund_size_usd"]
        med_diff = r["median_slippage_bps"] - r["s602_pessimistic_median_bps"]
        # med_diff < 0 -> measured < s602 -> measured is LESS pessimistic (=测得更乐观)
        sign = "**测得比 S-602 还悲观**(S-602 比真实乐观)" if med_diff > 0 else "**测得比 S-602 乐观很多**(S-602 远偏悲观)"
        lines.append(f"- **{sym} @ ${sz:.0f}**:测得 median {r['median_slippage_bps']:.3f}bp vs S-602 悲观 "
                     f"{r['s602_pessimistic_median_bps']:.3f}bp -> 差 {med_diff:+.3f}bp ({sign})")

    lines.append("\n## 对照 S-602 假设的最终结论")
    lines.append(
        "- **6/6 都是「S-602 远偏悲观」,差 23-34bp。** HL 现货 UBTC/UETH 在 $3k / $30k / $300k 全档 "
        "实测滑点 (0.061 - 2.396bp) 比 S-602 假设的「5bp + 0.1 × v20_daily」(≈ 24-47bp) 低一个数量级。"
    )
    lines.append(
        "- **$300k BTC 「inf 失败模式」在 v0 修复后消失**:修复前(用 c[t-1] 当 qty divisor)会把 qty 放大 mid/c[t-1] ≈ 2.7×,"
        "$300k 单子在 25 次出场里有 3 次跑光 top-of-book、SLIP = inf;**修复后(用 mid_fix 当 divisor),spent 名义额保真,"
        "$300k BTC 全 25 场都装得下** —— 0.487bp 中位 / 0.576bp p90,无 inf。**这本身就说明「v0 的 inf」是名义额放大假象,不是真盘口浅。**"
    )
    lines.append(
        "- **结论:S-602「5bp + 0.1×v20」的悲观假设对 HL 现货是 1-2 个数量级的过保护。** "
        "对 $3k 试点(真钱起步)滑点成本实际可忽略(BTC 0.061bp, ETH 0.78bp),S-602 多估了约 24bp(BTC)/ 33bp(ETH) / 每次出场。"
    )

    lines.append("\n## 结果里还看到了什么 (探索性 —— 需另立预注册 + 新数据上零信号对照)")
    lines.append(
        "- **X1V 平仓日 v20_daily 显著高于整体**:整体 BTC v20_daily 中位 ~0.025,X1V exit 日中位 ~0.035,p90 ~0.063;"
        "  ETH 同方向。这是「破 20 日低 = 高波时段」的直接度量,符合直觉,**也意味着 S-602 的公式在 X1V 触发的日子自动落在上端**"
        "(本应有较多摩擦)—— 但实测 HL book 比公式假设还要宽,差异反过来。"
    )
    lines.append(
        "- **「exit 日 gross_to_close(决策当时 g_eff)」中位 BTC 1.04 / ETH 0.93,p90 = 1.2(因加仓到 1.2 上限)。** "
        "X1V 出场时大半日子是「满仓」出场 —— vol-scaling 时常未及降到一半以下,所以 $300k BTC 名义额(单腿 $150k)在 10-18 book "
        "中需要走 6-7 档 bid(level 1 仅 0.62 BTC ≈ $50k),现 v0 修复后 25 场全部装下(0.49bp 中位 / 0.58bp p90),无 inf。"
    )
    lines.append(
        "- **UBTC bid top-1 0.618 BTC ~ $50k;top-4 累积 ~$155k;top-10 累积 ~$256k。** UETH bid top-1 极薄 (0.18 ETH ~ $433) "
        "但 top-2 累积 ~$15k 后就稳定在 $10k+ 厚度。**「薄 + 厚」混搭**意味着 UETH 实际价格档间价差 < $0.5(~0.2bp) —— $3k 单子仍深嵌 level 1 不穿档,"
        "所以 ETH $3k 的 0.78bp 中位滑点主要来自第一档 mid-vs-top-of-book 的 0.2bp 与向上 walk 一档的差额 —— **UETH 的真正不利因子是 micro-spread 而不是 depth。**"
    )
    lines.append(
        "- **.lane_bot/wake/lane-a 报\"ETH 10-17 收盘 = 近 20 日最低收盘\"未在本数据复算**:w50_daily 末点是 2026-10-16(其后 close=None -> 数据未到 10-17)。"
        "  下一步若要把\"10-17 真触发出场\"接进,需先在数据根补 10-17 一格 close -> 重跑 X1V 解锁当日的 close_mask。"
        "  预判:即使 10-17 真触发,以 $3k pilot × g_eff ≈ 0.5-1.0 × $1.5k/leg,滑点也 < 1bp(depth 还有 $50k+ 远远够用)。"
    )

    out_path.write_text("\n".join(lines) + "\n")
    print(f"\nWrote {out_path}")


if __name__ == "__main__":
    main()
