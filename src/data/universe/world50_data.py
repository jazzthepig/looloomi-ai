"""World50 的两份输入:候选的历史市值(按时点排名)与链上可持有的形式(资格)—— T-098 第二部分。

## 历史市值 → `world50_mcap_weekly`

- 公司:**SEC EDGAR 报告的股本 × 原始收盘**(Jazz 10-14 定;EODHD 基本面与历史市值我们的套餐都没有,403)。
  只覆盖在 SEC 申报的公司(美国公司 + 美国上市的外国公司);本地上市的公司没有 —— 它们大多也没有链上形式。
  股本有三种口径:封面股数(`dei:EntityCommonStockSharesOutstanding`)、期末股数(`us-gaap:CommonStockSharesOutstanding`)、
  每季加权平均基本股数(`us-gaap:WeightedAverageNumberOfSharesOutstandingBasic`)。多股类公司按类别报的不在这个接口里,
  有的公司某种口径只报到某一年 —— 所以**选最后一次报送最晚的口径**(差 120 天内按上面的顺序),
  最后一次报送比最新价格早 400 天以上 ⇒ 股数太旧,不写。换过申报主体的接上旧 CIK(`PREDECESSOR_CIKS`)。
  **按报送日(filed)才算已知**,同一期取最早报送的那一份(当时的原始报告,不用后来的重述)。
  拆股:报告里的股数是**报送日那天的口径**(拆股后报送的会按新口径重述),所以股数 × 报送日之后的拆股系数、
  价格 ÷ 当天之后的拆股系数,统一到今天的口径;拆股从「原始价 / 复权价」单日跳 > 20% 认。
  ADR:外国公司报的是普通股数,除以每份 ADR 对应的普通股数(`ADR_ORD_PER_ADS`,有生效日);换股比例没核实的不写。
  守卫:离中位数 100 倍以上的点当录入错误丢掉;单点错(离两边都 > 1.5 倍、两边彼此一致)丢那个点;
  相邻两点股数跳 50% 以上(并购、换股比例变了)⇒ 只用跳之后的段;跳之后只剩最新一个点 ⇒ 不写(口径待核)。
  周频(每周最后一个交易日),2015 起。
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

SPLIT_JUMP = 1.2              # 原始价 / 复权价 单日跳超过这个倍数 ⇒ 拆股
SHARE_JUMP = 1.5              # 相邻两点股数(今天口径)跳超过这个倍数 ⇒ 并购 / 换股比例变了,只用跳之后的段
OUTLIER_X = 100               # 离中位数这么多倍 ⇒ 录入错误(实测 BRK 有几期多乘了 100 万)
#: v2(10-15):v1 首跑里 MA / BRK-B / BABA 的行是错的,而拒写不会删掉旧行 —— 换 source 名,读者只认 v2,
#: v1 的行留着当记录(要清由 Jazz 定)。以后算法改到会改变已写的值,也照此升版本。
MCAP_SOURCE = "sec_shares_x_close_v2"
SPIKE_NEIGHBORS = 1.1          # 一个点离两边都 > 1.5 倍、两边彼此在 1.1 倍内 ⇒ 单点错,丢这个点(不截断历史)
STALE_DAYS = 400              # 选中的口径最后一次报送早于最新价格这么多天 ⇒ 股数是旧的,不写
#: 三种口径,按优先级。封面股数(某天的实际股数)> 资产负债表期末股数 > 每季加权平均基本股数。
SEC_TAGS = {"dei": ("dei", "EntityCommonStockSharesOutstanding", False),
            "cso": ("us-gaap", "CommonStockSharesOutstanding", False),
            "wavg": ("us-gaap", "WeightedAverageNumberOfSharesOutstandingBasic", True)}
#: 换了申报主体(控股公司重组)的公司:旧 CIK 的历史接在前面。实测 2026 年 XOM 归到新的 ExxonMobil Holdings(CIK 2115436)。
PREDECESSOR_CIKS: dict[str, list[int]] = {"XOM": [34088]}

#: 每份 ADR 对应几股普通股,[(生效日, 比例)],旧 → 新。只收核过的;外国公司没在表里也不在 UNVERIFIED_ADR 里 ⇒ 按 1:1。
ADR_ORD_PER_ADS: dict[str, list[tuple[str, float]]] = {
    "TSM": [("1997-01-01", 5.0)],
    "BABA": [("2014-01-01", 1.0), ("2019-07-30", 8.0)],   # 2019 普通股一拆八,ADR 改为 1 份 = 8 股
    "HSBC": [("1999-01-01", 5.0)],
    "BHP": [("2001-01-01", 2.0)],
    "SHEL": [("2005-01-01", 2.0)],
}
#: 换股比例我没核实 / 中途改过而我不确定生效日的 —— 不写,不猜。
UNVERIFIED_ADR = {"AZN", "TM", "TCEHY"}


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


def sec_points(concept: Any, duration: bool) -> list[tuple[str, str, float]]:
    """SEC companyconcept → [(期末 / 封面日, 报送日, 股数)],按期末排序。纯函数。
    同一期多份报送取**最早**的(原始报告);`duration=True`(加权平均)只收一季(80–100 天)或一年(350–380 天),
    同一期末季度优先于年度。"""
    concepts = concept if isinstance(concept, list) else [concept]
    facts = []
    for c in concepts:
        sh = (((c or {}).get("units") or {}).get("shares")) or []
        facts.extend(sh if isinstance(sh, list) else [])
    best: dict[str, tuple[str, float, int]] = {}
    for f in facts:
        end, filed, v = str(f.get("end") or "")[:10], str(f.get("filed") or "")[:10], _num(f.get("val"))
        if len(end) != 10 or len(filed) != 10 or not v or v <= 0:
            continue
        rank = 0
        if duration:
            try:
                days = (datetime.strptime(end, "%Y-%m-%d") - datetime.strptime(str(f.get("start"))[:10], "%Y-%m-%d")).days
            except ValueError:
                continue
            if 80 <= days <= 100:
                rank = 0
            elif 350 <= days <= 380:
                rank = 1
            else:
                continue
        cur = best.get(end)
        if cur is None or (rank, filed) < (cur[2], cur[0]):
            best[end] = (filed, v, rank)
    return [(e, best[e][0], best[e][1]) for e in sorted(best)]


def _adr_ratio(key: str, d: str) -> float:
    r = 1.0
    for eff, x in ADR_ORD_PER_ADS.get(key, []):
        if eff <= d:
            r = x
    return r


def clean_shares(key: str, pts: list[tuple[str, str, float]], splits: list[tuple[str, float]]
                 ) -> tuple[list[tuple[str, float]], list[str], Optional[str]]:
    """[(已知日 = 报送日, 今天口径的股数)]、备注、拒绝原因。纯函数。
    今天口径 = 报告股数 ÷ 当时 ADR 比例 × 报送日之后的拆股系数。依次:去掉离中位数 100 倍以上的录入错误;
    去掉单点错(离两边都 > 1.5 倍、两边彼此在 1.1 倍内);相邻跳 50% 以上 ⇒ 只留最后一跳之后的段 ——
    **但如果留下的只有最新一个点,就不写**:没法分辨是公司真变了还是最新一期换了口径(实测 BABA 2026 年报)。"""
    notes: list[str] = []
    if not pts:
        return [], notes, None
    vals = sorted(v for _, _, v in pts)
    med = vals[len(vals) // 2]
    kept = [(e, f, v) for e, f, v in pts if med / OUTLIER_X <= v <= med * OUTLIER_X]
    if len(kept) < len(pts):
        notes.append(f"丢掉 {len(pts) - len(kept)} 个录入错误点")
    adj = sorted((f, v / _adr_ratio(key, f) * _factor_after(f, splits)) for e, f, v in kept)
    i = 1
    while 0 < i < len(adj) - 1:
        a, b, c = adj[i - 1][1], adj[i][1], adj[i + 1][1]
        if max(b / a, a / b) > SHARE_JUMP and max(b / c, c / b) > SHARE_JUMP and max(a / c, c / a) <= SPIKE_NEIGHBORS:
            notes.append(f"{adj[i][0]} 单点错 ×{b / a:.2f},丢掉")
            adj.pop(i)
            continue
        i += 1
    start = 0
    for i in range(1, len(adj)):
        r = adj[i][1] / adj[i - 1][1]
        if r > SHARE_JUMP or r < 1 / SHARE_JUMP:
            start = i
            notes.append(f"{adj[i][0]} 股数跳 ×{r:.2f},只用之后的段")
    if start and len(adj) - start < 2:
        return [], notes, f"最新一期股数跳 ×{adj[start][1] / adj[start - 1][1]:.2f},口径待核,不写"
    return adj[start:], notes, None


def _iso_week_last(cl: list[tuple[str, float, float]], start: str) -> list[tuple[str, float]]:
    """每个 ISO 周的最后一个交易日 [(日期, 原始收盘)]。"""
    last: dict[tuple[int, int], tuple[str, float]] = {}
    for d, c, _ in cl:
        if d < start:
            continue
        y, w, _ = datetime.strptime(d, "%Y-%m-%d").isocalendar()
        last[(y, w)] = (d, c)
    return [last[k] for k in sorted(last)]


def choose_source(sources: dict[str, Any]) -> tuple[Optional[str], list[tuple[str, str, float]]]:
    """三种口径里选**最新还在报**的那一个:最后一次报送最晚者胜;相差 120 天内按 dei > cso > wavg。
    实测 MA 的封面股数只到 2010(之后按类别报),只按优先级选会用 16 年前的股数。纯函数。"""
    cand = {}
    for name in ("dei", "cso", "wavg"):
        pts = sec_points(sources.get(name), duration=SEC_TAGS[name][2])
        if len(pts) >= 2:
            cand[name] = pts
    if not cand:
        return None, []
    latest = {n: max(f for _, f, _ in p) for n, p in cand.items()}
    top = max(latest.values())
    for name in ("dei", "cso", "wavg"):
        if name in cand and (datetime.strptime(top, "%Y-%m-%d") - datetime.strptime(latest[name], "%Y-%m-%d")).days <= 120:
            return name, cand[name]
    return None, []


def build_mcap(key: str, raw: list[dict], sources: dict[str, Any], start: str = START) -> dict[str, Any]:
    """一家公司的周频美元市值(美国上市,价格本来就是美元)。sources = {dei / cso / wavg: SEC 概念(或多个 CIK 的列表)}。
    返回 {rows, src, notes, why}:why 非空 = 不写。纯函数。"""
    if key in UNVERIFIED_ADR:
        return {"rows": [], "why": "ADR 换股比例未核实,不写"}
    cl = _closes(raw)
    if not cl:
        return {"rows": [], "why": "没有日线"}
    src, pts = choose_source(sources)
    if not pts:
        return {"rows": [], "why": "SEC 里没有可用的股数(三种口径都没有)"}
    last_filed = max(f for _, f, _ in pts)
    if (datetime.strptime(cl[-1][0], "%Y-%m-%d") - datetime.strptime(last_filed, "%Y-%m-%d")).days > STALE_DAYS:
        return {"rows": [], "src": src, "why": f"股数停在 {last_filed}({src}),太旧,不写"}
    splits = split_events(raw)
    shares, notes, refuse = clean_shares(key, pts, splits)
    if refuse:
        return {"rows": [], "src": src, "notes": notes, "why": refuse}
    known_dates = [f for f, _ in shares]
    rows = []
    for d, c in _iso_week_last(cl, start):
        i = bisect.bisect_right(known_dates, d) - 1
        if i < 0:
            continue
        rows.append({"key": key, "d": d, "mcap_usd": shares[i][1] * (c / _factor_after(d, splits)), "source": MCAP_SOURCE})
    if not rows:
        return {"rows": [], "src": src, "notes": notes, "why": "没有一周同时有已知股数与价格"}
    return {"rows": rows, "src": src, "notes": notes, "latest_usd": rows[-1]["mcap_usd"], "why": None}


async def refresh_mcap(candidates: Optional[list] = None, start: str = START, concurrency: int = 4) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market import data_layer as dl
    from src.data.market.tradfi_history import split_code
    from src.data.universe.world50 import CANDIDATES
    pool = candidates if candidates is not None else [c for c in CANDIDATES if c.cls == "equity"]
    todo = [c for c in pool if c.code.endswith(".US")]
    skipped = [c.key for c in pool if not c.code.endswith(".US")]
    try:
        ciks = await dl.get_sec_ticker_ciks()
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "why": f"SEC 代码表读不到:{type(e).__name__}: {str(e)[:160]}", "companies": len(todo)}
    sem = asyncio.Semaphore(concurrency)

    async def one(c):
        cik = ciks.get(c.key.upper())
        if cik is None:
            return {"key": c.key, "ok": False, "why": "不在 SEC 申报公司表里"}
        async with sem:
            try:
                t, ex = split_code(c.code)
                sources: dict[str, list] = {}
                for k_cik in PREDECESSOR_CIKS.get(c.key, []) + [cik]:
                    for name, (tax, tag, _) in SEC_TAGS.items():
                        got = await dl.get_sec_concept(k_cik, tax, tag)
                        await asyncio.sleep(0.15)   # SEC 限速 10 次 / 秒,4 路并发留足余量
                        if got:
                            sources.setdefault(name, []).append(got)
                raw = await dl.get_eodhd_eod_range(t, ex, start)
            except Exception as e:  # noqa: BLE001 — 一家取不到不连坐整轮,原因带回去
                return {"key": c.key, "ok": False, "why": f"{type(e).__name__}: {str(e)[:140]}"}
        b = build_mcap(c.key, raw, sources, start)
        if b["why"]:
            return {"key": c.key, "ok": False, "why": b["why"], "notes": b.get("notes")}
        w = await supabase_upsert_table("world50_mcap_weekly", b["rows"], on_conflict="key,d,source")
        return {"key": c.key, "ok": w.ok, "rows": len(b["rows"]), "first": b["rows"][0]["d"], "src": b["src"],
                "latest_bn": round(b["latest_usd"] / 1e9, 1), "notes": b["notes"],
                **({} if w.ok else {"why": w.why[:140]})}

    res = await asyncio.gather(*[one(c) for c in todo])
    ok = [r for r in res if r.get("ok")]
    enough = len(ok) >= max(1, math.ceil(MCAP_MIN_SHARE_OK * len(todo)))
    return {"ok": enough, "companies": len(todo), "companies_ok": len(ok), "not_sec_listed": skipped,
            "rows": sum(int(r.get("rows") or 0) for r in ok),
            "earliest": min((r["first"] for r in ok), default=None),
            "src": {n: sorted(r["key"] for r in ok if r.get("src") == n) for n in ("cso", "wavg")},
            "latest_bn": {r["key"]: r["latest_bn"] for r in ok},
            "notes": {r["key"]: r["notes"] for r in res if r.get("notes")},
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

RERUN_AFTER_DAYS = 6
LOOP_NAME = "_world50_history_loop"
#: 某一段的算法改了就把它的版本加一:旧版本跑成的不算「已成」,下次部署会重跑这一段(没写版本的旧记录算 1)。
PART_VERSIONS = {"prices": 1, "mcap": 2, "onchain_forms": 1}


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
            if (isinstance(p, dict) and p.get("ok") and not p.get("skipped")
                    and p.get("v", 1) == PART_VERSIONS.get(name)):
                done.add(name)
    return done


def _brief(name: str, r: dict) -> dict:
    keep = {"prices": ("symbols", "symbols_ok", "written", "elapsed_s"),
            "mcap": ("companies", "companies_ok", "rows", "earliest", "src", "not_sec_listed", "notes"),
            "onchain_forms": ("tokens", "by_type", "matched", "candidates_with_form", "with_issuer")}[name]
    out = {"ok": bool(r.get("ok")), "v": PART_VERSIONS[name], **{k: r.get(k) for k in keep if k in r}}
    if r.get("skipped"):
        out["skipped"] = r["skipped"]
    fails = r.get("failed") or r.get("issuer_failed")
    if fails:
        out["failed"] = fails[:10]
    if r.get("why") or (not r.get("ok") and r.get("reason")):
        out["why"] = str(r.get("why") or r.get("reason"))[:200]
    return out


def _say(name: str, r: dict) -> str:
    label = {"prices": "日线", "mcap": "市值", "onchain_forms": "链上形式"}[name]
    if r.get("skipped"):
        return label + " 跳过(6 天内已成)"
    if not r.get("ok") and r.get("why") and not any(k in r for k in ("symbols_ok", "companies_ok", "tokens")):
        return f"{label} 没跑起来:{str(r['why'])[:80]}"
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
