"""agent 判断臂(S-725,Jazz 11-04「agent 主动调参,不做机械海龟」)—— 每天一次,LLM 读 ③ 决定的同一份时点档案,写 BTC 30 天三档概率。

## 为什么是这个形状

S-716 量过机械版的「主动」(按过去收益选参数)= 随机选参;S-715 / S-723 量过机械版的证据门 = 没有站得住的量。剩下的是 Tom 的
另一半 —— 一事一议的判断。它回测不了(模型见过历史),只能**前向记分**:和基率臂(`seth:exposure`)、近邻臂(`seth:exposure-knn`)
写同一组三档命题(30 天后 BTC 收盘 跌超 10% / ±10% 内 / 涨超 10%),到期一起按 Brier 结算。挣到了才给它一行描述;动钱另立预注册。

## 纪律

- 档案只来自已经落表的东西(`exposure_decision_daily` 的 inputs / probs、`feed_items` 近 48 小时与宇宙相关的标题);模型不给数,只给概率。
- 概率归一后原样入账,不截断、不平滑。理由过合规过滤(英文 `_BANNED` + 中文买卖词),不过就不存理由。
- 只在 d+1 当天(UTC)写;模型那天一直不通 ⇒ 那天空着,不补(补写 = 多看了几个小时)。
- 不发群、不动钱。

表 `agent_judgment_daily`(d, author)。判活:`select d, author, probs, left(rationale, 80) from agent_judgment_daily order by d desc limit 3`;
模型不通时看 `loop_attempt` 里 `_agent_judgment_loop` 的 reason。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from typing import Any, Optional

TABLE = "agent_judgment_daily"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {"agent_judgment_daily": ("d", "author", "model", "probs", "rationale", "drivers", "change_mind", "dossier_hash",
                                           "scenario_ids", "code_ref")}
CODE_REF = "agent_judgment v1 (11-05, S-725)"
LOOP_NAME = "_agent_judgment_loop"
PREFIX = "A"
TEMPERATURE = 0.2
MAX_TOKENS = 12000          # 11-05:推理模型先想再答;4,000 时 10:15 那轮整段都是没写完的思考(剥掉后为空)
TIMEOUT_S = 300.0          # 11-05:12k token 的推理回复 45 秒(NARRATIVE_LLM_TIMEOUT 默认)写不完 —— 12:10 那轮 ReadTimeout
NEWS_HOURS = 48
NEWS_MAX = 12
_BANNED_ZH = re.compile(r"(买入|卖出|加仓|减仓|建仓|清仓|抄底|止盈|止损|目标价|满仓|梭哈|建议.{0,4}(买|卖|持有))")

_SYSTEM = (
    "You are the forecasting desk of a crypto fund-of-funds. Each day you receive a point-in-time dossier: market state, "
    "historical base rates, nearest historical analogues and what followed them, liquidation map, implied volatility, "
    "recent events and news headlines. Your ONLY job is a calibrated probability forecast for ONE question: "
    "where will BTC close 30 days after the dossier date, relative to the dossier close — down more than 10%, within ±10%, "
    "or up more than 10%. You are scored by Brier score against two mechanical arms (base rate, nearest neighbours). "
    "Deviate from the base rates only where the dossier gives you a concrete reason; say which reason. "
    "Do not invent numbers that are not in the dossier. No advice, no instructions to act, no buy/sell language. "
    "Return STRICT JSON only."
)
_INSTRUCTION = (
    'Return JSON of exactly this shape:\n'
    '{"down": <0..1>, "flat": <0..1>, "up": <0..1>,\n'
    ' "rationale": "<2-4 sentences: what in the dossier moves you away from (or keeps you at) the base rates>",\n'
    ' "drivers": ["<dossier field you leaned on>", ...],\n'
    ' "change_mind": "<one sentence: what observable would make you revise>"}\n'
    "Probabilities must sum to 1. DOSSIER:\n"
)


def dossier(decision: dict, news: list[dict]) -> dict:
    """纯函数。③ 决定行 + 新闻 → 交给模型的档案(只放已落表的字段;不放规则敞口,免得它去猜规则)。"""
    inp = dict(decision.get("inputs") or {})
    keep = ("mom_200", "dist_200", "funding_7d_ann", "oi_chg_30d", "breadth_above_ma50", "liq_sell_5pct", "liq_buy_15pct",
            "cycle_phase", "cycle_deterioration", "cycle_shift_pct", "dvol_btc", "dvol_btc_pct_1y", "events_7d", "btc_close",
            "probs_uncond", "n_uncond", "bucket_today", "probs_knn", "knn_n", "knn_segments", "probs_window", "window_n",
            "window_segments", "window_matches")
    return {"date": str(decision.get("d"))[:10], "question": "BTC close 30 days later vs this close: <-10% / within ±10% / >+10%",
            "state": {k: inp.get(k) for k in keep if inp.get(k) is not None},
            "base_rate_same_state": {"probs": decision.get("probs"), "bucket": decision.get("bucket"), "n_days": decision.get("n_bucket")},
            "news_48h": [{"t": str(n.get("published_at") or "")[:16], "title": str(n.get("title") or "")[:160]} for n in news[:NEWS_MAX]]}


def dossier_hash(doc: dict) -> str:
    return hashlib.sha1(json.dumps(doc, sort_keys=True, ensure_ascii=False, default=str).encode("utf-8")).hexdigest()[:16]


def parse_reply(obj: Optional[dict]) -> Optional[dict]:
    """纯函数。模型回的 JSON → {probs, rationale, drivers, change_mind};概率缺 / 非数 / 全 0 ⇒ None。归一,不截断。"""
    if not isinstance(obj, dict):
        return None
    try:
        p = {k: float(obj.get(k)) for k in ("down", "flat", "up")}
    except (TypeError, ValueError):
        return None
    if any(v != v or v < 0 for v in p.values()) or sum(p.values()) <= 0:
        return None
    tot = sum(p.values())
    if abs(tot - 1.0) > 0.15:                     # 差太多说明它没按三档答,不是舍入
        return None
    probs = {k: round(v / tot, 4) for k, v in p.items()}
    drivers = [str(x)[:60] for x in (obj.get("drivers") or []) if isinstance(x, (str, int, float))][:8]
    return {"probs": probs, "rationale": comply(obj.get("rationale")), "drivers": drivers, "change_mind": comply(obj.get("change_mind"))}


def comply(s: Any) -> Optional[str]:
    """纯函数。英文 + 中文买卖词过滤;不过 ⇒ None(概率照记,理由不存)。"""
    from src.data.narrative.llm_narrator import _clean
    c = _clean(s) if isinstance(s, str) else None
    if c is None or _BANNED_ZH.search(c):
        return None
    return c[:800]


def author_for(model: str) -> str:
    return "ai:" + re.sub(r"[^A-Za-z0-9_.\-]", "-", (model or "unknown").strip())[:40]


async def _news(now: dt.datetime) -> list[dict]:
    from src.data.style.header import _read_all
    since = (now - dt.timedelta(hours=NEWS_HOURS)).isoformat()
    try:
        rows = await _read_all("feed_items", {"select": "title,published_at,score", "published_at": f"gte.{since}", "score": "gt.0",
                                              "dup_of": "is.null", "order": "score.desc,published_at.desc", "limit": str(NEWS_MAX)})
    except Exception:                                                     # noqa: BLE001 —— 新闻读不到不挡判断
        return []
    return rows


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.evaluation.scenario_ledger import submit
    from src.data.execution.exposure_decision import scenario_entries
    from src.data.narrative import llm_narrator as llm
    from src.data.style.header import _read_all
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    d = (now.date() - dt.timedelta(days=1)).isoformat()
    author = author_for(llm._MODEL)
    have = await _read_all(TABLE, {"select": "d", "d": f"eq.{d}", "author": f"eq.{author}", "limit": "1"})
    if have:
        return {"ok": True, "status": "skipped", "why": f"{d} 已写"}
    dec = await _read_all("exposure_decision_daily", {"select": "d,inputs,probs,bucket,n_bucket", "d": f"eq.{d}", "limit": "1"})
    if not dec:
        return {"ok": True, "status": "skipped", "why": f"{d} 的 ③ 决定还没落表"}
    close = (dec[0].get("inputs") or {}).get("btc_close")
    if not close:
        return {"ok": True, "status": "skipped", "why": f"{d} 的决定里没有 BTC 收盘"}
    if not llm.configured():
        return {"ok": False, "refused": True, "status": "refused", "why": "LLM_BASE_URL 未配"}
    doc = dossier(dec[0], await _news(now))
    text = await llm._chat([{"role": "system", "content": _SYSTEM},
                            {"role": "user", "content": _INSTRUCTION + json.dumps(doc, ensure_ascii=False, default=str)}],
                           temperature=TEMPERATURE, max_tokens=MAX_TOKENS, timeout=TIMEOUT_S)
    got = parse_reply(llm._extract_json(text or ""))
    if not got:
        # 模型不通 / 答非所问 ≠「没事可做」:记 refused + 原因进 loop_attempt(skipped 会被记成 ok,原因就看不见了)
        why = (llm.LAST_ERROR or {}).get("why") or ("模型没回" if not text else
                                                   ("思考段没写完就用完了 token(max_tokens 不够)" if "<think" in text.lower() and "</think>" not in text.lower()
                                                    else "回的不是三档概率 JSON:" + re.sub(r"\s+", " ", llm._THINK.sub("", text))[-160:]))
        return {"ok": False, "refused": True, "status": "refused", "why": f"{d}:{why}"}
    sub = await submit(scenario_entries(d, float(close), got["probs"], prefix=PREFIX), author, now)
    ids = list(sub.get("ids") or [])
    row = {"d": d, "author": author, "model": llm._MODEL, "probs": got["probs"], "rationale": got["rationale"], "drivers": got["drivers"],
           "change_mind": got["change_mind"], "dossier_hash": dossier_hash(doc), "scenario_ids": ids, "code_ref": CODE_REF}
    w = await supabase_upsert_table(TABLE, [row], on_conflict="d,author")
    if not w:
        return {"ok": False, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
    base = dec[0].get("probs") or {}
    return {"ok": True, "d": d, "author": author, "probs": got["probs"], "base": base, "scenarios": len(ids),
            "scenario_why": None if sub.get("ok") else sub.get("why"),
            "why": f"{d} {author}:{got['probs']} · 基率 {base}" + ("" if sub.get("ok") else f" · 命题没入账:{sub.get('why')}")}
