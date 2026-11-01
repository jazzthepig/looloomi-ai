"""真钱账户每日快照(P1,docs/PORTFOLIO_LAYER_DESIGN.md;Jazz 10-29「每日快照锚定」)。

## 从哪来

东京执行主机每小时一次心跳(`loop_attempt`,loop_name = executor_host):现货余额 + 账户模式 + 永续仓位与浮动盈亏
(心跳里的 `account` 段,10-29 起)。某一 UTC 日 d 的快照 = 那天**最后一次**心跳,按 d 的收盘价(`ohlcv_daily`
binance_hist)给现货币估值;USDC 记 1。**地址不进表**:读出入金要用它(HL 公开接口),只在内存里用。

## 净值(收益口径)

    nav_d = nav_{d−1} × (equity_d − flows_d) ÷ equity_{d−1}       开账日 nav = 1

`flows_d` = 那一天的外部出入金(HL `userNonFundingLedgerUpdates`:deposit / withdraw / send / spotTransfer /
internalTransfer / subAccountTransfer 按方向记;同一地址自己划转 = 内部,不算)。**认不出的类型不猜**:那天
`nav` 留空、`note` 写出类型 —— 一个被出入金推高的净值比一个空格更糟(规则 9)。

## 写一次不改

每个完成的 UTC 日写一行,写过就不再写(前向记录);锚定在 `anchor.SOURCES`。证据面只给收益,不给美元额。

## 独立核对(11-01,Jazz「要的」)

快照里的余额来自主机心跳 —— 主机是**同一个**写入方,它读错 / 停了 / 被改了,快照照单全收。所以写最近一天的行之前,
Railway 自己再向 HL 公开接口(`spotClearinghouseState`,只要地址,不要 key)读一次现在的现货余额,与心跳里的数量逐币对照:
心跳之后没有成交(`loop_attempt` 里没有带单的 cycle)⇒ 两边应当一样;差超过容差 ⇒ `note` 写明、Telegram 报。
**不一致也照写**(快照仍是心跳口径,规则写在 `rule`),但写着「与 HL 对不上」—— 这是报警不是修正。
手动交易也会在这里露出来(Jazz 11-01:以后不在这个账户手动交易)。

判活:`select d, equity_usd, nav, account_mode, note from live_account_daily order by d desc limit 3`。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

TABLE = "live_account_daily"
OPEN_DATE = "2026-10-29"           # 主机 10-29 14:48 UTC 恢复;这一天有心跳
RULE = "live_account_v1:P1(当天最后一次心跳;现货按当日收盘;nav 扣外部出入金;认不出的出入金类型 ⇒ nav 留空)"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"live_account_daily": ("d", "equity_usd", "usdc", "spot_usd", "perp_upnl", "perp_positions", "account_mode",
                          "flows_usd", "nav", "ret", "heartbeat_at", "n_heartbeats", "note", "rule")}
#: HL 现货代币 → 估值用的符号(与 dry_run.SPOT_TOKENS 同一张表,反过来查)
INTERNAL_TYPES = frozenset({"accountClassTransfer"})
FLOW_TYPES = frozenset({"deposit", "withdraw", "send", "spotTransfer", "internalTransfer", "subAccountTransfer"})


def _f(x: Any) -> Optional[float]:
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def flows_of(updates: list[dict], addr: str) -> tuple[float, list[str]]:
    """纯函数。账本更新 → (外部净流入 USD, 认不出的类型)。"""
    a = (addr or "").lower()
    total, unknown = 0.0, []
    for u in updates or []:
        dl = u.get("delta") or {}
        t = dl.get("type")
        if t in INTERNAL_TYPES:
            continue
        if t not in FLOW_TYPES:
            unknown.append(str(t))
            continue
        if t == "deposit":
            total += _f(dl.get("usdc")) or 0.0
            continue
        if t == "withdraw":
            total -= (_f(dl.get("usdc")) or 0.0) + (_f(dl.get("fee")) or 0.0)
            continue
        src, dst = str(dl.get("user") or "").lower(), str(dl.get("destination") or "").lower()
        if src == dst:
            continue                                   # 自己的现货 ↔ 永续 / 不同 dex 之间
        v = _f(dl.get("usdcValue"))
        if v is None:
            v = _f(dl.get("usdc"))
        if v is None and str(dl.get("token") or "").upper().startswith("USDC"):
            v = _f(dl.get("amount"))
        if v is None:
            unknown.append(f"{t}(没有美元值)")
            continue
        total += v if dst == a else (-v - (_f(dl.get("fee")) or 0.0) if src == a else 0.0)
    return total, unknown


def snapshot_row(d: str, beats: list[dict], closes: dict[str, float], flows: Optional[float], unknown: list[str],
                 prev: Optional[dict]) -> Optional[dict[str, Any]]:
    """纯函数。d 这天的心跳(按时间升序,detail 已解开)+ d 的收盘 + 出入金 + 前一天的行 → 一行;没心跳 ⇒ None。"""
    from src.data.execution.dry_run import SPOT_TOKENS
    beats = [b for b in beats if isinstance((b.get("detail") or {}).get("balances"), dict)
             and "error" not in (b.get("detail") or {}).get("balances")]
    if not beats:
        return None
    last = beats[-1]
    det = last["detail"]
    bal = {k: float(v) for k, v in det["balances"].items() if _f(v)}
    acct = det.get("account") or {}
    usdc = bal.get("USDC", 0.0)
    tok_to_sym = {t: s for s, t in SPOT_TOKENS.items()}
    host_vals = {k: float(v) for k, v in (acct.get("spot_values") or {}).items() if _f(v) is not None}
    spot, unpriced, notes, host_valued = {}, [], [], []
    for tok, qty in bal.items():
        if tok == "USDC":
            continue
        sym = tok_to_sym.get(tok, tok)
        px = closes.get(sym)
        if px:
            spot[sym] = round(qty * px, 4)
        elif tok in host_vals:                       # 10-30:XAUT0 / SPYX 没有日线收盘 ⇒ 用主机心跳里按 HL 中间价估的市值
            spot[sym] = round(host_vals[tok], 4)
            host_valued.append(tok)
        else:
            unpriced.append(tok)
    if host_valued:
        notes.append(f"{sorted(host_valued)} 按最后一次心跳的 HL 中间价估值(不是日线收盘)")
    upnl = _f(acct.get("upnl")) or 0.0
    equity = usdc + sum(spot.values()) + upnl
    if unpriced:
        notes.append(f"没有收盘价的代币 {sorted(unpriced)} —— 净值不算")
    if unknown:
        notes.append(f"认不出的出入金类型 {sorted(set(unknown))} —— 净值不算")
    if acct.get("perp_positions"):
        notes.append("有永续仓位:统一账户下 USDC 合计是否已含浮动盈亏未证 —— 对照 HL 网页账户净值核一次")
    nav = ret = None
    if prev is not None and str(prev.get("d") or "")[:10] and str(prev["d"])[:10] != (
            dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat():
        notes.append(f"上一份快照是 {str(prev['d'])[:10]}(中间主机没有心跳)—— 收益跨这几天算")
    if not unpriced and not unknown and flows is not None:
        if d == OPEN_DATE or prev is None:
            nav = 1.0 if d == OPEN_DATE else None
            if nav is None:
                notes.append("开账日之后第一份快照前面没有行 —— 净值不算")
        elif prev.get("nav") is not None and (prev.get("equity_usd") or 0) > 0:
            ret = (equity - flows) / float(prev["equity_usd"]) - 1
            nav = float(prev["nav"]) * (1 + ret)
        else:
            notes.append("上一份快照的净值是空的 —— 链断了,净值不算")
    return {"d": d, "equity_usd": round(equity, 4), "usdc": round(usdc, 4), "spot_usd": spot,
            "perp_upnl": round(upnl, 4), "perp_positions": acct.get("perp_positions") or {},
            "account_mode": acct.get("mode"), "flows_usd": None if flows is None else round(flows, 4),
            "nav": None if nav is None else round(nav, 8), "ret": None if ret is None else round(ret, 8),
            "heartbeat_at": last.get("at"), "n_heartbeats": len(beats),
            "note": "; ".join(notes) or None, "rule": RULE}


def _ms(d: str) -> int:
    return int(dt.datetime.fromisoformat(d).replace(tzinfo=dt.timezone.utc).timestamp() * 1000)


#: 这个文件对 HL 公开接口只读按地址查的这几类(不要 key);`dead_host_guard` 也经这里,不再开一条取数路径(S-302)
HL_ACCOUNT_INFO_TYPES = frozenset({"userNonFundingLedgerUpdates", "spotClearinghouseState", "clearinghouseState",
                                   "frontendOpenOrders"})


async def hl_info(body: dict[str, Any]) -> Any:
    """HL 公开 `/info`,只允许按账户地址查的那几类。"""
    if body.get("type") not in HL_ACCOUNT_INFO_TYPES:
        raise ValueError(f"refusing info type {body.get('type')!r}")
    import httpx
    async with httpx.AsyncClient(timeout=20) as c:
        r = await c.post("https://api.hyperliquid.xyz/info", json=body)
        r.raise_for_status()
        return r.json()


async def _ledger(addr: str, first_d: str, last_d: str) -> list[dict]:
    """[first_d 00:00, last_d + 1 日 00:00) 的账本更新(UTC)。"""
    out = await hl_info({"type": "userNonFundingLedgerUpdates", "user": addr, "startTime": _ms(first_d),
                         "endTime": _ms(last_d) + 86_400_000 - 1})
    if not isinstance(out, list):
        raise RuntimeError(f"ledger 回了 {type(out).__name__}")
    return out


#: 独立核对容差:数量相对 0.5%,绝对下限只够吃掉粉尘(0.001 UBTC 是一百美元,绝对容差不能按 USDC 的尺子定)
XCHECK_REL_TOL, XCHECK_ABS_TOL = 0.005, 1e-6


async def _hl_spot_balances(addr: str) -> dict[str, float]:
    """HL 公开接口:这个地址**现在**的现货余额(coin → total)。只读、不要 key。"""
    out = await hl_info({"type": "spotClearinghouseState", "user": addr})
    bals = (out or {}).get("balances") if isinstance(out, dict) else None
    if not isinstance(bals, list):
        raise RuntimeError(f"spotClearinghouseState 回了 {type(out).__name__}")
    return {str(b.get("coin")): float(b.get("total")) for b in bals if _f(b.get("total")) is not None}


def cross_check(heartbeat: dict[str, Any], live: dict[str, float]) -> list[str]:
    """纯函数。心跳余额 vs HL 公开余额(都是数量)→ 不一致的币(空 = 一致)。两边都没有或都 ≈0 的币不算。"""
    bad = []
    for tok in sorted(set(heartbeat) | set(live)):
        a, b = _f(heartbeat.get(tok)) or 0.0, _f(live.get(tok)) or 0.0
        if abs(a - b) <= max(XCHECK_ABS_TOL, XCHECK_REL_TOL * max(abs(a), abs(b))):
            continue
        bad.append(f"{tok} 心跳 {a:g} / HL {b:g}")
    return bad


async def _xcheck(addr: str, beat: dict, now: dt.datetime) -> dict[str, Any]:
    """最近一天的行写之前:心跳之后没有成交 ⇒ 心跳余额应当等于 HL 现在的余额。读不到 / 中间有单 ⇒ 不下结论,写明。"""
    from src.data.style.header import _read_all
    hb_at = str(beat.get("at") or "")
    try:
        later = await _read_all("loop_attempt", {"select": "at,detail", "loop_name": "eq.executor_host",
                                                 "at": f"gt.{hb_at}", "order": "at.asc"})
    except Exception as e:                                               # noqa: BLE001
        return {"verdict": "unknown", "why": f"心跳之后的回报读不到:{type(e).__name__}"}
    traded = [r for r in later or [] if (r.get("detail") or {}).get("kind") == "cycle"
              and ((r.get("detail") or {}).get("orders") or (r.get("detail") or {}).get("intents_written"))]
    if traded:
        return {"verdict": "skipped", "why": f"心跳之后有 {len(traded)} 轮带单,余额本就该变"}
    try:
        live = await _hl_spot_balances(addr)
    except Exception as e:                                               # noqa: BLE001
        return {"verdict": "unknown", "why": f"HL 公开余额读不到:{type(e).__name__}"}
    bad = cross_check((beat.get("detail") or {}).get("balances") or {}, live)
    return {"verdict": "mismatch" if bad else "match", "diff": bad, "checked_at": now.isoformat(),
            "n_tokens": len(set(live) | set((beat.get("detail") or {}).get("balances") or {}))}


async def run_once(now: Optional[dt.datetime] = None, max_days: int = 7) -> dict[str, Any]:
    """补写所有完成了、还没写的 UTC 日(从开账日起,一轮最多 max_days 天)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    yday = (now.date() - dt.timedelta(days=1)).isoformat()
    if yday < OPEN_DATE:
        return {"ok": True, "waiting": f"第一份快照 {OPEN_DATE} 收盘后"}
    have = await _read_all(TABLE, {"select": "d,equity_usd,nav", "order": "d.asc"})
    done = {str(r["d"])[:10]: r for r in have or []}
    todo, cur = [], dt.date.fromisoformat(OPEN_DATE)
    while cur.isoformat() <= yday and len(todo) < max_days:
        if cur.isoformat() not in done:
            todo.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    wrote, skipped, xchecks = [], [], {}
    for d in todo:
        d1 = (dt.date.fromisoformat(d) + dt.timedelta(days=1)).isoformat()
        rows = await _read_all("loop_attempt", {
            "select": "at,detail", "loop_name": "eq.executor_host",
            "and": f"(at.gte.{d}T00:00:00Z,at.lt.{d1}T00:00:00Z)", "order": "at.asc"})
        beats = [r for r in rows or [] if (r.get("detail") or {}).get("kind") == "heartbeat"]
        if not beats:
            skipped.append(f"{d}: 主机当天没有心跳")
            continue
        addr = str(((beats[-1].get("detail") or {}).get("trade_account")) or "")
        older = [k for k in done if k < d]
        prev = done[max(older)] if older else None
        # 出入金从上一行的第二天算起:中间有几天主机沉默(没快照),那几天的出入金也要扣
        first = (dt.date.fromisoformat(str(max(older))) + dt.timedelta(days=1)).isoformat() if older else d
        flows, unknown = None, []
        if addr:
            try:
                flows, unknown = flows_of(await _ledger(addr, first, d), addr)
            except Exception as e:                       # noqa: BLE001 — 读不到出入金 ⇒ 净值留空,不当 0
                unknown = [f"出入金读不到:{type(e).__name__}"]
        else:
            unknown = ["心跳里没有账户地址"]
        bars = await _read_all("ohlcv_daily", {"select": "symbol,close", "source": "eq.binance_hist",
                                               "trade_date": f"eq.{d}"})
        closes = {b["symbol"]: float(b["close"]) for b in bars or [] if b.get("close")}
        row = snapshot_row(d, beats, closes, flows, unknown, prev)
        if row is None:
            skipped.append(f"{d}: 心跳里没有余额")
            continue
        if d == yday and addr:
            xc = await _xcheck(addr, beats[-1], now)
            xchecks[d] = xc
            if xc["verdict"] == "mismatch":
                msg = f"独立核对:心跳余额与 HL 公开余额对不上 —— {'; '.join(xc['diff'])}"
                row["note"] = f"{row['note']}; {msg}" if row.get("note") else msg
                try:
                    from src.api.notify import notify_telegram
                    await notify_telegram(f"[live_account] {d} {msg}(手动交易?主机读错?快照照写,按心跳口径)")
                except Exception:                                        # noqa: BLE001 — 报警失败不拦快照
                    pass
            elif xc["verdict"] != "match":
                row["note"] = f"{row['note']}; 独立核对未做:{xc['why']}" if row.get("note") else f"独立核对未做:{xc['why']}"
        w = await supabase_upsert_table(TABLE, [row], on_conflict="d")
        if not w:
            return {"ok": False, "why": f"写 {d} 失败:{(getattr(w, 'why', '') or '')[:200]}", "written": wrote}
        done[d] = row
        wrote.append(d)
    return {"ok": True, "written": wrote, "skipped": skipped, "xcheck": xchecks}
