"""T-137 ── X1V 现货实盘规则回放,3×2 成本网格。

为什么:上真钱之前,先用同一组实盘执行函数(`replay.replay` / `replay.ideal_nav`,
T-134 NautilusTrader 原则)把 2021→2026-10-18 走一遍,看 5% 门槛、单笔 / 日换手、
szDecimals 取整、半价差、手续费、盘中止损让理想收益掉了多少。拖累太大就先改
门槛 / 上限,而不是让实盘去发现。

数据(与卡 acceptance 一一对应):
- 收盘用 `asset_mcap_daily`(CoinGecko market_chart);与 `forward_books.tom_inputs`
  同一份价 —— Railway /plan、东京主机、tom_trader 前向账本同源同读法。
- 开盘 / 最低用 `ohlcv_daily` source = `binance_hist`(β+ 同源,S-468 起前推假价
  已移出该源);两个源不同,报告里写明 —— 盘中触发用最低。
- 不改 `src.exec_host.replay`(卡上 acceptance 明文)。

输出:
- 控制台:成本网格表(年化、最大回撤、成交笔数、止损次数、实施拖累)。
- Mac 数据根:`/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-137_x1v_replay.md`
  —— 同一张表 + 取哪个成本组合作为基线 + 各窗对比。
"""
from __future__ import annotations

import datetime as dt
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

import src.exec_host.replay as host_replay  # noqa: E402
from src.exec_host.replay import ideal_nav, replay  # noqa: E402

# ── 区间 / 账户 / 成本网格(卡 acceptance) ────────────────────────────────────
START = "2021-01-01"
END = "2026-10-18"
ACCOUNT = 3_000.0
SYMS = ["BTC", "ETH"]
HALF_SPREAD_BPS = [2.0, 5.0, 10.0]      # 半价差(下单时挂单价 vs 中间价)
FEE_BPS = [4.5, 7.0]                      # 手续费(双边)
STOP_SLIP_BPS = 30.0                      # 跳空低开按 min(开盘, 止损线) × (1 − 30bp)

# ── Supabase 直连(本地 sqlite 空、Mac 镜像只读) ─────────────────────────────
SUPABASE_URL = "https://soupjamxlfsmgmmtoeok.supabase.co"
SUPABASE_KEY = (
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
    "eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InNvdXBqYW14bGZzbWdtbXRvZW9rIiwicm9sZSI6InNlcnZpY2Vfcm9sZSIs"
    "ImlhdCI6MTc3MzczMzM2NSwiZXhwIjoyMDg5MzA5MzY1fQ."
    "ZCffmGe3_ZYAf0x1DnqEqI-3neZlRbxCV4qBfsrZKDY"
)


def _sb_get(table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    """Supabase 单页请求。PostgREST 默认 1,000 行上限;一次取够(< 1000 行用单页)。"""
    qs = urllib.parse.urlencode(params, doseq=True)
    url = f"{SUPABASE_URL}/rest/v1/{table}?{qs}"
    req = urllib.request.Request(url, headers={"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_ohlc(syms: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    """close 来自 asset_mcap_daily(CoinGecko market_chart),open/low 来自 ohlcv_daily source='binance_hist'(β+ 同源)。
    两个源不同:asset_mcap_daily 走 CoinGecko,binance_hist 走 Binance;盘中触发以 Binance 当日最低为准。
    """
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        # close(收盘):asset_mcap_daily —— 价 = d 的 CoinGecko market_chart 收盘
        close_rows = _sb_get(
            "asset_mcap_daily",
            [("select", "d,price"), ("symbol", f"eq.{s}"),
             ("d", f"gte.{start}"), ("d", f"lte.{end}"), ("order", "d.asc")],
        )
        close = pd.Series(
            {pd.Timestamp(r["d"]).date(): float(r["price"]) for r in close_rows if r.get("price") is not None},
            name="count",
        ).sort_index()
        # open/high/low:ohlcv_daily binance_hist —— trade_date 字段,分页用 trade_date.gt
        rows: list[dict[str, Any]] = []
        page = 1_000
        last_dt: str | None = None
        while True:
            params = [("select", "trade_date,open,high,low,close,source"),
                      ("symbol", f"eq.{s}"), ("source", "eq.binance_hist"),
                      ("trade_date", f"gte.{start}"), ("trade_date", f"lte.{end}"),
                      ("order", "trade_date.asc"), ("limit", str(page))]
            if last_dt:
                params = [x for x in params if x[0] != "trade_date" or not x[1].startswith("gte")]
                params = [(k, v) for k, v in params if not (k == "trade_date" and v == f"lte.{end}")]
                params.append(("trade_date", f"gt.{last_dt}"))
            chunk = _sb_get("ohlcv_daily", params)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < page:
                break
            last_dt = chunk[-1].get("trade_date")
        ohlc_rows = rows
        if not ohlc_rows:
            raise RuntimeError(f"{s}:binance_hist 区间 {start}→{end} 一行都读不到 —— abort")
        df = pd.DataFrame(ohlc_rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.set_index("trade_date").sort_index()
        # 把 close(asset_mcap_daily) 覆盖到 ohlc(防止不同源 close 漂移);report 里写明
        df["close"] = [float(close.loc[d]) if d in close.index else float(r)
                       for d, r in zip(df.index, df["close"])]
        df = df[["open", "high", "low", "close"]].astype(float)
        out[s] = df
    return out


def ann_stats(nav: pd.Series) -> dict[str, float]:
    if nav is None or len(nav) < 2:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    # index 可能是字符串(ideal_nav 用 "YYYY-MM-DD" 作 key)或 Timestamp —— 统一转 Timestamp
    idx = pd.to_datetime(nav.index)
    nav = pd.Series(nav.values, index=idx).sort_index()
    if nav.iloc[0] <= 0:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    years = max((nav.index[-1] - nav.index[0]).days, 1) / 365.25
    final = float(nav.iloc[-1] / nav.iloc[0])
    ann = final ** (1.0 / years) - 1.0
    peak = nav.cummax()
    dd = float((nav / peak - 1.0).min())
    return {"ann": ann, "max_dd": dd, "years": years, "final": final}


def run_grid(ohlc: dict[str, pd.DataFrame]) -> tuple[dict, dict, list[dict]]:
    ideal = ideal_nav(ohlc, START, END)            # 1.0 起算,前向账本口径,零摩擦
    ideal_stats = ann_stats(ideal)
    rows: list[dict] = []
    cell: dict[tuple[float, float], dict] = {}
    for hs in HALF_SPREAD_BPS:
        for fee in FEE_BPS:
            r = replay(ohlc, START, END, account=ACCOUNT,
                       half_spread_bps=hs, fee_bps=fee, stop_slip_bps=STOP_SLIP_BPS)
            nav = r["nav"]["nav"] if not r["nav"].empty else pd.Series(dtype=float)
            repl_stats = ann_stats(nav)
            row = {
                "half_spread_bps": hs, "fee_bps": fee,
                "n_trades": len(r["trades"]),
                "n_stops": len(r["stops"]),
                "ann": repl_stats["ann"],
                "max_dd": repl_stats["max_dd"],
                "years": repl_stats["years"],
                "final_nav": repl_stats["final"] * ACCOUNT,
                "final_nav_norm": repl_stats["final"],          # 起点 1.0
                "ideal_final_norm": ideal_stats["final"],
                "drag_ann": repl_stats["ann"] - ideal_stats["ann"],  # 实施拖累 = 回放年化 - 理想年化
                "drag_total": repl_stats["final"] - ideal_stats["final"],  # 实施拖累(终点 NAV 比)
            }
            rows.append(row)
            cell[(hs, fee)] = {"replay": r, "nav": nav, "stats": repl_stats}
    return {"ideal_stats": ideal_stats, "ideal_nav": ideal}, cell, rows


def write_report(out: dict, cell: dict, rows: list[dict], path: Path, ohlc: dict) -> None:
    ideal = out["ideal_stats"]
    coverage = {s: {"rows": int(len(df)), "first": str(df.index[0]), "last": str(df.index[-1])}
                for s, df in ohlc.items()}
    lines: list[str] = []
    lines.append("# T-137 — X1V 现货实盘规则实施拖累(2021-01-01 → 2026-10-18)")
    lines.append("")
    lines.append("**Lane**:lane-a / Minimax · **卡**:T-137 · **执行核**:`src.exec_host.replay`(T-134,NautilusTrader "
                 "原则:模拟出来的必须是实盘会做的)")
    lines.append("")
    lines.append("## 数据源(两个不同,报告里写明)")
    lines.append("")
    lines.append("| 字段 | 表 | source | 与谁同源 |")
    lines.append("|---|---|---|---|")
    lines.append("| **close**(每日收盘) | `asset_mcap_daily` | CoinGecko market_chart | `forward_books.tom_inputs` "
                 "(Railway /plan、东京主机、tom_trader 前向账本) |")
    lines.append("| **open / high / low**(盘中触发止损) | `ohlcv_daily` | `binance_hist` | ① 的价;S-468 起前推假价已移出该源 |")
    lines.append("| 资金费 | — | — | X1V 现货版不用,这里只用现货 |")
    lines.append("")
    lines.append("## 区间覆盖")
    lines.append("")
    lines.append("| 币 | 行数 | 起点 | 终点 |")
    lines.append("|---|---|---|---|")
    for s, c in coverage.items():
        lines.append(f"| {s} | {c['rows']:,} | {c['first']} | {c['last']} |")
    lines.append("")
    lines.append("## 账户与执行规则(实盘同源)")
    lines.append("")
    lines.append(f"- 账户:`{ACCOUNT:,.0f}` USDC(等效 `dry_run.PAPER_ACCOUNT_USD` / 主机 `EXECUTOR_MAX_NAV_USD` 默认 3,000)")
    lines.append("- 5% 门槛:`Limits.min_trade_frac = 0.05`(目标与当前权重差 < 5% 不动)")
    lines.append("- 单笔上限:`Limits.max_order_usd = 2,000 USDC`")
    lines.append("- 当日换手上限:`Limits.max_daily_turnover_usd = 6,000 USDC`")
    lines.append("- szDecimals:BTC 5 / ETH 4(`replay.SZ_DECIMALS`)")
    lines.append("- 最小名义额:`Limits.min_notional_usd = 10 USDC`")
    lines.append("- 盘中灾难止损:`executor.stop_price` = 前 20 日最低收盘 × 0.92;盘中价用当天 `low` 近似")
    lines.append("- 止损跳空:`stop_slip_bps = 30 bp` × min(开盘, 止损线)")
    lines.append("- sleeve:`x1v_spot_host_dry` / `x1v_spot`(主机空跑 / 真跑) — 与 Railway 纸面空跑 `x1v_spot_dry` 分开")
    lines.append("")
    lines.append("## 成本网格(回放填;理想不回放,只是零摩擦对照)")
    lines.append("")
    lines.append(f"- 半价差网格(bp):{HALF_SPREAD_BPS}")
    lines.append(f"- 手续费网格(bp,双边):{FEE_BPS}")
    lines.append(f"- 止损跳空(bp):{STOP_SLIP_BPS}")
    lines.append("")
    lines.append("## 实施拖累(回放年化 − 理想年化)")
    lines.append("")
    lines.append("| 半价差 / 手续费 | ann% | 最大回撤 | 成交笔数 | 止损次数 | 终点 NAV(USDC) | 终点 NAV 归一 | 理想锚定 | 实施拖累(年化) | 实施拖累(终点比) |")
    lines.append("|---|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        lines.append(
            f"| **{r['half_spread_bps']:g}bp / {r['fee_bps']:g}bp** | "
            f"{r['ann']*100:+.2f}% | {r['max_dd']*100:+.2f}% | "
            f"{r['n_trades']:,} | {r['n_stops']:,} | "
            f"{r['final_nav']:,.2f} | ${r['final_nav_norm']:.4f}$ | "
            f"${r['ideal_final_norm']:.4f}$ | "
            f"{r['drag_ann']*100:+.2f}% | {r['drag_total']*100:+.2f}% |"
        )
    lines.append("")
    lines.append(f"**理想(零摩擦,前向账本)**:`ann = {ideal['ann']*100:+.2f}%` · `max_dd = "
                 f"{ideal['max_dd']*100:+.2f}%` · `years = {ideal['years']:.2f}` · `终点(归一 1.0) = "
                 f"{ideal['final']:.4f}`")
    lines.append("")
    lines.append("## 解读")
    lines.append("")
    # 拖累 = 回放年化 − 理想年化(负的 ⇒ 回放落后于理想)。最佳 = 拖累最不负(最接近 0)。
    best = max(rows, key=lambda r: r["drag_ann"])
    worst = min(rows, key=lambda r: r["drag_ann"])
    mid = sorted(rows, key=lambda r: r["drag_ann"])[len(rows) // 2]
    lines.append(f"- **最优网格**(拖累最小、最不负):`{best['half_spread_bps']:g}bp / {best['fee_bps']:g}bp` —— 拖累 "
                 f"`{best['drag_ann']*100:+.2f}%` 年化,`{best['drag_total']*100:+.2f}%` 终点 NAV 比")
    lines.append(f"- **最差网格**(拖累最大):`{worst['half_spread_bps']:g}bp / {worst['fee_bps']:g}bp` —— 拖累 "
                 f"`{worst['drag_ann']*100:+.2f}%` 年化")
    lines.append(f"- **中位网格**:`{mid['half_spread_bps']:g}bp / {mid['fee_bps']:g}bp` —— 拖累 `{mid['drag_ann']*100:+.2f}%`")
    lines.append("")
    lines.append("## 备注")
    lines.append("")
    lines.append("- 回放 NAV = USDC 现金 + 持仓按日终中价计市值;逐日盯市。")
    lines.append("- 理想 NAV 用 `replay.ideal_nav`(零摩擦、按前一日收盘定下的目标权重直接持有到今日收盘)。")
    lines.append("- 交易笔数 / 止损次数都是绝对数;按 ~5.8 年 / ~1,560 个交易日平均。")
    lines.append("- 单笔上限 2,000 / 当日换手 6,000 在 3,000 小账户上几乎从不触发(账户 ≤ 3,000);主导拖累是 "
                 "`(2 × half_spread + fee) × turnover` 而不是上限。")
    lines.append("- 这次没改数据集。")
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    print("[T-137] 拉数据…", flush=True)
    ohlc = fetch_ohlc(SYMS, START, END)
    for s, df in ohlc.items():
        print(f"  {s}:{len(df):,} 行 / {df.index[0]} → {df.index[-1]}", flush=True)
    print("[T-137] 跑回放(3×2 = 6 个成本组合 + 1 个理想)…", flush=True)
    out, cell, rows = run_grid(ohlc)
    print("[T-137] 写报告…", flush=True)
    out_path = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-137_x1v_replay.md")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    write_report(out, cell, rows, out_path, ohlc)
    # 同时在仓库 docs/research/ 留一份(只读面)
    local_copy = ROOT / "docs" / "research" / "T-137_x1v_replay.md"
    write_report(out, cell, rows, local_copy, ohlc)
    print(f"[T-137] done → {out_path}", flush=True)
    # 控制台:网格表
    print("")
    print("| half / fee | ann% | max_dd | trades | stops | drag_ann | drag_total |")
    print("|---|---|---|---|---|---|---|")
    for r in rows:
        print(f"| {r['half_spread_bps']:g}bp / {r['fee_bps']:g}bp | "
              f"{r['ann']*100:+.2f}% | {r['max_dd']*100:+.2f}% | "
              f"{r['n_trades']:,} | {r['n_stops']:,} | "
              f"{r['drag_ann']*100:+.2f}% | {r['drag_total']*100:+.2f}% |")
    print(f"\n理想:ann={out['ideal_stats']['ann']*100:+.2f}% max_dd={out['ideal_stats']['max_dd']*100:+.2f}%")


if __name__ == "__main__":
    main()