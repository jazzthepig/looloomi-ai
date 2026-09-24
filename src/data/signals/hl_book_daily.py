"""HL 4 币组合的每日「只算不发」—— 五条前向记录,一个调度器,一张表(S-413)。

每天一行 `hl_book_daily`,对应一根**已收盘**的日线(UTC,价格走 `panel_read`,资金费走 `funding_history`)。五个臂:

    H0_hold          等权持有(基准)
    T3_weekly        趋势规则,每周一决策 + 0.2 不动带   ← 实盘执行器首版就跑它
    MECH_tom         机械 Tom
    JEV_tom          Jev 回答全部四类问题
    JEV_trend_only   只用 Jev 的「趋势确认」,其余机械       ← S-412 事后归因提出的假设

决策内核是 `paper_trading/hl_book.py`,和 3.4 年回放 `jev_replay_s412.py` 是同一份代码:
**回放里的仓位,就是这里那天会算出的仓位。** 口径也相同 —— t 日收盘决策,
t+1 收盘成交,吃 t+2 的收益;成本和资金费同 S-409。

## 状态存在表里,不存在进程里

每一行带着 `decided`(决策后的目标仓位)、`held`(当天实际持有,= 两天前的 decided)、
`book`(每臂每币上次决策时的仓位和价格,用来判断「是否在赚钱」)和 `nav`。
下一行只读上一两行就能算,Railway 重启不丢状态。

## Jev 失败 fail-closed

Jev 调用失败:`jev_error` 写明原因,两个 Jev 臂**保持上次仓位**(不补机械答案冒充),
同一天后续轮次会重试。**这是研究记录,「没接通」必须看起来像没接通。**

## 判活判据(规则 5b ②)

    select max(d) from hl_book_daily;        -- UTC 01:00 之后应 = 昨天
    select count(*) from hl_book_daily where is_decision and jev_error is not null;  -- 应为 0
"""
from __future__ import annotations

import asyncio
import os
import random
from typing import Any, Optional

import pandas as pd

TABLE = "hl_book_daily"
WRITES_TABLES = (TABLE,)
ARMS = ("H0_hold", "T3_weekly", "MECH_tom", "JEV_tom", "JEV_trend_only")
JEV_ARMS = ("JEV_tom", "JEV_trend_only")
MAX_BACKFILL_DAYS = 14
HISTORY_DAYS = 270
COINS_ = ("BTC", "ETH", "SOL", "HYPE")
PRICE_SOURCE = "coingecko_pro_ohlc"


# ───────────────────────── 输入 ─────────────────────────
#
# 价格走 `panel_read.read_panel`(账本读价的唯一入口,S-302),**不自己出去打外网**。
# 首版直接调场馆 K 线,preflight 的 Sense 入口预算当场 25 > 24 —— 那条守卫是对的:
# 再多一条私有取数路径,就多一处「两本账对同一资产用不同价格」的可能。
# 资金费读 `funding_history`(HL 采集器已落库),也不出网。

async def live_inputs(target: pd.Timestamp) -> tuple[pd.DataFrame, pd.DataFrame, str]:
    """→ (px, fd, 未就绪原因)。原因非空 = 这一轮不该算,等下一轮。

    就绪判据:四个币 target 那根 bar 都在,**且都是 target 收盘之后写入的**。
    实测 2026-09-24:面板 bar 一般在次日 01:00–06:00 UTC 写入(终值),但也存在
    当天写入、之后没被覆盖的半根(HYPE 09-19 记录于 09-19 09:05)。
    所以看 `recorded_at`,不看「有没有这根 bar」。
    """
    from src.data.market.panel_read import read_panel
    start = (target - pd.Timedelta(days=HISTORY_DAYS)).date().isoformat()
    p = await read_panel(list(COINS_), start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    filled = pd.DataFrame(p.filled, index=idx, columns=p.symbols)
    px = px.mask(filled)                                  # 前推的价格不是价格
    missing = [c for c in COINS_ if c not in px.columns or target not in px.index
               or pd.isna(px.at[target, c])]
    if missing:
        return px, pd.DataFrame(), f"{target.date()} 的收盘缺 {missing}"
    rec = await _recorded_at(target)
    close_ts = target + pd.Timedelta(days=1)
    not_final = [c for c in COINS_ if c not in rec or rec[c] < close_ts]
    if not_final:
        return px, pd.DataFrame(), (f"{target.date()} 的 bar 是收盘前写入的半根 "
                                    f"或读不到写入时间:{not_final}")
    px = px.loc[:target]
    fd = await _funding_daily(target)
    return px, fd.reindex(px.index), ""


async def _supabase_get(url_tail: str) -> list[dict]:
    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(f"{base}/rest/v1/{url_tail}",
                        headers={"apikey": key, "Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise RuntimeError(f"读 {url_tail.split('?')[0]} HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


async def _recorded_at(target: pd.Timestamp) -> dict[str, pd.Timestamp]:
    rows = await _supabase_get(
        f"ohlcv_daily?select=symbol,recorded_at&source=eq.{PRICE_SOURCE}"
        f"&symbol=in.({','.join(COINS_)})&trade_date=eq.{target.date().isoformat()}")
    return {r["symbol"]: pd.Timestamp(r["recorded_at"]).tz_convert("UTC").tz_localize(None)
            for r in rows if r.get("recorded_at")}


async def _funding_daily(target: pd.Timestamp) -> pd.DataFrame:
    """HL 资金费,按日:当天小时费率的均值 × 24。采集器是抽样写入(非每小时一条),
    直接求和会低估,所以用均值 × 24。"""
    since = (target - pd.Timedelta(days=10)).date().isoformat()
    rows = await _supabase_get(
        f"funding_history?select=symbol,funding_time,funding_rate"
        f"&venue=eq.hyperliquid&symbol=in.({','.join(COINS_)})&funding_time=gte.{since}"
        f"&order=funding_time.asc&limit=1000")
    if len(rows) >= 1000:
        raise RuntimeError("funding_history 10 天读满 1000 行,可能被截断 —— 缩短窗口或分页")
    f = pd.DataFrame(rows)
    if f.empty:
        return pd.DataFrame(columns=list(COINS_))
    f["d"] = pd.to_datetime(f["funding_time"], utc=True).dt.tz_localize(None).dt.normalize()
    return f.groupby(["d", "symbol"])["funding_rate"].mean().unstack() * 24


# ───────────────────────── 单日计算(纯函数,可离线测)─────────────────────────

def _answers_dict(a) -> dict:
    return {"trend_confirmed": a.trend_confirmed, "crowded": a.crowded,
            "capitulation": a.capitulation, "mode": a.mode}


def compute_row(hb, px: pd.DataFrame, fd: pd.DataFrame, d: pd.Timestamp,
                prev: Optional[dict], prev2: Optional[dict], jev_call) -> dict:
    """算 d 这一天的记录。`prev`/`prev2` = d−1 / d−2 的已存行(可为 None = 起点)。

    `jev_call(feats, bstate, rng) -> Answers`;抛异常 = Jev 失败(fail-closed)。
    """
    feats = hb.features_at(px, fd, d)
    if not feats:
        raise RuntimeError(f"{d.date()} 没有任何币满足 200 天历史 —— 特征为空")
    is_decision = prev is None or d.weekday() == 0
    decided_prev = (prev or {}).get("decided") or {a: {} for a in ARMS}
    book_prev = (prev or {}).get("book") or {a: {} for a in ARMS}

    def bstate(arm):
        return {c: {"w": v["w"], "ret_since": float(px[c].loc[d] / v["px"] - 1)}
                for c, v in book_prev.get(arm, {}).items()}

    decided, book = dict(decided_prev), dict(book_prev)
    mech_d, jev_raw, jev_error = None, None, None
    if is_decision:
        mech = hb.mechanical_answers(feats)
        mech_d = _answers_dict(mech)
        cur = {a: dict(decided_prev.get(a, {})) for a in ARMS}
        new = {
            "H0_hold": {c: 1.0 for c in feats},
            "T3_weekly": hb.apply_turnover_limits({c: hb.t3_base(f) for c, f in feats.items()}, cur["T3_weekly"]),
            "MECH_tom": hb.apply_turnover_limits(hb.tom_targets(feats, mech, bstate("MECH_tom")), cur["MECH_tom"]),
        }
        try:
            rng = random.Random(int(d.strftime("%Y%m%d")))
            ja = jev_call(feats, bstate("JEV_tom"), rng)
            jev_raw = ja.raw
            new["JEV_tom"] = hb.apply_turnover_limits(hb.tom_targets(feats, ja, bstate("JEV_tom")), cur["JEV_tom"])
            trend_only = hb.Answers(ja.trend_confirmed, mech.crowded, mech.capitulation, mech.mode)
            new["JEV_trend_only"] = hb.apply_turnover_limits(
                hb.tom_targets(feats, trend_only, bstate("JEV_trend_only")), cur["JEV_trend_only"])
        except Exception as e:                                        # noqa: BLE001
            jev_error = f"{type(e).__name__}: {str(e)[:300]}"
            for a in JEV_ARMS:
                new[a] = cur[a]                                       # 保持上次仓位,不冒充
        for a in ARMS:
            decided[a] = {c: float(w) for c, w in new[a].items()}
            book[a] = {c: {"w": float(w), "px": float(px[c].loc[d])} for c, w in new[a].items() if w != 0}

    # 第 d 天实际持有 = d−2 的决策;成本按 d−1 → d 的持有变化算
    held = (prev2 or {}).get("decided") or {a: {} for a in ARMS}
    held_prev = (prev or {}).get("held") or {a: {} for a in ARMS}
    r = px.pct_change().loc[d]
    ret, nav = {}, {}
    for a in ARMS:
        h, hp = held.get(a, {}), held_prev.get(a, {})
        n = max(len(h), 1)
        tot = 0.0
        for c in set(h) | set(hp):
            w, wp = float(h.get(c, 0.0)), float(hp.get(c, 0.0))
            s, sp = min(max(w, 0.0), 1.0), min(max(wp, 0.0), 1.0)
            p, pp = w - s, wp - sp
            rc = float(r.get(c)) if pd.notna(r.get(c)) else 0.0
            fc = float(fd[c].loc[d]) if c in fd and pd.notna(fd[c].loc[d]) else 0.0
            tot += w * rc - abs(s - sp) * hb.COST_SPOT - abs(p - pp) * hb.COST_PERP - p * fc
        ret[a] = round(tot / n, 8) if h else 0.0
        nav[a] = round(float(((prev or {}).get("nav") or {}).get(a, 1.0)) * (1 + ret[a]), 8)

    clean = {c: {k: (round(v, 6) if isinstance(v, float) else v) for k, v in f.items()} for c, f in feats.items()}
    return {
        "d": d.date().isoformat(), "is_decision": bool(is_decision), "n_coins": len(feats),
        "features": clean, "mech_answers": mech_d, "jev_raw": jev_raw, "jev_error": jev_error,
        "decided": decided, "held": held, "book": book, "ret": ret, "nav": nav,
        "code_ref": os.environ.get("RAILWAY_GIT_COMMIT_SHA", "")[:12] or None,
    }


# ───────────────────────── 读写 ─────────────────────────

async def _read_recent(n: int = 3) -> list[dict]:
    import httpx
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        raise RuntimeError("SUPABASE_URL / SUPABASE_KEY 不在环境里")
    url = f"{base}/rest/v1/hl_book_daily?select=*&order=d.desc&limit={n}"
    async with httpx.AsyncClient(timeout=10) as c:
        r = await c.get(url, headers={"apikey": key, "Authorization": f"Bearer {key}"})
    if r.status_code != 200:
        raise RuntimeError(f"读 hl_book_daily HTTP {r.status_code}: {r.text[:200]}")
    return r.json()


async def run_once() -> dict[str, Any]:
    """补齐到昨天那根已收盘日线。幂等:已记录且无需重试 ⇒ refused(没活干)。"""
    from paper_trading import hl_book as hb
    from src.api.store import supabase_upsert_table

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    rows = await _read_recent(3)
    by_d = {pd.Timestamp(r["d"]): r for r in rows}
    last_d = max(by_d) if by_d else None
    retry = last_d == target and by_d[target].get("is_decision") and by_d[target].get("jev_error")
    if last_d is not None and last_d >= target and not retry:
        return {"ok": True, "refused": True, "reason": f"{target.date()} 已记录", "written": 0}

    px, fd, not_ready = await live_inputs(target)
    if not_ready:
        # 数据没就绪不是故障:面板循环还没写到收盘后的终值。等下一轮。
        # 但收盘后 30 小时还没就绪就是故障了 —— 「等」不能无限期地显示成健康。
        late_h = (pd.Timestamp.now(tz="UTC").tz_localize(None) - (target + pd.Timedelta(days=1))
                  ).total_seconds() / 3600
        if late_h > 30:
            return {"ok": False, "refused": False, "written": 0,
                    "reason": f"收盘后 {late_h:.0f}h 仍未就绪:{not_ready}"}
        return {"ok": True, "refused": True, "written": 0, "reason": f"未就绪:{not_ready}"}

    key = os.environ.get("JEV_API_KEY")
    client = hb.JevClient(cache_file=_jev_cache_path(), api_key=key)

    def jev_call(feats, bstate, rng):
        return hb.jev_answers(client, feats, bstate, rng)

    if retry:
        start = target
    elif last_d is None:
        start = target                                   # 起点:从昨天开始记
    elif (target - last_d).days > MAX_BACKFILL_DAYS:
        # 断档太久:补的话 prev 读不到 ⇒ NAV 会悄悄从 1.0 重来。宁可红灯等人决定。
        return {"ok": False, "refused": False, "written": 0,
                "reason": f"断档 {(target - last_d).days} 天 > {MAX_BACKFILL_DAYS},不自动补;"
                          f"需要人决定是补历史还是开新起点"}
    else:
        start = last_d + pd.Timedelta(days=1)
    written, errors = 0, []
    for d in pd.date_range(start, target, freq="D"):
        prev = by_d.get(d - pd.Timedelta(days=1))
        prev2 = by_d.get(d - pd.Timedelta(days=2))
        row = await asyncio.to_thread(compute_row, hb, px, fd, d, prev, prev2, jev_call)
        res = await supabase_upsert_table(TABLE, [row], on_conflict="d")
        if not res.ok:
            return {"ok": False, "refused": False, "written": written,
                    "reason": f"写 {d.date()} 失败:{res.why}"}
        by_d[d] = row
        written += 1
        if row["jev_error"]:
            errors.append(f"{d.date()} {row['jev_error'][:120]}")
    return {"ok": not errors, "refused": False, "written": written,
            "reason": ("Jev 失败:" + "; ".join(errors)) if errors else f"写到 {target.date()}",
            "nav": by_d[target]["nav"]}


def _jev_cache_path():
    """同一天重试时不重复计费用的去重缓存。**不是记录** —— Jev 的原始回答落在行的 `jev_raw` 里,
    这个文件随进程消失也不丢任何东西。"""
    from pathlib import Path
    return Path(os.environ.get("HL_BOOK_STATE_DIR", "/tmp")) / "hl_book_jev_cache.jsonl"
