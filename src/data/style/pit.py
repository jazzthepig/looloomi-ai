"""T-067 / S-512 —— 风格指数按时点、在更宽的历史宇宙上重算。

## 原来错在哪(S-504 第 1 条)

`style_index_daily` 的成员来自**今天**各 CoinGecko 分类的市值前 40 名,再往回取历史:2023 年的「头部公链」
只能从今天还活着、还排得上号的币里挑,当年大、后来掉队或死掉的币根本不在宇宙里。层级本身是按 d−1 市值排的
(这一步一直是时点的),**错的是宇宙**。

## 这里怎么做

宇宙 = 今天的分类成员 ∪ **在 Binance 现货上市过的全部币**(`binance_hist` 深盘 262 个符号,含已下架的),
后者经 `cg_coin_map` 映射到 CoinGecko,取分类与 2020 起的市值历史。每天的层级与成员仍只看 d−1 市值
(同一个纯函数 `compute_style_index`)。

**剩下的偏差,如实标注:**
- 成分的**分类**是今天的分类(一个币属于哪个板块,用的是 CoinGecko 今天的标签);
- 从没在 Binance 现货上过、又已经死掉的币仍然看不见 —— 每天看不见多少,写进 `style_pit_coverage_daily`:
  宇宙里有市值的币合计 / (CoinGecko 全市场市值 − 主要稳定币);
- `cg_coin_map` 的同名映射可能错(S-470 修过几次);映射不到的符号不进宇宙,不猜。

每行 `n_not_in_today_lists` = 当天成员里**不在今天前 40 名单上**的个数 —— 就是旧口径看不见的那部分。
幸存者偏差的量 = 两版风格指数逐年收益之差,每轮写进 loop_attempt.detail。

## 判活判据(规则 5b ②)

    select max(d) from style_index_pit_daily;   -- = 昨天(UTC)
"""
from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

import pandas as pd

from src.data.style.header import (HISTORY_START, MIN_MCAP_USD, SOURCE, _dims, _member, _read_all,
                                   compute_style_index, latest_membership)

PIT_TABLE = "style_index_pit_daily"
UNIVERSE_TABLE = "style_universe_broad"
COVERAGE_TABLE = "style_pit_coverage_daily"
WRITES_TABLES = (PIT_TABLE, UNIVERSE_TABLE, COVERAGE_TABLE)
BASIS_PIT = "point_in_time_broad_universe"
CODE_REF_PIT = "t067-v1"
UNIVERSE_SOURCE = "binance_listed"
CATEGORY_REFRESH_DAYS = 30
MAX_CATEGORY_FETCH = 250
STABLE_IDS = ("tether", "usd-coin", "dai", "ethena-usde", "first-digital-usd", "usds", "paypal-usd", "binance-usd")


# ── 纯函数 ──────────────────────────────────────────────────────────────────

def universe_candidates(binance_symbols: list[str], coin_map: dict[str, str],
                        current: set[str]) -> dict[str, str]:
    """深盘符号 → coin_id,去掉今天已在分类名单里的。映射不到的不进宇宙(不猜)。"""
    return {s: coin_map[s] for s in sorted(set(binance_symbols)) if s in coin_map and s not in current}


def needs_refresh(have: dict[str, dict], cands: dict[str, str], today: date) -> list[str]:
    """没有分类、coin_id 变了、或分类超过 CATEGORY_REFRESH_DAYS 天的,重新取。"""
    out = []
    for s, cid in cands.items():
        h = have.get(s)
        if not h or h.get("coin_id") != cid or \
                (today - date.fromisoformat(str(h["fetched_d"])[:10])).days >= CATEGORY_REFRESH_DAYS:
            out.append(s)
    return out[:MAX_CATEGORY_FETCH]


def category_ids(names: list[str], name_map: dict[str, str]) -> list[str]:
    return sorted({name_map[n] for n in names if n in name_map})


def annotate_rows(rows: list[dict], current: set[str]) -> list[dict]:
    """compute_style_index 的行 → PIT 表的行:换 code_ref,数出不在今天名单上的成员。"""
    for r in rows:
        r["code_ref"] = CODE_REF_PIT
        r["n_not_in_today_lists"] = sum(1 for s in r.get("members") or [] if s not in current)
    return rows


def coverage_rows(mcap: pd.DataFrame, total: pd.Series, stables: pd.Series, current: set[str],
                  start: pd.Timestamp, end: pd.Timestamp) -> list[dict]:
    """每天:宇宙里市值 ≥ MIN_MCAP_USD 的币合计 / (全市场 − 稳定币)。分母缺 ⇒ coverage 为空,不猜。"""
    out = []
    now = datetime.now(timezone.utc).isoformat()
    for d in mcap.index[(mcap.index >= start) & (mcap.index <= end)]:
        row = mcap.loc[d].dropna()
        row = row[row >= MIN_MCAP_USD]
        tot, st = total.get(d), stables.get(d)
        denom = (float(tot) - float(st)) if (pd.notna(tot) and pd.notna(st)) else None
        out.append({"d": d.date().isoformat(), "universe_mcap": float(row.sum()),
                    "total_mcap": float(tot) if pd.notna(tot) else None,
                    "coverage": round(float(row.sum()) / denom, 5) if denom and denom > 0 else None,
                    "n_universe": int(len(row)), "n_not_in_today_lists": int(sum(1 for s in row.index if s not in current)),
                    "code_ref": CODE_REF_PIT, "computed_at": now})
    return out


def yearly_gap(old_levels: dict[tuple[str, str], float], new_levels: dict[tuple[str, str], float],
               years: list[int], styles: list[str]) -> dict[str, dict[str, Optional[float]]]:
    """两版指数的逐年收益差(旧 − 新)= 幸存者偏差的量。键 (style, 'YYYY-12-31')。缺端点 ⇒ None。"""
    out: dict[str, dict[str, Optional[float]]] = {}
    for st in styles:
        per: dict[str, Optional[float]] = {}
        for y in years:
            a, b = f"{y - 1}-12-31", f"{y}-12-31"
            o0, o1 = old_levels.get((st, a)), old_levels.get((st, b))
            n0, n1 = new_levels.get((st, a)), new_levels.get((st, b))
            if None in (o0, o1, n0, n1):
                per[str(y)] = None
            else:
                per[str(y)] = round((o1 / o0 - 1) - (n1 / n0 - 1), 4)
        out[st] = per
    return out


# ── I/O ─────────────────────────────────────────────────────────────────────

async def refresh_universe(today: date, current: set[str]) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.market.data_layer import get_cg_category_name_map, get_cg_coin_categories
    from src.data.market.deep_panel_collector import deep_panel_symbols
    syms = await deep_panel_symbols()
    if syms is None:
        raise RuntimeError("深盘符号读不到 —— 不按「没有」处理")
    cmap_rows = await _read_all("cg_coin_map", {"select": "symbol,coin_id"})
    coin_map = {str(r["symbol"]).upper(): r["coin_id"] for r in cmap_rows if r.get("coin_id")}
    cands = universe_candidates([s.upper() for s in syms], coin_map, current)
    have_rows = await _read_all(UNIVERSE_TABLE, {"select": "symbol,coin_id,fetched_d"})
    have = {r["symbol"]: r for r in have_rows}
    todo = needs_refresh(have, cands, today)
    failed: dict[str, str] = {}
    rows: list[dict] = []
    if todo:
        name_map = await get_cg_category_name_map()
        for s in todo:
            try:
                ids = category_ids(await get_cg_coin_categories(cands[s]), name_map)
            except Exception as e:                          # noqa: BLE001
                failed[s] = f"{type(e).__name__}: {str(e)[:80]}"
                continue
            m = _member(s, cands[s], ids, today.isoformat())
            rows.append({"symbol": s, "coin_id": cands[s], "categories": ids, "tier_base": m["tier_base"],
                         "sectors": m["sectors"], "source": UNIVERSE_SOURCE, "fetched_d": today.isoformat()})
            await asyncio.sleep(0.15)
        for i in range(0, len(rows), 500):
            res = await supabase_upsert_table(UNIVERSE_TABLE, rows[i:i + 500], on_conflict="symbol,coin_id")
            if not res.ok:
                raise RuntimeError(f"{UNIVERSE_TABLE} 写入失败:{res.why}")
    return {"candidates": len(cands), "fetched": len(rows), "failed": failed}


async def broad_members(current_members: list[dict]) -> list[dict]:
    cur = {m["symbol"] for m in current_members}
    rows = await _read_all(UNIVERSE_TABLE, {"select": "symbol,coin_id,tier_base,sectors,fetched_d"})
    extra = [{"symbol": r["symbol"], "coin_id": r["coin_id"], "tier_base": r.get("tier_base"),
              "sectors": r.get("sectors") or [], "fetched_d": r["fetched_d"]}
             for r in rows if r["symbol"] not in cur and r.get("tier_base")]
    return extra


async def _global_ex_stables(start: str) -> tuple[pd.Series, pd.Series]:
    from src.data.market.bar_semantics import covered_day, is_day_boundary
    from src.data.market.data_layer import get_cg_global_market_cap_chart
    g = await get_cg_global_market_cap_chart("max")
    tot = {pd.Timestamp(covered_day("coingecko_market_chart", int(t))): float(v)
           for t, v in g.get("market_cap") or [] if v is not None and is_day_boundary(int(t))}
    st_rows = await _read_all("cg_coin_mcap_daily", {"select": "d,coin_id,mcap", "coin_id": f"in.({','.join(STABLE_IDS)})",
                                                     "d": f"gte.{start}"})
    st = pd.DataFrame(st_rows)
    stables = (st.assign(d=pd.to_datetime(st["d"])).groupby("d")["mcap"].sum().astype(float)
               if len(st) else pd.Series(dtype=float))
    return pd.Series(tot, dtype=float).sort_index(), stables


async def rebuild_pit(members: list[dict], current: set[str], end: date) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.vector.market_state_writer import _sb_get
    tier_base, sectors = _dims(members)
    rd = await _sb_get(PIT_TABLE, {"select": "d,code_ref", "order": "d.desc", "limit": "1"})
    if not rd.ok:
        raise RuntimeError(f"{PIT_TABLE} 读不到:{rd.reason}")
    top = (rd.rows or [{}])[0]
    last = top.get("d") if top.get("code_ref") == CODE_REF_PIT else None
    start = (date.fromisoformat(last) - timedelta(days=40)) if last else date.fromisoformat(HISTORY_START)
    prev_level: dict[tuple[str, str], float] = {}
    if last:
        prev = await _read_all(PIT_TABLE, {"select": "style,weighting,level,d",
                                           "d": f"eq.{(start - timedelta(days=1)).isoformat()}"})
        prev_level = {(r["style"], r["weighting"]): float(r["level"]) for r in prev}
    rows = await _read_all("asset_mcap_daily", {"select": "symbol,coin_id,d,price,mcap", "source": f"eq.{SOURCE}",
                                                "d": f"gte.{(start - timedelta(days=3)).isoformat()}",
                                                "order": "d.asc,symbol.asc"})
    if not rows:
        return {"written": 0, "reason": "asset_mcap_daily 在窗口里 0 行"}
    want = {m["symbol"]: m["coin_id"] for m in members}
    df = pd.DataFrame(rows)
    df = df[df["coin_id"] == df["symbol"].map(want)]
    df["d"] = pd.to_datetime(df["d"])
    days = pd.date_range(df["d"].min(), df["d"].max(), freq="D")
    price = df.pivot_table(index="d", columns="symbol", values="price").reindex(days)
    mcap = df.pivot_table(index="d", columns="symbol", values="mcap").reindex(days)
    out = await asyncio.to_thread(compute_style_index, price, mcap, tier_base, sectors,
                                  start=start.isoformat(), end=end.isoformat(), prev_level=prev_level,
                                  basis=BASIS_PIT)
    out = annotate_rows(out, current)
    for i in range(0, len(out), 2000):
        res = await supabase_upsert_table(PIT_TABLE, out[i:i + 2000], on_conflict="d,style,weighting")
        if not res.ok:
            raise RuntimeError(f"{PIT_TABLE} 写入失败:{res.why}")
    cov_note = None
    try:
        total, stables = await _global_ex_stables((start - timedelta(days=3)).isoformat())
        cov = coverage_rows(mcap, total, stables, current, pd.Timestamp(start), pd.Timestamp(end))
        for i in range(0, len(cov), 2000):
            res = await supabase_upsert_table(COVERAGE_TABLE, cov[i:i + 2000], on_conflict="d")
            if not res.ok:
                cov_note = f"覆盖率写入失败:{res.why}"
                break
    except Exception as e:                                  # noqa: BLE001 — 覆盖率读不到不挡指数,但留痕
        cov_note = f"覆盖率没算成:{type(e).__name__}: {str(e)[:120]}"
    return {"written": len(out), "from": start.isoformat(), "to": end.isoformat(), "coverage_note": cov_note}


async def survivorship_gap() -> dict[str, Any]:
    """两版(旧:今天成分回填;新:时点 + 宽宇宙)cap 加权的逐年收益差。"""
    from src.data.style.header import CODE_REF
    from src.data.style.taxonomy import STYLES
    years = list(range(2021, datetime.now(timezone.utc).year))
    ends = ",".join(f"{y}-12-31" for y in [years[0] - 1] + years)
    old = await _read_all("style_index_daily", {"select": "d,style,level", "weighting": "eq.cap",
                                                "code_ref": f"eq.{CODE_REF}", "d": f"in.({ends})"})
    new = await _read_all(PIT_TABLE, {"select": "d,style,level", "weighting": "eq.cap",
                                      "code_ref": f"eq.{CODE_REF_PIT}", "d": f"in.({ends})"})
    lv = lambda rows: {(r["style"], str(r["d"])[:10]): float(r["level"]) for r in rows}  # noqa: E731
    return yearly_gap(lv(old), lv(new), years, list(STYLES))


async def run_once() -> dict[str, Any]:
    from src.data.style.header import backfill_mcap
    today = datetime.now(timezone.utc).date()
    current_members = await latest_membership()
    if not current_members:
        return {"ok": False, "refused": True, "reason": "今天的分类名单读到 0 行 —— 等风格表头那一轮"}
    current = {m["symbol"] for m in current_members}
    uni = await refresh_universe(today, current)
    extra = await broad_members(current_members)
    mc = await backfill_mcap(extra, today)
    idx = await rebuild_pit(current_members + extra, current, today - timedelta(days=1))
    gap = await survivorship_gap()
    ok = idx.get("written", 0) > 0 and len(mc["failed"]) <= max(5, len(extra) // 5)
    return {"ok": ok, "refused": False, "universe": uni, "n_broad": len(extra), "mcap_rows": mc["rows"],
            "mcap_failed": list(mc["failed"])[:10], "index": idx, "survivorship_gap_cap": gap,
            "reason": (f"宽宇宙 {len(extra)} 个币(候选 {uni['candidates']},本轮取分类 {uni['fetched']},"
                       f"失败 {len(uni['failed'])});市值写 {mc['rows']} 行,失败 {len(mc['failed'])};"
                       f"时点指数写 {idx.get('written', 0)} 行")}
