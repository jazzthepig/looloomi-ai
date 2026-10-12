"""正式 CIS —— 统一标准的日终序列,每天发布一次,只追加(T-080 / S-533)。

## 为什么

Jazz 10-11 批准:对外的正式 CIS = 统一标准的日终序列(每天 UTC 收盘算一次,只用当时已知的数据);档位按同组
(加密 / 传统资产)当日分位定,±10 个百分位滞回(外侧两道门槛 ±5,S-535);等级仍按绝对分;30 分钟一轮的引擎降为盘中预览。
这样「过往表现」就是这条序列本身 —— 历史(`cis_rebuild_daily`,按时点重建)与发布(这张表)同一个函数、同一套时点。

## 规则

- 每天 UTC 收盘后算前一天 d。**一个 d 只发一次**:表上有触发器,写进去之后不能改、不能删 —— 后来修订的数据不回改已发布的信号。
- 数据不全(BTC 没有价、加密名字有价的 < 90%、恐惧贪婪或全市场市值缺)时等;过了 UTC 06:00 照发,缺的写进 `missing`。
- 滞回的「上一档」= 前一天的正式档;没有(第一天、或漏了一天)取重建序列(`cis_rebuild_daily` 同版本)的前一天;
  两者都没有就不发,等重建跑完。漏掉的日子不补发 —— 留空,如实。
- 公式、取数、分位都复用 `rebuild`(同一段代码)。

## 判活判据(规则 5b ②)

    select max(d) from cis_official_daily;   -- UTC 06:00 后 = 昨天
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Mapping, Optional

import pandas as pd

from src.data.cis.rebuild import CODE_REF, LEVELS, TRADFI, group_pct, pct_step

TABLE = "cis_official_daily"
WRITES_TABLES = (TABLE,)
PUBLISH_DEADLINE_HOUR = 6
MIN_CRYPTO_PRICED = 0.90


def completeness(rows: list[dict], assets: Mapping[str, Mapping[str, Any]]) -> list[str]:
    """纯函数。d 这一批能不能发:返回缺的东西(空 = 齐)。"""
    probs: list[str] = []
    syms = {r["symbol"] for r in rows}
    if "BTC" not in syms:
        probs.append("BTC 没有价格")
    crypto = [s for s, c in assets.items() if c["class"] not in TRADFI]
    priced = sum(1 for s in crypto if s in syms)
    if crypto and priced / len(crypto) < MIN_CRYPTO_PRICED:
        probs.append(f"加密名字有价的 {priced}/{len(crypto)}")
    btc = next((r for r in rows if r["symbol"] == "BTC"), None)
    if btc is not None:
        if btc["inputs"].get("fng") is None:
            probs.append("恐惧贪婪缺")
        if btc["inputs"].get("btc_dom") is None:
            probs.append("全市场市值缺(BTC 占比算不出)")
    return probs


def official_rows(rows: list[dict], prev_level: Mapping[str, Optional[int]], published_at: str) -> list[dict]:
    """纯函数。score_day 的行(已排好分位)+ 前一天的档 → 正式发布的行。"""
    out = []
    for r in rows:
        lv, watch = pct_step(prev_level.get(r["symbol"]), r.get("pct"))
        out.append({
            "symbol": r["symbol"], "d": r["d"], "asset_class": r["asset_class"],
            "cis_score": _r(r.get("raw_score")), "regime_adjusted_score": _r(r.get("score")),
            "grade": r.get("grade"), "signal": LEVELS[lv] if lv is not None else None, "watch": watch,
            "pct": r.get("pct"),
            "pillar_f": _r(r.get("pillar_f")), "pillar_m": _r(r.get("pillar_m")), "pillar_o": _r(r.get("pillar_o")),
            "pillar_s": _r(r.get("pillar_s")), "pillar_a": _r(r.get("pillar_a")),
            "regime": r.get("regime"), "inputs": r.get("inputs"), "missing": r.get("missing") or [],
            "code_ref": CODE_REF, "published_at": published_at,
        })
    return out


def _r(v: Any) -> Optional[float]:
    try:
        return round(float(v), 2)
    except (TypeError, ValueError):
        return None


def merge_prev(official: list[dict], rebuild: list[dict]) -> dict[str, Optional[int]]:
    """纯函数。前一天的档:正式发布过的优先;正式表里没有的名字(新进宇宙、迁移换了代码)取同版本重建的。"""
    out = {r["symbol"]: (LEVELS.index(r["signal_pct"]) if r.get("signal_pct") in LEVELS else None) for r in rebuild}
    out.update({r["symbol"]: (LEVELS.index(r["signal"]) if r.get("signal") in LEVELS else None) for r in official})
    return out


async def _prev_levels(d: date) -> dict[str, Optional[int]]:
    """前一天的正式档;正式表里没有的名字取重建序列的前一天(S-537:SKY 第一次进正式表时接重建的链)。"""
    from src.data.style.header import _read_all
    y = (d - timedelta(days=1)).isoformat()
    off = await _read_all(TABLE, {"select": "symbol,signal", "d": f"eq.{y}"})
    reb = await _read_all("cis_rebuild_daily", {"select": "symbol,signal_pct", "d": f"eq.{y}", "code_ref": f"eq.{CODE_REF}"})
    if not reb:
        return {}                                           # 同版本重建还没写完 —— 宁可等(见 run_once),不在半截上接
    return merge_prev(off, reb)


async def run_once(now: Optional[datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_insert_table
    from src.data.cis.rebuild import load_inputs, score_day
    from src.data.vector.market_state_writer import _sb_get
    now = now or datetime.now(timezone.utc)
    d = now.date() - timedelta(days=1)
    have = await _sb_get(TABLE, {"select": "d", "d": f"eq.{d.isoformat()}", "limit": "1"})
    if not have.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"{TABLE} 读不到:{have.reason}"}
    if have.rows:
        return {"ok": True, "refused": False, "written": 0, "reason": f"{d} 已发布 —— 只发一次"}
    assets, data = await load_inputs(pd.Timestamp(d))
    rows = score_day(pd.Timestamp(d), assets, data)
    probs = completeness(rows, assets)
    if probs and now.hour < PUBLISH_DEADLINE_HOUR:
        return {"ok": True, "refused": True, "written": 0,
                "reason": f"{d} 数据还不齐({'; '.join(probs)})—— UTC {PUBLISH_DEADLINE_HOUR}:00 前等"}
    group_pct(rows)
    prev = await _prev_levels(d)
    if not prev:
        # 第一批是整条链的种子(表只追加,发错了改不回来):前一天既没有正式档也没有同版本重建档时不发,等重建跑完。
        # 过了 UTC 06:00 还在等 = ok False(心跳变红)—— 比静默用「无滞回」的档位起头好,也比一直「正常地拒绝」看得见。
        return {"ok": now.hour < PUBLISH_DEADLINE_HOUR, "refused": True, "written": 0,
                "reason": f"{d} 前一天没有正式档,也没有 {CODE_REF} 的重建档 —— 等重建跑完再发(滞回需要上一档)"}
    out = official_rows(rows, prev, now.isoformat())
    if probs:
        for r in out:
            r["missing"] = sorted(set(r["missing"]) | {"batch:" + p for p in probs})
    res = await supabase_insert_table(TABLE, out)
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    dist: dict[str, int] = {}
    for r in out:
        dist[r["signal"] or "—"] = dist.get(r["signal"] or "—", 0) + 1
    return {"ok": True, "refused": False, "written": len(out), "d": d.isoformat(), "signals": dist,
            "incomplete": probs, "reason": f"{d} 发布 {len(out)} 个名字" + (f"(不齐:{probs})" if probs else "")}


# ── 对外:把正式序列叠到实时宇宙上(API 层)────────────────────────────────────────
#
# 实时宇宙(Mac T1 / Railway T2,30 分钟一轮)照常算、照常记进 cis_scores;对外响应里的分数、等级、档位、
# 支柱换成最近一次正式发布,实时值挪进每个名字的 `intraday` 块。没有正式发布(第一天之前、表读不到)时
# 原样返回实时值,并在顶层 `official.applied = false` 说明 —— 不编、不静默。

#: 叠加时从实时值挪进 `intraday` 的字段。
INTRADAY_KEYS = ("cis_score", "raw_cis_score", "regime_adjusted_score", "grade", "signal",
                 "f", "m", "o", "s", "a", "pillars", "percentile_rank", "macro_regime")
SELECT = ("symbol,d,asset_class,cis_score,regime_adjusted_score,grade,signal,watch,pct,"
          "pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,regime,missing,code_ref,published_at")
CACHE_S = 600.0
CACHE_FAIL_S = 60.0
_LATEST: dict[str, Any] = {"at": 0.0, "ttl": 0.0, "val": None}


def overlay(data: Any, latest: Optional[Mapping[str, Any]], today: Optional[date] = None,
            names: Optional[Mapping[str, str]] = None) -> Any:
    """纯函数,不改入参。`latest` = {"d", "rows": {symbol: 正式行}, "code_ref", "published_at"} 或 None。
    names:代码 → 显示名(正式有、实时没有的名字补进来时用)。"""
    names = names or {}
    from src.api.contracts.disclosure import OFFICIAL_BASIS
    if not isinstance(data, dict) or not data.get("universe"):
        return data
    if isinstance(data.get("official"), dict):
        return data
    out = dict(data)
    rows = (latest or {}).get("rows") or {}
    if not rows:
        out["official"] = {"applied": False, "basis": "intraday",
                           "reason": (latest or {}).get("reason") or "no official publication yet",
                           "method": OFFICIAL_BASIS}
        return out
    from src.data.cis.migrations import RETIRED
    d = str(latest["d"])
    uni, hit, seen, retired = [], 0, set(), []
    for a in data["universe"]:
        b = dict(a)
        sym = str(a.get("symbol") or a.get("asset_id") or "").upper()
        if sym in RETIRED and RETIRED[sym] in rows:
            retired.append(f"{sym}->{RETIRED[sym]}")          # 迁移后的旧代码:正式视图只放新代码(S-537)
            continue
        seen.add(sym)
        r = rows.get(sym)
        if r is None:
            b["signal_basis"] = "intraday"
            uni.append(b)
            continue
        hit += 1
        b["intraday"] = {k: a.get(k) for k in INTRADAY_KEYS if k in a}
        p = {k.upper(): r.get(f"pillar_{k}") for k in "fmosa"}
        pct = r.get("pct")
        b.update({
            "cis_score": r.get("cis_score"), "raw_cis_score": r.get("cis_score"),
            "regime_adjusted_score": r.get("regime_adjusted_score"),
            "grade": r.get("grade"), "signal": r.get("signal"),
            "f": p["F"], "m": p["M"], "o": p["O"], "s": p["S"], "a": p["A"], "pillars": p,
            "percentile_rank": round(pct * 100, 1) if pct is not None else None,
            "macro_regime": r.get("regime"),
            "signal_basis": "daily_close", "official_date": d,
            "watch": r.get("watch"), "group_percentile": pct,
            "missing_inputs": r.get("missing") or [],
        })
        uni.append(b)
    for sym, r in rows.items():                             # 正式发布了、实时引擎还没有的名字(如刚换代码的 SKY)
        if sym in seen:
            continue
        hit += 1
        p = {k.upper(): r.get(f"pillar_{k}") for k in "fmosa"}
        pct = r.get("pct")
        uni.append({"symbol": sym, "name": names.get(sym, sym), "asset_class": r.get("asset_class"),
                    "cis_score": r.get("cis_score"), "raw_cis_score": r.get("cis_score"),
                    "regime_adjusted_score": r.get("regime_adjusted_score"), "grade": r.get("grade"),
                    "signal": r.get("signal"), "f": p["F"], "m": p["M"], "o": p["O"], "s": p["S"], "a": p["A"],
                    "pillars": p, "percentile_rank": round(pct * 100, 1) if pct is not None else None,
                    "macro_regime": r.get("regime"), "signal_basis": "daily_close", "official_date": d,
                    "watch": r.get("watch"), "group_percentile": pct, "missing_inputs": r.get("missing") or [],
                    "intraday": None})
    uni.sort(key=lambda x: (x.get("cis_score") is None, -(x.get("cis_score") or 0)))
    out["universe"] = uni
    out["intraday"] = {k: data.get(k) for k in ("macro_regime", "regime_confidence", "timestamp", "source") if k in data}
    regimes = {r.get("regime") for r in rows.values() if r.get("regime")}
    if len(regimes) == 1:
        out["macro_regime"] = regimes.pop()
    age = None
    try:
        age = ((today or datetime.now(timezone.utc).date()) - date.fromisoformat(d[:10])).days
    except ValueError:
        pass
    out["official"] = {"applied": True, "basis": "daily_close", "d": d, "age_days": age,
                       "code_ref": latest.get("code_ref"), "published_at": latest.get("published_at"),
                       "covered": hit, "total": len(uni), "intraday_key": "intraday", "method": OFFICIAL_BASIS,
                       **({"retired": retired} if retired else {})}
    return out


async def latest_official(now: Optional[float] = None) -> dict[str, Any]:
    """最近一次正式发布(整批)。缓存 10 分钟;读失败缓存 1 分钟并如实说读不到 —— 读不到 ≠ 没发布(S-180)。"""
    import time
    from src.data.style.header import _read_all
    from src.data.vector.market_state_writer import _sb_get
    t = now if now is not None else time.time()
    if _LATEST["val"] is not None and t - _LATEST["at"] < _LATEST["ttl"]:
        return _LATEST["val"]
    ttl = CACHE_S
    try:
        top = await _sb_get(TABLE, {"select": "d", "order": "d.desc", "limit": "1"})
        if not top.ok:
            val, ttl = {"rows": {}, "reason": "official series unavailable"}, CACHE_FAIL_S
        elif not top.rows:
            val = {"rows": {}, "reason": "no official publication yet"}
        else:
            d = top.rows[0]["d"]
            rows = await _read_all(TABLE, {"select": SELECT, "d": f"eq.{d}"})
            val = {"d": d, "rows": {str(r["symbol"]).upper(): r for r in rows},
                   "code_ref": rows[0].get("code_ref") if rows else None,
                   "published_at": max((r.get("published_at") or "" for r in rows), default=None)}
    except Exception:
        val, ttl = {"rows": {}, "reason": "official series unavailable"}, CACHE_FAIL_S
    _LATEST.update({"at": t, "ttl": ttl, "val": val})
    return val


async def apply_official(data: Any) -> Any:
    from src.data.cis.cis_provider import ASSETS_CONFIG
    return overlay(data, await latest_official(), names={k: v.get("name", k) for k, v in ASSETS_CONFIG.items()})
