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


#: 缺了就不发的(过了 UTC 06:00 也不发,心跳变红);其余的(恐惧贪婪、BTC 占比)过点照发并标在 missing 里(S-538)。
HARD_PREFIXES = ("BTC 没有价格", "加密名字有价的")


def is_hard(problem: str) -> bool:
    return problem.startswith(HARD_PREFIXES)


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


def merge_prev_rows(official: list[dict], rebuild: list[dict]) -> dict[str, dict]:
    """纯函数。前一天每个名字的 {grade, signal}:正式发布过的优先;正式表里没有的名字(新进宇宙、迁移换了代码)取同版本重建的。"""
    out = {r["symbol"]: {"grade": r.get("grade"), "signal": r.get("signal_pct")} for r in rebuild}
    out.update({r["symbol"]: {"grade": r.get("grade"), "signal": r.get("signal")} for r in official})
    return out


def merge_prev(official: list[dict], rebuild: list[dict]) -> dict[str, Optional[int]]:
    """纯函数。前一天的档(滞回用)。"""
    return {k: (LEVELS.index(v["signal"]) if v.get("signal") in LEVELS else None)
            for k, v in merge_prev_rows(official, rebuild).items()}


async def _prev_rows(d: date) -> dict[str, dict]:
    """前一天的正式等级 / 档;正式表里没有的名字取重建序列的前一天(S-537:SKY 第一次进正式表时接重建的链)。
    同版本重建还没写完 → {}(调用方等,不在半截上接)。"""
    from src.data.style.header import _read_all
    y = (d - timedelta(days=1)).isoformat()
    off = await _read_all(TABLE, {"select": "symbol,grade,signal", "d": f"eq.{y}"})
    reb = await _read_all("cis_rebuild_daily", {"select": "symbol,grade,signal_pct", "d": f"eq.{y}",
                                                "code_ref": f"eq.{CODE_REF}"})
    if not reb:
        return {}
    return merge_prev_rows(off, reb)


async def _prev_levels(d: date) -> dict[str, Optional[int]]:
    rows = await _prev_rows(d)
    return {k: (LEVELS.index(v["signal"]) if v.get("signal") in LEVELS else None) for k, v in rows.items()}


GRADE_RANK = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
SIGNAL_RANK = {"STRONG OUTPERFORM": 5, "OUTPERFORM": 4, "NEUTRAL": 3, "UNDERPERFORM": 2, "UNDERWEIGHT": 1}


def change_events(out: list[dict], prev: Mapping[str, Mapping[str, Any]]) -> dict[str, list[dict]]:
    """纯函数。正式一批 vs 前一天 → GRADE_UPGRADE / GRADE_DOWNGRADE / SIGNAL_CHANGE(载荷形状沿用实时推送的)。"""
    ups, downs, sigs = [], [], []
    for r in out:
        sym, p = r["symbol"], prev.get(r["symbol"])
        if not p:
            continue
        g0, g1, s0, s1 = p.get("grade"), r.get("grade"), p.get("signal"), r.get("signal")
        base = {"symbol": sym, "asset_class": r.get("asset_class"), "cis_score": r.get("cis_score"), "official_date": r["d"]}
        if g0 and g1 and g0 != g1:
            ev = {**base, "from": g0, "to": g1, "delta": GRADE_RANK.get(g1, 0) - GRADE_RANK.get(g0, 0),
                  "old_signal": s0, "new_signal": s1}
            (ups if ev["delta"] > 0 else downs).append(ev)
        elif s0 and s1 and s0 != s1:
            sigs.append({**base, "from": s0, "to": s1, "delta": SIGNAL_RANK.get(s1, 0) - SIGNAL_RANK.get(s0, 0),
                         "grade": g1})
    return {"GRADE_UPGRADE": ups, "GRADE_DOWNGRADE": downs, "SIGNAL_CHANGE": sigs}


async def publish_events(out: list[dict], prev: Mapping[str, Mapping[str, Any]], d: date) -> dict[str, Any]:
    """S-539:对外的变化事件只在正式发布时发一次 —— webhook、Telegram(高等级上调)、信号日志。尽力而为,不挡发布。"""
    res: dict[str, Any] = {}
    evs = change_events(out, prev)
    regime = next((r.get("regime") for r in out if r.get("regime")), "") or ""
    try:
        from src.api.routers.webhooks import fire_grade_webhooks
        for name, items in evs.items():
            if items:
                await fire_grade_webhooks(event=name, assets=items, regime=regime)
        res["webhooks"] = {k: len(v) for k, v in evs.items()}
    except Exception as e:                                  # noqa: BLE001
        res["webhooks_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    notable = [a for a in evs["GRADE_UPGRADE"] if a.get("to") in ("A+", "A", "B+")]
    if notable:
        try:
            from src.api.notify import notify_telegram
            from src.api.telegram_bot import broadcast_subscribers
            msg = "\n".join([f"📈 CIS grade upgrades (official, UTC close {d.isoformat()})"] +
                             [f"  {a['symbol']}: {a['from']}→{a['to']}" + (f" · {a['new_signal']}" if a.get("new_signal") else "")
                              for a in notable[:8]])
            await notify_telegram(msg)
            await broadcast_subscribers(msg)
            res["telegram"] = len(notable)
        except Exception as e:                              # noqa: BLE001
            res["telegram_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    try:
        from src.api.routers.signals import log_official_signals
        res["journal"] = await log_official_signals(out, d.isoformat())
    except Exception as e:                                  # noqa: BLE001
        res["journal_error"] = f"{type(e).__name__}: {str(e)[:100]}"
    return res


async def _close_inputs_ready(d: date) -> bool:
    """便宜的预检:d 的加密收盘(≥ 90% 的名字)与全市场市值 / 恐惧贪婪都已落库。读不到当作没齐(会去补)。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    from src.data.style.header import SOURCE, _read_all
    coins = [c["coingecko"] for c in CRYPTO_ASSETS.values() if c.get("coingecko")]
    try:
        have = await _read_all("asset_mcap_daily", {"select": "coin_id", "source": f"eq.{SOURCE}", "d": f"eq.{d.isoformat()}",
                                                    "coin_id": f"in.({','.join(coins)})"})
        mac = await _read_all("macro_daily", {"select": "series", "d": f"eq.{d.isoformat()}",
                                              "series": "in.(total_mcap,fng)"})
    except Exception:                                       # noqa: BLE001
        return False
    return len({r["coin_id"] for r in have}) >= MIN_CRYPTO_PRICED * len(coins) and \
        {r["series"] for r in mac} >= {"total_mcap", "fng"}


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
    refreshed = None
    if not await _close_inputs_ready(d):
        # S-538:收盘输入还没落库(每日采集跑在一天里的哪个钟点不由发布器决定)—— 自己补,再算
        from src.data.market.cis_inputs import refresh_close_inputs
        try:
            refreshed = await refresh_close_inputs(now)
        except Exception as e:                              # noqa: BLE001
            refreshed = {"error": f"{type(e).__name__}: {str(e)[:120]}"}
    assets, data = await load_inputs(pd.Timestamp(d))
    rows = score_day(pd.Timestamp(d), assets, data)
    probs = completeness(rows, assets)
    hard = [p for p in probs if is_hard(p)]
    if hard:
        # 硬性输入缺(BTC / 大部分加密名字没有收盘)—— 永远不发半批;过了 06:00 还缺 = 心跳红
        return {"ok": now.hour < PUBLISH_DEADLINE_HOUR, "refused": True, "written": 0, "refreshed": refreshed,
                "reason": f"{d} 缺硬性输入({'; '.join(hard)})—— 不发,下一小时再补再试"}
    if probs and now.hour < PUBLISH_DEADLINE_HOUR:
        return {"ok": True, "refused": True, "written": 0, "refreshed": refreshed,
                "reason": f"{d} 数据还不齐({'; '.join(probs)})—— UTC {PUBLISH_DEADLINE_HOUR}:00 前等"}
    group_pct(rows)
    prev_rows = await _prev_rows(d)
    prev = {k: (LEVELS.index(v["signal"]) if v.get("signal") in LEVELS else None) for k, v in prev_rows.items()}
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
    events = await publish_events(out, prev_rows, d)
    return {"ok": True, "refused": False, "written": len(out), "d": d.isoformat(), "signals": dist,
            "incomplete": probs, "events": events, "refreshed": bool(refreshed),
            "reason": f"{d} 发布 {len(out)} 个名字" + (f"(不齐:{probs})" if probs else "")}


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


# ── 对外:历史与变化也只用正式序列(Jazz 10-12「不同页面显示不同打分」,S-539)──────────────
#
# 正式序列的历史 = 已发布(cis_official_daily)优先,之前的日子用同版本按时点重建(cis_rebuild_daily)。
# 每个点带 provenance(published / reconstructed)。字段沿用旧接口的名字(score / grade / signal / pillar_* /
# macro_regime / recorded_at),页面不用改取数,只是数从同一条序列来。

HIST_REB_COLS = "symbol,d,asset_class,raw_score,score,grade,signal_pct,pct,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,regime"
HIST_OFF_COLS = ("symbol,d,asset_class,cis_score,regime_adjusted_score,grade,signal,pct,"
                 "pillar_f,pillar_m,pillar_o,pillar_s,pillar_a,regime,code_ref")


def history_rows(official: list[dict], rebuild: list[dict], cap: Optional[str] = None) -> dict[str, list[dict]]:
    """纯函数。两张表的行 → {symbol: [点,旧→新]}。同一天已发布的优先。
    cap = 最近一次正式发布的日子:重建里比它新的日子不出 —— 历史的最后一点不能抢在正式发布前面(否则走势图上
    出现一个页面上还没发布的分数)。"""
    pts: dict[tuple[str, str], dict] = {}
    for r in rebuild or []:
        k = (str(r["symbol"]).upper(), str(r["d"])[:10])
        if cap and k[1] > cap:
            continue
        pts[k] = {"symbol": k[0], "d": k[1], "recorded_at": k[1], "asset_class": r.get("asset_class"),
                  "score": _r(r.get("raw_score")), "raw_cis_score": _r(r.get("raw_score")),
                  "regime_adjusted_score": _r(r.get("score")), "grade": r.get("grade"), "signal": r.get("signal_pct"),
                  "group_percentile": r.get("pct"), "macro_regime": r.get("regime"),
                  **{f"pillar_{p}": _r(r.get(f"pillar_{p}")) for p in "fmosa"},
                  "provenance": "reconstructed", "source": "cis_rebuild_daily"}
    for r in official or []:
        k = (str(r["symbol"]).upper(), str(r["d"])[:10])
        pts[k] = {"symbol": k[0], "d": k[1], "recorded_at": k[1], "asset_class": r.get("asset_class"),
                  "score": r.get("cis_score"), "raw_cis_score": r.get("cis_score"),
                  "regime_adjusted_score": r.get("regime_adjusted_score"), "grade": r.get("grade"),
                  "signal": r.get("signal"), "group_percentile": r.get("pct"), "macro_regime": r.get("regime"),
                  **{f"pillar_{p}": r.get(f"pillar_{p}") for p in "fmosa"},
                  "provenance": "published", "source": TABLE}
    out: dict[str, list[dict]] = {}
    for (sym, _), p in sorted(pts.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        out.setdefault(sym, []).append(p)
    for rows in out.values():
        prev = None
        for p in rows:
            p["score_delta"] = round(p["score"] - prev, 2) if p.get("score") is not None and prev is not None else None
            prev = p.get("score")
    return out


async def standard_history(symbols: list[str], days: int, today: Optional[date] = None) -> dict[str, list[dict]]:
    """正式序列最近 days 天(旧→新)。读不到抛异常 —— 读不到 ≠ 没有历史(S-180)。"""
    from src.data.cis.rebuild import CODE_REF as STD_REF, TABLE as REBUILD
    from src.data.style.header import _read_all
    syms = sorted({s.upper() for s in symbols if s})
    if not syms:
        return {}
    start = ((today or datetime.now(timezone.utc).date()) - timedelta(days=int(days))).isoformat()
    flt = {"symbol": f"in.({','.join(syms)})", "d": f"gte.{start}"}
    off = await _read_all(TABLE, {"select": HIST_OFF_COLS, **flt, "order": "d.asc,symbol.asc"})
    reb = await _read_all(REBUILD, {"select": HIST_REB_COLS, **flt, "code_ref": f"eq.{STD_REF}",
                                    "order": "d.asc,symbol.asc"})
    latest = await latest_official()
    cap = str(latest["d"])[:10] if latest.get("d") else None
    out = history_rows(off, reb, cap)
    return {s: out.get(s, []) for s in syms}


def official_changes(history: Mapping[str, list[dict]], lookback_days: int) -> dict[str, Any]:
    """纯函数。每个名字:最新一点 vs lookback_days 天前(或最早)那一点 —— 等级与档位的变化。"""
    grade_rank = {"A+": 8, "A": 7, "B+": 6, "B": 5, "C+": 4, "C": 3, "D": 2, "F": 1}
    ups, downs, sig_changes, stable = [], [], [], 0
    for sym, rows in history.items():
        if len(rows) < 2:
            stable += 1
            continue
        last = rows[-1]
        cut = (date.fromisoformat(last["d"]) - timedelta(days=max(1, lookback_days))).isoformat()
        base = next((r for r in reversed(rows[:-1]) if r["d"] <= cut), rows[0])
        g0, g1 = grade_rank.get(base.get("grade"), 0), grade_rank.get(last.get("grade"), 0)
        item = {"symbol": sym, "from_grade": base.get("grade"), "to_grade": last.get("grade"),
                "from_signal": base.get("signal"), "to_signal": last.get("signal"),
                "from_score": base.get("score"), "to_score": last.get("score"),
                "score_delta": round(last["score"] - base["score"], 2)
                if last.get("score") is not None and base.get("score") is not None else None,
                "from_date": base["d"], "to_date": last["d"], "provenance": last.get("provenance"),
                # 旧接口的字段名(页面在用)
                "delta": g1 - g0, "cis_score": last.get("score"), "signal": last.get("signal"), "changed_at": last["d"]}
        if g1 > g0:
            ups.append(item)
        elif g1 < g0:
            downs.append(item)
        else:
            stable += 1
        if base.get("signal") != last.get("signal"):
            sig_changes.append(item)
    ups.sort(key=lambda x: (-x["delta"], -(x["score_delta"] or 0)))
    downs.sort(key=lambda x: (x["delta"], x["score_delta"] or 0))
    return {"upgrades": ups, "downgrades": downs, "signal_changes": sig_changes, "stable_count": stable,
            "checked": len(history), "total_changes": len(ups) + len(downs)}


# ── 市场状态(regime)也只有一份(S-539)────────────────────────────────────────────
#
# 实测 10-12:CIS 页 RISK_ON(正式日终),宏观脉搏 / 档位带 / 简报 TIGHTENING(Mac T1 推送的状态,或 FRED / EODHD 推出来的)。
# 对外显示的状态 = 最近一次正式发布那天的状态;实时引擎的状态放进 `intraday_regime`(盘中预览)。
# 只改对外响应,不改喂给实时引擎的 `cis:regime`(那是盘中引擎的输入)。

def regime_overlay(data: Any, latest: Optional[Mapping[str, Any]]) -> Any:
    """纯函数,不改入参。宏观脉搏一类响应:macro_regime 换成正式那天的,原值挪进 intraday_regime。"""
    if not isinstance(data, dict):
        return data
    regimes = {r.get("regime") for r in ((latest or {}).get("rows") or {}).values() if r.get("regime")}
    if len(regimes) != 1:
        return data
    out = dict(data)
    out["intraday_regime"] = {"macro_regime": data.get("macro_regime"), "regime_source": data.get("regime_source")}
    out["macro_regime"] = regimes.pop()
    out["regime_source"] = "official_daily_close"
    out["regime_as_of"] = str(latest.get("d"))
    return out


def regime_transitions(points: list[dict]) -> list[dict]:
    """纯函数。[{d, regime, provenance}](旧→新)→ 状态切换(新→旧)。"""
    out, prev = [], None
    for p in sorted(points, key=lambda x: x["d"]):
        if prev is not None and p.get("regime") and prev.get("regime") and p["regime"] != prev["regime"]:
            out.append({"symbol": None, "previous_regime": prev["regime"], "new_regime": p["regime"],
                        "transition_time": p["d"], "provenance": p.get("provenance")})
        if p.get("regime"):
            prev = p
    return list(reversed(out))



# ── 协议页:协议评分不是 CIS(S-541)────────────────────────────────────────────────
#
# 实测 10-12:协议页把另一套方法(TVL / 审计 / 资金流,`protocol_engine`)也叫「CIS」并给档位 ——
# Aave A+ 96.4 STRONG OUTPERFORM,而 CIS 页的 AAVE 是 B 63.4;Sky A+ 90 vs C+ 51。同一个名字两个「CIS」。
# 对外:协议自己的分叫 protocol_score / protocol_grade,不再带定位档位;`cis_*` 只放正式 CIS(协议有对应代币时)。

#: 协议 id → CIS 宇宙里的代币
PROTOCOL_TOKEN = {"aave": "AAVE", "uniswap": "UNI", "lido": "LDO", "pendle": "PENDLE", "ondo": "ONDO",
                  "maker": "SKY", "hyperliquid": "HYPE"}


def protocol_view(result: Any, latest: Optional[Mapping[str, Any]]) -> Any:
    """纯函数(深拷贝,不动缓存)。协议宇宙响应 → 协议分与正式 CIS 分开。"""
    import copy
    if not isinstance(result, dict):
        return result
    out = copy.deepcopy(result)
    rows = (latest or {}).get("rows") or {}
    for p in out.get("protocols") or []:
        p["protocol_score"] = p.pop("cis_score", None)
        p["protocol_grade"] = p.pop("grade", None)
        p.pop("signal", None)                                  # 定位档位只属于正式 CIS
        p["protocol_pillars"] = p.get("pillars")
        tok = PROTOCOL_TOKEN.get(p.get("id"))
        r = rows.get(tok) if tok else None
        p["cis"] = ({"symbol": tok, "cis_score": r.get("cis_score"), "grade": r.get("grade"), "signal": r.get("signal"),
                     "official_date": str(latest.get("d"))} if r else None)
        p["cis_score"] = r.get("cis_score") if r else None
        p["grade"] = r.get("grade") if r else None
        p["signal"] = r.get("signal") if r else None
    for c in (out.get("categories") or {}).values():
        if isinstance(c, dict) and "avg_score" in c:
            c["avg_protocol_score"] = c.pop("avg_score")
    ranked = sorted(out.get("protocols") or [], key=lambda p: -(p.get("protocol_score") or 0))
    out["agent_picks"] = [p["id"] for p in ranked if p.get("protocol_grade") in ("A+", "A")][:5]
    out["score_basis"] = ("protocol_score: CometCloud protocol scoring (TVL scale and flows, audits, age, peers) — a "
                          "separate method from CIS. cis_*: the official CIS of the protocol's token, where it is in "
                          "the CIS universe.")
    return out
