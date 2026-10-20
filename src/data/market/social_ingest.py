"""外部注意力数据入库(台账 S-628 / S-629):Santiment 社交提及(日)+ Sharpe mindshare(代币快照 + 叙事历史)。

为什么要入库而不是用时现取:
- **Santiment 免费档是滚动窗口**(约 1 年,且不含最近 30 天)—— 不存,每天就有一天的历史从窗口里走掉;
  它只能做历史检验(S-628 K 臂),做不了实时信号。
- **Sharpe 只给当期代币快照**(没有代币级历史)—— 不每天存,前向臂(S-629)就不存在。

写入方:Railway `_social_ingest_loop`(每天一次;同一 UTC 日内重启不重复取 —— Santiment 免费档每月约 1,000 次)。
读法 / 判活:`select at, outcome, reason, detail from loop_attempt where loop_name = '_social_ingest_loop' order by at desc limit 3`;
`select metric, count(*), max(d) from social_daily group by metric`(max(d) ≈ 今天 − 31 天);
`select max(snap_d) from sharpe_mindshare_snap`(≈ 今天)。

映射规则在 S-628 里写死(读社交数值之前):binance_hist 名字去 1000000 / 1000 前缀,与 Santiment ticker 大写精确匹配;
同一 ticker 多个项目取 marketcapUsd 最大的;匹配不上的也落一行(slug = null),免得每天重试。
"""
from __future__ import annotations

import asyncio
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Optional

#: 写入是注入的(`upsert(table, …)`),AST 推断看不见 —— 显式声明给 schema_manifest(S-166 写表必须存在)
WRITES_TABLES = ("santiment_slug_map", "social_daily", "sharpe_mindshare_snap", "sharpe_narrative_mindshare")

SAN_METRICS = ("social_volume_total", "sentiment_weighted_total")
SAN_BACKFILL_FROM = "2025-09-01"      # 免费档自己截到允许的最早一天(10-20 实测从 2025-10-20 起)
POINTS_PER_CALL = 8000                # 一次请求的 名字 × 天数 上限;复杂度报错时再对半拆
MIN_BATCH, MAX_BATCH = 5, 50
REFETCH_DAYS = 3                      # 尾部重取(供应方会回补最近几天)
STALE_DAYS = 90                       # 最后一天比这还旧的序列不再追(多半已下架)
MAP_MAX_AGE_DAYS = 7
SKIP_IF_FETCHED_WITHIN_H = 20
UPSERT_CHUNK = 2000
SAN_SLEEP_S = 1.0
SHARPE_SLEEP_S = 2.2                  # 免费档 30 次 / 分钟

_SLUG_OK = re.compile(r"^[a-z0-9][a-z0-9._-]{0,80}$")
_PREFIXES = ("1000000", "1000")


# ───────────────────────── 纯函数 ─────────────────────────

def normalize_symbol(sym: str) -> str:
    """1000PEPE → PEPE;1INCH 不动(前缀必须是整段 1000 / 1000000,且去掉后还剩东西)。"""
    s = (sym or "").strip().upper()
    for p in _PREFIXES:
        if s.startswith(p) and len(s) > len(p):
            return s[len(p):]
    return s


def build_slug_map(projects: list[dict], symbols: list[str]) -> tuple[list[dict], dict[str, list[str]]]:
    """纯函数。Santiment 项目表 + 我们的名字 → santiment_slug_map 的行(含没匹配上的,slug = None)与诊断。"""
    by_ticker: dict[str, list[dict]] = {}
    for p in projects or []:
        t = str(p.get("ticker") or "").strip().upper()
        slug = str(p.get("slug") or "")
        if t and _SLUG_OK.match(slug):
            by_ticker.setdefault(t, []).append(p)
    rows: list[dict] = []
    info: dict[str, list[str]] = {"unmatched": [], "ambiguous_unresolved": [], "collisions": []}
    for sym in sorted(set(symbols or [])):
        cands = by_ticker.get(normalize_symbol(sym), [])
        if not cands:
            info["unmatched"].append(sym)
            rows.append({"symbol": sym, "slug": None, "ticker": None, "marketcap_usd": None,
                         "n_candidates": 0, "note": "no ticker match"})
            continue
        if len(cands) == 1:
            best = cands[0]
        else:
            with_mc = [c for c in cands if isinstance(c.get("marketcapUsd"), (int, float))]
            if not with_mc:
                info["ambiguous_unresolved"].append(sym)
                rows.append({"symbol": sym, "slug": None, "ticker": normalize_symbol(sym), "marketcap_usd": None,
                             "n_candidates": len(cands), "note": "ticker collision, no market cap to resolve"})
                continue
            best = max(with_mc, key=lambda c: float(c["marketcapUsd"]))
            info["collisions"].append(f"{sym}->{best['slug']}({len(cands)})")
        mc = best.get("marketcapUsd")
        rows.append({"symbol": sym, "slug": best["slug"], "ticker": best.get("ticker"),
                     "marketcap_usd": float(mc) if isinstance(mc, (int, float)) else None,
                     "n_candidates": len(cands), "note": None})
    return rows, info


def batch_size(days: int) -> int:
    return max(MIN_BATCH, min(MAX_BATCH, POINTS_PER_CALL // max(1, days)))


def _f(x: Any) -> Optional[float]:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v and v not in (float("inf"), float("-inf")) else None


def _ts(x: Any) -> Optional[datetime]:
    """'2026-04-23T00:00:00.000Z' / '2026-04-23 00:00:00+00' / '2026-04-23T00:00:00+00:00' → 带时区的 datetime。"""
    s = str(x or "").strip().replace(" ", "T").replace("Z", "+00:00")
    if re.search(r"[+-]\d\d$", s):
        s += ":00"
    try:
        t = datetime.fromisoformat(s)
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def parse_per_slug(payload: Any, slug_to_symbols: dict[str, list[str]], metric: str) -> list[dict]:
    """纯函数。timeseriesDataPerSlugJson → social_daily 行。payload = [{datetime, data: [{slug, value}]}]。"""
    out: list[dict] = []
    for pt in payload or []:
        if not isinstance(pt, dict):
            continue
        d = str(pt.get("datetime") or "")[:10]
        if len(d) != 10:
            continue
        for x in pt.get("data") or []:
            slug = (x or {}).get("slug")
            for sym in slug_to_symbols.get(slug, []):
                out.append({"source": "santiment", "symbol": sym, "metric": metric, "d": d,
                            "value": _f(x.get("value")), "slug": slug})
    return out


def plan_santiment(plan: dict, now: datetime) -> dict[str, Any]:
    """纯函数。social_ingest_plan() 的结果 → 这一轮要不要取、要不要重建映射、按起始日分组的名字。"""
    today = now.astimezone(timezone.utc).date()
    lf = _ts(plan.get("last_fetch")) if plan.get("last_fetch") else None
    if lf is not None and now - lf < timedelta(hours=SKIP_IF_FETCHED_WITHIN_H):
        return {"due": False, "why": f"今天已取过(最近一次 {lf.isoformat()[:16]})"}
    universe = list(plan.get("universe") or [])
    mp = dict(plan.get("map") or {})
    missing = [s for s in universe if s not in mp]
    built = _ts(plan.get("map_built_at")) if plan.get("map_built_at") else None
    old = built is None or now - built > timedelta(days=MAP_MAX_AGE_DAYS)
    need_map = (not mp) or (bool(missing) and old)
    return {"due": True, "today": today.isoformat(), "need_map": need_map, "missing_from_map": missing}


def groups_for(metric: str, symbols_with_slug: list[str], last: dict[str, Any], today: date,
               include_new: bool = True) -> dict[str, list[str]]:
    """纯函数。按起始日把名字分组:没取过的 → SAN_BACKFILL_FROM;最近的 → 它们最早的 last_d − REFETCH_DAYS;太旧的不追。
    `include_new = False`:有 slug 但供应方没有数据的名字不再每天回补一年(只在映射重建、或库里还一行都没有时才试)。"""
    new, recent = [], []
    recent_from: Optional[date] = None
    for s in symbols_with_slug:
        v = last.get(f"{s}|{metric}")
        if not v:
            new.append(s)
            continue
        ld = date.fromisoformat(str(v)[:10])
        if (today - ld).days > STALE_DAYS:
            continue
        recent.append(s)
        f = ld - timedelta(days=REFETCH_DAYS)
        recent_from = f if recent_from is None or f < recent_from else recent_from
    out: dict[str, list[str]] = {}
    if new and include_new:
        out[SAN_BACKFILL_FROM] = new
    if recent and recent_from is not None:
        out.setdefault(recent_from.isoformat(), []).extend(recent)
    return out


def token_rows(resp: Any, win: str) -> tuple[Optional[str], list[dict]]:
    """纯函数。Sharpe mindshare tokens 响应 → (snap_d, 行)。snap_d = 供应方 as_of 的 UTC 日期。"""
    if not isinstance(resp, dict):
        return None, []
    meta = resp.get("meta") or {}
    as_of = meta.get("as_of") or meta.get("generated_at")
    snap_d = str(as_of)[:10] if as_of else None
    data = resp.get("data") or {}
    toks = data.get("tokens") if isinstance(data, dict) else None
    if not snap_d or not isinstance(toks, list):
        return snap_d, []
    rows = []
    for t in toks:
        if not isinstance(t, dict) or not t.get("id"):
            continue
        nids = t.get("narrativeIds")
        rows.append({
            "snap_d": snap_d, "win": win, "token_id": str(t["id"]), "symbol": t.get("symbol"), "name": t.get("name"),
            "mindshare_pct": _f(t.get("mindsharePct")), "sentiment_pct": _f(t.get("sentimentPct")),
            "social_score": _f(t.get("socialScore")), "watchlist_users": _f(t.get("watchlistUsers")),
            "delta24h": _f(t.get("delta24h")), "delta7d": _f(t.get("delta7d")), "price": _f(t.get("price")),
            "market_cap": _f(t.get("marketCap")), "price_change24h": _f(t.get("priceChange24h")),
            "narrative_ids": [str(x) for x in nids if x] if isinstance(nids, list) else None,
            "as_of": as_of,
        })
    return snap_d, rows


def narrative_rows(resp: Any, after: Optional[str]) -> list[dict]:
    """纯函数。Sharpe mindshare historical → sharpe_narrative_mindshare 行(只要 after 之后的)。"""
    if not isinstance(resp, dict):
        return []
    data = resp.get("data") if isinstance(resp.get("data"), dict) else resp
    snaps = (data or {}).get("snapshots") or []
    cut = _ts(after) if after else None
    out = []
    for s in snaps:
        if not isinstance(s, dict) or not s.get("snapshot_at") or not s.get("narrative_id"):
            continue
        at = str(s["snapshot_at"])
        t = _ts(at)
        if t is None or (cut is not None and t <= cut):
            continue
        tc = s.get("token_count")
        out.append({"snapshot_at": at, "narrative_id": str(s["narrative_id"]),
                    "mindshare_pct": _f(s.get("mindshare_pct")), "watchlist_users": _f(s.get("watchlist_users")),
                    "token_count": int(tc) if isinstance(tc, (int, float)) else None,
                    "total_social_score": _f(s.get("total_social_score"))})
    return out


def dedupe(rows: list[dict], key: tuple[str, ...]) -> list[dict]:
    """同一批里主键重复会让 Postgres upsert 报「cannot affect row a second time」—— 保留第一条。"""
    seen: set = set()
    out = []
    for r in rows:
        k = tuple(r.get(c) for c in key)
        if k in seen:
            continue
        seen.add(k)
        out.append(r)
    return out


# ───────────────────────── IO ─────────────────────────

Getter = Callable[..., Awaitable[Any]]


async def _upsert(upsert: Getter, table: str, rows: list[dict], on_conflict: str) -> tuple[int, list[str]]:
    n, errs = 0, []
    for i in range(0, len(rows), UPSERT_CHUNK):
        chunk = rows[i:i + UPSERT_CHUNK]
        r = await upsert(table, chunk, on_conflict)
        if getattr(r, "ok", False):
            n += len(chunk)
        else:
            errs.append(str(getattr(r, "why", r))[:160])
    return n, errs


async def _san_projects(gql: Getter) -> tuple[list[dict], int]:
    out: list[dict] = []
    calls = 0
    fields = "slug ticker marketcapUsd"
    for page in range(1, 21):
        q = "{ allProjects(page: %d, pageSize: 500) { %s } }" % (page, fields)
        try:
            d = await gql(q)
        except RuntimeError as e:
            if "marketcapUsd" in str(e) and fields != "slug ticker":
                fields = "slug ticker"
                d = await gql("{ allProjects(page: %d, pageSize: 500) { %s } }" % (page, fields))
                calls += 1
            else:
                raise
        calls += 1
        got = d.get("allProjects") or []
        out.extend(got)
        if len(got) < 500:
            break
        await asyncio.sleep(SAN_SLEEP_S)
    return out, calls


def _q_per_slug(metric: str, slugs: list[str], frm: str) -> str:
    sl = ",".join('"%s"' % s for s in slugs if _SLUG_OK.match(s))
    return ('{ getMetric(metric: "%s") { timeseriesDataPerSlugJson(selector: {slugs: [%s]}, '
            'from: "%sT00:00:00Z", to: "utc_now", interval: "1d") } }' % (metric, sl, frm))


async def _san_fetch(gql: Getter, metric: str, slugs: list[str], frm: str, counter: list[int], depth: int = 0) -> list:
    try:
        counter[0] += 1
        d = await gql(_q_per_slug(metric, slugs, frm))
        await asyncio.sleep(SAN_SLEEP_S)
        return ((d.get("getMetric") or {}).get("timeseriesDataPerSlugJson")) or []
    except RuntimeError as e:
        if "omplexity" in str(e) and len(slugs) > 1 and depth < 5:
            h = len(slugs) // 2
            a = await _san_fetch(gql, metric, slugs[:h], frm, counter, depth + 1)
            b = await _san_fetch(gql, metric, slugs[h:], frm, counter, depth + 1)
            return a + b
        raise


async def run_santiment(plan: dict, now: datetime, gql: Getter, upsert: Getter) -> dict[str, Any]:
    p = plan_santiment(plan, now)
    if not p["due"]:
        return {"status": "ok", "skipped": True, "reason": p["why"]}
    today = date.fromisoformat(p["today"])
    universe = list(plan.get("universe") or [])
    mp: dict[str, Optional[str]] = dict(plan.get("map") or {})
    calls = [0]
    detail: dict[str, Any] = {"universe": len(universe)}
    errs: list[str] = []
    if p["need_map"]:
        projects, c = await _san_projects(gql)
        calls[0] += c
        rows, info = build_slug_map(projects, universe)
        n, e = await _upsert(upsert, "santiment_slug_map", rows, "symbol")
        errs += e
        mp = {r["symbol"]: r["slug"] for r in rows}
        detail["map"] = {"projects": len(projects), "rows": n, "unmatched": info["unmatched"][:60],
                         "ambiguous_unresolved": info["ambiguous_unresolved"], "collisions": info["collisions"][:40]}
    with_slug = [s for s in universe if mp.get(s)]
    slug_to_syms: dict[str, list[str]] = {}
    for s in with_slug:
        slug_to_syms.setdefault(str(mp[s]), []).append(s)
    last = dict(plan.get("last") or {})
    include_new = bool(p["need_map"]) or not plan.get("last_fetch")
    stamp = now.astimezone(timezone.utc).isoformat()
    per_metric: dict[str, Any] = {}
    for metric in SAN_METRICS:
        rows_m: list[dict] = []
        for frm, syms in sorted(groups_for(metric, with_slug, last, today, include_new).items()):
            days = (today - date.fromisoformat(frm)).days + 1
            slugs = sorted({str(mp[s]) for s in syms})
            bs = batch_size(days)
            for i in range(0, len(slugs), bs):
                payload = await _san_fetch(gql, metric, slugs[i:i + bs], frm, calls)
                rows_m += parse_per_slug(payload, slug_to_syms, metric)
        rows_m = dedupe(rows_m, ("source", "symbol", "metric", "d"))
        for r in rows_m:
            r["fetched_at"] = stamp     # upsert 只更新给了的列:不带它,重取的行 fetched_at 不动,「今天取过」就判不出来
        n, e = await _upsert(upsert, "social_daily", rows_m, "source,symbol,metric,d")
        errs += e
        per_metric[metric] = {"rows": n, "symbols": len({r["symbol"] for r in rows_m}),
                              "max_d": max((r["d"] for r in rows_m), default=None)}
    detail.update({"with_slug": len(with_slug), "calls": calls[0], "metrics": per_metric})
    if errs:
        return {"status": "error", "reason": "; ".join(errs)[:300], "detail": detail}
    return {"status": "ok", "reason": f"{calls[0]} 次调用;" + ",".join(
        f"{m} {v['rows']} 行至 {v['max_d']}" for m, v in per_metric.items()), "detail": detail}


async def run_sharpe(plan: dict, now: datetime, get: Getter, upsert: Getter) -> dict[str, Any]:
    today = now.astimezone(timezone.utc).date().isoformat()
    last_snap = plan.get("sharpe_last_snap")
    if last_snap and str(last_snap)[:10] >= today:
        return {"status": "ok", "skipped": True, "reason": f"今天的快照已在({last_snap})"}
    calls = 1
    first = await get("mindshare/data", {"tokens": "true", "window": "now"})
    snap_d, rows = token_rows(first, "now")
    if not snap_d:
        return {"status": "error", "reason": "Sharpe tokens 响应里没有 as_of", "detail": {}}
    if last_snap and snap_d <= str(last_snap)[:10]:
        return {"status": "ok", "skipped": True, "reason": f"供应方还没出新快照(as_of {snap_d})"}
    errs: list[str] = []
    await asyncio.sleep(SHARPE_SLEEP_S)
    calls += 1
    _, r7 = token_rows(await get("mindshare/data", {"tokens": "true", "window": "7d"}), "7d")
    rows += r7
    ids: list[str] = []
    try:
        await asyncio.sleep(SHARPE_SLEEP_S)
        calls += 1
        nd = await get("narratives/data")
        ids = [str(n.get("id")) for n in ((nd.get("data") or {}).get("narratives") or []) if n.get("id")]
    except Exception as e:                                         # noqa: BLE001 — 只少了按叙事补全,不致命
        errs.append(f"narratives: {type(e).__name__}: {str(e)[:100]}")
    for nid in ids[:40]:
        await asyncio.sleep(SHARPE_SLEEP_S)
        calls += 1
        try:
            _, rn = token_rows(await get("mindshare/data", {"tokens": "true", "window": "now", "narrative": nid}), "now")
            rows += [r for r in rn if r["snap_d"] == snap_d]
        except Exception as e:                                     # noqa: BLE001
            errs.append(f"{nid}: {str(e)[:60]}")
    rows = dedupe(rows, ("snap_d", "win", "token_id"))
    n_tok, e = await _upsert(upsert, "sharpe_mindshare_snap", rows, "snap_d,win,token_id")
    errs += e
    await asyncio.sleep(SHARPE_SLEEP_S)
    calls += 1
    nrows: list[dict] = []
    try:
        nrows = dedupe(narrative_rows(await get("mindshare/data", {"historical": "true", "timeframe": "6M"}),
                                      plan.get("sharpe_last_narr")), ("snapshot_at", "narrative_id"))
    except Exception as e:                                         # noqa: BLE001
        errs.append(f"historical: {type(e).__name__}: {str(e)[:100]}")
    n_nar, e = await _upsert(upsert, "sharpe_narrative_mindshare", nrows, "snapshot_at,narrative_id") if nrows else (0, [])
    errs += e
    detail = {"snap_d": snap_d, "token_rows": n_tok, "tokens_now": len({r["token_id"] for r in rows if r["win"] == "now"}),
              "narratives": len(ids), "narrative_rows": n_nar, "calls": calls, "soft_errors": errs[:10]}
    hard = n_tok == 0
    return {"status": "error" if hard else "ok",
            "reason": f"快照 {snap_d}:代币 {detail['tokens_now']} 个、叙事历史新增 {n_nar} 行" + (f";{len(errs)} 处小错" if errs else ""),
            "detail": detail}


async def run_once(now: Optional[datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_rpc, supabase_upsert_table
    from src.data.market.data_layer import QUOTA_SEEN, get_santiment_gql, get_sharpe_v1
    now = now or datetime.now(timezone.utc)
    plan = await supabase_rpc("social_ingest_plan")
    if not isinstance(plan, dict):
        return {"status": "error", "reason": f"social_ingest_plan 返回 {type(plan).__name__}", "detail": {}}
    parts: dict[str, Any] = {}
    for name, fn in (("santiment", lambda: run_santiment(plan, now, get_santiment_gql, supabase_upsert_table)),
                     ("sharpe", lambda: run_sharpe(plan, now, get_sharpe_v1, supabase_upsert_table))):
        try:
            parts[name] = await fn()
        except Exception as e:                                     # noqa: BLE001 — 一家坏了不拖另一家
            parts[name] = {"status": "error", "reason": f"{type(e).__name__}: {str(e)[:240]}"}
    status = "error" if any(v.get("status") == "error" for v in parts.values()) else "ok"
    reason = " | ".join(f"{k}: {v.get('reason', '')}" for k, v in parts.items())
    return {"status": status, "reason": reason[:400], "detail": {**parts, "quota": QUOTA_SEEN}}
