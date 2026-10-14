"""World50 的两份输入:候选的历史市值(按时点排名)与链上可持有的形式(资格)—— T-098 第二部分。

## 历史市值 → `world50_mcap_weekly`

- 公司:EODHD `historical-market-cap`(周频、美元),2015 起整段重取。取不到的公司一行不写、原因带回。
- 加密:不另存 —— `asset_mcap_daily`(CoinGecko Pro)已有。
- 贵金属:不存 —— 排名时用「价格 × 可投资存量」现算(`metal_mcap_usd`)。存量口径**待 Jazz 定**,
  这里给两档:`bars_coins_etfs`(私人投资:金条、金币、ETF)与 `bars_coins_etfs_cb`(再加央行)。
  黄金数字是世界黄金协会 2025 年底的地上存量分解(第三方转述,见 S-579);白银、铂金还没有可靠来源 ⇒ None(不可算)。

## 链上形式 → `world50_onchain_forms`

来源:CoinGecko Pro `/rwas/markets`(S-266 已在用的那一族;`asset_type` 是 CG 的封闭枚举 stock / etf / commodity,
市场数据在 `tokenized_market_data` 里)。发行方由 `/rwas/markets?issuer=<id>` 反查,一只资产可以有多家。
对到候选上的规则(`match_rwa`,纯函数,规则写进 `match_rule` 便于复查):
- 商品:名字里的 gold / silver / platinum。**只在 `asset_type = commodity` 里按名字对** —— 金矿公司的代币化股票名字里也有 Gold。
- ETF:只有追踪实物金属的 ETF(GLD、IAU、SLV、PPLT …)算金属的链上形式;其余 ETF 不是成分(方法 §2),记 `etf-not-a-member`。
- 股票:符号(或去掉发行方后缀 xStocks `x` / Ondo `on` 之后)等于候选代码;**1–2 个字母的代码还要名字对得上**
  (V、C、T、MA、GS …太容易撞)。本地上市、没有美国代码的公司按公司全名对,长名字先对(Bank of China ⊂ Agricultural Bank of China)。
- 对不上的也写进表(key 为空),方便查漏配。
**这只是「有没有链上形式、成交多少」;发行结构(追踪凭证还是 1:1 托管)、谁能买(地域限制)要另外核 —— 资格规则由 Jazz 定。**

## 一周一轮(`run_week`,由 `_world50_history_loop` 调)

复权日线(`tradfi_history.run_once`)→ 历史市值 → 链上形式。三段各自报结果;**任何一段没成,整轮就不是 ok**,
哪一段、为什么写在 reason 里 —— 不让一段静默地死在一个「ok」的循环里。
"""
from __future__ import annotations

import asyncio
import math
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any, Iterable, Optional

WRITES_TABLES = ("world50_mcap_weekly", "world50_onchain_forms")
WRITES_COLUMNS = {
    "world50_mcap_weekly": ("key", "d", "mcap_usd", "source"),
    "world50_onchain_forms": ("as_of", "token_id", "key", "symbol", "name", "category", "issuer", "match_rule",
                              "price_usd", "mcap_usd", "volume_24h_usd"),
}

START = "2015-01-01"
TROY_OZ_PER_TONNE = 32_150.7466
MCAP_MIN_SHARE_OK = 0.6       # 低于这个比例的公司取到市值,整段按故障报(和日线的 60/103 同一量级)

#: 世界黄金协会 2025 年底的地上黄金存量(吨)—— 第三方转述(EBC / WorldAtlas 引 WGC),官方表格待核。
GOLD_STOCK_T_2025 = {"total": 219_891, "jewellery": 97_645, "bars_coins_etfs": 50_978,
                     "central_banks": 38_666, "other": 32_602}
INVESTABLE_BASES = ("bars_coins_etfs", "bars_coins_etfs_cb")


def metal_mcap_usd(key: str, price_usd_per_oz: float, basis: str = "bars_coins_etfs") -> Optional[float]:
    """贵金属的可投资市值。没有可靠存量来源的金属返回 None(不可算,不是 0)。"""
    if basis not in INVESTABLE_BASES:
        raise ValueError(f"basis 只能是 {INVESTABLE_BASES}")
    if key != "XAUUSD" or not price_usd_per_oz or price_usd_per_oz <= 0:
        return None
    t = GOLD_STOCK_T_2025["bars_coins_etfs"] + (GOLD_STOCK_T_2025["central_banks"] if basis.endswith("_cb") else 0)
    return t * TROY_OZ_PER_TONNE * float(price_usd_per_oz)


# ── 历史市值 ────────────────────────────────────────────────────────────────

def mcap_rows(key: str, raw: Iterable[dict], source: str = "eodhd_hist_mcap") -> list[dict]:
    """EODHD 返回的 [{date, value}] → world50_mcap_weekly 行。读不出数字或 ≤ 0 的点不收。纯函数。"""
    out = []
    for x in raw or []:
        d = str(x.get("date") or "")[:10]
        try:
            v = float(x.get("value"))
        except (TypeError, ValueError):
            continue
        if len(d) == 10 and v > 0:
            out.append({"key": key, "d": d, "mcap_usd": v, "source": source})
    return out


async def refresh_mcap(candidates: Optional[list] = None, start: str = START, concurrency: int = 4) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.market.tradfi_history import split_code
    from src.data.universe.world50 import CANDIDATES
    todo = candidates if candidates is not None else [c for c in CANDIDATES if c.cls == "equity"]
    sem = asyncio.Semaphore(concurrency)

    async def one(c):
        async with sem:
            try:
                t, ex = split_code(c.code)
                rows = mcap_rows(c.key, await dl.get_eodhd_historical_mcap(t, ex, start))
            except Exception as e:  # noqa: BLE001 — 一家取不到不连坐整轮,原因带回去
                return {"key": c.key, "ok": False, "why": f"{type(e).__name__}: {str(e)[:140]}"}
            if not rows:
                return {"key": c.key, "ok": False, "why": "0 行可用市值"}
            res = await supabase_upsert_table("world50_mcap_weekly", rows, on_conflict="key,d,source")
            return {"key": c.key, "ok": res.ok, "rows": len(rows), "first": rows[0]["d"],
                    **({} if res.ok else {"why": res.why[:140]})}

    res = await asyncio.gather(*[one(c) for c in todo])
    ok = [r for r in res if r.get("ok")]
    enough = len(ok) >= max(1, math.ceil(MCAP_MIN_SHARE_OK * len(todo)))
    return {"ok": enough, "companies": len(todo), "companies_ok": len(ok),
            "rows": sum(int(r.get("rows") or 0) for r in ok),
            "earliest": min((r["first"] for r in ok), default=None),
            "failed": [{"key": r["key"], "why": r.get("why")} for r in res if not r.get("ok")][:40]}


# ── 链上形式 ────────────────────────────────────────────────────────────────

METAL_WORDS = (("gold", "XAUUSD"), ("silver", "XAGUSD"), ("platinum", "XPTUSD"))
METAL_ETFS = {"GLD": "XAUUSD", "IAU": "XAUUSD", "SGOL": "XAUUSD", "GLDM": "XAUUSD", "AAAU": "XAUUSD", "PHYS": "XAUUSD",
              "SLV": "XAGUSD", "SIVR": "XAGUSD", "PSLV": "XAGUSD", "PPLT": "XPTUSD"}
ISSUER_SUFFIXES = ("ON", "X")          # Ondo: NVDAon;xStocks: NVDAx


def _norm(t: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", (t or "").upper())


def _plain(s: str) -> str:
    """小写、去重音(Nestlé → nestle,L'Oréal → l'oreal)。"""
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def _bases(sym: str) -> list[str]:
    """符号本身在前,再是去掉发行方后缀的版本。"""
    out = [sym]
    for suf in ISSUER_SUFFIXES:
        if sym.endswith(suf) and len(sym) > len(suf):
            out.append(sym[: -len(suf)])
    return out


def _first_word(name: str) -> str:
    w = re.split(r"[\s&\-,.]+", _plain(name).strip())
    return w[0] if w else ""


def match_rwa(symbol: str, name: str, asset_type: str, candidates: Iterable[Any]) -> tuple[Optional[str], str]:
    """一个代币化 RWA → (候选 key 或 None, 规则)。纯函数。"""
    sym, at, lname = _norm(symbol), (asset_type or "").strip().lower(), _plain(name)
    if at == "commodity":
        for w, k in METAL_WORDS:
            if w in lname:
                return k, f"commodity:{w}"
        return None, "commodity-not-a-candidate"
    if at == "etf":
        for b in _bases(sym):
            if b in METAL_ETFS:
                return METAL_ETFS[b], f"metal-etf:{b}"
        return None, "etf-not-a-member"
    cands = [c for c in candidates if c.cls == "equity"]
    by_ticker = {_norm(c.key): c for c in cands if "." not in c.key}
    for i, b in enumerate(_bases(sym)):
        c = by_ticker.get(b)
        if c is None:
            continue
        if len(b) <= 2 and _first_word(c.name) not in lname:
            continue                     # 短代码必须名字也对得上
        return c.key, ("ticker" if i == 0 else f"ticker-strip:{b}")
    for c in sorted((c for c in cands if "." in c.key), key=lambda c: -len(c.name)):
        if len(c.name) >= 4 and _plain(c.name) in lname:
            return c.key, f"name:{c.name}"
    return None, "unmatched"


def _num(v: Any) -> Optional[float]:
    if v is None or isinstance(v, bool):
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f and f not in (float("inf"), float("-inf")) else None


def form_rows(raw: Iterable[dict], issuers: dict[str, set[str]], candidates: Iterable[Any], as_of: str) -> list[dict]:
    """`/rwas/markets` 的行 → world50_onchain_forms 行。市场数据在 `tokenized_market_data` 里(S-266);
    **没测的是 None,不是 0**。纯函数。"""
    cands = list(candidates)
    out, seen = [], set()
    for r in raw or []:
        rid = str(r.get("id") or "").strip()
        if not rid or rid in seen:
            continue
        seen.add(rid)
        tmd = r.get("tokenized_market_data") if isinstance(r.get("tokenized_market_data"), dict) else {}
        at = str(r.get("asset_type") or "").strip().lower()
        key, rule = match_rwa(r.get("symbol") or "", r.get("name") or "", at, cands)
        out.append({"as_of": as_of, "token_id": rid, "key": key, "symbol": r.get("symbol"), "name": r.get("name"),
                    "category": f"rwa:{at or 'unknown'}", "issuer": "|".join(sorted(issuers.get(rid, ()))) or None,
                    "match_rule": rule,
                    "price_usd": _num(tmd.get("current_price", r.get("current_price"))),
                    "mcap_usd": _num(tmd.get("market_cap")), "volume_24h_usd": _num(tmd.get("total_volume"))})
    return out


async def discover_onchain_forms(as_of: Optional[str] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.universe.world50 import CANDIDATES
    as_of = as_of or datetime.now(timezone.utc).date().isoformat()
    try:
        raw = await dl.get_cg_rwa_markets()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"/rwas/markets 读不到:{type(e).__name__}: {str(e)[:160]}"}
    issuers: dict[str, set[str]] = {}
    issuer_failed = []
    try:
        issuer_list = await dl.get_cg_rwa_issuers()
    except Exception as e:  # noqa: BLE001 — 发行方是附加信息,读不到照写,只是 issuer 为空并报出来
        issuer_list, issuer_failed = [], [f"issuers/list: {type(e).__name__}: {str(e)[:100]}"]
    for it in issuer_list:
        try:
            for r in await dl.get_cg_rwa_markets(issuer=it["id"]):
                if r.get("id"):
                    issuers.setdefault(str(r["id"]), set()).add(str(it["id"]))
        except Exception as e:  # noqa: BLE001
            issuer_failed.append(f"{it['id']}: {type(e).__name__}")
    rows = form_rows(raw, issuers, CANDIDATES, as_of)
    if not rows:
        return {"ok": False, "why": f"/rwas/markets 返回 {len(raw)} 条,0 条有 id —— 形状变了?"}
    res = await supabase_upsert_table("world50_onchain_forms", rows, on_conflict="as_of,token_id")
    matched = [r for r in rows if r["key"]]
    by_type: dict[str, int] = {}
    for r in rows:
        by_type[r["category"]] = by_type.get(r["category"], 0) + 1
    return {"ok": res.ok, "tokens": len(rows), "by_type": by_type, "matched": len(matched),
            "candidates_with_form": len({r["key"] for r in matched}),
            "issuers": len(issuer_list), "with_issuer": sum(1 for r in rows if r["issuer"]),
            "issuer_failed": issuer_failed[:10], **({} if res.ok else {"why": res.why[:160]})}


# ── 一周一轮 ────────────────────────────────────────────────────────────────

def _brief(name: str, r: dict) -> dict:
    keep = {"prices": ("symbols", "symbols_ok", "written", "elapsed_s"),
            "mcap": ("companies", "companies_ok", "rows", "earliest"),
            "onchain_forms": ("tokens", "by_type", "matched", "candidates_with_form", "with_issuer")}[name]
    out = {"ok": bool(r.get("ok")), **{k: r.get(k) for k in keep if k in r}}
    fails = r.get("failed") or r.get("issuer_failed")
    if fails:
        out["failed"] = fails[:10]
    if r.get("why") or (not r.get("ok") and r.get("reason")):
        out["why"] = str(r.get("why") or r.get("reason"))[:200]
    return out


async def run_week() -> dict[str, Any]:
    from src.data.market.tradfi_history import run_once
    steps = (("prices", run_once), ("mcap", refresh_mcap), ("onchain_forms", discover_onchain_forms))
    parts: dict[str, dict] = {}
    for name, fn in steps:
        try:
            parts[name] = await fn()
        except Exception as e:  # noqa: BLE001 — 一段炸了,后面的照跑,炸的原因带回去
            parts[name] = {"ok": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}
    bad = [n for n, r in parts.items() if not r.get("ok")]
    p = parts["prices"]
    reason = (f"日线 {p.get('symbols_ok')}/{p.get('symbols')} · 市值 {parts['mcap'].get('companies_ok')}/"
              f"{parts['mcap'].get('companies')} · 链上形式 {parts['onchain_forms'].get('tokens')} 条、"
              f"对上 {parts['onchain_forms'].get('candidates_with_form')} 个候选")
    if bad:
        reason = "没成的段:" + "、".join(bad) + " —— " + reason
    return {"ok": not bad, "refused": bool(p.get("refused")), "reason": reason,
            "parts": {n: _brief(n, r) for n, r in parts.items()}}
