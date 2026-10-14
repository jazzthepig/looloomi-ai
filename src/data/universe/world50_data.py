"""World50 的两份输入:候选的历史市值(按时点排名)与链上可持有的形式(资格)—— T-098 第二部分。

## 历史市值 → `world50_mcap_weekly`

- 公司:**股本 × 原始收盘 × 汇率**,自己算。EODHD 的 `historical-market-cap` 我们的套餐没有(10-14 首跑 99/99 家 403)。
  股本 = 基本面里的每季股本(`outstandingShares.quarterly`),**季末 60 天后才算已知**(按时点,不偷看)。
  拆股从我们自己的数据里认:原始价 / 复权价 的比值单日跳 > 20% 就是拆股(分红只造成约 1% 的跳);
  股本是「当时报告的数」还是「按今天口径回改过的数」,用拆股前后两季股本之比判,判不出来就不写。
  一切换到今天的股本口径再乘:股本 × 之后拆股系数,价格 ÷ 之后拆股系数。
  **校准**:最新一季股本 × 最新收盘,与 EODHD 当前市值差 25% 以上(ADR 换股比例、股本口径不对)⇒ 这家不写、比值报出来。
  汇率:EODHD `USD{币种}.FOREX`,取不到 ⇒ 这家不写。周频(每周最后一个交易日),2015 起。
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
import bisect
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

SHARES_LAG_DAYS = 60          # 季末之后多少天股本才算「已知」(10-Q 最晚约 40 天,海外更慢)
CALIB_TOL = 1.25              # 与 EODHD 当前市值的容差;拆股前后股本之比的容差同一个数
SPLIT_JUMP = 1.2              # 原始价 / 复权价 单日跳超过这个倍数 ⇒ 拆股
MCAP_SOURCE = "eodhd_shares_x_close"
EXCHANGE_CCY = {"US": "USD", "KO": "KRW", "SHG": "CNY", "SHE": "CNY", "HK": "HKD", "SW": "CHF", "XETRA": "EUR",
                "PA": "EUR", "TW": "TWD", "SR": "SAR"}


def _pick(j: dict, path: str) -> Any:
    """`A::B::C` —— EODHD 按过滤路径平铺或嵌套返回,两种都收(cis_inputs.fundamentals_rows 同一做法)。"""
    if not isinstance(j, dict):
        return None
    if path in j:
        return j[path]
    cur: Any = j
    for p in path.split("::"):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(p)
    return cur


def shares_points(j: dict) -> list[tuple[str, float]]:
    """每季股本 [(季末, 股数)],旧 → 新。读不出数字的季不收。纯函数。"""
    q = _pick(j, "outstandingShares::quarterly") or {}
    items = q.values() if isinstance(q, dict) else (q if isinstance(q, list) else [])
    out: dict[str, float] = {}
    for x in items:
        if not isinstance(x, dict):
            continue
        d = str(x.get("dateFormatted") or "")[:10]
        v = _num(x.get("shares"))
        if v is None and _num(x.get("sharesMln")) is not None:
            v = _num(x.get("sharesMln")) * 1e6
        if len(d) == 10 and v and v > 0:
            out[d] = v
    return sorted(out.items())


def _closes(raw: Iterable[dict]) -> list[tuple[str, float, float]]:
    """EODHD 日线 → [(日期, 原始收盘, 复权收盘)],旧 → 新,只收两个都 > 0 的。"""
    out = []
    for x in raw or []:
        d, c = str(x.get("date") or "")[:10], _num(x.get("close"))
        a = _num(x.get("adjusted_close"))
        if len(d) == 10 and c and c > 0:
            out.append((d, c, a if a and a > 0 else c))
    return sorted(out)


def split_events(raw: Iterable[dict]) -> list[tuple[str, float]]:
    """[(拆股后第一个交易日, 比例 k)]。k > 1 = 一拆 k;k < 1 = 合股。纯函数。"""
    cl = _closes(raw)
    out = []
    for (d0, c0, a0), (d1, c1, a1) in zip(cl, cl[1:]):
        jump = (c0 / a0) / (c1 / a1)
        if jump > SPLIT_JUMP or jump < 1 / SPLIT_JUMP:
            out.append((d1, jump))
    return out


def _factor_after(x: str, splits: list[tuple[str, float]]) -> float:
    f = 1.0
    for d, k in splits:
        if d > x:
            f *= k
    return f


def shares_basis(splits: list[tuple[str, float]], pts: list[tuple[str, float]]) -> str:
    """股本是当时报告的数(as_reported)还是按今天口径回改过的(adjusted)。股本序列开始之后没有拆股 ⇒ none。"""
    if not pts:
        return "ambiguous"
    relevant = [(d, k) for d, k in splits if d > pts[0][0]]
    if not relevant:
        return "none"
    votes = set()
    tol = math.log(CALIB_TOL)
    for d, k in relevant:
        before = [v for pe, v in pts if pe < d]
        after = [v for pe, v in pts if pe >= d]
        if not before or not after:
            votes.add("ambiguous")
            continue
        r = after[0] / before[-1]
        votes.add("as_reported" if abs(math.log(r / k)) < tol else "adjusted" if abs(math.log(r)) < tol else "ambiguous")
    return votes.pop() if len(votes) == 1 else "ambiguous"


def _iso_week_last(cl: list[tuple[str, float, float]], start: str) -> list[tuple[str, float]]:
    """每个 ISO 周的最后一个交易日 [(日期, 原始收盘)]。"""
    last: dict[tuple[int, int], tuple[str, float]] = {}
    for d, c, _ in cl:
        if d < start:
            continue
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        last[(y, w)] = (d, c)
    return [last[k] for k in sorted(last)]


def _fx_at(fx_dates: list[str], fx_vals: list[float], d: str) -> Optional[float]:
    """美元 / 1 单位本币:d 当天或之前 7 天内最近的一个(fx 是 USD{币种} 的收盘,取倒数)。"""
    i = bisect.bisect_right(fx_dates, d) - 1
    if i < 0 or (datetime.strptime(d, "%Y-%m-%d") - datetime.strptime(fx_dates[i], "%Y-%m-%d")).days > 7:
        return None
    return 1.0 / fx_vals[i] if fx_vals[i] > 0 else None


def build_mcap(key: str, raw: list[dict], fund: dict, fx: Optional[list[tuple[str, float]]], ccy: str,
               start: str = START) -> dict[str, Any]:
    """一家公司的周频美元市值。返回 {rows, basis, calib, why}:why 非空 = 不写,原因在里面。纯函数。"""
    from datetime import timedelta
    pts = shares_points(fund)
    cl = _closes(raw)
    if not pts:
        return {"rows": [], "why": "基本面里没有每季股本"}
    if not cl:
        return {"rows": [], "why": "没有日线"}
    if ccy != "USD" and not fx:
        return {"rows": [], "why": f"{ccy} 汇率读不到"}
    fx_dates, fx_vals = [d for d, _ in fx or []], [v for _, v in fx or []]
    splits = split_events(raw)
    basis = shares_basis(splits, pts)
    if basis == "ambiguous":
        return {"rows": [], "basis": basis, "splits": splits[:4], "why": "拆股前后股本之比判不出口径"}
    adj_shares = [(pe, v * (_factor_after(pe, splits) if basis in ("as_reported", "none") else 1.0)) for pe, v in pts]
    # 校准:最新一季股本 × 最新收盘 对 EODHD 当前市值(可能是本币,也可能是美元 —— 两个都比)
    h = _num(_pick(fund, "Highlights::MarketCapitalization"))
    d_last, c_last, _ = cl[-1]
    local_now = adj_shares[-1][1] * c_last
    calib = None
    if h and h > 0:
        usd_now = local_now * (1.0 if ccy == "USD" else (_fx_at(fx_dates, fx_vals, d_last) or float("nan")))
        rs = [r for r in (local_now / h, usd_now / h) if r == r and r > 0]
        calib = min(rs, key=lambda r: abs(math.log(r))) if rs else None
        if calib is None or abs(math.log(calib)) > math.log(CALIB_TOL):
            return {"rows": [], "basis": basis, "calib": calib,
                    "why": f"与 EODHD 当前市值差 ×{calib:.2f}(换股比例或股本口径不对)" if calib else "校准算不出"}
    rows = []
    for d, c in _iso_week_last(cl, start):
        known = (datetime.strptime(d, "%Y-%m-%d") - timedelta(days=SHARES_LAG_DAYS)).strftime("%Y-%m-%d")
        sh = [v for pe, v in adj_shares if pe <= known]
        if not sh:
            continue
        fxv = 1.0 if ccy == "USD" else _fx_at(fx_dates, fx_vals, d)
        if fxv is None:
            continue
        rows.append({"key": key, "d": d, "mcap_usd": sh[-1] * (c / _factor_after(d, splits)) * fxv, "source": MCAP_SOURCE})
    if not rows:
        return {"rows": [], "basis": basis, "calib": calib, "why": "没有一周同时有已知股本与价格"}
    return {"rows": rows, "basis": basis, "calib": calib, "splits": len(splits), "why": None}


async def refresh_mcap(candidates: Optional[list] = None, start: str = START, concurrency: int = 4) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.market.tradfi_history import split_code
    from src.data.universe.world50 import CANDIDATES
    todo = candidates if candidates is not None else [c for c in CANDIDATES if c.cls == "equity"]
    sem = asyncio.Semaphore(concurrency)

    async def fetch(c):
        async with sem:
            try:
                t, ex = split_code(c.code)
                fund = await dl.get_eodhd_share_history(t, ex)
                raw = await dl.get_eodhd_eod_range(t, ex, start)
            except Exception as e:  # noqa: BLE001 — 一家取不到不连坐整轮,原因带回去
                return c, None, None, None, f"{type(e).__name__}: {str(e)[:140]}"
            ccy = str(_pick(fund, "General::CurrencyCode") or EXCHANGE_CCY.get(ex) or "").upper()
            return c, fund, raw, ccy, None

    got = await asyncio.gather(*[fetch(c) for c in todo])
    fx: dict[str, list[tuple[str, float]]] = {}
    for ccy in sorted({g[3] for g in got if g[3] and g[3] != "USD"}):
        try:
            fx[ccy] = [(d, c) for d, c, _ in _closes(await dl.get_eodhd_eod_range(f"USD{ccy}", "FOREX", start))]
        except Exception:  # noqa: BLE001 — 某个币种读不到:用它的公司各自报「汇率读不到」
            fx[ccy] = []
    res = []
    for c, fund, raw, ccy, err in got:
        if err:
            res.append({"key": c.key, "ok": False, "why": err})
            continue
        b = build_mcap(c.key, raw, fund, fx.get(ccy), ccy or "?", start)
        if b["why"]:
            res.append({"key": c.key, "ok": False, "why": b["why"], "basis": b.get("basis"), "calib": b.get("calib")})
            continue
        w = await supabase_upsert_table("world50_mcap_weekly", b["rows"], on_conflict="key,d,source")
        res.append({"key": c.key, "ok": w.ok, "rows": len(b["rows"]), "first": b["rows"][0]["d"], "basis": b["basis"],
                    **({} if w.ok else {"why": w.why[:140]})})
    ok = [r for r in res if r.get("ok")]
    enough = len(ok) >= max(1, math.ceil(MCAP_MIN_SHARE_OK * len(todo)))
    return {"ok": enough, "companies": len(todo), "companies_ok": len(ok),
            "rows": sum(int(r.get("rows") or 0) for r in ok),
            "earliest": min((r["first"] for r in ok), default=None),
            "fx": {k: len(v) for k, v in fx.items()},
            "failed": [{k: r.get(k) for k in ("key", "why", "basis", "calib") if r.get(k) is not None}
                       for r in res if not r.get("ok")][:40]}


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

RERUN_AFTER_DAYS = 6
LOOP_NAME = "_world50_history_loop"


async def _recent_ok_parts(now: Optional[datetime] = None) -> set[str]:
    """6 天内已经真跑成了的段。每次部署都会重启循环 —— 不拦的话,一天几次部署就是一天几次整段重写 29 万行日线。
    **只认真跑成的,不认「跳过」**:否则跳过会一轮轮续期,永远不再真跑。读不到 ⇒ 空集(全跑)。"""
    from src.data.signals.hl_book_daily import _supabase_get
    now = now or datetime.now(timezone.utc)
    try:
        rows = await _supabase_get(f"loop_attempt?select=at,detail&loop_name=eq.{LOOP_NAME}&order=at.desc&limit=20")
    except Exception:  # noqa: BLE001
        return set()
    done: set[str] = set()
    for r in rows or []:
        try:
            at = datetime.fromisoformat(str(r.get("at")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if (now - at).total_seconds() > RERUN_AFTER_DAYS * 86400:
            break
        for name, p in (r.get("detail") or {}).items():
            if isinstance(p, dict) and p.get("ok") and not p.get("skipped"):
                done.add(name)
    return done


def _brief(name: str, r: dict) -> dict:
    keep = {"prices": ("symbols", "symbols_ok", "written", "elapsed_s"),
            "mcap": ("companies", "companies_ok", "rows", "earliest", "fx"),
            "onchain_forms": ("tokens", "by_type", "matched", "candidates_with_form", "with_issuer")}[name]
    out = {"ok": bool(r.get("ok")), **{k: r.get(k) for k in keep if k in r}}
    if r.get("skipped"):
        out["skipped"] = r["skipped"]
    fails = r.get("failed") or r.get("issuer_failed")
    if fails:
        out["failed"] = fails[:10]
    if r.get("why") or (not r.get("ok") and r.get("reason")):
        out["why"] = str(r.get("why") or r.get("reason"))[:200]
    return out


def _say(name: str, r: dict) -> str:
    if r.get("skipped"):
        return {"prices": "日线", "mcap": "市值", "onchain_forms": "链上形式"}[name] + " 跳过(6 天内已成)"
    if name == "prices":
        return f"日线 {r.get('symbols_ok')}/{r.get('symbols')}"
    if name == "mcap":
        return f"市值 {r.get('companies_ok')}/{r.get('companies')}"
    return f"链上形式 {r.get('tokens')} 条、对上 {r.get('candidates_with_form')} 个候选"


async def run_week(force: bool = False) -> dict[str, Any]:
    from src.data.market.tradfi_history import run_once
    steps = (("prices", run_once), ("mcap", refresh_mcap), ("onchain_forms", discover_onchain_forms))
    done = set() if force else await _recent_ok_parts()
    parts: dict[str, dict] = {}
    for name, fn in steps:
        if name in done:
            parts[name] = {"ok": True, "skipped": f"{RERUN_AFTER_DAYS} 天内已成"}
            continue
        try:
            parts[name] = await fn()
        except Exception as e:  # noqa: BLE001 — 一段炸了,后面的照跑,炸的原因带回去
            parts[name] = {"ok": False, "why": f"{type(e).__name__}: {str(e)[:160]}"}
    bad = [n for n, r in parts.items() if not r.get("ok")]
    reason = " · ".join(_say(n, r) for n, r in parts.items())
    if bad:
        reason = "没成的段:" + "、".join(bad) + " —— " + reason
    return {"ok": not bad, "refused": bool(parts["prices"].get("refused")), "reason": reason,
            "parts": {n: _brief(n, r) for n, r in parts.items()}}
