"""每日简报(Jazz 11-01「往前铺排」第 2 条):UTC 01:00 之后发一条 Telegram,把真钱账本昨天的样子放在一眼之内。

## 内容(全部来自装置已经在记的表,不新算)

1. 真钱:`live_account_daily` 最后两行 —— 净值、当日收益、开账以来、账户模式;两条腿与 USDC 的市值。
2. 昨夜执行器三本账(X1V / T25 腿 / R-v2)各跑了没有、下了几单、有没有报错(`loop_attempt` 里 `executor_host` 非心跳行)。
3. 执行质量累计(`execution_quality_daily` since_inception,live sleeve):笔数、成交率、滑点、差额。
4. 不 ok 的循环(过去 24 小时每个循环最后一次 outcome = error 的)。
5. OPEN RISKS 条数(`PROJECT_STATE.md` 第一屏,仓库里就有)。

## 规则

- 一天只发一次(UTC 01:00 后;以 `loop_attempt` 里当天是否已有 `_daily_digest_loop` ok 行为准)。读不到的段写「读不到」,不写 0。
- 纯文本(notify_telegram 默认不解析 Markdown —— 符号 / 下划线会 400)。合规:简报只说仓位与收益,不出现买卖字样;这是内部频道,但习惯要一样。
"""
from __future__ import annotations

import datetime as dt
import re
from typing import Any, Optional

#: DECISIONS 11-02 的两个触发线,简报每天替 Jazz 看着:
#: 真钱净值过 $5 万(或第一笔外部钱)⇒ 独立 HL 账户 + key + 第二台待命主机;股票 / 黄金腿的目标额超过 HL 现货 ±2% 深度 ⇒ 超出部分走券商或更深场所。
SCALE_TRIGGER_USD = 50_000.0
LEG_TOKENS_FOR_DEPTH = ("XAUT0", "SPYX")
SEND_AFTER_UTC = (1, 0)          # 11-02:R-v2 的一轮在 00:45 之后 —— 00:30 发会把它写成「没跑」
LOOP_NAME = "_daily_digest_loop"


def _f(x: Any) -> Optional[float]:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


def _pct(x: Optional[float], nd: int = 2) -> str:
    return "—" if x is None else f"{x * 100:+.{nd}f}%"


def open_risks_count(state_md: str) -> Optional[int]:
    """纯函数。PROJECT_STATE 第一屏 OPEN RISKS 块里顶层 `N. **` 的条数;块不存在 ⇒ None。"""
    m = re.search(r"^##\s*OPEN RISKS.*?$(.*?)(?=^##\s)", state_md, re.M | re.S)
    if not m:
        return None
    return len(re.findall(r"^\d+\.\s+\*\*", m.group(1), re.M))


def _bp(x: Any) -> str:
    v = _f(x)
    return "—" if v is None else f"{v:+.1f}bp"


def _exec_line(r: dict) -> str:
    fr = _f(r.get("fill_rate"))
    lat = _f(r.get("median_decision_to_fill_s"))
    return (f"{r.get('sleeve')} {r.get('n_intents')} 笔 成交率 {'—' if fr is None else f'{fr * 100:.0f}%'} "
            f"滑点 {_bp(r.get('mean_slippage_bps'))} 差额 {_bp(r.get('implementation_shortfall_bps'))}"
            + (f" 决策→回报 {lat:.1f}s" if lat is not None else ""))


def exposure_lines(rows: list[dict]) -> list[str]:
    """纯函数。③ 每日决定(11-03):敞口 · 基率三档 · 分歧标记;没有行 ⇒ 空。"""
    if not rows:
        return []
    r = rows[0]
    p = r.get("probs") or {}
    e = r.get("rule_exposure")
    line = (f"③ 决定 {r.get('d')}:敞口 {'—' if e is None else f'{float(e):.0%}'} · 30 日基率 跌>10% {p.get('down', 0):.0%} / "
            f"±10% {p.get('flat', 0):.0%} / 涨>10% {p.get('up', 0):.0%}({r.get('bucket')}, n={r.get('n_bucket')})")
    if r.get("flag"):
        line += f" · ⚑ {r['flag']}"
    return [line]


def calibration_lines(entries: list[dict], scores: list[dict]) -> list[str]:
    """纯函数。情景台账按作者的校准(S-705:lane 也是作者):已结 n、命中率、平均 Brier;什么都没结 ⇒ 一行「未结 / 已写」。"""
    from src.data.evaluation.scenario_ledger import calibration
    if not entries:
        return []
    cal = calibration(entries, {s["id"]: s for s in scores})
    if not cal:
        return [f"情景台账:已写 {len(entries)} 条,还没有结算的(第一批 11-04 起)"]
    parts = [f"{a} {v['n']} 条 命中 {v['hit_rate']:.0%} Brier {v['mean_brier']:.3f}" for a, v in sorted(cal.items())]
    return ["情景台账(已结 / 命中率 / Brier,0 = 全对、0.25 = 乱猜):" + " · ".join(parts)]


def decision_lines(d: str, equity: Optional[float], leg_targets: dict[str, float], depth2: dict[str, float]) -> list[str]:
    """纯函数。DECISIONS 11-02 的触发线:到了就写一行(不到不写);每月 1 号提醒重跑现货触发单探针。"""
    out = []
    if equity is not None and equity >= SCALE_TRIGGER_USD:
        out.append(f"⚑ 净值 {equity:,.0f} ≥ {SCALE_TRIGGER_USD:,.0f}:DECISIONS 11-02 —— 独立 HL 账户 + key + 第二台待命主机")
    for tok in LEG_TOKENS_FOR_DEPTH:
        t, dep = leg_targets.get(tok), depth2.get(tok)
        if t and dep and t > dep:
            out.append(f"⚑ {tok} 腿目标 ${t:,.0f} > HL 现货 ±2% 深度 ${dep:,.0f}:DECISIONS 11-02 —— 超出部分走券商或更深场所")
    if str(d)[8:10] == "01":
        out.append("提醒(每月 1 号):重跑 scripts/host_probe_spot_trigger.command —— HL 现货触发单开了没有")
    return out


def compose(d: str, live: list[dict], exec_rows: list[dict], host_events: list[dict], bad_loops: list[dict],
            n_open_risks: Optional[int], unreadable: Optional[list[str]] = None,
            host_code: Optional[str] = None, railway_code: Optional[str] = None,
            decisions: Optional[list[str]] = None) -> str:
    """纯函数。`live` 按 d 升序(最后两行);`host_events` = 昨夜 executor_host 非心跳行;`bad_loops` = [{loop_name, reason}]。"""
    L = [f"CometCloud 日报 · {d}"]
    # 1 真钱
    if live:
        cur = live[-1]
        eq, nav, ret = _f(cur.get("equity_usd")), _f(cur.get("nav")), _f(cur.get("ret"))
        spot = cur.get("spot_usd") or {}
        legs = " ".join(f"{k} {_f(v):.0f}" for k, v in sorted(spot.items()) if _f(v) is not None)
        usdc = _f(cur.get("usdc"))
        L.append(f"真钱 {cur.get('d')}: 净值 {eq:.2f} USDC" if eq is not None else f"真钱 {cur.get('d')}: 净值读不到")
        L.append(f"  当日 {_pct(ret)} · 开账以来 {_pct((nav - 1) if nav is not None else None)} · "
                 f"USDC {usdc:.0f}" + (f" · {legs}" if legs else "") + (f" · {cur.get('account_mode')}" if cur.get("account_mode") else ""))
        if cur.get("note"):
            L.append(f"  注:{str(cur['note'])[:120]}")
    else:
        L.append("真钱:昨天的快照还没落(或读不到)")
    # 2 执行器
    by_book: dict[str, dict[str, Any]] = {}
    for e in host_events:
        det = e.get("detail") or {}
        book = det.get("book") or "x1v"
        kind = det.get("kind")
        b = by_book.setdefault(book, {"cycles": 0, "orders": 0, "errors": 0, "stops": 0})
        if kind == "cycle":
            b["cycles"] += 1
            b["orders"] += len(det.get("orders") or []) if isinstance(det.get("orders"), list) else int(det.get("intents_written") or 0)
        elif kind == "stop":
            b["stops"] += 1
        elif kind == "error" or e.get("outcome") == "error":
            b["errors"] += 1
    if by_book:
        parts = []
        for book in ("x1v", "t25", "r_v2"):
            b = by_book.get(book)
            if not b:
                parts.append(f"{book} 没跑")
                continue
            s = f"{book} {b['cycles']} 轮 / {b['orders']} 单"
            if b["stops"]:
                s += f" / 止损 {b['stops']}"
            if b["errors"]:
                s += f" / 错 {b['errors']}"
            parts.append(s)
        L.append("执行器昨夜: " + " · ".join(parts))
    else:
        L.append("执行器昨夜: 没有任何回报(看心跳)")
    # 11-02:真钱跑在主机上,主机拉没拉代码 Railway 看不到 —— 两个版本并排写出来(不判对错:主机只在主机侧代码改了才需要拉)
    L.append(f"代码: 主机 {host_code or '心跳里没有(旧版主机)'} · Railway {railway_code or '—'}")
    # 3 执行质量
    live_eq = [r for r in exec_rows if not str(r.get("sleeve", "")).endswith("_dry")]
    if live_eq:
        L.append("执行质量(累计): " + " · ".join(_exec_line(r) for r in live_eq))
    # 4 循环
    if bad_loops:
        L.append("循环不 ok: " + " · ".join(f"{b['loop_name']}({str(b.get('reason') or '')[:40]})" for b in bad_loops[:6])
                 + (f" · 还有 {len(bad_loops) - 6} 个" if len(bad_loops) > 6 else ""))
    else:
        L.append("循环: 全部 ok")
    # 5 风险
    L.append(f"OPEN RISKS: {n_open_risks} 条" if n_open_risks is not None else "OPEN RISKS: 读不到")
    L.extend(decisions or [])
    if unreadable:
        L.append("读不到的段: " + ", ".join(unreadable))
    return "\n".join(L)


def due(now: dt.datetime, sent_today: bool) -> bool:
    """UTC 01:00 之后、今天还没发 ⇒ 该发。"""
    h, m = SEND_AFTER_UTC
    return not sent_today and (now.hour, now.minute) >= (h, m)


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.notify import notify_telegram, telegram_configured
    from src.data.style.header import _read_all
    now = now or dt.datetime.now(dt.timezone.utc)
    today = now.date().isoformat()
    sent = await _read_all("loop_attempt", {"select": "at", "loop_name": f"eq.{LOOP_NAME}", "outcome": "eq.ok",
                                            "at": f"gte.{today}T00:00:00Z", "limit": "1"})
    if not due(now, bool(sent)):
        return {"ok": True, "refused": True, "why": "今天已发" if sent else "还没到 01:00 UTC"}
    unreadable: list[str] = []

    async def _try(name, coro):
        try:
            return await coro
        except Exception as e:                                           # noqa: BLE001 —— 一段读不到不拦简报,写明
            unreadable.append(f"{name}: {type(e).__name__}")
            return []

    live = await _try("live_account_daily", _read_all("live_account_daily", {"select": "d,equity_usd,usdc,spot_usd,nav,ret,account_mode,note",
                                                                           "order": "d.desc", "limit": "2"}))
    live = sorted(live, key=lambda r: str(r.get("d")))
    exec_rows = await _try("execution_quality_daily", _read_all("execution_quality_daily", {
        "select": "sleeve,d,n_intents,fill_rate,mean_slippage_bps,implementation_shortfall_bps,median_decision_to_fill_s",
        "span": "eq.since_inception",
        "order": "d.desc", "limit": "20"}))
    latest: dict[str, dict] = {}
    for r in exec_rows:
        latest.setdefault(r["sleeve"], r)
    yday = (now.date() - dt.timedelta(days=1)).isoformat()
    host = await _try("loop_attempt(executor_host)", _read_all("loop_attempt", {
        "select": "at,outcome,detail", "loop_name": "eq.executor_host", "at": f"gte.{yday}T23:00:00Z", "order": "at.asc"}))
    host_code = next((str((e.get("detail") or {}).get("code")) for e in reversed(host)
                      if (e.get("detail") or {}).get("code")), None)
    host = [e for e in host if (e.get("detail") or {}).get("kind") != "heartbeat"]
    recent = await _try("loop_attempt", _read_all("loop_attempt", {"select": "loop_name,outcome,reason,at",
                                                                   "at": f"gte.{yday}T00:30:00Z", "order": "at.desc"}))
    last_by: dict[str, dict] = {}
    for r in recent:
        last_by.setdefault(r["loop_name"], r)
    bad = [r for r in last_by.values() if r.get("outcome") == "error" and r["loop_name"] != LOOP_NAME]
    n_risks = None
    try:
        from pathlib import Path
        n_risks = open_risks_count(Path(__file__).resolve().parents[3].joinpath("PROJECT_STATE.md").read_text(encoding="utf-8"))
    except Exception as e:                                               # noqa: BLE001
        unreadable.append(f"PROJECT_STATE: {type(e).__name__}")
    tg = await _try("portfolio_targets_daily", _read_all("portfolio_targets_daily", {
        "select": "d,sleeve,target_usd", "sleeve": "in.(gold,equity)", "order": "d.desc", "limit": "4"}))
    leg_t: dict[str, float] = {}
    for r in tg:
        k = {"gold": "XAUT0", "equity": "SPYX"}.get(str(r.get("sleeve")))
        if k and k not in leg_t and _f(r.get("target_usd")):
            leg_t[k] = float(r["target_usd"])
    vd = await _try("venue_depth_snapshots", _read_all("venue_depth_snapshots", {
        "select": "symbol,depth_2pct_bid_usd,depth_2pct_ask_usd", "venue": "eq.hyperliquid_spot",
        "symbol": f"in.({','.join(LEG_TOKENS_FOR_DEPTH)})", "order": "fetched_utc.desc", "limit": "6"}))
    dep: dict[str, float] = {}
    for r in vd:
        b_, a_ = _f(r.get("depth_2pct_bid_usd")), _f(r.get("depth_2pct_ask_usd"))
        if r.get("symbol") not in dep and b_ is not None and a_ is not None:
            dep[r["symbol"]] = min(b_, a_)
    eq = _f(live[-1].get("equity_usd")) if live else None
    xd = await _try("exposure_decision_daily", _read_all("exposure_decision_daily", {
        "select": "d,rule_exposure,probs,bucket,n_bucket,flag", "order": "d.desc", "limit": "1"}))
    sc_entries = await _try("scenario_ledger", _read_all("scenario_ledger", {"select": "id,author,prob"}))
    sc_scores = await _try("scenario_scores", _read_all("scenario_scores", {"select": "id,outcome,brier", "outcome": "not.is.null"}))
    from src.api.loop_beat import build_sha
    text = compose(today, live, sorted(latest.values(), key=lambda r: r["sleeve"]), host, bad, n_risks, unreadable,
                   host_code=host_code, railway_code=build_sha() or None,
                   decisions=exposure_lines(xd) + decision_lines(today, eq, leg_t, dep) + calibration_lines(sc_entries, sc_scores))
    if not telegram_configured():
        return {"ok": False, "why": "TELEGRAM_BOT_TOKEN 未配", "text": text}
    sent_ok = await notify_telegram(text)
    return {"ok": bool(sent_ok), "why": None if sent_ok else "Telegram 发送失败", "text": text, "unreadable": unreadable}
