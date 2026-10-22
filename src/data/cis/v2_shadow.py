"""CIS v2 影子(S-668;Jazz 10-22「影子并行,过了再切」)—— 每天在 v1 正式发布之后,用同一个 d 算一遍 v2,只追加进 `cis_v2_daily`。

- 公式只来自 `src/data/cis/v2.py`(研究卡 T-169 / T-170 用的是同一个函数)。
- 加密:CIS 的 25 个(不加币);规模 / 稳定 / 供给纪律取 `asset_mcap_daily`(按 coingecko id),F / O 取**当天已发布的 v1 正式行**
  —— 所以 v1 没发,v2 不算(同一个 d、同一批收盘)。
- 个股:CIS 现有美股单股 + World50 候选池里不带 . 后缀的公司(美股挂牌 / 美元 ADR);市值 `world50_mcap_weekly`,收盘 `ohlcv_daily`(eodhd)。
- 宏观 ETF 不打分(只给状态层,S-669)。
- **档位**:只给加密(组内分位 + 与 v1 同一套滞回 `pct_step`,接前一天 v2 的档);**个股不给档位**(Jazz 10-22:合成与之后收益反向)。
- **状态**(`v2_state`,S-669):趋势标签、30 日动量与 7 日资金费(只给数值)、市场情绪 —— 描述,不是预测。
- 对外仍是 v1;Jazz 10-22:加密影子满 20 天(且 S-668 条件 ① ② 满足)即切;个股只展示状态与质量事实。

判活:`select max(d) from cis_v2_daily` = 昨天(v1 正式发布之后);`loop_attempt` 里 `_cis_v2_shadow_loop`。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from src.data.cis import v2

TABLE = "cis_v2_daily"
WRITES_TABLES = (TABLE,)
CRYPTO_LOOKBACK_DAYS = max(v2.CRYPTO_WINDOW_DAYS + 10, 210)   # 趋势标签要 SMA200
EQUITY_LOOKBACK_WEEKS = v2.EQUITY_SUPPLY_WEEKS + 4
MIN_COVERAGE = 0.95


def crypto_universe() -> dict[str, str]:
    """{CIS 符号: coingecko id}。"""
    from src.data.cis.cis_provider import CRYPTO_ASSETS
    return {s: c["coingecko"] for s, c in CRYPTO_ASSETS.items() if c.get("coingecko")}


def equity_universe(world50_keys: list[str]) -> list[str]:
    """CIS 现有美股单股 + World50 里不带 . 后缀的公司;SPY / QQQ / XLF 是 ETF,不算公司。"""
    from src.data.cis.cis_provider import US_EQUITIES
    singles = {s for s, c in US_EQUITIES.items() if c.get("class") == "US Equity" and s not in ("SPY", "QQQ", "XLF")}
    return sorted(singles | {k for k in world50_keys if "." not in k})


def weekly_closes(mcap_rows: list[dict], closes: dict[str, list[tuple[str, float]]]) -> dict[str, list[tuple]]:
    """world50 周市值 + eodhd 日收盘 → {公司: [(周日期, mcap_usd, 该周日期当天或之前最后一个收盘, shares)]}。纯函数。
    shares 原样从 world50_mcap_weekly 带过来(没有 ⇒ None);**不要**用 mcap ÷ 这个收盘推股数 —— 收盘是总回报复权的。"""
    out: dict[str, list[tuple]] = {}
    for r in sorted(mcap_rows, key=lambda r: (r["key"], str(r["d"]))):
        cs = closes.get(r["key"]) or []
        px = None
        for d, c in cs:                                   # cs 升序
            if d <= str(r["d"])[:10]:
                px = c
            else:
                break
        out.setdefault(r["key"], []).append((str(r["d"])[:10], r.get("mcap_usd"), px, r.get("shares")))
    return out


def shadow_rows(d: date, crypto: dict[str, dict], equity: dict[str, dict], published_at: str,
                states: Optional[dict[str, dict]] = None, prev_signal: Optional[dict[str, str]] = None) -> list[dict]:
    """两组的原始维度 → 写库的行(含状态;加密带档位)。纯函数。"""
    out = []
    for grp, raw in (("crypto", crypto), ("equity", equity)):
        if not raw:
            continue
        scored = v2.score_group(grp, raw)
        for name, s in sorted(scored.items()):
            out.append({"symbol": name, "d": d.isoformat(), "grp": grp, "score": s["score"], "n_dims": s["n_dims"],
                        "ranks": s["ranks"], "raw": {k: (None if v is None else round(float(v), 8))
                                                      for k, v in (raw[name] or {}).items()},
                        "missing": s["missing"], "code_ref": v2.CODE_REF, "published_at": published_at,
                        "state": (states or {}).get(name), "pct": None, "signal": None, "watch": None})
    add_bands(out, prev_signal or {})
    return out


def add_bands(rows: list[dict], prev_signal: dict[str, str]) -> None:
    """就地。只给加密:组内按 v2 分数排分位(平均名次 ÷ 人数,同 v1 `group_pct`),再走 v1 的滞回一步 `pct_step`,
    接前一天 v2 的档。个股不给档位(Jazz 10-22)。少于 5 个有分的名字不排。"""
    from src.data.cis.rebuild import LEVELS, pct_step
    sc = sorted((r for r in rows if r["grp"] == "crypto" and r["score"] is not None), key=lambda r: r["score"])
    if len(sc) < 5:
        return
    n, i = len(sc), 0
    while i < n:
        j = i
        while j + 1 < n and sc[j + 1]["score"] == sc[i]["score"]:
            j += 1
        p = ((i + j) / 2.0 + 1.0) / n
        for k in range(i, j + 1):
            sc[k]["pct"] = round(p, 4)
        i = j + 1
    for r in sc:
        prev = prev_signal.get(r["symbol"])
        lv, watch = pct_step(LEVELS.index(prev) if prev in LEVELS else None, r["pct"])
        r["signal"] = LEVELS[lv] if lv is not None else None
        r["watch"] = watch


def coverage(rows: list[dict], grp: str, universe_n: int) -> float:
    n = sum(1 for r in rows if r["grp"] == grp and r["score"] is not None)
    return n / universe_n if universe_n else 0.0


async def run_once(now: Optional[datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_insert_table
    from src.data.style.header import _read_all
    now = now or datetime.now(timezone.utc)
    d = now.date() - timedelta(days=1)
    have = await _read_all(TABLE, {"select": "symbol", "d": f"eq.{d.isoformat()}", "code_ref": f"eq.{v2.CODE_REF}",
                                   "limit": "1"})
    if have:
        return {"ok": True, "refused": False, "written": 0, "reason": f"{d} 已算 —— 只发一次"}
    official = await _read_all("cis_official_daily", {"select": "symbol,pillar_f,pillar_o", "d": f"eq.{d.isoformat()}"})
    if not official:
        return {"ok": True, "refused": True, "written": 0, "reason": f"{d} v1 正式还没发布 —— v2 跟着同一个 d,等"}
    fo = {r["symbol"]: r for r in official}
    from src.data.cis import v2_state
    prev = await _read_all(TABLE, {"select": "symbol,signal", "d": f"eq.{(d - timedelta(days=1)).isoformat()}",
                                   "code_ref": f"eq.{v2.CODE_REF}", "grp": "eq.crypto"})
    prev_signal = {r["symbol"]: r["signal"] for r in prev if r.get("signal")}
    macro = await _read_all("macro_daily", {"select": "series,d,value", "series": "in.(fng,vix)",
                                            "d": f"gte.{(d - timedelta(days=10)).isoformat()}", "order": "series.asc,d.asc"})
    mkt = {s_: [float(r["value"]) for r in macro if r["series"] == s_ and str(r["d"])[:10] <= d.isoformat()
               and r.get("value") is not None] for s_ in ("fng", "vix")}
    fng, vix = (mkt["fng"][-1] if mkt["fng"] else None), (mkt["vix"][-1] if mkt["vix"] else None)
    states: dict[str, dict] = {}
    # 加密
    cu = crypto_universe()
    lo = (d - timedelta(days=CRYPTO_LOOKBACK_DAYS)).isoformat()
    mrows = await _read_all("asset_mcap_daily", {"select": "coin_id,d,price,mcap", "coin_id": f"in.({','.join(cu.values())})",
                                                 "d": f"gte.{lo}", "order": "coin_id.asc,d.asc"})
    by_coin: dict[str, list[tuple]] = {}
    for r in mrows:
        if str(r["d"])[:10] <= d.isoformat():
            by_coin.setdefault(r["coin_id"], []).append((str(r["d"])[:10], r.get("price"), r.get("mcap")))
    frows = await _read_all("funding_history", {"select": "symbol,funding_time,funding_rate,venue",
                                                "symbol": f"in.({','.join(cu)})",
                                                "funding_time": f"gte.{(d - timedelta(days=8)).isoformat()}",
                                                "order": "symbol.asc,funding_time.asc"})
    crypto: dict[str, dict] = {}
    for sym, cid in cu.items():
        states[sym] = v2_state.state_for("crypto", [(x[0], x[1]) for x in by_coin.get(cid) or [] if x[1]], d,
                                         [r for r in frows if r["symbol"] == sym], fng)
        raw = v2.crypto_inputs(by_coin.get(cid) or [], d)
        raw["f"] = (fo.get(sym) or {}).get("pillar_f")
        raw["o"] = (fo.get(sym) or {}).get("pillar_o")
        crypto[sym] = raw
    # 个股
    wlo = (d - timedelta(weeks=EQUITY_LOOKBACK_WEEKS)).isoformat()
    # 只取一个口径(三个历史口径并存,混用会把口径差当成股数变化 —— 实测 CMCSA 在 4.6B / 4.2B 股之间来回跳)
    from src.data.universe.world50_data import MCAP_SOURCE
    keys = sorted({r["key"] for r in await _read_all("world50_mcap_weekly", {"select": "key", "d": f"gte.{wlo}",
                                                                             "source": f"eq.{MCAP_SOURCE}"})})
    eu = equity_universe(keys)
    w50 = await _read_all("world50_mcap_weekly", {"select": "key,d,mcap_usd,shares", "key": f"in.({','.join(eu)})",
                                                  "source": f"eq.{MCAP_SOURCE}", "d": f"gte.{wlo}",
                                                  "order": "key.asc,d.asc"})
    px = await _read_all("ohlcv_daily", {"select": "symbol,trade_date,close", "source": "eq.eodhd",
                                         "symbol": f"in.({','.join(eu)})", "trade_date": f"gte.{wlo}",
                                         "order": "symbol.asc,trade_date.asc"})
    closes: dict[str, list[tuple[str, float]]] = {}
    for r in px:
        if str(r["trade_date"])[:10] <= d.isoformat() and r.get("close"):
            closes.setdefault(r["symbol"], []).append((str(r["trade_date"])[:10], float(r["close"])))
    weekly = weekly_closes([r for r in w50 if str(r["d"])[:10] <= d.isoformat()], closes)
    equity = {k: v2.equity_inputs(weekly.get(k) or [], d) for k in eu}
    for k in eu:
        states[k] = v2_state.state_for("equity", closes.get(k) or [], d, (), vix)
    rows = shadow_rows(d, crypto, equity, now.isoformat(), states, prev_signal)
    cov = {"crypto": round(coverage(rows, "crypto", len(cu)), 4), "equity": round(coverage(rows, "equity", len(eu)), 4)}
    res = await supabase_insert_table(TABLE, rows)
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    low = [g for g, c in cov.items() if c < MIN_COVERAGE]
    return {"ok": True, "refused": False, "written": len(rows), "d": d.isoformat(), "coverage": cov,
            "reason": f"{d} v2 影子 {len(rows)} 行(加密 {len(cu)} / 个股 {len(eu)})"
                      + (f" · 有分比例低于 {MIN_COVERAGE:.0%}:{low}(S-668 切换条件 ① 这天不算)" if low else "")}
