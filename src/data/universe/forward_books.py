"""另外两本前向账本,与 World50 账本同日(2026-12-31)开账、在同一个周更循环里记(book 段之后)。

1. **山寨龙头腿**(alt_leaders,台账 S-589 的前向预注册;Jazz 10-16「山寨只拿基本面和资金面好的龙头」):
   宇宙 = CIS 正式序列(cis_official_daily)里的加密名,去掉 BTC(在核心里)与稳定 / 包装币;每 28 天调仓。
   龙头门槛 = 当日市值前 15,且 13 周年化波动 ≤ 宇宙中位数 × 1.5,且 13 周流通量增幅 ≤ 10%(流通量 = 市值 / 价格)。
   打分 = 秩(F) + 秩(O) + 秩(市值) − 秩(vol13),在门槛内算;取前 6 名等权。
   臂:TOP6(规则)· FO6(S-591:同一道门,只按秩 F + 秩 O 挑前 6 —— v1 的打分在门里又把最大最稳的选回来)·
   GATE_EW(门槛内全部等权,对照)· ETH(只持 ETH,对照)。随机 6 名的对照在评估时从 GATE_EW 的成员重抽,不存。
2. **灵活配置组合**(flex,S-585 之后的 v1;Jazz 10-16「维持」):加密腿 = ① 的前向(core_cap_daily cap_a1_u),
   World50 腿 = World50 账本 EW×Mom,现金腿收益记 0(保守,注明);每个记账日回到 35 / 50 / 15(两本账的组合,这一层不计成本)。
   引擎版(S-585)没过,不记。

写什么:forward_book_holdings(调仓日 × 账本 × 臂 × 成分的目标权重)、forward_book_nav(工作日 × 账本 × 臂的净值,开账 = 1,写一次不再改)。
FORWARD_START 之前:不写,只在循环 detail 里放「如果今天调仓,龙头腿选谁」。
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

FORWARD_START = "2026-12-31"
FREEZE_DAYS = 2
ALT_EVERY_DAYS = 28
ALT_TOP_MCAP, ALT_PICK, ALT_VOL_MULT, ALT_SUPPLY_MAX = 15, 6, 1.5, 0.10
CRYPTO_CLASSES = ("L1", "L2", "DeFi", "Infrastructure", "RWA", "Memecoin", "Gaming", "Crypto")
EXCLUDE = {"BTC", "USDT", "USDC", "DAI", "USDE", "FDUSD", "PYUSD", "USDS", "WBTC", "WETH", "STETH", "WSTETH", "PAXG", "XAUT"}
FLEX_WEIGHTS = {"crypto": 0.35, "world50": 0.50, "cash": 0.15}
COST_CRYPTO = 20 / 1e4
RULE_ALT = "alt_leaders_v1:S-589(前 15、波动 ≤ 中位数 × 1.5、流通量 13 周增幅 ≤ 10%;秩 F + O + 市值 − vol13;前 6 等权;28 天)"
RULE_FO6 = "alt_leaders_fo6:S-591(门同 S-589;秩 F + O,同分市值大者先;前 6 等权;28 天)"
ALT_ARMS = ("TOP6", "FO6", "GATE_EW", "ETH")
RULE_FLEX = "flex_v1:加密 ① cap_a1_u 35% / World50 EW×Mom 50% / 现金 15%(收益 0),每周回到目标"
#: S-600(Jazz 10-16「跌破就空仓,熊市赚了就跑,或者开空」):Trader Tom 交易层前向纸面账本,不等 12-31,今天开账
TOM_START = "2026-10-16"
TOM_WARM_FROM = "2024-01-01"     # 规则要 200 天历史;起算日固定 ⇒ 开账那天的状态可复现
#: (资产, 熊市做法, 空头仓位, 出场, 波动率缩放)。X1V = S-601 在没看过的 12 个币上回撤全部变浅的那一版(破 20 日低即平 + 波动率缩放)
TOM_ARMS = {"BTC_H": ("BTC", None, 0.0, "ma", False), "BTC_F": ("BTC", "flat", 0.0, "ma", False), "BTC_FB": ("BTC", "rally", 0.0, "ma", False),
            "BTC_S50": ("BTC", "short", -0.5, "ma", False), "BTC_X1V": ("BTC", "rally", 0.0, "l20", True),
            "ETH_H": ("ETH", None, 0.0, "ma", False), "ETH_F": ("ETH", "flat", 0.0, "ma", False), "ETH_FB": ("ETH", "rally", 0.0, "ma", False),
            "ETH_S50": ("ETH", "short", -0.5, "ma", False), "ETH_X1V": ("ETH", "rally", 0.0, "l20", True),
            "CORE_H": ("CORE", None, 0.0, "ma", False), "CORE_F": ("CORE", "flat", 0.0, "ma", False), "CORE_FB": ("CORE", "rally", 0.0, "ma", False),
            "CORE_X1V": ("CORE", "rally", 0.0, "l20", True)}
#: S-604 + Jazz 10-18(风险事件,「你看看怎么配」):灵活组合按回撤档位配 —— 加密腿 = tom_trader 的 ① X1V,股票 = ACWI(World50 开账前的替身),黄金 = XAUUSD,现金 0;
#: 21 个交易日回到目标。T25 = 最差 5% 回撤 −25% 档(执行器跑稳前用这一档),T35 = −35% 档(悲观摩擦列),H_T25 = 加密持有的 −25% 档作对照
FLEX_X1V_ARMS = {"T25": ({"crypto": 0.30, "equity": 0.30, "gold": 0.20}, "CORE_X1V"),
                 "T35": ({"crypto": 0.40, "equity": 0.40, "gold": 0.20}, "CORE_X1V"),
                 "H_T25": ({"crypto": 0.10, "equity": 0.30, "gold": 0.20}, "CORE_H")}
FLEX_REB_DAYS = 21
RULE_FLEX_X1V = "flex_x1v_v1:S-604(加密 ① X1V / ACWI / XAUUSD / 现金,21 个交易日再平衡,10bp)"
RULE_TOM = "tom_trader_v2:S-600 / S-601(多头 >200 日线且破 20 日高,盈利加仓到 1.3;跌破即平;F 空仓 / FB 反弹 0.5 +15% 止盈 / S50 开空 −20% 止盈 / X1V 破 20 日低即平 + 波动率缩放)"
WRITES_TABLES = ("forward_book_holdings", "forward_book_nav")
WRITES_COLUMNS = {
    "forward_book_holdings": ("book", "arm", "as_of", "key", "weight", "note", "rule"),
    "forward_book_nav": ("book", "arm", "d", "nav", "ret", "as_of", "rule"),
}


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def _ranks(vals: list[float]) -> list[float]:
    order = sorted(range(len(vals)), key=lambda i: vals[i])
    r = [0.0] * len(vals)
    for pos, i in enumerate(order):
        r[i] = float(pos)
    return r


def alt_select(rows: list[dict]) -> dict[str, Any]:
    """rows = [{sym, f, o, mcap, vol13, sup13}]。返回 {"gate": [...], "top": [...], "scores": {...}}。纯函数。"""
    ok = [r for r in rows if r["sym"].upper() not in EXCLUDE
          and all(r.get(k) is not None and math.isfinite(r[k]) for k in ("f", "o", "mcap", "vol13", "sup13"))]
    if not ok:
        return {"gate": [], "top": [], "scores": {}, "fo6": [], "fo_scores": {}}
    vols = sorted(r["vol13"] for r in ok)
    med = vols[len(vols) // 2] if len(vols) % 2 else (vols[len(vols) // 2 - 1] + vols[len(vols) // 2]) / 2
    top = sorted(ok, key=lambda r: -r["mcap"])[:ALT_TOP_MCAP]
    gate = [r for r in top if r["vol13"] <= ALT_VOL_MULT * med and r["sup13"] <= ALT_SUPPLY_MAX]
    if not gate:
        return {"gate": [], "top": [], "scores": {}, "fo6": [], "fo_scores": {}}
    rf, ro, rm, rv = (_ranks([r[k] for r in gate]) for k in ("f", "o", "mcap", "vol13"))
    sc = {r["sym"]: rf[i] + ro[i] + rm[i] - rv[i] for i, r in enumerate(gate)}
    pick = sorted(gate, key=lambda r: (-sc[r["sym"]], -r["mcap"]))[:ALT_PICK]
    fo = {r["sym"]: rf[i] + ro[i] for i, r in enumerate(gate)}                        # S-591:门负责「龙头」,挑选只看 F 与 O
    pick_fo = sorted(gate, key=lambda r: (-fo[r["sym"]], -r["mcap"]))[:ALT_PICK]
    return {"gate": [r["sym"] for r in gate], "top": [r["sym"] for r in pick], "scores": sc,
            "fo6": [r["sym"] for r in pick_fo], "fo_scores": fo}


def vol_and_supply(series: list[tuple[str, float, float]], as_of: str) -> tuple[Optional[float], Optional[float]]:
    """series = [(d, price, mcap)] 旧 → 新。13 周(91 天)年化波动与流通量增幅;不够 ⇒ None。纯函数。"""
    pts = [(d, p, m) for d, p, m in series if d <= as_of and p and p > 0]
    if len(pts) < 70:
        return None, None
    last = [x for x in pts if x[0] > (date.fromisoformat(as_of) - timedelta(days=91)).isoformat()]
    lr = [math.log(b[1] / a[1]) for a, b in zip(last, last[1:])]
    vol = (sum((x - sum(lr) / len(lr)) ** 2 for x in lr) / (len(lr) - 1)) ** 0.5 * math.sqrt(365) if len(lr) > 30 else None
    base = [x for x in pts if x[0] <= (date.fromisoformat(as_of) - timedelta(days=91)).isoformat()]
    if not base or not base[-1][2] or not pts[-1][2]:
        return vol, None
    units0, units1 = base[-1][2] / base[-1][1], pts[-1][2] / pts[-1][1]
    return vol, units1 / units0 - 1


def rebalance_dates(first: str, last: str, every: int = ALT_EVERY_DAYS) -> list[str]:
    out, d = [], date.fromisoformat(first)
    while d.isoformat() <= last:
        out.append(d.isoformat())
        d += timedelta(days=every)
    return out


def flex_step(nav_prev: float, r_crypto: float, r_world50: float) -> float:
    w = FLEX_WEIGHTS
    return nav_prev * (1 + w["crypto"] * r_crypto + w["world50"] * r_world50)


# ── 读库 ────────────────────────────────────────────────────────────────────

async def _get_all(tail: str) -> list[dict]:
    from src.data.universe.world50_book import _get_all as g
    return await g(tail)


def _shift(d: str, days: int) -> str:
    return (date.fromisoformat(d) + timedelta(days=days)).isoformat()


async def alt_inputs(as_of: str) -> list[dict]:
    rows = await _get_all("cis_official_daily?select=symbol,d,pillar_f,pillar_o,asset_class"
                          f"&d=gte.{_shift(as_of, -3)}&d=lte.{as_of}&order=d")
    latest: dict[str, dict] = {}
    for r in rows:
        if r.get("asset_class") in CRYPTO_CLASSES:
            latest[r["symbol"]] = r
    out = []
    for sym, r in latest.items():
        px = await _get_all(f"asset_mcap_daily?select=d,price,mcap&symbol=eq.{sym}"
                            f"&d=gte.{_shift(as_of, -100)}&d=lte.{as_of}&order=d")
        ser = [(x["d"], float(x["price"]), float(x["mcap"]) if x.get("mcap") else None) for x in px if x.get("price")]
        vol, sup = vol_and_supply(ser, as_of)
        mc = ser[-1][2] if ser else None
        out.append({"sym": sym, "f": r.get("pillar_f"), "o": r.get("pillar_o"), "mcap": mc, "vol13": vol, "sup13": sup})
    return out


async def prices(keys: list[str], start: str, end: str) -> dict[str, list[tuple[str, float]]]:
    out = {}
    for k in keys:
        rows = await _get_all(f"asset_mcap_daily?select=d,price&symbol=eq.{k}&d=gte.{start}&d=lte.{end}&order=d")
        out[k] = [(r["d"], float(r["price"])) for r in rows if r.get("price")]
    return out


async def tom_inputs(end: str) -> tuple[dict, dict]:
    """收盘:BTC / ETH = asset_mcap_daily;CORE = ① cap_a1_u 的回放 NAV(multiplier_daily core_u_replay)。
    资金费:funding_history 币安永续按天求和 × 365(CORE 用 BTC 的)。"""
    import pandas as pd
    px = await prices(["BTC", "ETH"], TOM_WARM_FROM, end)
    closes = {k: pd.Series([v for _, v in pts], index=pd.to_datetime([d for d, _ in pts])) for k, pts in px.items() if pts}
    core = await _get_all(f"multiplier_daily?select=d,nav&arm=eq.core_u_replay&d=gte.{TOM_WARM_FROM}&d=lte.{end}&order=d")
    if core:
        closes["CORE"] = pd.Series([float(r["nav"]) for r in core], index=pd.to_datetime([r["d"] for r in core]))
    fund = {}
    for sym in ("BTC", "ETH"):
        rows = await _get_all(f"funding_history?select=funding_time,funding_rate&venue=eq.binance_perp&symbol=eq.{sym}"
                              f"&funding_time=gte.{TOM_WARM_FROM}&order=funding_time")
        if rows:
            df = pd.DataFrame(rows)
            df["d"] = pd.to_datetime(df["funding_time"].str[:10])
            fund[sym] = df.groupby("d")["funding_rate"].sum().astype(float) * 365
    fund["CORE"] = fund.get("BTC")
    return closes, fund


def mix_nav(legs: dict[str, "Any"], weights: dict[str, float], reb: int = FLEX_REB_DAYS, cost: float = COST_CRYPTO):
    """纯函数。legs:{腿: NAV Series},取共同日期;恒定配比,每 reb 个共同日期回到目标(换手 × cost),现金收益 0。
    返回从第一个共同日期起 = 1 的 NAV Series。"""
    import pandas as pd
    df = pd.concat({k: v for k, v in legs.items()}, axis=1).dropna().sort_index()
    if df.empty:
        return pd.Series(dtype=float)
    r = df.pct_change().iloc[1:]
    tgt = pd.Series(weights, dtype=float)
    hold = tgt.copy()
    nav, out = 1.0, {df.index[0]: 1.0}
    for i, (d, row) in enumerate(r.iterrows(), start=1):
        if i % reb == 0:
            nav *= 1 - float((hold - tgt).abs().sum()) * cost
            hold = tgt.copy()
        g = float((hold * row[hold.index]).sum())
        nav *= 1 + g
        grown = hold * (1 + row[hold.index])
        hold = grown / (1 + g)                                  # 权重按当日涨跌漂移;现金 1 − Σ 不动
        out[d] = nav
    return pd.Series(out)


FLEX_TRADFI = (("ACWI", "equity"), ("XAUUSD", "gold"))


def last_weekday(cutoff: str) -> str:
    """纯函数。≤ cutoff 的最后一个工作日(周一至周五;不管节假日 —— 节假日那天腿上本来就没有行,共同日期会跳过它)。"""
    import pandas as pd
    d = pd.Timestamp(cutoff)
    while d.weekday() >= 5:
        d -= pd.Timedelta(days=1)
    return d.date().isoformat()


async def _flex_tradfi_legs(cutoff: str) -> dict[str, "Any"]:
    """股票腿 ACWI、黄金腿 XAUUSD 的日收盘(TOM_START 起)。

    10-18 实测:这两个只由 World50 的周更整段重取写入(6 天一轮),`ohlcv_daily` 停在 10-15,
    灵活组合三条臂一行都写不出来(「腿还没有前向数据」)。腿落后于最后一个工作日时,
    就地把**从开账前一周起**的整段重取一次 —— 走既有的 `tradfi_history.refresh_one`(EODHD,复权),
    不新增取数入口;整段而不是只补最后几天,是为了让窗口里所有行同一个复权口径(否则分红日前后会出一道缝)。"""
    import pandas as pd
    want = last_weekday(cutoff)

    async def read():
        out = {}
        for sym, leg in FLEX_TRADFI:
            rows = await _get_all(f"ohlcv_daily?select=trade_date,close&source=eq.eodhd&symbol=eq.{sym}&trade_date=gte.{TOM_START}&order=trade_date")
            out[leg] = pd.Series({pd.Timestamp(x["trade_date"]): float(x["close"]) for x in rows if x.get("close")})
        return out
    tf = await read()
    stale = [sym for sym, leg in FLEX_TRADFI if tf[leg].empty or tf[leg].index[-1].date().isoformat() < want]
    if stale:
        from src.data.market.tradfi_history import refresh_one
        from src.data.universe.world50 import BENCHMARKS, CANDIDATES
        by_key = {c.key: c for c in (*BENCHMARKS, *CANDIDATES)}
        start = (pd.Timestamp(TOM_START) - pd.Timedelta(days=7)).date().isoformat()
        for sym in stale:
            if sym in by_key:
                await refresh_one(by_key[sym], start=start)
        tf = await read()
    return tf


async def run_flex_x1v(cutoff: str) -> dict[str, Any]:
    """S-604 灵活组合前向:每次从 TOM_START 起整段重算(纯函数、可复现),只追加没写过的天。"""
    import pandas as pd
    from src.api.store import supabase_upsert_table
    if cutoff <= TOM_START:
        return {"ok": True, "waiting": f"从 {TOM_START} 收盘起"}
    have_rows = await _get_all("forward_book_nav?select=arm,d,nav&book=eq.flex_x1v&order=d")
    have = {(r["arm"], r["d"]): float(r["nav"]) for r in have_rows}
    tom = await _get_all(f"forward_book_nav?select=arm,d,nav&book=eq.tom_trader&d=gte.{TOM_START}&order=d")
    tnav: dict[str, dict] = {}
    for r in tom:
        tnav.setdefault(r["arm"], {})[r["d"]] = float(r["nav"])
    tf = await _flex_tradfi_legs(cutoff)
    rows_n, notes = [], []
    for arm, (w, crypto_arm) in FLEX_X1V_ARMS.items():
        c = tnav.get(crypto_arm)
        if not c or tf["equity"].empty or tf["gold"].empty:
            notes.append(f"{arm}: 腿还没有前向数据")
            continue
        legs = {"crypto": pd.Series({pd.Timestamp(d): v for d, v in c.items()}), "equity": tf["equity"], "gold": tf["gold"]}
        nav = mix_nav(legs, w)
        nav = nav[nav.index <= pd.Timestamp(cutoff)]
        done = sorted(d for (a, d) in have if a == arm)
        prev = None
        for d, v in nav.items():
            ds = d.date().isoformat()
            if not (done and ds <= done[-1]):
                rows_n.append({"book": "flex_x1v", "arm": arm, "d": ds, "nav": float(v),
                               "ret": (float(v) / prev - 1) if prev else None, "as_of": TOM_START, "rule": RULE_FLEX_X1V})
            prev = float(v)
    if rows_n:
        wr = await supabase_upsert_table("forward_book_nav", rows_n, on_conflict="book,arm,d")
        if not wr.ok:
            return {"ok": False, "why": f"写 forward_book_nav 失败:{(wr.why or '')[:160]}"}
    return {"ok": True, "nav_written": len(rows_n), **({"notes": notes} if notes else {})}


async def run_tom_trader(cutoff: str) -> dict[str, Any]:
    """S-600 交易层前向:每次从 TOM_WARM_FROM 整段重算敞口(纯函数、可复现),只写 TOM_START 之后还没写过的天;写过的不改。"""
    import pandas as pd
    from src.api.store import supabase_upsert_table
    from src.data.signals.tom import trade_path, trade_returns
    if cutoff <= TOM_START:
        return {"ok": True, "waiting": f"交易层前向从 {TOM_START} 收盘起"}
    navs = await _get_all("forward_book_nav?select=arm,d,nav&book=eq.tom_trader&order=d")
    have = {(r["arm"], r["d"]): float(r["nav"]) for r in navs}
    # 每小时被 ③ 的循环叫一次:每条臂都已经写到 cutoff ⇒ 不再读价格(只花一次查询)
    last_by_arm = {a: max(d for (x, d) in have if x == a) for a in {x for (x, _) in have}}
    if set(last_by_arm) >= set(TOM_ARMS) and min(last_by_arm.values()) >= cutoff:
        return {"ok": True, "up_to_date": cutoff}
    closes, fund = await tom_inputs(cutoff)
    rows_n, rows_h, notes = [], [], []
    for arm, (key, bear, size, exit_mode, vol) in TOM_ARMS.items():
        c = closes.get(key)
        if c is None or len(c) < 260:
            notes.append(f"{arm}: {key} 收盘不足")
            continue
        g = pd.Series(1.0, index=c.index) if bear is None else trade_path(c, bear, size, exit_mode, vol)
        r = trade_returns(c, g, fund.get(key))
        r = r[(r.index > pd.Timestamp(TOM_START)) & (r.index <= pd.Timestamp(cutoff))]
        done = sorted(d for (a, d) in have if a == arm)
        nav = have[(arm, done[-1])] if done else 1.0
        if not done:
            rows_n.append({"book": "tom_trader", "arm": arm, "d": TOM_START, "nav": 1.0, "ret": None, "as_of": TOM_START, "rule": RULE_TOM})
            if bear is not None:
                rows_h.append({"book": "tom_trader", "arm": arm, "as_of": TOM_START, "key": key,
                               "weight": float(g.get(pd.Timestamp(TOM_START), float("nan"))), "note": "exposure set at close", "rule": RULE_TOM})
        for d, x in r.items():
            ds = d.date().isoformat()
            if done and ds <= done[-1]:
                continue
            nav *= 1 + float(x)
            rows_n.append({"book": "tom_trader", "arm": arm, "d": ds, "nav": nav, "ret": float(x), "as_of": TOM_START, "rule": RULE_TOM})
            if bear is not None:
                rows_h.append({"book": "tom_trader", "arm": arm, "as_of": ds, "key": key, "weight": float(g.get(d, float("nan"))),
                               "note": "exposure set at close", "rule": RULE_TOM})
    for t, rows, oc in (("forward_book_nav", rows_n, "book,arm,d"), ("forward_book_holdings", rows_h, "book,arm,as_of,key")):
        if rows:
            w = await supabase_upsert_table(t, rows, on_conflict=oc)
            if not w.ok:
                return {"ok": False, "why": f"写 {t} 失败:{(w.why or '')[:160]}"}
    last = {a: g for a, g in ((h["arm"], h["weight"]) for h in rows_h)}
    return {"ok": not notes, "nav_written": len(rows_n), "exposure_now": last, **({"notes": notes} if notes else {})}


# ── 一轮 ────────────────────────────────────────────────────────────────────

async def run_forward_books(today: Optional[str] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.universe.world50_book import drift, turnover_cost, weekdays
    today = today or datetime.now(timezone.utc).date().isoformat()
    cutoff = _shift(today, -FREEZE_DAYS)
    tom = await run_tom_trader(_shift(today, -1))
    if cutoff < FORWARD_START:
        sel = alt_select(await alt_inputs(cutoff))
        return {"ok": bool(tom.get("ok")), "waiting": f"前向账本从 {FORWARD_START} 起",
                "preview": {"as_of": cutoff, "alt_gate": sel["gate"], "alt_top6": sel["top"], "alt_fo6": sel["fo6"]}, "tom_trader": tom}
    held = await _get_all("forward_book_holdings?select=book,arm,as_of,key,weight&order=as_of")
    navs = await _get_all("forward_book_nav?select=book,arm,d,nav&order=d")
    book: dict[tuple[str, str], dict[str, dict[str, float]]] = {}
    for r in held:
        book.setdefault((r["book"], r["arm"]), {}).setdefault(r["as_of"], {})[r["key"]] = float(r["weight"])
    nav_of = {(r["book"], r["arm"], r["d"]): float(r["nav"]) for r in navs}
    wrote, notes = 0, []
    # 1) 山寨龙头腿
    for q in rebalance_dates(FORWARD_START, cutoff):
        if ("alt_leaders", "TOP6") in book and q in book[("alt_leaders", "TOP6")]:
            continue
        sel = alt_select(await alt_inputs(q))
        if not sel["top"]:
            notes.append(f"alt {q}: 门槛内没有名字")
            break
        targets = {"TOP6": {k: 1 / len(sel["top"]) for k in sel["top"]},
                   "FO6": {k: 1 / len(sel["fo6"]) for k in sel["fo6"]},
                   "GATE_EW": {k: 1 / len(sel["gate"]) for k in sel["gate"]}, "ETH": {"ETH": 1.0}}
        rows_h, rows_n = [], []
        for arm, new in targets.items():
            prev = sorted(d for d in book.get(("alt_leaders", arm), {}) if d < q)
            if prev:
                p = prev[-1]
                px = await prices(sorted(book[("alt_leaders", arm)][p]), _shift(p, -5), q)
                g, drifted, _ = drift(book[("alt_leaders", arm)][p], px, p, q)
                if g is None:
                    notes.append(f"alt {arm} {q}: 上一段没有价")
                    continue
                nav_q = nav_of[("alt_leaders", arm, p)] * g * (1 - turnover_cost(drifted, new, {k: "crypto" for k in new}))
            else:
                nav_q = 1.0
            rule = RULE_FO6 if arm == "FO6" else RULE_ALT
            sc_of = sel["fo_scores"] if arm == "FO6" else sel["scores"]
            rows_h += [{"book": "alt_leaders", "arm": arm, "as_of": q, "key": k, "weight": w,
                        "note": f"score {sc_of.get(k, 0):.1f}" if arm != "ETH" else None, "rule": rule}
                       for k, w in new.items()]
            rows_n.append({"book": "alt_leaders", "arm": arm, "d": q, "nav": nav_q, "ret": None, "as_of": q, "rule": rule})
            book.setdefault(("alt_leaders", arm), {})[q] = new
            nav_of[("alt_leaders", arm, q)] = nav_q
        for t, rows, oc in (("forward_book_holdings", rows_h, "book,arm,as_of,key"), ("forward_book_nav", rows_n, "book,arm,d")):
            w = await supabase_upsert_table(t, rows, on_conflict=oc)
            if not w.ok:
                return {"ok": False, "why": f"写 {t} 失败:{(w.why or '')[:160]}"}
        wrote += len(rows_n)
    for arm in ALT_ARMS:
        hist = book.get(("alt_leaders", arm))
        if not hist:
            continue
        p = max(hist)
        days = [d for d in weekdays(p, cutoff) if ("alt_leaders", arm, d) not in nav_of]
        if not days:
            continue
        px = await prices(sorted(hist[p]), _shift(p, -5), cutoff)
        rows, last_nav = [], nav_of[("alt_leaders", arm, p)]
        for d in days:
            g, _, n = drift(hist[p], px, p, d)
            if g is None or n < len(hist[p]) * 0.8:
                break
            nav = nav_of[("alt_leaders", arm, p)] * g
            rows.append({"book": "alt_leaders", "arm": arm, "d": d, "nav": nav, "ret": nav / last_nav - 1, "as_of": p,
                         "rule": RULE_FO6 if arm == "FO6" else RULE_ALT})
            last_nav = nav
        if rows:
            w = await supabase_upsert_table("forward_book_nav", rows, on_conflict="book,arm,d")
            if not w.ok:
                return {"ok": False, "why": f"写 alt 净值失败:{(w.why or '')[:160]}"}
            wrote += len(rows)
    # 2) 灵活配置组合:两条腿各自的前向净值 → 每个两边都有的工作日
    core = await _get_all(f"core_cap_daily?select=d,nav&arm=eq.cap_a1_u&d=gte.{_shift(FORWARD_START, -7)}&order=d")
    w50 = await _get_all(f"world50_book_nav?select=d,nav&arm=eq.EWxMom&d=gte.{FORWARD_START}&order=d")
    cmap = {r["d"]: float(r["nav"]) for r in core if r.get("nav")}
    wmap = {r["d"]: float(r["nav"]) for r in w50 if r.get("nav")}
    common = sorted(d for d in wmap if d in cmap and FORWARD_START <= d <= cutoff)
    if common:
        done = sorted(d for (b, a, d) in nav_of if b == "flex")
        rows, prev_d = [], (done[-1] if done else None)
        prev_nav = nav_of.get(("flex", "CONST_35_50_15", prev_d), 1.0) if prev_d else None
        for d in common:
            if done and d <= done[-1]:
                continue
            if prev_d is None:
                rows.append({"book": "flex", "arm": "CONST_35_50_15", "d": d, "nav": 1.0, "ret": None, "as_of": d, "rule": RULE_FLEX})
                prev_d, prev_nav = d, 1.0
                continue
            nav = flex_step(prev_nav, cmap[d] / cmap[prev_d] - 1, wmap[d] / wmap[prev_d] - 1)
            rows.append({"book": "flex", "arm": "CONST_35_50_15", "d": d, "nav": nav, "ret": nav / prev_nav - 1, "as_of": prev_d,
                         "rule": RULE_FLEX})
            prev_d, prev_nav = d, nav
        if rows:
            w = await supabase_upsert_table("forward_book_nav", rows, on_conflict="book,arm,d")
            if not w.ok:
                return {"ok": False, "why": f"写 flex 净值失败:{(w.why or '')[:160]}"}
            wrote += len(rows)
    return {"ok": not notes and bool(tom.get("ok")), "nav_written": wrote, "tom_trader": tom, **({"notes": notes} if notes else {})}
