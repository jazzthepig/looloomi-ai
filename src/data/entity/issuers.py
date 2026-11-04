"""发行方 / 决策层(Jazz 11-04「今天开始」;HIGH_DIM_ONTOLOGY §5 的 Entity / Decision —— 内核最深的对象,此前从未建表)。

## 为什么

我们一直按 symbol 记账。可 Circle 发 USDC 也发 CRCL,Hyperliquid 发 HYPE 也开场所,Sky 发 SKY 也发 USDS,Strategy 的
MSTR 是 BTC 的壳 —— 「对小股东好不好」是**发行方**的属性,不是某个 symbol 的。没有发行方这个对象,T-218「轨道公司是
代币 β 的更窄表达」只能按 ticker 说,CIS v2.1 的核心维度也无处挂。

## 两张表

- `issuer_entities`(登记表,**代码是真源**,每轮同步进库):id · name · kind(protocol / foundation / company / stablecoin_issuer /
  venue)· instruments[{symbol, cls: token|equity|stablecoin|venue}] · coingecko ids · defillama gecko_id · sec ticker · confidence
  (verified / assumed)· note。**assumed = 我按公开常识写的,等 lane 逐条带出处核验(T-230)。**
- `issuer_decisions`(只追加,按 id upsert):发行方对持有人**做了什么**,带日期 —— 三个写入端,全部从已记的表派生,不新接源:
  1. `issuer_fundamentals_quarterly`:每个 (symbol, period) ⇒ `buyback` / `dividend`(> 0 才写)/ `share_dilution`(摊薄股数
     环比 > +1% 才写),**ts = 披露日 `filed`**(时点);
  2. `events`:kind ∈ listing / delisting / perp_listing / perp_delisting,symbols 命中登记表的代币 ⇒ `venue_listing` / `venue_delisting`;
  3. `treatment_daily`(每周一):`payout_class`(pays / keeps / none,value = holders_share)与 `token_dilution`(supply_growth_30d > 2%)。
  每条:id(来源 + 外部键的 sha1)· entity_id · ts · kind · symbols · value · payload · source。

判活:`select kind, count(*), max(ts) from issuer_decisions group by 1`;`select count(*) from issuer_entities`。
"""
from __future__ import annotations

import datetime as dt
import hashlib
from typing import Any, Optional

ENTITIES_TABLE = "issuer_entities"
DECISIONS_TABLE = "issuer_decisions"
WRITES_TABLES = (ENTITIES_TABLE, DECISIONS_TABLE)
WRITES_COLUMNS = {
    "issuer_entities": ("id", "name", "kind", "instruments", "coingecko_ids", "sec_ticker", "confidence", "note", "code_ref"),
    "issuer_decisions": ("id", "entity_id", "ts", "kind", "symbols", "value", "payload", "source", "code_ref"),
}
CODE_REF = "issuers v1 (11-04)"
LOOP_NAME = "_issuer_decisions_loop"
DILUTION_SHARES_PCT = 0.01
DILUTION_SUPPLY_PCT = 0.02


def _e(id_: str, name: str, kind: str, instruments: list[tuple[str, str]], coingecko: tuple[str, ...] = (),
       sec: Optional[str] = None, confidence: str = "assumed", note: str = "") -> dict:
    return {"id": id_, "name": name, "kind": kind, "instruments": [{"symbol": s, "cls": c} for s, c in instruments],
            "coingecko_ids": list(coingecko), "sec_ticker": sec, "confidence": confidence, "note": note, "code_ref": CODE_REF}


#: 登记表 v1 —— CIS 25 个加密名字 + 10 家轨道公司 + 稳定币发行方。kind:protocol = 没有单一发行方(BTC);
#: foundation = 基金会 / DAO 主导;company = 公司;stablecoin_issuer;venue = 交易场所。confidence=assumed 待 T-230 核验。
ENTITIES: tuple[dict, ...] = (
    _e("bitcoin", "Bitcoin", "protocol", [("BTC", "token")], ("bitcoin",), confidence="verified", note="无发行方;决策流为空是对的"),
    _e("ethereum-foundation", "Ethereum Foundation", "foundation", [("ETH", "token")], ("ethereum",)),
    _e("solana-foundation", "Solana Foundation / Solana Labs", "foundation", [("SOL", "token")], ("solana",)),
    _e("binance", "Binance", "venue", [("BNB", "token"), ("BINANCE", "venue")], ("binancecoin",), note="BNB 的发行与场所同一主体"),
    _e("ripple", "Ripple Labs", "company", [("XRP", "token"), ("RLUSD", "stablecoin")], ("ripple",)),
    _e("cardano-iog", "Cardano (IOG / Cardano Foundation)", "foundation", [("ADA", "token")], ("cardano",)),
    _e("ava-labs", "Ava Labs / Avalanche Foundation", "foundation", [("AVAX", "token")], ("avalanche-2",)),
    _e("web3-foundation", "Web3 Foundation / Parity", "foundation", [("DOT", "token")], ("polkadot",)),
    _e("near-foundation", "NEAR Foundation", "foundation", [("NEAR", "token")], ("near",)),
    _e("sui-foundation", "Sui Foundation / Mysten Labs", "foundation", [("SUI", "token")], ("sui",)),
    _e("aptos-foundation", "Aptos Foundation / Aptos Labs", "foundation", [("APT", "token")], ("aptos",)),
    _e("hyperliquid", "Hyperliquid (Hyper Foundation / Hyperliquid Labs)", "venue", [("HYPE", "token"), ("HYPERLIQUID", "venue"), ("USDH", "stablecoin")],
       ("hyperliquid",), note="代币 + 场所 + 稳定币同一主体;分配率 1.0 来自回购"),
    _e("arbitrum", "Arbitrum DAO / Arbitrum Foundation / Offchain Labs", "foundation", [("ARB", "token")], ("arbitrum",), note="有收入不分:在建国库"),
    _e("optimism", "Optimism Foundation / OP Labs", "foundation", [("OP", "token")], ("optimism",), note="有收入不分:在建国库"),
    _e("polygon-labs", "Polygon Labs / Polygon Foundation", "foundation", [("POL", "token")], ("polygon-ecosystem-token",)),
    _e("starkware", "StarkWare / Starknet Foundation", "foundation", [("STRK", "token")], ("starknet",)),
    _e("uniswap", "Uniswap Labs / Uniswap Foundation", "foundation", [("UNI", "token")], ("uniswap",), note="费用开关 2025 起分给持有人"),
    _e("aave", "Aave Labs / Aave DAO", "foundation", [("AAVE", "token"), ("GHO", "stablecoin")], ("aave",), note="DeFiLlama 口径 holders 0;实际有回购计划,待核"),
    _e("lido", "Lido DAO", "foundation", [("LDO", "token"), ("STETH", "token")], ("lido-dao",)),
    _e("pendle", "Pendle", "foundation", [("PENDLE", "token")], ("pendle",)),
    _e("chainlink-labs", "Chainlink Labs", "company", [("LINK", "token")], ("chainlink",)),
    _e("injective", "Injective Labs / Foundation", "foundation", [("INJ", "token")], ("injective-protocol",)),
    _e("celestia", "Celestia Foundation / Labs", "foundation", [("TIA", "token")], ("celestia",)),
    _e("ondo", "Ondo Finance", "company", [("ONDO", "token"), ("USDY", "stablecoin")], ("ondo-finance",)),
    _e("sky", "Sky (ex-Maker)", "foundation", [("SKY", "token"), ("MKR", "token"), ("USDS", "stablecoin"), ("DAI", "stablecoin")], ("sky", "maker"),
       note="MKR 1 : 24,000 换 SKY;ohlcv_daily 的 SKY 只有 15 行,价格在 asset_mcap_daily"),
    # 轨道公司(研究宇宙;T-218 / T-219)
    _e("circle", "Circle Internet Group", "stablecoin_issuer", [("CRCL", "equity"), ("USDC", "stablecoin")], sec="CRCL", note="HL 现货 CRCL 是冒名币;真股在券商"),
    _e("coinbase", "Coinbase Global", "venue", [("COIN", "equity"), ("COINBASE", "venue")], sec="COIN", note="USDC 收入分成方"),
    _e("robinhood", "Robinhood Markets", "venue", [("HOOD", "equity")], sec="HOOD"),
    _e("galaxy", "Galaxy Digital", "company", [("GLXY", "equity")], sec="GLXY"),
    _e("strategy", "Strategy (ex-MicroStrategy)", "company", [("MSTR", "equity")], sec="MSTR", note="BTC 国库壳;β(BTC) 1.42(T-219)"),
    _e("paypal", "PayPal Holdings", "company", [("PYPL", "equity"), ("PYUSD", "stablecoin")], sec="PYPL", note="PYUSD 由 Paxos 发行、PayPal 品牌"),
    _e("block", "Block, Inc.", "company", [("XYZ", "equity")], sec="XYZ"),
    _e("bullish", "Bullish", "venue", [("BLSH", "equity"), ("BULLISH", "venue")], sec="BLSH", note="SEC 无 CIK(外国发行人)"),
    _e("figure", "Figure Technology Solutions", "company", [("FIGR", "equity")], sec="FIGR"),
    _e("gemini", "Gemini Space Station", "venue", [("GEMI", "equity"), ("GEMINI", "venue")], sec="GEMI"),
    _e("tether", "Tether", "stablecoin_issuer", [("USDT", "stablecoin"), ("XAUT", "token")], note="收入 $5.2 亿 / 30 日(DeFiLlama),持有人 0"),
    _e("paxos", "Paxos", "stablecoin_issuer", [("PYUSD", "stablecoin"), ("USDG", "stablecoin")], note="PYUSD 实际发行方"),
)


def entity_by_symbol() -> dict[str, str]:
    """symbol(大写)→ entity id;一个 symbol 只归一个发行方(PYUSD 归 paxos,见 note)。"""
    out: dict[str, str] = {}
    for e in ENTITIES:
        for ins in e["instruments"]:
            sym = ins["symbol"].upper()
            if sym not in out or (ins["cls"] == "stablecoin" and e["kind"] == "stablecoin_issuer"):
                out[sym] = e["id"]            # 稳定币归实际发行方(PYUSD → paxos,不归 paypal)
    return out


def entity_by_gecko() -> dict[str, str]:
    return {g: e["id"] for e in ENTITIES for g in e["coingecko_ids"]}


def did(source: str, external: str) -> str:
    return hashlib.sha1(f"{source}:{external}".encode("utf-8")).hexdigest()[:24]


def _f(x: Any) -> Optional[float]:
    try:
        v = None if x is None else float(x)
    except (TypeError, ValueError):
        return None
    return v if v is None or v == v else None


def decisions_from_fundamentals(rows: list[dict], by_symbol: dict[str, str]) -> list[dict]:
    """纯函数。issuer_fundamentals_quarterly 行 → 回购 / 分红 / 摊薄股数稀释;ts = 披露日。"""
    out = []
    by_sym: dict[str, list[dict]] = {}
    for r in rows:
        by_sym.setdefault(str(r.get("symbol") or "").upper(), []).append(r)
    for sym, rs in by_sym.items():
        ent = by_symbol.get(sym)
        if not ent:
            continue
        rs = sorted(rs, key=lambda r: str(r.get("period") or ""))
        prev_sh = None
        for r in rs:
            per, filed = str(r.get("period") or ""), str(r.get("filed") or "")[:10]
            if not per or not filed:
                continue
            base = {"entity_id": ent, "ts": f"{filed}T00:00:00+00:00", "symbols": [sym], "source": "sec_edgar", "code_ref": CODE_REF,
                    "payload": {"period": per}}
            bb, dv, sh = _f(r.get("buybacks")), _f(r.get("dividends")), _f(r.get("diluted_shares"))
            if bb and bb > 0:
                out.append({**base, "id": did("fund", f"{sym}:{per}:buyback"), "kind": "buyback", "value": bb})
            if dv and dv > 0:
                out.append({**base, "id": did("fund", f"{sym}:{per}:dividend"), "kind": "dividend", "value": dv})
            if sh and prev_sh and prev_sh > 0 and sh / prev_sh - 1 > DILUTION_SHARES_PCT:
                out.append({**base, "id": did("fund", f"{sym}:{per}:dilution"), "kind": "share_dilution", "value": round(sh / prev_sh - 1, 5),
                            "payload": {"period": per, "shares": sh, "prev_shares": prev_sh}})
            if sh:
                prev_sh = sh
    return out


def decisions_from_events(rows: list[dict], by_symbol: dict[str, str]) -> list[dict]:
    """纯函数。events(上 / 下币)里命中登记表代币的 ⇒ venue_listing / venue_delisting。"""
    out = []
    for r in rows:
        kind = str(r.get("kind") or "")
        if kind not in ("listing", "delisting", "perp_listing", "perp_delisting"):
            continue
        for sym in r.get("symbols") or []:
            ent = by_symbol.get(str(sym).upper())
            if not ent:
                continue
            out.append({"id": did("event", f"{r.get('id')}:{sym}"), "entity_id": ent, "ts": r.get("ts"),
                        "kind": "venue_delisting" if "delisting" in kind else "venue_listing", "symbols": [str(sym).upper()],
                        "value": None, "payload": {"event": r.get("id"), "venue": r.get("source"), "scope": ((r.get("payload") or {}).get("scope")),
                                                   "perp": kind.startswith("perp")},
                        "source": f"events:{r.get('source')}", "code_ref": CODE_REF})
    return out


def decisions_from_treatment(rows: list[dict], by_symbol: dict[str, str], d: str) -> list[dict]:
    """纯函数。treatment_daily 某一天(周一)→ payout_class(有协议收入的才写)与 token_dilution(> 2% / 30 日)。"""
    out = []
    for r in rows:
        sym = str(r.get("symbol") or "").upper()
        ent = by_symbol.get(sym)
        if not ent:
            continue
        rev, share, dil = _f(r.get("revenue_30d")), _f(r.get("holders_share")), _f(r.get("supply_growth_30d"))
        base = {"entity_id": ent, "ts": f"{d}T00:00:00+00:00", "symbols": [sym], "source": "treatment_daily", "code_ref": CODE_REF}
        if rev is not None and share is not None:
            out.append({**base, "id": did("treat", f"{sym}:{d}:payout"), "kind": "payout_class", "value": share,
                        "payload": {"class": "pays" if share >= 0.5 else "keeps", "revenue_30d": rev, "holders_30d": _f(r.get("holders_30d"))}})
        if dil is not None and dil > DILUTION_SUPPLY_PCT:
            out.append({**base, "id": did("treat", f"{sym}:{d}:dilution"), "kind": "token_dilution", "value": round(dil, 5),
                        "payload": {"supply": _f(r.get("supply"))}})
    return out


async def sync_entities() -> int:
    from src.api.store import supabase_upsert_table
    rows = [{k: e.get(k) for k in WRITES_COLUMNS[ENTITIES_TABLE]} for e in ENTITIES]
    w = await supabase_upsert_table(ENTITIES_TABLE, rows, on_conflict="id")
    return len(rows) if w else 0


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    by_symbol = entity_by_symbol()
    n_ent = await sync_entities()
    decisions: list[dict] = []
    errors: list[str] = []
    try:
        fund = await _read_all("issuer_fundamentals_quarterly", {"select": "symbol,period,filed,buybacks,dividends,diluted_shares",
                                                                "order": "symbol.asc,period.asc"})
        decisions += decisions_from_fundamentals(fund, by_symbol)
    except Exception as e:                                                # noqa: BLE001
        errors.append(f"fundamentals: {type(e).__name__}")
    try:
        since = (now - dt.timedelta(days=400)).isoformat()
        ev = await _read_all("events", {"select": "id,ts,kind,source,symbols,payload", "ts": f"gte.{since}",
                                        "kind": "in.(listing,delisting,perp_listing,perp_delisting)"})
        decisions += decisions_from_events(ev, by_symbol)
    except Exception as e:                                                # noqa: BLE001
        errors.append(f"events: {type(e).__name__}")
    try:
        d = now.date() - dt.timedelta(days=1)
        monday = (d - dt.timedelta(days=d.weekday())).isoformat()        # 本周一(含当天)
        tr = await _read_all("treatment_daily", {"select": "symbol,revenue_30d,holders_30d,holders_share,supply_growth_30d,supply",
                                                 "d": f"eq.{monday}"})
        decisions += decisions_from_treatment(tr, by_symbol, monday)
    except Exception as e:                                                # noqa: BLE001
        errors.append(f"treatment: {type(e).__name__}")
    decisions = list({x["id"]: x for x in decisions if x.get("ts")}.values())
    written = 0
    if decisions:
        w = await supabase_upsert_table(DECISIONS_TABLE, [{k: x.get(k) for k in WRITES_COLUMNS[DECISIONS_TABLE]} for x in decisions],
                                        on_conflict="id")
        if not w:
            return {"ok": False, "why": f"写 {DECISIONS_TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}", "errors": errors}
        written = len(decisions)
    kinds: dict[str, int] = {}
    for x in decisions:
        kinds[x["kind"]] = kinds.get(x["kind"], 0) + 1
    return {"ok": not errors or written > 0, "entities": n_ent, "written": written, "kinds": kinds, "errors": errors,
            "why": f"登记 {n_ent} 家;决策 {written} 条 {kinds}" + (f";错 {errors}" if errors else "")}
