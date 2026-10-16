"""另外两本前向账本,与 World50 账本同日(2026-12-31)开账、在同一个周更循环里记(book 段之后)。

1. **山寨龙头腿**(alt_leaders,台账 S-589 的前向预注册;Jazz 10-16「山寨只拿基本面和资金面好的龙头」):
   宇宙 = CIS 正式序列(cis_official_daily)里的加密名,去掉 BTC(在核心里)与稳定 / 包装币;每 28 天调仓。
   龙头门槛 = 当日市值前 15,且 13 周年化波动 ≤ 宇宙中位数 × 1.5,且 13 周流通量增幅 ≤ 10%(流通量 = 市值 / 价格)。
   打分 = 秩(F) + 秩(O) + 秩(市值) − 秩(vol13),在门槛内算;取前 6 名等权。
   臂:TOP6(规则)· GATE_EW(门槛内全部等权,对照)· ETH(只持 ETH,对照)。随机 6 名的对照在评估时从 GATE_EW 的成员重抽,不存。
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
RULE_FLEX = "flex_v1:加密 ① cap_a1_u 35% / World50 EW×Mom 50% / 现金 15%(收益 0),每周回到目标"
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
        return {"gate": [], "top": [], "scores": {}}
    vols = sorted(r["vol13"] for r in ok)
    med = vols[len(vols) // 2] if len(vols) % 2 else (vols[len(vols) // 2 - 1] + vols[len(vols) // 2]) / 2
    top = sorted(ok, key=lambda r: -r["mcap"])[:ALT_TOP_MCAP]
    gate = [r for r in top if r["vol13"] <= ALT_VOL_MULT * med and r["sup13"] <= ALT_SUPPLY_MAX]
    if not gate:
        return {"gate": [], "top": [], "scores": {}}
    rf, ro, rm, rv = (_ranks([r[k] for r in gate]) for k in ("f", "o", "mcap", "vol13"))
    sc = {r["sym"]: rf[i] + ro[i] + rm[i] - rv[i] for i, r in enumerate(gate)}
    pick = sorted(gate, key=lambda r: (-sc[r["sym"]], -r["mcap"]))[:ALT_PICK]
    return {"gate": [r["sym"] for r in gate], "top": [r["sym"] for r in pick], "scores": sc}


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


# ── 一轮 ────────────────────────────────────────────────────────────────────

async def run_forward_books(today: Optional[str] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.universe.world50_book import drift, turnover_cost, weekdays
    today = today or datetime.now(timezone.utc).date().isoformat()
    cutoff = _shift(today, -FREEZE_DAYS)
    if cutoff < FORWARD_START:
        sel = alt_select(await alt_inputs(cutoff))
        return {"ok": True, "waiting": f"前向账本从 {FORWARD_START} 起",
                "preview": {"as_of": cutoff, "alt_gate": sel["gate"], "alt_top6": sel["top"]}}
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
            rows_h += [{"book": "alt_leaders", "arm": arm, "as_of": q, "key": k, "weight": w,
                        "note": f"score {sel['scores'].get(k, 0):.1f}" if arm != "ETH" else None, "rule": RULE_ALT}
                       for k, w in new.items()]
            rows_n.append({"book": "alt_leaders", "arm": arm, "d": q, "nav": nav_q, "ret": None, "as_of": q, "rule": RULE_ALT})
            book.setdefault(("alt_leaders", arm), {})[q] = new
            nav_of[("alt_leaders", arm, q)] = nav_q
        for t, rows, oc in (("forward_book_holdings", rows_h, "book,arm,as_of,key"), ("forward_book_nav", rows_n, "book,arm,d")):
            w = await supabase_upsert_table(t, rows, on_conflict=oc)
            if not w.ok:
                return {"ok": False, "why": f"写 {t} 失败:{(w.why or '')[:160]}"}
        wrote += len(rows_n)
    for arm in ("TOP6", "GATE_EW", "ETH"):
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
            rows.append({"book": "alt_leaders", "arm": arm, "d": d, "nav": nav, "ret": nav / last_nav - 1, "as_of": p, "rule": RULE_ALT})
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
    return {"ok": not notes, "nav_written": wrote, **({"notes": notes} if notes else {})}
