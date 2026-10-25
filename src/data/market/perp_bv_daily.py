"""Binance U 本位永续**全部** USDT 合约的日线(含之后下架的)→ `perp_bv_daily`(S-683)。

## 为什么

做空纸面前向臂(台账 S-683)要的宇宙是「Binance 上所有 USDT 永续」:臂 L 要第一时间知道哪个合约**刚上市**,
臂 H(熊市反弹失败 × 闸门)要所有 30 日成交额 ≥ $5M 的合约的 220 根以上日线。`binance_hist` 只有面板里的
约 140–260 个名字,而且只收「今天还在的」—— 用它做前向,等于把研究里刚去掉的幸存者偏差又装回去。

## 从哪里取

`data.binance.vision` 的 U 本位永续 1d klines:日档(每天上传前一天)+ 月档(回补);合约名单 = 同一个桶的目录。
全部经 `data_layer.get_binance_vision_um_daily`(同一个取数入口,klines 与 index 只是它的参数)。无 key、静态文件。

## 取什么

- **合约登记** `perp_bv_pairs`:每轮列一次目录(约 1,100 个前缀,两三页);新出现的合约查它第一份日档的日期
  (`first_d`,目录按字典序,第一份就是最早的)和 BACKFILL_FROM 之后还有没有档(`active`)。
- **日线**:每个 active 合约从 max(first_d, BACKFILL_FROM) 到昨天;整月用月档,当月用日档。
  缺口由视图 `perp_bv_coverage`(每个合约的 min / max / 行数)算。
- 日档 404:最近 3 天内 ⇒ 还没上传,下一轮再取;更早 ⇒ 合约那天已不在(下架),`dead_from` 记下,不再往后取。

## 判活

    select max(d), count(*) from perp_bv_daily where d = (select max(d) from perp_bv_daily);  -- max(d) ≥ 前天,行数 ≈ 活跃合约数
    select count(*) filter (where active) from perp_bv_pairs;                                    -- 活跃合约数
"""
from __future__ import annotations

import asyncio
import csv
import io
import re
import time
import zipfile
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

TABLE = "perp_bv_daily"
PAIRS = "perp_bv_pairs"
COVERAGE_VIEW = "perp_bv_coverage"
WRITES_TABLES = ("perp_bv_daily", "perp_bv_pairs")   # 字面量:schema_manifest 只读字面量
KIND = "klines"
VENUE = "binance_perp"
BACKFILL_FROM = "2025-12-01"          # 臂 H 要 220 根以上:inception 2026-10-26 前约 330 根
UPLOAD_GRACE_DAYS = 3                 # 日档最近 3 天 404 = 还没传,不是下架
CONCURRENCY = 24
TIME_BUDGET_S = 210.0
FAIL_REFUSE_FRACTION = 0.5
CLASSIFY_LOOKBACK_DAYS = 60           # S-683 修订:只给最近 60 天上的新合约问 CoinGecko 分类
#: 与研究抓取同一张排除表(docs/research/s681_um_fetch.py):指数类、稳定币、非常规合约。
EXCLUDE_BASE = frozenset({"BTCDOM", "DEFI", "USDC", "FDUSD", "TUSD", "BUSD", "USDP", "DAI", "FOOTBALL", "BLUEBIRD"})

_PREFIX_RE = re.compile(r"<Prefix>data/futures/um/daily/klines/([^<]+)/</Prefix>")
_KEY_RE = re.compile(r"<Key>([^<]+)</Key>")
_DAY_RE = re.compile(r"-1d-(\d{4}-\d{2}-\d{2})\.zip$")


def keep(pair: str) -> bool:
    """纯函数。USDT 本位、ASCII 字母数字(交割合约带「_」,非 ASCII 名排除)、不在排除表。"""
    if not (pair.isascii() and pair.isalnum() and pair.endswith("USDT") and len(pair) > 4):
        return False
    return pair[:-4] not in EXCLUDE_BASE


def parse_index_prefixes(xml: bytes) -> tuple[list[str], bool]:
    """纯函数。目录页 → (合约名, 是否还有下一页)。"""
    x = xml.decode("utf-8", errors="replace")
    return _PREFIX_RE.findall(x), "<IsTruncated>true</IsTruncated>" in x


def parse_index_days(xml: bytes) -> list[str]:
    """纯函数。某合约的档目录页 → 日档日期(去掉 .CHECKSUM)。"""
    x = xml.decode("utf-8", errors="replace")
    return [m.group(1) for k in _KEY_RE.findall(x) if (m := _DAY_RE.search(k))]


def parse_klines_zip(blob: bytes) -> list[tuple[str, float, float, float, float, float]]:
    """纯函数。klines zip → [(UTC 日期, o, h, l, c, quote_volume)]。表头行 / 读不出的行跳过。
    列序(Binance 文档):open_time, open, high, low, close, volume, close_time, quote_volume, …"""
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        names = [n for n in z.namelist() if n.endswith(".csv")]
        if not names:
            raise ValueError("zip 里没有 csv")
        text = z.read(names[0]).decode("utf-8", errors="replace")
    out = []
    for r in csv.reader(io.StringIO(text)):
        if not r or not r[0].strip().isdigit():
            continue
        try:
            t = int(r[0])
            t = t // 1000 if t > 10 ** 14 else t                      # 2025 起部分档是微秒
            d = datetime.fromtimestamp(t / 1000, tz=timezone.utc).date().isoformat()
            o, h, l, c = (float(v) for v in r[1:5])
            qv = float(r[7]) if len(r) > 7 and r[7] else float(r[5]) * c
        except (IndexError, ValueError):
            continue
        if c > 0:
            out.append((d, o, h, l, c, qv))
    return out


def bar_rows(pair: str, bars: list[tuple]) -> list[dict]:
    sym = pair[:-4]
    return [{"pair": pair, "symbol": sym, "d": d, "o": o, "h": h, "l": l, "c": c, "qv": qv} for d, o, h, l, c, qv in bars]


def _month(d: str) -> str:
    return d[:7]


def plan(pairs: list[dict], coverage: dict[str, dict], today: date) -> list[tuple[str, str, bool]]:
    """纯函数。→ 这一轮要取的 (合约, 日期或月份, 是否月档),最近的优先(前向先要)。
    每个 active 合约要覆盖 [max(first_d, BACKFILL_FROM), min(昨天, dead_from − 1)];
    已有的段 = coverage 的 [min_d, max_d](月档整月写入,中间不留洞)。"""
    yday = today - timedelta(days=1)
    cur_month = today.isoformat()[:7]
    recent: list[tuple[str, str, bool]] = []
    back: list[tuple[str, str, bool]] = []
    for p in pairs:
        if not p.get("active"):
            continue
        pair = p["pair"]
        start = max(str(p.get("first_d") or BACKFILL_FROM)[:10], BACKFILL_FROM)
        end = yday.isoformat()
        if p.get("dead_from"):
            end = min(end, (date.fromisoformat(str(p["dead_from"])[:10]) - timedelta(days=1)).isoformat())
        if start > end:
            continue
        cov = coverage.get(pair) or {}
        lo, hi = (str(cov.get("min_d") or "")[:10] or None), (str(cov.get("max_d") or "")[:10] or None)
        want: list[tuple[str, str]] = []
        if lo is None:
            want.append((start, end))
        else:
            if hi < end:
                want.append(((date.fromisoformat(hi) + timedelta(days=1)).isoformat(), end))
            if lo > start:
                want.append((start, (date.fromisoformat(lo) - timedelta(days=1)).isoformat()))
        for a, b in want:
            d = date.fromisoformat(a)
            last = date.fromisoformat(b)
            while d <= last:
                m = d.isoformat()[:7]
                if m < cur_month and d.day == 1 and (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1)) <= last:
                    back.append((pair, m, True))                      # 整月 ⇒ 月档
                    d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
                    continue
                (recent if (yday - d).days <= 7 else back).append((pair, d.isoformat(), False))
                d += timedelta(days=1)
    recent.sort(key=lambda t: t[1], reverse=True)
    back.sort(key=lambda t: t[1], reverse=True)
    return recent + back


async def _index_pairs() -> list[str]:
    from src.data.market.data_layer import get_binance_vision_um_daily
    out: list[str] = []
    marker = ""
    for _ in range(20):
        got, more = parse_index_prefixes(await get_binance_vision_um_daily(KIND, "", marker, index=True))
        out += got
        if not more or not got:
            return out
        marker = got[-1]
    return out


async def _probe_pair(pair: str, sem: asyncio.Semaphore) -> dict:
    """新合约:第一份日档的日期 + BACKFILL_FROM 之后还有没有档。"""
    from src.data.market.data_layer import get_binance_vision_um_daily
    async with sem:
        try:
            first = parse_index_days(await get_binance_vision_um_daily(KIND, pair, "", index=True, max_keys=2))
            after = parse_index_days(await get_binance_vision_um_daily(KIND, pair, BACKFILL_FROM, index=True, max_keys=3))
        except Exception as e:                                       # noqa: BLE001  读不到 ⇒ 这轮不登记,下轮再查
            return {"pair": pair, "error": f"{type(e).__name__}: {str(e)[:80]}"}
    return {"pair": pair, "symbol": pair[:-4], "first_d": first[0] if first else None, "active": bool(after),
            "seen_at": datetime.now(timezone.utc).isoformat()}


def month_days(month: str, last: date) -> list[str]:
    """纯函数。'YYYY-MM' 里不晚于 last 的每一天(月档 404 时退回日档)。"""
    d = date.fromisoformat(month + "-01")
    out = []
    while d.isoformat()[:7] == month and d <= last:
        out.append(d.isoformat())
        d += timedelta(days=1)
    return out


async def _fetch(pair: str, when: str, monthly: bool, sem: asyncio.Semaphore) -> tuple[Optional[list[dict]], bool, Optional[str]]:
    """→ (行, 是否 404, 错误)。"""
    from src.data.market.data_layer import get_binance_vision_um_daily
    async with sem:
        try:
            blob = await get_binance_vision_um_daily(KIND, pair, when, monthly=monthly)
        except Exception as e:                                       # noqa: BLE001
            return None, False, f"{pair} {when}: {type(e).__name__}: {str(e)[:80]}"
    if blob is None:
        return None, True, None
    try:
        return bar_rows(pair, parse_klines_zip(blob)), False, None
    except Exception as e:                                           # noqa: BLE001
        return None, False, f"{pair} {when}: parse {type(e).__name__}: {str(e)[:80]}"


def classify(pairs: list[str], tickers: list[dict], now_iso: str) -> list[dict]:
    """纯函数(S-683 修订)。CoinGecko 的 binance_futures 行情 → 有 coin_id 的合约记为 coin;
    没有 coin_id 的**不分类**(可能是股票 / 商品永续,也可能是 CG 还没对上的新币)—— 下一轮再查,臂里不用。
    2026-10-25 快照上:520 / 520 个加密合约有 coin_id,225 个 TradFi 里 222 个没有。"""
    m = {str(t.get("symbol") or "").upper(): t.get("coin_id") for t in tickers if t.get("symbol")}
    return [{"pair": p, "symbol": p[:-4], "kind": "coin", "underlying_type": "COIN(cg)",
             "classified_by": f"coingecko:{m[p]}", "classified_at": now_iso} for p in pairs if m.get(p)]


async def _classify_new(known: dict[str, dict], today: date) -> tuple[int, Optional[str]]:
    """最近 60 天上的、还没分类的合约,问一次 CoinGecko(只在有这种合约时才问)。→ (分了几个, 错误)。"""
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_derivatives_exchange_tickers
    cutoff = (today - timedelta(days=CLASSIFY_LOOKBACK_DAYS)).isoformat()
    todo = sorted(p for p, r in known.items() if not r.get("kind") and str(r.get("first_d") or "")[:10] >= cutoff)
    if not todo:
        return 0, None
    try:
        rows = classify(todo, await get_cg_derivatives_exchange_tickers("binance_futures"), datetime.now(timezone.utc).isoformat())
    except Exception as e:                                           # noqa: BLE001  读不到 ⇒ 不分类,臂里照样不用
        return 0, f"{type(e).__name__}: {str(e)[:120]}"
    if rows:
        r = await supabase_upsert_table(PAIRS, rows, on_conflict="pair")
        if not r.ok:
            return 0, f"{PAIRS} 写入失败(分类):{r.why}"
    return len(rows), None


async def run_once(today: Optional[date] = None, time_budget: float = TIME_BUDGET_S) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.source_policy import MARKET_DATA, assert_purpose_source
    from src.data.style.header import _read_all
    t0 = time.monotonic()
    today = today or datetime.now(timezone.utc).date()
    sem = asyncio.Semaphore(CONCURRENCY)
    # 1. 合约名单
    known = {r["pair"]: r for r in await _read_all(PAIRS, {"select": "pair,symbol,first_d,active,dead_from,kind"})}
    listed = [p for p in await _index_pairs() if keep(p)]
    new = [p for p in listed if p not in known]
    assert_purpose_source(MARKET_DATA, VENUE, n_assets=max(len(listed), 1),
                          job="S-683 perp universe daily bars (data.binance.vision archive)", secondary_ok=True)
    probed_all = await asyncio.gather(*[_probe_pair(p, sem) for p in new]) if new else []
    probed = [p for p in probed_all if "error" not in p]
    probe_errors = [f"{p['pair']}: {p['error']}" for p in probed_all if "error" in p]
    if new and len(probe_errors) > FAIL_REFUSE_FRACTION * len(new):
        return {"ok": False, "refused": True, "reason": f"{len(probe_errors)}/{len(new)} 个新合约的目录读不到 —— 整轮拒写:{probe_errors[:2]}"}
    if probed:
        r = await supabase_upsert_table(PAIRS, probed, on_conflict="pair")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{PAIRS} 写入失败:{r.why}"}
        for p in probed:
            known[p["pair"]] = p
    n_classified, classify_error = await _classify_new(known, today)
    # 2. 日线
    cov = {r["pair"]: r for r in await _read_all(COVERAGE_VIEW, {"select": "pair,min_d,max_d,n"})}
    tasks = plan(list(known.values()), cov, today)
    rows: list[dict] = []
    dead: dict[str, str] = {}
    errors: list[str] = []
    done = 0
    i = 0
    while i < len(tasks):
        if time.monotonic() - t0 > time_budget:
            break
        chunk = tasks[i:i + 400]
        i += len(chunk)
        res = await asyncio.gather(*[_fetch(p, w, m, sem) for p, w, m in chunk])
        done += len(chunk)
        for (pair, when, monthly), (got, missing, err) in zip(chunk, res):
            if err:
                errors.append(err)
            elif got:
                rows.extend(got)
            elif missing and monthly:                             # 月档没有 ≠ 下架:退回日档,由日档 404 判下架
                tasks.extend((pair, d, False) for d in month_days(when, today - timedelta(days=1)))
            elif missing and (today - date.fromisoformat(when)).days > UPLOAD_GRACE_DAYS:
                dead[pair] = min(dead.get(pair, when), when)
    detail = {"pairs_listed": len(listed), "pairs_new": len(new), "active": sum(1 for p in known.values() if p.get("active")),
              "planned": len(tasks), "fetched": done, "rows": len(rows), "errors": len(errors), "error_sample": errors[:3],
              "dead_marked": len(dead), "backlog": len(tasks) - done,
              "classified_coin": n_classified, "classify_error": classify_error}
    if done and len(errors) > FAIL_REFUSE_FRACTION * done:
        return {"ok": False, "refused": True, "reason": f"{len(errors)}/{done} 个档读不到 —— 整轮拒写:{errors[:2]}", **detail}
    seen: dict[tuple, dict] = {}
    for r in rows:
        seen[(r["pair"], r["d"])] = r
    rows = list(seen.values())
    for i in range(0, len(rows), 2000):
        r = await supabase_upsert_table(TABLE, rows[i:i + 2000], on_conflict="pair,d")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{TABLE} 写入失败:{r.why}", **detail}
    if dead:
        upd = [{**{k: known[p].get(k) for k in ("pair", "symbol", "first_d", "active")}, "dead_from": d} for p, d in dead.items()]
        r = await supabase_upsert_table(PAIRS, upd, on_conflict="pair")
        if not r.ok:
            return {"ok": False, "refused": False, "reason": f"{PAIRS} 写入失败(dead_from):{r.why}", **detail}
    return {"ok": True, "refused": False,
            "reason": f"合约 {len(listed)}(新 {len(new)})· 写 {len(rows)} 行 · 积压 {len(tasks) - done} 档 · 失败 {len(errors)}",
            **detail}
