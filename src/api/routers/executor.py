"""云主机执行器 ↔ Railway 的两个口子(T-015 / TRADE_PATH §4)+ 一键停。

    GET  /internal/executor/plan     X-Executor-Token   今天的计划(目标、止损线、一键停)
    POST /internal/executor/report   X-Executor-Token   主机回报:意图、成交结果、余额、心跳
    POST /internal/executor/halt     X-Internal-Token   一键停 / 解除(Redis `executor:halt`);INTERNAL_TOKEN_HALT 只能停(scripts/seth_halt.sh)
    GET  /internal/executor/book-of-truth  X-Internal-Token   R-v2 真相之书:纸面 vs 交易所逐票对账(只读)
    POST /internal/regime-call       X-Internal-Token   Jazz ⓪ 开关:提交一条判断(on / off / flat、信心、战场)
    GET  /internal/regime-call       X-Internal-Token   生效的判断、最近 20 条、在持 J 票、记分卡
    GET  /internal/regime-call/brief X-Internal-Token   ⓪ 战场简报(HL 前 N 永续的趋势 / 第二段形态 / 资金费,只读)

## 为什么用单独的 EXECUTOR_TOKEN

主机只需要这两个口子。给它 INTERNAL_TOKEN 就等于给了它几十个 /internal 写口 —— 主机被拿下时,
爆炸半径应该是「能读计划、能写执行记录」,不是「能改 CIS」。一键停反过来:那是 Jazz 的按钮,走 INTERNAL_TOKEN,
主机自己不能解除自己的停。

## 回报的校验(与 mac_writes 同一条纪律)

未知字段**拒绝**,不丢弃;sleeve 必须与 mode 对上(空跑不能写进真跑的 sleeve);空跑不能带成交结果
(没下单哪来的成交)。主机侧有落盘的发件箱,4xx 的那批会被挪进 rejected/ 留证,不会被无限重发。

判活:`select at, outcome, detail from loop_attempt where loop_name = 'executor_host' order by at desc limit 5`
—— 主机每小时一次心跳、每天一轮 cycle,各写一行。
"""
from __future__ import annotations

import datetime as dt
import hmac
import logging
import os
import re
from dataclasses import fields
from typing import Any, Optional

from fastapi import APIRouter, Body, Header, HTTPException
from src.api.auth_internal import require_internal_token   # S-371 A-1:INTERNAL_TOKEN 只在一处校验(EXECUTOR_TOKEN 另算,爆炸半径不同)

from src.data.execution.dry_run import SPOT_TOKENS
from src.data.execution.fill_log import _TERMINAL, Intent, Outcome
from src.data.execution.host_plan import HALT_KEY, SLEEVE_FOR_MODE
from src.data.execution.ticket_plan import TICKET_SLEEVE_FOR_MODE

log = logging.getLogger(__name__)
router = APIRouter()

INTENT_FIELDS = frozenset(f.name for f in fields(Intent))
OUTCOME_FIELDS = frozenset(f.name for f in fields(Outcome))
INTENT_REQUIRED = frozenset({"intent_id", "ts_decision", "symbol", "side", "target_notional_usd", "decision_mid", "sleeve"})
KINDS = frozenset({"cycle", "stop", "heartbeat", "error", "probe", "liqmap"})   # probe:一次性真钱验证(11-02 现货触发单),不带意图 / 结果
REPORT_KEYS = frozenset({"mode", "kind", "host", "asof", "intents", "outcomes", "detail", "alert", "book"})
#: 三本账:X1V 现货(没有 book 字段 = x1v,向后兼容)、R-v2 单票(HL 永续)、T25 的黄金 / 股票腿(HL 现货,10-30)。
#: sleeve 按 (book, mode) 定,互不串
from src.exec_host.legs import LEG_TOKENS as _T25_LEGS, SLEEVES as _T25_SLEEVES  # noqa: E402
SLEEVES = {"x1v": SLEEVE_FOR_MODE, "r_v2": TICKET_SLEEVE_FOR_MODE, "t25": _T25_SLEEVES}
_PERP_COIN = re.compile(r"^[A-Za-z0-9]{1,20}$")
MAX_ROWS = 50
LOOP_NAME = "executor_host"


def _token_ok(given: Optional[str], env_name: str) -> None:
    expected = os.environ.get(env_name, "")
    if not expected:
        # 未配置 ⇒ 关门(S-262:空字符串比较曾经放行过)
        raise HTTPException(503, f"{env_name} is not configured on the server")
    if not given or not hmac.compare_digest(given.encode(), expected.encode()):
        raise HTTPException(403, "bad or missing token")


def vet_report(body: Any) -> tuple[Optional[dict], list[str]]:
    """纯函数。返回 (清洗后的回报, 拒绝理由)。有任何拒绝理由 ⇒ 整批拒,不部分写入 ——
    一批意图里混着一行坏的,部分写入会让 intent 与 outcome 对不上,而那正是 fill_log 要防的偏差。"""
    why: list[str] = []
    if not isinstance(body, dict):
        return None, ["body 必须是 JSON 对象"]
    extra = set(body) - REPORT_KEYS
    if extra:
        why.append(f"未知字段 {sorted(extra)} —— 拒绝而不是丢弃")
    mode, kind, book = body.get("mode"), body.get("kind"), body.get("book") or "x1v"
    if book not in SLEEVES:
        why.append(f"book 必须是 {sorted(SLEEVES)},收到 {book!r}")
    modes = SLEEVES.get(book) or SLEEVE_FOR_MODE
    if mode not in modes:
        why.append(f"mode 必须是 {sorted(modes)},收到 {mode!r}")
    if kind not in KINDS:
        why.append(f"kind 必须是 {sorted(KINDS)},收到 {kind!r}")
    intents = body.get("intents") or []
    outcomes = body.get("outcomes") or []
    if not isinstance(intents, list) or not isinstance(outcomes, list):
        return None, why + ["intents / outcomes 必须是列表"]
    if len(intents) + len(outcomes) > MAX_ROWS:
        why.append(f"一批最多 {MAX_ROWS} 行")
    sleeve = modes.get(mode or "")
    for k, row in enumerate(intents):
        if not isinstance(row, dict):
            why.append(f"intents[{k}] 不是对象")
            continue
        bad = set(row) - INTENT_FIELDS
        miss = INTENT_REQUIRED - set(row)
        if bad:
            why.append(f"intents[{k}] 未知列 {sorted(bad)}")
        if miss:
            why.append(f"intents[{k}] 缺列 {sorted(miss)}")
        if row.get("sleeve") != sleeve:
            why.append(f"intents[{k}] sleeve {row.get('sleeve')!r} 与 mode {mode!r} 不符(应为 {sleeve!r})")
        if row.get("side") not in ("buy", "sell"):
            why.append(f"intents[{k}] side {row.get('side')!r}")
        if book == "x1v" and row.get("symbol") not in SPOT_TOKENS:
            why.append(f"intents[{k}] symbol {row.get('symbol')!r} 不在 {sorted(SPOT_TOKENS)}")
        if book == "r_v2" and not _PERP_COIN.match(str(row.get("symbol") or "")):
            why.append(f"intents[{k}] symbol {row.get('symbol')!r} 不是 HL 永续币名")
        if book == "t25" and row.get("symbol") not in _T25_LEGS:
            why.append(f"intents[{k}] symbol {row.get('symbol')!r} 不在 {sorted(_T25_LEGS)}")
    if mode == "dry_run" and outcomes:
        why.append("空跑不下单,不能带成交结果")
    for k, row in enumerate(outcomes):
        if not isinstance(row, dict):
            why.append(f"outcomes[{k}] 不是对象")
            continue
        bad = set(row) - OUTCOME_FIELDS
        if bad:
            why.append(f"outcomes[{k}] 未知列 {sorted(bad)}")
        if not row.get("intent_id") or not row.get("ts_resolved"):
            why.append(f"outcomes[{k}] 缺 intent_id / ts_resolved")
        if row.get("status") not in _TERMINAL:
            why.append(f"outcomes[{k}] status {row.get('status')!r} 不是终态")
    if body.get("alert") is not None and not isinstance(body.get("alert"), str):
        why.append("alert 必须是字符串")
    if why:
        return None, why
    return {**body, "intents": intents, "outcomes": outcomes}, []


@router.get("/internal/executor/plan")
async def executor_plan(x_executor_token: Optional[str] = Header(None, alias="X-Executor-Token")):
    _token_ok(x_executor_token, "EXECUTOR_TOKEN")
    from src.data.execution.host_plan import build_host_plan
    try:
        return await build_host_plan()
    except Exception as e:                                       # noqa: BLE001
        log.warning("[EXECUTOR] plan failed: %s", e)
        return {"ok": False, "why": f"{type(e).__name__}: {str(e)[:300]}"}


@router.post("/internal/executor/report")
async def executor_report(body: Any = Body(...),
                          x_executor_token: Optional[str] = Header(None, alias="X-Executor-Token")):
    _token_ok(x_executor_token, "EXECUTOR_TOKEN")
    clean, why = vet_report(body)
    if clean is None:
        raise HTTPException(422, {"rejected": why})
    from src.api.store import supabase_upsert_table
    written = {"intents": 0, "outcomes": 0}
    # 先意图后结果:execution_outcomes.intent_id 外键指向 execution_intents。同一 intent_id 重发 = 覆盖成同一行(主机发件箱可能重发)
    if clean["intents"]:
        r = await supabase_upsert_table("execution_intents", clean["intents"], on_conflict="intent_id")
        if not r:
            raise HTTPException(502, f"execution_intents write failed: {getattr(r, 'why', '')}")
        written["intents"] = len(clean["intents"])
    if clean["outcomes"]:
        r = await supabase_upsert_table("execution_outcomes", clean["outcomes"], on_conflict="intent_id")
        if not r:
            raise HTTPException(502, f"execution_outcomes write failed: {getattr(r, 'why', '')}")
        written["outcomes"] = len(clean["outcomes"])
    if clean["kind"] == "liqmap":
        # T-221:强平地图的汇总进自己的表;loop_attempt 只留个数(不把几百行塞进心跳表)
        from src.data.market.liq_map import write_rows
        lm = await write_rows((clean.get("detail") or {}).get("rows") or [], (clean.get("detail") or {}).get("at"))
        if not lm.get("ok"):
            raise HTTPException(422 if lm.get("bad") else 502, lm)
        written["liq_rows"] = lm["written"]
        # 11-09 S-794:同一批快照的完整持仓。写不进去不拒整批(强平地图照写,主机发件箱不重送),原因记进心跳表
        det = clean.get("detail") or {}
        if det.get("positioning"):
            from src.data.market.liq_map import write_positioning
            wp = await write_positioning(det.get("positioning") or [], det.get("at"), det.get("n_accounts"))
            written["pos_rows"] = wp.get("written", 0)
            if not wp.get("ok"):
                det["positioning_error"] = wp.get("bad") or wp.get("why")
        clean["detail"] = {k: v for k, v in det.items() if k not in ("rows", "positioning")}
    detail = {**(clean.get("detail") or {}), "mode": clean["mode"], "kind": clean["kind"], "book": clean.get("book") or "x1v",
              "host": clean.get("host"), "asof": clean.get("asof"), **{f"{k}_written": v for k, v in written.items()}}
    outcome = "error" if clean["kind"] == "error" or (clean.get("detail") or {}).get("errors") else "ok"
    from src.api.rpc_diagnostics import _record_loop_attempt
    await _record_loop_attempt(LOOP_NAME, outcome, reason=(clean.get("alert") or None), detail=detail,
                               writer="src.api.routers.executor.executor_report")
    if clean.get("alert"):
        from src.api.notify import notify_telegram
        await notify_telegram(f"[executor {clean.get('book') or 'x1v'} {clean['mode']} · {clean['kind']}] {clean['alert'][:500]}")
    return {"ok": True, **written}


@router.get("/internal/executor/book-of-truth")
async def executor_book_of_truth(mode: str = "live", detail: bool = False,
                                 x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """R-v2 的真相之书(docs/TRADER_TOM_DOCTRINE.md §11):纸面票 vs 交易所上实际发生的,逐票对账 + 违规 + 挣来的杠杆上限。
    `mode` = live / dry_run;`detail=true` 带逐票明细。只读;走 Jazz 的 INTERNAL_TOKEN(这是真钱的账)。"""
    require_internal_token(x_internal_token)
    from src.data.execution.book_of_truth import load_book_of_truth
    if mode not in TICKET_SLEEVE_FOR_MODE:
        raise HTTPException(422, f"mode 必须是 {sorted(TICKET_SLEEVE_FOR_MODE)}")
    try:
        r = await load_book_of_truth(mode)
    except Exception as e:                                       # noqa: BLE001
        log.warning("[EXECUTOR] book of truth failed: %s", e)
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")
    if not detail:
        r = {**r, "tickets": [t for t in r["tickets"] if t["breaches"]]}
    return {"ok": True, **r}


@router.post("/internal/regime-call")
async def regime_call_post(body: Any = Body(...),
                           x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """Jazz ⓪ 开关:提交一条完整的判断(state on / off / flat、conviction 1–3、battlefield、close、note、days)。
    只追加;最新一条生效。说明见 src/data/execution/regime_call.py。"""
    require_internal_token(x_internal_token)
    from src.data.execution.regime_call import post_call
    r = await post_call(body)
    if not r.get("ok"):
        raise HTTPException(422, {"rejected": r.get("rejected")})
    c = r["call"]
    from src.api.notify import notify_telegram
    await notify_telegram(f"[⓪ Jazz] {c.get('state')} · 信心 {c.get('conviction')} · 战场 {','.join(c.get('battlefield') or []) or '—'}"
                          f"{' · 离场 ' + ','.join(c.get('close_coins') or []) if c.get('close_coins') else ''}"
                          f" · 到 {str(c.get('expires_at'))[:10]} · {str(c.get('note') or '')[:200]}")
    return r


@router.get("/internal/regime-call")
async def regime_call_get(x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """现在生效的判断(下一轮计划用哪条)、最近 20 条、在持的 J 票、记分卡。"""
    require_internal_token(x_internal_token)
    from src.data.execution.regime_call import call_view, governing_call, load_scorecard, read_calls, read_j_tickets
    try:
        calls, js = await read_calls(), await read_j_tickets()
        card = await load_scorecard()
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")
    today = dt.datetime.now(dt.timezone.utc).date()
    return {"ok": True,
            "next_cycle": {"asof": today.isoformat(), "call": call_view(governing_call(calls, today))},
            "last_cycle": {"asof": (today - dt.timedelta(days=1)).isoformat(),
                           "call": call_view(governing_call(calls, today - dt.timedelta(days=1)))},
            "recent_calls": [call_view(c) for c in calls[-20:]][::-1],
            "j_live": [j for j in js if j.get("status") in ("pending", "open")],
            "scorecard": card}


@router.get("/internal/regime-call/brief")
async def regime_call_brief(top: int = 40, x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """⓪ 战场简报:HL 成交额前 N 的永续,趋势位置 / 第一段 / 回撤 / 第二段形态 / 资金费 / 未平仓 / 止损宽度。只读;筛子不是信号。"""
    require_internal_token(x_internal_token)
    from src.data.execution.battlefield_brief import build_brief
    # 11-13(S-849 第 4 条 / S-855):第一屏先给状态读法 —— 边际流动性 / 宏观 / 周期 / 仓位 / 叙事 + 盯盘·派发·吸筹三张清单。
    # 现算(截至昨天收盘的 UTC 日),只读、只描述;它读不到不挡战场表,战场表读不到也不挡它。
    state: dict[str, Any] = {}
    try:
        from src.data.execution import dossier_context as _dc
        state = await _dc.context((dt.datetime.now(dt.timezone.utc).date() - dt.timedelta(days=1)).isoformat())
    except Exception as e:                                       # noqa: BLE001
        state = {"error": f"{type(e).__name__}: {str(e)[:160]}"}
    try:
        return {"ok": True, **await build_brief(max(5, min(int(top), 80))), "state_read": state}
    except Exception as e:                                       # noqa: BLE001
        if "error" in state:
            raise HTTPException(502, f"HL 读不到:{type(e).__name__}: {str(e)[:200]}")
        return {"ok": True, "state_read": state, "breadth": None, "rows": [], "hl_error": f"{type(e).__name__}: {str(e)[:200]}"}


@router.post("/internal/scenarios")
async def scenarios_submit(body: dict = Body(...), x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """情景台账(`src/data/evaluation/scenario_ledger.py`,11-02):事前写下的命题,只追加。
    body: {"author": "weekly", "entries": [{id, scenario, statement, variable, op, lo, hi, prob, horizon_d}, …]}。
    作者 = 「token 的 lane:body.author」—— 谁写的从 token 来,不从正文来。任何一条有问题 ⇒ 整批不写(422 带原因)。"""
    lane = require_internal_token(x_internal_token)
    from src.data.evaluation.scenario_ledger import submit
    entries = body.get("entries")
    if not isinstance(entries, list):
        raise HTTPException(422, "entries 必须是列表")
    author = f"{lane}:{str(body.get('author') or 'default')[:40]}"
    r = await submit(entries, author)
    if not r.get("ok"):
        raise HTTPException(422, r)
    return r


@router.get("/internal/scenarios")
async def scenarios_view(x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """最近 50 条情景、各自的结算,与按作者的校准(平均 Brier、命中率、五档可靠性)。"""
    require_internal_token(x_internal_token)
    from src.data.evaluation.scenario_ledger import SCORES, TABLE, calibration, open_manual
    from src.data.style.header import _read_all
    try:                                                         # 11-12:不带 limit —— 原来只读最近 500 条,校准漏掉最早的那批
        entries = await _read_all(TABLE, {"select": "*", "order": "written_at.desc"})
        scores = {r["id"]: r for r in await _read_all(SCORES, {"select": "*", "order": "id.asc"})}
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")
    return {"ok": True, "n": len(entries), "calibration": calibration(entries, scores),
            "manual_open": open_manual(entries, scores, dt.datetime.now(dt.timezone.utc).date()),
            "recent": [{**e, "score": scores.get(e["id"])} for e in entries[:50]]}


@router.get("/internal/liq-map")
async def liq_map_view(x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """T-221:最近一小时的强平地图 —— 跌 / 涨 5 / 10 / 15% 时被迫卖出 / 买入的名义额,对永续 ±2% 深度的倍数。"""
    require_internal_token(x_internal_token)
    from src.data.market.liq_map import latest_view
    try:
        return await latest_view()
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")


@router.get("/internal/whale-positioning")
async def whale_positioning_view(x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """S-794(11-10):HL 盈利头部账户的完整持仓 —— 每币净向、名义额、账户数、24 小时变化。只描述。"""
    require_internal_token(x_internal_token)
    from src.data.market.liq_map import positioning_view
    try:
        return await positioning_view()
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")


@router.post("/internal/overlays")
async def overlays_submit(body: dict = Body(...), x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """偏离(`src/data/execution/overlays.py`,Jazz 11-02 规则是零假设):在预算内动真钱的、带编号与退出条件的调整。
    只有主 token 能写;只追加;撤回走 /internal/overlays/cancel。"""
    lane = require_internal_token(x_internal_token)
    from src.data.execution.overlays import submit
    r = await submit(body if isinstance(body, dict) else {}, lane)
    if not r.get("ok"):
        raise HTTPException(422 if "problems" in r else 403, r)
    from src.api.notify import notify_telegram
    await notify_telegram(f"[overlay] {body.get('id')} 已写 · {body.get('source')} · {str(body.get('thesis'))[:120]} · "
                          f"{body.get('starts_d')} → {body.get('ends_d')}")
    return r


@router.post("/internal/overlays/cancel")
async def overlays_cancel(body: dict = Body(...), x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    lane = require_internal_token(x_internal_token)
    from src.data.execution.overlays import cancel
    r = await cancel(str(body.get("id") or ""), str(body.get("reason") or ""), lane)
    if not r.get("ok"):
        raise HTTPException(422, r)
    from src.api.notify import notify_telegram
    await notify_telegram(f"[overlay] {body.get('id')} 撤回 · {str(body.get('reason'))[:160]}")
    return r


@router.get("/internal/overlays")
async def overlays_view(x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """今天生效的偏离、它们对计划的影响(基线 vs 偏离后)、最近 30 天的逐日记录。"""
    require_internal_token(x_internal_token)
    from src.data.execution.overlays import DAILY
    from src.data.execution.portfolio_targets import plan_fields_live
    from src.data.style.header import _read_all
    try:
        today = await plan_fields_live()
        daily = await _read_all(DAILY, {"select": "*", "order": "d.desc", "limit": "30"})
    except Exception as e:                                       # noqa: BLE001
        raise HTTPException(502, f"{type(e).__name__}: {str(e)[:300]}")
    return {"ok": True, "today": today.get("overlays"), "x1v_nav_budget_usd": today.get("x1v_nav_budget_usd"),
            "legs": (today.get("t25") or {}).get("legs"), "daily": daily}


@router.post("/internal/executor/halt")
async def executor_halt(body: dict = Body(...),
                        x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token")):
    """一键停 / 解除。body: {"halted": true|false, "reason": "..."}。TTL 90 天(过期 = 解除,写在这里不藏)。
    Jazz 11-01:除了正常 lane 的 token,还接受只能停的 `INTERNAL_TOKEN_HALT`(Seth 那把);**解除**仍只有正常 token 能做 ——
    停是最小动作,恢复真钱不是。"""
    from src.api.auth_internal import require_halt_token
    lane = require_halt_token(x_internal_token)
    if not isinstance(body.get("halted"), bool):
        raise HTTPException(422, "halted 必须是 true / false")
    if lane == "halt" and body["halted"] is False:
        raise HTTPException(403, "这把 token 只能停,不能解除")
    from src.api.store import redis_set_key
    payload = {"halted": body["halted"], "reason": str(body.get("reason") or "")[:300],
               "at": dt.datetime.now(dt.timezone.utc).isoformat(), "by": lane}
    r = await redis_set_key(HALT_KEY, payload, ttl=90 * 86400)
    if not r:
        raise HTTPException(502, f"halt flag not written: {getattr(r, 'why', '')}")
    from src.api.notify import notify_telegram
    await notify_telegram(f"[executor] {'HALTED' if body['halted'] else 'resumed'} · {payload['reason']} · by {lane}")
    return {"ok": True, **payload}
