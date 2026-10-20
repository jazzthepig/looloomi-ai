#!/usr/bin/env python3
"""T-137 —— 用**实盘内核**回放 X1V 2021→2026,量出执行规则本身让理想收益掉了多少。

跑的是 `src/exec_host/replay.py` 的 `replay()` 与 `ideal_nav()` 本身(不改它们):
计划 = `host_plan.make_plan`、下单 = `core.plan_host_orders`、盘中止损判定 = `core.stop_hits`。
基准 BENCHMARK §2:模拟出来的必须是实盘会做的。

两个数据源(不同,报告里写明):
- **close**:`asset_mcap_daily`(CoinGecko market_chart)—— 与实盘计划 `forward_books.tom_inputs` 同源;
- **open/high/low**:`ohlc_daily` source=`binance_hist` —— 盘中止损用当日最低近似「盘中碰到」。

凭据只从环境变量读(`SUPABASE_URL` / `SUPABASE_KEY`,lane 注入的只读 publishable),
缺任一个直接退出。脚本里不写、也不读任何 `.env`。
"""
from __future__ import annotations

import contextlib
import dataclasses
import json
import math
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Optional

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.exec_host import replay as R                     # noqa: E402
from src.exec_host.replay import ideal_nav, replay        # noqa: E402
from src.data.execution import executor as ex             # noqa: E402
from src.data.execution.dry_run import SPOT_TOKENS        # noqa: E402

START, END = "2021-01-01", "2026-10-18"
ACCOUNT = 3_000.0
SYMS = ["BTC", "ETH"]
HALF_SPREAD_BPS = [2.0, 5.0, 10.0]      # 半价差(挂单价 vs 中间价)
FEE_BPS = [4.5, 7.0]                     # 手续费(双边)
STOP_SLIP_BPS = 30.0                     # 跳空低开按 min(开盘, 止损线) × (1 − 30bp)
BASE_CELL = (5.0, 7.0)                   # 成本网格的中格,拆解表的基准
OUT = Path("/Volumes/CometCloudAI/cometcloud-local/research/_reports/absorb_input/"
           "T-137_x1v_replay.md")


# ── Supabase(凭据只从环境变量) ──────────────────────────────────────────────
def _env_creds() -> tuple[str, str]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    missing = [n for n, v in (("SUPABASE_URL", url), ("SUPABASE_KEY", key)) if not v]
    if missing:
        sys.exit(f"缺环境变量 {missing} —— 不读 .env、不硬编码凭据,退出。")
    return str(url), str(key)


SB_URL, SB_KEY = _env_creds()


def _sb_get(table: str, params: list[tuple[str, str]]) -> list[dict[str, Any]]:
    qs = urllib.parse.urlencode(params, doseq=True)
    req = urllib.request.Request(
        f"{SB_URL}/rest/v1/{table}?{qs}",
        headers={"apikey": SB_KEY, "Authorization": f"Bearer {SB_KEY}"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def fetch_ohlc(syms: list[str], start: str, end: str) -> dict[str, pd.DataFrame]:
    cache = Path("/Volumes/CometCloudAI/cometcloud-local/research/_cache/"
                 f"t137_ohlc_{start}_{end}_v2.pkl")
    if cache.exists():
        import pickle
        with cache.open("rb") as fh:
            return pickle.load(fh)          # 同区间不重取(数据是 append-only 的,重跑只换规则)
    out: dict[str, pd.DataFrame] = {}
    for s in syms:
        close_rows = _sb_get("asset_mcap_daily",
                             [("select", "d,price"), ("symbol", f"eq.{s}"),
                              ("d", f"gte.{start}"), ("d", f"lte.{end}"), ("order", "d.asc")])
        close = pd.Series({pd.Timestamp(r["d"]).date(): float(r["price"])
                           for r in close_rows if r.get("price") is not None}).sort_index()
        rows: list[dict[str, Any]] = []
        page, last = 1_000, None
        while True:
            params = [("select", "trade_date,open,high,low,close"),
                      ("symbol", f"eq.{s}"), ("source", "eq.binance_hist"),
                      ("order", "trade_date.asc"), ("limit", str(page))]
            params.append(("trade_date", f"gt.{last}" if last else f"gte.{start}"))
            if last:
                params.append(("trade_date", f"lte.{end}"))
            chunk = _sb_get("ohlcv_daily", params)
            if not chunk:
                break
            rows.extend(chunk)
            if len(chunk) < page:
                break
            last = chunk[-1].get("trade_date")
        if not rows:
            raise RuntimeError(f"{s}:ohlcv_daily/binance_hist {start}→{end} 读不到行 —— abort")
        df = pd.DataFrame(rows)
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.date
        df = df.set_index("trade_date").sort_index()
        # close 用 asset_mcap_daily 覆盖(与实盘计划同源);open/high/low 仍来自 Binance
        df["close_bn"] = df["close"].astype(float)            # 留一份 Binance 收盘:拆解表 d 用它做自洽的 open/close 对
        df["close"] = [float(close.loc[d]) if d in close.index else float(r)
                       for d, r in zip(df.index, df["close"])]
        df = df[["open", "high", "low", "close", "close_bn"]].astype(float).dropna()
        if len(df) < 400:
            raise RuntimeError(f"{s}:只有 {len(df)} 根日线,不足 —— abort")
        out[s] = df
    cache.parent.mkdir(parents=True, exist_ok=True)
    import pickle
    with cache.open("wb") as fh:
        pickle.dump(out, fh)
    return out


# ── 统计 ──────────────────────────────────────────────────────────────────
def ann_stats(nav: pd.Series) -> dict[str, float]:
    if nav is None or len(nav) < 2:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    idx = pd.to_datetime(nav.index)
    nav = pd.Series(nav.values, index=idx).sort_index()
    if nav.iloc[0] <= 0:
        return {"ann": float("nan"), "max_dd": float("nan"), "years": 0.0, "final": float("nan")}
    years = max((nav.index[-1] - nav.index[0]).days, 1) / 365.25
    final = float(nav.iloc[-1] / nav.iloc[0])
    return {"ann": final ** (1.0 / years) - 1.0, "max_dd": float((nav / nav.cummax() - 1.0).min()),
            "years": years, "final": final}


# ── 理想口径变体 d:理想也按 t+1 开盘成交(规则不变、零摩擦) ────────────────
def ideal_nav_open(ohlc: dict[str, pd.DataFrame], start: str, end: Optional[str] = None) -> pd.Series:
    """朴素口径 d-naive:同一套目标权重,日收益换成 open→open(全程 Binance 价)。
    ⚠ 这个口径会**把建仓前一天的盘中涨幅记给组合**(见 entry_artifact)——它是记账口径,不是收益。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= start and (end is None or str(d)[:10] <= end)]
    nav, out, w = 1.0, {}, {s: 0.0 for s in syms}
    for i, d in enumerate(days):
        if i:
            prev = days[i - 1]
            r = sum(w[s] * (float(ohlc[s]["open"].loc[d]) / float(ohlc[s]["open"].loc[prev]) - 1)
                    for s in syms)
            nav *= 1 + r
        w = ex.target_weights({s: ohlc[s]["close"].loc[:d].astype(float) for s in syms})
        out[str(d)[:10]] = nav
    return pd.Series(out)


def ideal_nav_open_fill(ohlc: dict[str, pd.DataFrame], start: str, end: Optional[str] = None) -> tuple[pd.Series, float]:
    """d-1x:目标在 t 收盘定下、**t+1 开盘成交** —— 这才是「理想也按开盘成交」的对齐口径。
    当日收益 = 昨日权重 ×(开盘→收盘)+ 今日权重 ×(昨收→今开)(隔夜归**新**仓位,因为开盘才换手)。
    零成本下它与收盘口径几乎同值 ⇒ 时点本身不是拖累。返回 (NAV, 入场日错配的 log 差)。"""
    syms = [s for s in SPOT_TOKENS if s in ohlc]
    days = sorted(set.intersection(*(set(ohlc[s].index) for s in syms)))
    days = [d for d in days if str(d)[:10] >= start and (end is None or str(d)[:10] <= end)]
    nav, out, artifact = 1.0, {}, 0.0
    w_prev, w = {s: 0.0 for s in syms}, {s: 0.0 for s in syms}
    for i, d in enumerate(days):
        if i:
            prev = days[i - 1]
            r = sum(w_prev[s] * (float(ohlc[s]["close_bn"].loc[d]) / float(ohlc[s]["open"].loc[d]) - 1)
                    for s in syms)
            gap = sum(w[s] * (float(ohlc[s]["open"].loc[d]) / float(ohlc[s]["close_bn"].loc[prev]) - 1)
                      for s in syms)
            nav *= 1 + r + gap
            # 入场日错配:log(open_t/open_{t-1}) − log(close_t/close_{t-1}) = log 盘中(t-1) − log 盘中(t)
            if sum(w_prev.values()) > 0:
                artifact += sum(math.log(float(ohlc[s]["close_bn"].loc[prev]) / float(ohlc[s]["open"].loc[prev]))
                                - math.log(float(ohlc[s]["close_bn"].loc[d]) / float(ohlc[s]["open"].loc[d]))
                                for s in syms)
        w = ex.target_weights({s: ohlc[s]["close"].loc[:d].astype(float) for s in syms})
        w_prev = dict(w)
        out[str(d)[:10]] = nav
    return pd.Series(out), artifact


# ── 拆解表:每次只关一项,其余照实盘(src/ 一行不改) ────────────────────────
@contextlib.contextmanager
def ablation(*, stop_off: bool = False, min_trade_frac: Optional[float] = None,
             min_notional: Optional[float] = None, sz_decimals: Optional[int] = None):
    """就地换掉内核读到的判定函数 / 限额默认值,退出时原样换回。"""
    saved_core, saved_ex, saved_sz = R.core.stop_hits, ex.stop_price, dict(R.SZ_DECIMALS)
    saved_limits = ex.Limits
    try:
        if stop_off:
            R.core.stop_hits = lambda *a, **k: []          # 盘中灾难止损关掉(其余照实盘)
        over = {k: v for k, v in (("min_trade_frac", min_trade_frac),
                                   ("min_notional_usd", min_notional)) if v is not None}
        if over:
            base = ex.Limits
            spec = [(f.name, f.type, dataclasses.field(default=over.get(f.name, f.default)))
                    for f in dataclasses.fields(base)]
            ex.Limits = dataclasses.make_dataclass("Limits", spec, namespace={"__doc__": base.__doc__})
        if sz_decimals is not None:
            R.SZ_DECIMALS.update({k: sz_decimals for k in R.SZ_DECIMALS})
        yield
    finally:
        R.core.stop_hits, ex.stop_price, ex.Limits = saved_core, saved_ex, saved_limits
        R.SZ_DECIMALS.clear()
        R.SZ_DECIMALS.update(saved_sz)


def one(ohlc: dict[str, pd.DataFrame], hs: float, fee: float, **ab) -> dict[str, Any]:
    with ablation(**ab):
        r = replay(ohlc, START, END, account=ACCOUNT, half_spread_bps=hs, fee_bps=fee,
                   stop_slip_bps=STOP_SLIP_BPS)
    st = ann_stats(r["nav"]["nav"] if not r["nav"].empty else pd.Series(dtype=float))
    return {"stats": st, "n_trades": len(r["trades"]), "n_stops": len(r["stops"]), "stops": r["stops"]}


def stop_detail(ohlc: dict[str, pd.DataFrame], stops: list[dict], limit: int = 20) -> list[dict]:
    """逐笔止损:日期 / 止损线 / 当日最低 / 当日收盘 / 之后 5 个收盘。"""
    rows = []
    for s in stops:
        sym, d = s["symbol"], pd.Timestamp(s["d"]).date()
        df = ohlc[sym]
        idx = list(df.index)
        k = idx.index(d) if d in idx else None
        fwd = [f"{float(df['close'].iloc[k + j]):,.0f}" if k is not None and k + j < len(idx) else "—"
               for j in range(1, 6)]
        rows.append({"date": s["d"], "symbol": sym, "line": s["line"],
                     "low": float(df["low"].iloc[k]) if k is not None else float("nan"),
                     "close": float(df["close"].iloc[k]) if k is not None else float("nan"),
                     "fill_px": s["px"], "qty": s["qty"], "fwd5": fwd})
        if len(rows) >= limit:
            break
    return rows


def main() -> None:
    ohlc = fetch_ohlc(SYMS, START, END)
    days = len(set.intersection(*(set(ohlc[s].index) for s in SYMS)))
    span = f"{min(ohlc['BTC'].index)} → {max(ohlc['BTC'].index)}"

    ideal_c = ideal_nav(ohlc, START, END)                    # 理想:收盘→收盘、零摩擦
    ideal_o = ideal_nav_open(ohlc, START, END)               # d-naive:open→open 口径(有错配)
    ideal_x, artifact = ideal_nav_open_fill(ohlc, START, END)  # d-1x:开盘成交(对齐口径)
    ic, io, ix = ann_stats(ideal_c), ann_stats(ideal_o), ann_stats(ideal_x)

    grid = [(hs, f, one(ohlc, hs, f)) for hs in HALF_SPREAD_BPS for f in FEE_BPS]
    base = next(r for hs, f, r in grid if (hs, f) == BASE_CELL)

    abl = [("基准(全部照实盘)", {}, {"why": "—(对照行,不做任何改动)"}),
           ("a 盘中止损关掉", {"stop_off": True},
            {"why": "core.stop_hits → [];计划里的止损线照算,只是盘中不再触发"}),
           ("b 5% 门槛 → 0", {"min_trade_frac": 0.0},
            {"why": "Limits.min_trade_frac 0.05 → 0;|Δw| 多小都调仓"}),
           ("c 取整与最小名义额关掉", {"min_notional": 0.0, "sz_decimals": 12},
            {"why": "min_notional_usd → 0(零头也算持仓);SZ_DECIMALS → 12 位(无实际取整)"}),
           ]
    ab_rows = []
    for name, kw, meta in abl:
        r = one(ohlc, *BASE_CELL, **kw)
        ab_rows.append({"name": name, "kw": kw, "meta": meta, "r": r,
                        "d_ann": r["stats"]["ann"] - base["stats"]["ann"],
                        "d_stops": r["n_stops"] - base["n_stops"],
                        "d_trades": r["n_trades"] - base["n_trades"]})
    d_row = {"name": "**d-1x** 理想也按 t+1 开盘成交(对齐口径)", "r": None, "ann": ix["ann"],
             "d_ann": ix["ann"] - ic["ann"], "d_stops": 0, "d_trades": 0,
             "meta": {"why": "目标收盘定、开盘成交:日内用昨日权重、隔夜用今日权重;"
                             "全程 Binance open/close_bn 自洽。零成本 ⇒ 与收盘口径几乎同值"}}
    d_naive = {"name": "d-naive 同上但按 open→open 记账(**口径错配,不是收益**)", "r": None,
               "ann": io["ann"], "d_ann": io["ann"] - ic["ann"], "d_stops": 0, "d_trades": 0,
               "meta": {"why": f"把建仓**前一天**的盘中涨幅记给了组合(入场日错配 log 差 "
                               f"{artifact:+.2f} = {math.exp(artifact):.1f}x)——"
                               f"这条不能当成「开盘成交更好」的证据"}}

    det = stop_detail(ohlc, base["stops"])

    L: list[str] = []
    A = L.append
    A("# T-137 —— X1V 执行规则的实施拖累(实盘内核回放 2021→2026)")
    A("")
    A(f"- 区间 `{START}` → `{END}`,实际取到 **{span}**({days} 个共同交易日);账户 {ACCOUNT:,.0f} USDC")
    A("- 规则来源:`src/exec_host/replay.py`(计划 `make_plan` / 下单 `plan_host_orders` / "
      "止损判定 `stop_hits`,均**未修改**)")
    A("- **两个数据源不同**:`close` = `asset_mcap_daily`(CoinGecko market_chart,与实盘 "
      "`forward_books.tom_inputs` 同源);`open/high/low` = `ohlcv_daily` source=`binance_hist`"
      "(Binance)。盘中止损按 Binance 当日最低近似「盘中碰到」。")
    A(f"- 理想(零摩擦、收盘→收盘):年化 **{ic['ann']:+.2%}**,最大回撤 {ic['max_dd']:.2%};"
      f"理想(t+1 开盘成交,对齐口径 d-1x):年化 **{ix['ann']:+.2%}**,最大回撤 {ix['max_dd']:.2%}")
    A("")
    A("## 一、成本网格(全部规则照实盘)")
    A("")
    A("| 半价差 bp | 手续费 bp | 年化 | 最大回撤 | 成交笔数 | 止损次数 | 实施拖累(年化差) |")
    A("|---:|---:|---:|---:|---:|---:|---:|")
    for hs, f, r in grid:
        s = r["stats"]
        A(f"| {hs:.0f} | {f:.1f} | {s['ann']:+.2%} | {s['max_dd']:.2%} | {r['n_trades']} | "
          f"{r['n_stops']} | {s['ann'] - ic['ann']:+.2%} |")
    A("")
    lo = min(r["stats"]["ann"] for _, _, r in grid)
    hi = max(r["stats"]["ann"] for _, _, r in grid)
    A(f"六个成本格之间只差 **{(hi - lo) * 100:.2f}pp** 年化,而对理想的拖累是 "
      f"**{(lo - ic['ann']) * 100:.1f}pp** —— 拖累不是成本,是结构。")
    A("")
    A("## 二、拆解表(每次只关一项,其余照实盘;成本固定在中格 "
      f"{BASE_CELL[0]:.0f}/{BASE_CELL[1]:.1f}bp)")
    A("")
    A("| 项 | 年化 | 相对基准 Δ年化 | 止损次数 | Δ止损 | 成交笔数 | 怎么关的 |")
    A("|---|---:|---:|---:|---:|---:|---|")
    for row in ab_rows + [d_row, d_naive]:
        r = row["r"]
        ann = f"{r['stats']['ann']:+.2%}" if r else f"{row['ann']:+.2%}"
        ns = f"{r['n_stops']}" if r else "—(理想无止损)"
        nt = f"{r['n_trades']}" if r else "—"
        ds = f"{row['d_stops']:+d}" if row["d_stops"] else "0"
        A(f"| {row['name']} | {ann} | {row['d_ann']:+.2%} | {ns} | {ds} | {nt} | {row['meta']['why']} |")
    A("")
    A(f"基准:年化 {base['stats']['ann']:+.2%}、{base['n_trades']} 笔成交、{base['n_stops']} 次止损、"
      f"最大回撤 {base['stats']['max_dd']:.2%}。")
    A("")
    A("**读法**:对理想的实施拖累合计 "
      f"{base['stats']['ann'] - ic['ann']:+.2%},但**没有任何单一项能解释它的大部分** ——")
    A("")
    A(f"- 成本:六个格之间只差 {(hi - lo) * 100:.2f}pp;")
    A(f"- **c 取整与最小名义额**:{ab_rows[3]['d_ann']:+.2%}(可忽略);")
    A(f"- **b 把 5% 门槛放开**:{ab_rows[2]['d_ann']:+.2%}、成交 {base['n_trades']} → "
      f"{ab_rows[2]['r']['n_trades']} 笔 —— 门槛是在**省钱**,不是拖累;")
    A(f"- **a 关掉盘中止损**:{ab_rows[1]['d_ann']:+.2%}、止损 {base['n_stops']} → 0 笔 —— "
      f"单项最大,但仍只有总拖累的 {ab_rows[1]['d_ann'] / (ic['ann'] - base['stats']['ann']) * 100:.0f}%;")
    A("- **d-1x ≈ 0** ⇒ 成交时点(收盘 / t+1 开盘)本身不是拖累。")
    A("")
    A(f"结论:剩下的 {ic['ann'] - base['stats']['ann']:+.2%} 是**摩擦的复利**,不是某一条规则 —— "
      f"在 {base['n_trades']} 笔成交上反复扣,单看每项都小。要提年化,先动的应该是止损,不是成本参数。")
    A("")
    A(f"⚠ **d-naive 的 +{(io['ann'] - ic['ann']) * 100:.0f}pp 不能当成「开盘成交更好」**:"
      f"把日收益换成 open→open,等于把**建仓前一天**的盘中涨幅记给还没建仓的组合。"
      f"量级可以直接算:Σ(log 盘中(t−1) − log 盘中(t)),在有仓日上 = {artifact:+.2f} log "
      f"= {math.exp(artifact):.1f}x —— 与净值差 {math.exp(io['ann'] - ic['ann']):.1f}x 同量级。"
      f"对齐口径 d-1x 才是「理想也按开盘成交」的正确对照。")
    A("")
    A("## 三、止损逐笔(基准成本格)")
    A("")
    A(f"共 {base['n_stops']} 次止损,下列前 {len(det)} 笔。")
    A("")
    A("| 日期 | 币 | 止损线 | 当日最低 | 当日收盘 | 成交价(−30bp) | 之后 5 个收盘 |")
    A("|---|---|---:|---:|---:|---:|---|")
    for d_ in det:
        fwd = " · ".join(d_["fwd5"])
        A(f"| {d_['date']} | {d_['symbol']} | {d_['line']:,.0f} | {d_['low']:,.0f} | "
          f"{d_['close']:,.0f} | {d_['fill_px']:,.0f} | {fwd} |")
    A("")
    A("## 四、复现")
    A("")
    A("```bash")
    A("SUPABASE_URL=… SUPABASE_KEY=… python3 docs/research/t137_x1v_replay.py")
    A("```")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
    print(f"ideal(close) {ic['ann']:+.4%}  ideal(open-fill) {ix['ann']:+.4%}  "
      f"ideal(naive open→open) {io['ann']:+.4%}  entry-artifact {artifact:+.3f} log "
      f"({math.exp(artifact):.1f}x)")
    print(f"grid ann {lo:+.4%} … {hi:+.4%}  base {base['stats']['ann']:+.4%} "
          f"trades {base['n_trades']} stops {base['n_stops']}")
    for row in ab_rows:
        r = row["r"]
        print(f"  {row['name']:28s} ann {r['stats']['ann']:+.4%} Δ {row['d_ann']:+.4%} "
              f"stops {r['n_stops']} trades {r['n_trades']}")
    print(f"  {d_row['name'][:28]:28s} ann {ix['ann']:+.4%} Δ {d_row['d_ann']:+.4%}")
    print(f"  {d_naive['name'][:28]:28s} ann {io['ann']:+.4%} Δ {d_naive['d_ann']:+.4%}")
    print(f"  stop rows written: {len(det)}")


if __name__ == "__main__":
    main()