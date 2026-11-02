"""轨道公司的季度基本面(SEC EDGAR XBRL,免费;11-02,`docs/UPGRADE_PATHS.md` A4)—— 「小股东待遇」在 TradFi 侧也量得到。

## 为什么

Jazz 11-02:看一家发行方 / 平台值不值得长期持有,看它给公开市场和小股东留没留可分配利润,还是内部关联交易瓜分了。
链上这一半是 protocol_revenue_daily(持币人收入占比);轨道公司(CRCL / COIN / HOOD / MSTR / PYPL / XYZ / GLXY …)这一半
在 SEC 的 XBRL 里:收入、净利、回购、分红、摊薄股数 —— **带 `filed`(披露日)**,研究按时点取值不会偷看未来。

## 做法

`https://www.sec.gov/files/company_tickers.json` 解析 ticker → CIK(BLSH / FIGR / GEMI 这类外国发行人 / 新上市不在里面 ⇒ 记「读不到」);
`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` 一家一份,取 us-gaap 概念的 **frame 值**(`CY2025Q3` 这种,SEC 已去重):
- revenue:`Revenues` → 没有就 `RevenueFromContractWithCustomerExcludingAssessedTax`
- net_income:`NetIncomeLoss`
- buybacks:`PaymentsForRepurchaseOfCommonStock`(现金流,年内累计口径 ⇒ 按 frame 季度值)
- dividends:`PaymentsOfDividends` / `PaymentsOfDividendsCommonStock`
- diluted_shares:`WeightedAverageNumberOfDilutedSharesOutstanding`
Q4 没有单独 frame 时 = 年度 frame(`CY2025`)− Q1 − Q2 − Q3(三个季度都在才算)。每条带该值最早的 `filed`。
SEC 要求 User-Agent 带联系方式:`SEC_USER_AGENT` env(默认 `CometCloud-research/1.0`),每秒 ≤ 5 次,这里一家一次、间隔 0.5s。

表 `issuer_fundamentals_quarterly`(symbol, period)主键;`_issuer_fundamentals_loop` 每天跑一轮、7 天内跑过就跳过(Redis)。
判活:`select symbol, max(period), max(filed) from issuer_fundamentals_quarterly group by 1`。
"""
from __future__ import annotations

import datetime as dt
import os
import re
from typing import Any, Optional

TABLE = "issuer_fundamentals_quarterly"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"issuer_fundamentals_quarterly": ("symbol", "cik", "period", "period_end", "filed", "revenue", "net_income",
                                                     "buybacks", "dividends", "diluted_shares", "source")}
LOOP_NAME = "_issuer_fundamentals_loop"
TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"
FACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json"
RAN_KEY = "issuer_fundamentals:last_run"
CONCEPTS: dict[str, tuple[str, ...]] = {
    "revenue": ("Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax"),
    "net_income": ("NetIncomeLoss",),
    "buybacks": ("PaymentsForRepurchaseOfCommonStock",),
    "dividends": ("PaymentsOfDividends", "PaymentsOfDividendsCommonStock"),
    "diluted_shares": ("WeightedAverageNumberOfDilutedSharesOutstanding",),
}
_Q = re.compile(r"^CY(\d{4})Q([1-4])$")
_Y = re.compile(r"^CY(\d{4})$")


def user_agent() -> str:
    return os.environ.get("SEC_USER_AGENT", "CometCloud-research/1.0")


def cik_map(tickers_json: dict, symbols: list[str]) -> dict[str, int]:
    """纯函数。company_tickers.json → {symbol: cik};不在里面的不出现。"""
    want = {s.upper() for s in symbols}
    out: dict[str, int] = {}
    for rec in (tickers_json or {}).values():
        if not isinstance(rec, dict):
            continue
        t = str(rec.get("ticker") or "").upper()
        if t in want and rec.get("cik_str") is not None:
            out[t] = int(rec["cik_str"])
    return out


def _frames(facts: dict, concept: str, unit_prefs=("USD", "shares")) -> dict[str, tuple[float, str, str]]:
    """概念的 frame 值 → {frame: (val, end, filed)};同一 frame 取最早披露的那条(时点口径)。"""
    node = (((facts or {}).get("facts") or {}).get("us-gaap") or {}).get(concept) or {}
    units = node.get("units") or {}
    rows = next((units[u] for u in unit_prefs if u in units), None)
    if rows is None:
        rows = next(iter(units.values()), [])
    out: dict[str, tuple[float, str, str]] = {}
    for r in rows:
        f, v, filed = r.get("frame"), r.get("val"), str(r.get("filed") or "")
        if not f or v is None or not (_Q.match(f) or _Y.match(f)):
            continue
        try:
            v = float(v)
        except (TypeError, ValueError):
            continue
        if f not in out or filed < out[f][2]:
            out[f] = (v, str(r.get("end") or ""), filed)
    return out


def quarterly(facts: dict, symbol: str, cik: int) -> list[dict]:
    """纯函数。companyfacts → 季度行(Q4 由年度减三季推,三季都在才推;flow 口径的概念才推)。"""
    per: dict[str, dict] = {}
    for col, names in CONCEPTS.items():
        fr: dict = {}
        for n in names:
            fr = _frames(facts, n, ("shares",) if col == "diluted_shares" else ("USD",))
            if fr:
                break
        if not fr:
            continue
        years = {_Y.match(f).group(1) for f in fr if _Y.match(f)}
        for f, (v, end, filed) in fr.items():
            m = _Q.match(f)
            if m:
                p = per.setdefault(f, {"period_end": end, "filed": filed})
                p[col] = v
                p["filed"] = max(p["filed"], filed) if p.get("filed") else filed
        if col == "diluted_shares":
            continue                                     # 股数不是流量,年度减不出 Q4
        for y in years:
            q4 = f"CY{y}Q4"
            if q4 in fr:
                continue
            qs = [fr.get(f"CY{y}Q{i}") for i in (1, 2, 3)]
            if all(q is not None for q in qs):
                yv, yend, yfiled = fr[f"CY{y}"]
                p = per.setdefault(q4, {"period_end": yend, "filed": yfiled})
                p[col] = yv - sum(q[0] for q in qs)
                p["filed"] = max(p.get("filed") or "", yfiled)
    rows = []
    for f, p in sorted(per.items()):
        if not any(p.get(c) is not None for c in CONCEPTS):
            continue
        rows.append({"symbol": symbol, "cik": cik, "period": f, "period_end": p.get("period_end") or None, "filed": p.get("filed") or None,
                     **{c: p.get(c) for c in CONCEPTS}, "source": "sec_edgar"})
    return rows


async def run_once(now: Optional[dt.datetime] = None, force: bool = False) -> dict[str, Any]:
    import asyncio
    import httpx
    from src.api.store import redis_get_key_status, redis_set_key, supabase_upsert_table
    from src.data.universe.world50 import RAIL_EQUITIES
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    last, _st = await redis_get_key_status(RAN_KEY)
    if not force and last and last.get("at"):
        try:
            if (now - dt.datetime.fromisoformat(last["at"])).days < 7:
                return {"ok": True, "status": "skipped", "why": f"7 天内跑过({last['at'][:10]})"}
        except ValueError:
            pass
    symbols = [c.key for c in RAIL_EQUITIES]
    headers = {"User-Agent": user_agent(), "Accept-Encoding": "gzip, deflate"}
    written, missing, errors = 0, [], []
    async with httpx.AsyncClient(timeout=60, headers=headers) as client:
        r = await client.get(TICKERS_URL)
        if r.status_code != 200:
            return {"ok": False, "why": f"company_tickers.json HTTP {r.status_code}"}
        ciks = cik_map(r.json(), symbols)
        missing = sorted(set(symbols) - set(ciks))
        for sym, cik in sorted(ciks.items()):
            try:
                rr = await client.get(FACTS_URL.format(cik=cik))
                if rr.status_code != 200:
                    errors.append(f"{sym}: HTTP {rr.status_code}")
                    continue
                rows = quarterly(rr.json(), sym, cik)
                if rows:
                    w = await supabase_upsert_table(TABLE, rows, on_conflict="symbol,period")
                    if not w:
                        errors.append(f"{sym}: 写失败 {(getattr(w, 'why', '') or '')[:120]}")
                        continue
                    written += len(rows)
            except Exception as e:                                        # noqa: BLE001
                errors.append(f"{sym}: {type(e).__name__}")
            await asyncio.sleep(0.5)
    await redis_set_key(RAN_KEY, {"at": now.isoformat(), "written": written}, ttl=14 * 86400)
    return {"ok": written > 0 or not errors, "written": written, "companies": len(ciks), "missing_cik": missing, "errors": errors,
            "why": f"{len(ciks)} 家 {written} 行" + (f";没有 CIK:{missing}" if missing else "") + (f";错 {errors}" if errors else "")}
