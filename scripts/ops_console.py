#!/usr/bin/env python3
"""指挥台 — the local ops console for loops, health, and the forward record.

    python3 scripts/ops_console.py            # serve on http://127.0.0.1:8787
    python3 scripts/ops_console.py --json     # print the state once and exit
    python3 scripts/ops_console.py --port 9000

Stdlib only, no install, no credentials required for the public surface.

────────────────────────────────────────────────────────────────────────────────
WHY THIS EXISTS, AND WHAT IT REFUSES TO DO

The S-323 chain cost five rounds of diagnosis. Every round, the panel I was
reading said `failing` and gave me a sentence naming three suspects. The actual
causes were, in order: a missing index, a cold PostgREST schema cache, a 4xx
recorded as breaker SUCCESS, a GRANT on a function named nowhere in the message,
and finally a loop that was simply ASLEEP after one failed attempt.

The single property that would have shortened all five: **states that need
different remedies must not render the same.** So this console's whole job is
to sort by REMEDY, not by colour:

    ACT NOW      something is broken and a person must do something
    NO ACTION    a guard refused correctly — this is the system working
    WAITING      failed earlier, hasn't retried yet; nothing is broken *now*
    FOSSIL       the verdict predates the current build; it is not a judgement
    UNREGISTERED we do not have a rule for this object — a hole, not a state

A red light that is permanently on is the same as a broken light, so
"refused by policy" and "retired by policy" are pulled OUT of the alarm set and
shown as their own thing, with the reason and the S-number.

WHAT IT WILL NOT DO. It does not act. It reads, classifies, and hands each item
a `remedy_class` plus a copy-pasteable `verify` command. Execution belongs to a
person or, later, to a responder agent reading /api/state — and an agent that
acts on a misclassified state is worse than no agent, so classification is the
product here and it is deliberately conservative: anything it cannot place goes
to `unregistered` rather than to `ok`.
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

BASE = "https://web-production-0cdf76.up.railway.app"
FRESHNESS = "/internal/data-freshness"
TIMEOUT = 25

# ── Declared policy registries ──────────────────────────────────────────────
# S-323n's lesson: an object we have no rule for must be LOUD, never silently
# folded into a bucket. Anything not named here and not obviously fine lands in
# `unregistered`, which is a hole in this file — not a fact about the system.

#: Sources whose current "dead/collapsed" verdict is a DELIBERATE retirement.
#: `by_source` cannot tell "it died" from "we retired it", and the two have
#: opposite remedies: one is an incident, the other is the plan working.
RETIRED_BY_POLICY = {
    "hyperliquid": ("S-296 2026-08-23 — daily-bar role retired on the purpose "
                    "axis (market_data → CG Pro). Funding/oracle/OI still live; "
                    "check funding_history, not ohlcv_daily."),
    "binance_hist": ("S-323i — 262-symbol fan-out to a FREE venue API violates "
                     "source_policy; frozen as history. Panel bars come from "
                     "coingecko_pro_ohlc. Recovery is OPEN RISK #0a, not this feed."),
    "yfinance": ("barred from return series (S-195 bar-convention); TradFi is "
                 "served by eodhd."),
    "coingecko": ("flowing but BARRED for returns (S-195: hourly samples "
                  "collapsed to a 'daily close')."),
}

#: Loops whose refusal is the system working — **and what clears it, and when.**
#:
#: 「一个只拦不导的守卫,会把违规变成缺口」(S-296). Every outage in the S-323
#: chain was a CORRECT refusal that then never cleared, and for a product whose
#: substance is a continuous daily record, a refusal that persists is
#: outcome-identical to a crash. So "correct" is not a permanent excuse: each
#: refusal carries who clears it and how long it may sit before it becomes an
#: alarm again. A refusal with no expiry is how a guard turns into an outage.
REFUSAL_POLICY = {
    "_deep_panel_loop": {
        "reason": "S-323i source_policy — must not fan out to a free venue API.",
        "clears_when": "OPEN RISK #0a closes: cg_coin_map covers the panel and "
                       "coingecko_pro_ohlc carries the bars.",
        "owner": "Seth (ingestion is one lane, rule 3b)",
        "stale_after_days": 30,
    },
    "_forward_record_loop": {
        "reason": "S-323f/g — declared coverage baseline 262; refuses to write a "
                  "record on a panel the maintained feed does not reach.",
        "clears_when": "maintained-feed coverage ≥ 50% of 262 on a day ≤3d old.",
        "owner": "Seth",
        "stale_after_days": 30,
    },
    "_beta_core_loop": {
        "reason": "S-193/S-323o — will not mark ① against an unverified venue "
                  "universe.",
        # ① is the product book. A single missed valuation point is a permanent
        # hole (§3 refuses rather than marking late), so this one is allowed to
        # sit for essentially no time at all.
        "clears_when": "the venue listing is reachable, or the persisted copy "
                       "(S-323o/p) is fresh enough at 00:05 UTC.",
        "owner": "Seth",
        "stale_after_days": 1,
    },
    "_factor_tilt_loop": {
        "reason": "status=skipped — insufficient_live_data.",
        "clears_when": "factor_tilt_nav takes its first row.",
        "owner": "Seth",
        "stale_after_days": 3,
    },
    "_pod_aggregator_loop": {
        "reason": "status=skipped — insufficient_live_data.",
        "clears_when": "pod_aggregator_nav takes its first row.",
        "owner": "Seth",
        "stale_after_days": 3,
    },
    "_two_layer_paper_loop": {
        "reason": "status=skipped — no positions held (R57: V5c core structurally "
                  "dead; the sleeve holds zero size by design).",
        "clears_when": "a core hot-swaps in via redis two_layer_paper:core.",
        "owner": "Minimax-C",
        "stale_after_days": 14,
    },
}

#: The forward-paper gate every sleeve must clear (tests/test_strategy_discipline).
PAPER_GATE_DAYS = 60

_STARTED_AT = datetime.now(timezone.utc).isoformat()

SEV = {"act_now": 0, "unregistered": 1, "waiting": 2, "no_action": 3, "ok": 4}


def _get(path: str) -> dict:
    req = urllib.request.Request(
        BASE + path + ("&" if "?" in path else "?") + f"cb={int(_now().timestamp())}",
        headers={"User-Agent": "looloomi-ops-console"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return json.loads(r.read().decode("utf-8"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _refusal_overdue(row: dict, pol: dict) -> bool:
    """Has this refusal outlived the window we said it could sit for?

    `last_ok_at` is the only timestamp the heartbeat carries (there is no
    `last_failure_at` — recorded as debt in S-323l). So this measures "how long
    since it last did real work", which is the right question for a refusal
    anyway: a sleeve that has not produced in N days is the thing we care about,
    whatever it calls its own state.

    Missing timestamp ⇒ **not** treated as fine. Unknown is not success.
    """
    last_ok = row.get("last_ok_at")
    days = pol.get("stale_after_days")
    if days is None:
        return False
    if not last_ok:
        return True
    age_days = (_now().timestamp() - float(last_ok)) / 86400.0
    return age_days > days


def _classify_loops(loops: dict) -> list[dict]:
    """Sort loops by REMEDY. The panel's own verdict is an input, not the answer."""
    out = []
    for r in loops.get("rows", []):
        name = r.get("loop")
        verdict = r.get("verdict")
        stale = bool(r.get("stale_build"))
        err = (r.get("last_error") or r.get("last_refusal") or "").strip()
        n = r.get("n_consecutive_failures") or r.get("n_consecutive_refusals") or 0

        if verdict == "refused":
            pol = REFUSAL_POLICY.get(name)
            if not pol:
                cls = "unregistered"
                note = ("a loop is refusing and this console has no rule for it "
                        "— decide whether that refusal is correct, who clears "
                        "it, and by when; then add it to REFUSAL_POLICY")
            else:
                # A refusal is only "no action" while it is still inside the
                # window we said it could sit for. Past that, a correct refusal
                # IS the outage — that is the S-296 lesson made mechanical.
                overdue = _refusal_overdue(r, pol)
                cls = "act_now" if overdue else "no_action"
                note = (f"{pol['reason']}  ·  clears when: {pol['clears_when']}"
                        f"  ·  owner: {pol['owner']}")
                if overdue:
                    note = (f"⏱ REFUSING LONGER THAN ITS {pol['stale_after_days']}d "
                            f"WINDOW — a guard that never clears is an outage. "
                            + note)
        elif verdict == "failing":
            # A fossil verdict is NOT a judgement on the running build (S-322).
            cls = "waiting" if stale else "act_now"
            note = ("recorded on an older build — it has not run under the "
                    "current one yet, so this is not 'still failing'"
                    if stale else "failing on the current build")
            # S-325: 失败**多久之前**发生的,决定它是新闻还是旧闻。
            # 2026-09-09 Supabase 503 之后六个循环同时挂 failing,
            # 而其中大部分只是「在那次故障里失败过一次,还没轮到下一轮」。
            _age = r.get("age_s")
            if isinstance(_age, (int, float)) and _age > 0:
                _h = _age / 3600.0
                note += (f"  ·  最后一次运行在 **{_h:.1f} 小时前**"
                         + ("(**这是旧闻** —— 之后它还没再跑过,"
                            "别把它当成此刻正在坏)" if _h >= 1.5 else ""))
            if not stale and not err:
                # S-323z: 2026-09-09 `_hyperliquid_loop` showed FAILING with an
                # EMPTY error. A failure that records no reason is the thing
                # this whole console exists to surface — say so on the card
                # rather than showing a blank and letting it read as "minor".
                note = ("failing on the current build, and **the heartbeat "
                        "recorded NO reason** — the loop beat ok=False with an "
                        "empty error. Fix the beat call before diagnosing the "
                        "loop; you cannot debug a blank.")
        elif verdict == "ok":
            cls = "ok"
            note = "fossil verdict (older build)" if stale else ""
        elif verdict == "never_ran":
            cls = "act_now"
            note = "no heartbeat at all — a loop that never beats is invisible"
        else:
            cls = "unregistered"
            note = f"unrecognised verdict {verdict!r} — not treated as success"

        out.append({
            "id": f"loop:{name}", "name": name, "kind": "loop",
            "verdict": verdict, "remedy_class": cls, "n": n,
            "stale_build": stale, "detail": err[:400], "note": note,
            "verify": (f"curl -s {BASE}{FRESHNESS} | python3 -c \"import sys,json;"
                       f"[print(r) for r in json.load(sys.stdin)['loops']['rows'] "
                       f"if r['loop']=='{name}']\""),
        })
    return out


def _classify_sources(by_source: dict) -> list[dict]:
    out = []
    for s in by_source.get("sources", []):
        name = s.get("source")
        verdict = s.get("verdict")
        retired = RETIRED_BY_POLICY.get(name)
        if verdict in ("DEAD", "COLLAPSED") and retired:
            cls, note = "no_action", retired
        elif verdict in ("DEAD", "COLLAPSED"):
            cls, note = "act_now", "a source stopped and no policy explains it"
        elif verdict == "flowing" and not s.get("usable_for_returns") and retired:
            cls, note = "no_action", retired
        elif verdict == "flowing":
            cls, note = "ok", ""
        else:
            cls, note = "unregistered", f"unrecognised source verdict {verdict!r}"
        out.append({
            "id": f"source:{name}", "name": name, "kind": "source",
            "verdict": verdict, "remedy_class": cls,
            "detail": (f"{s.get('symbols_recent')}/{s.get('symbols_typical')} symbols · "
                       f"last {s.get('last_bar')} · usable_for_returns="
                       f"{s.get('usable_for_returns')}"),
            "note": note,
            "verify": f"select count(distinct symbol) from ohlcv_daily where source='{name}' and trade_date >= current_date - 3;",
        })
    # S-323n: a source with no domain rule must announce itself.
    for u in by_source.get("unregistered_sources", []) or []:
        out.append({
            "id": f"source-registry:{u}", "name": u, "kind": "source",
            "verdict": "unregistered", "remedy_class": "unregistered",
            "detail": "not in DOMAIN_OF_SOURCE",
            "note": ("a registry hole, not a domain. Per-domain verdicts are "
                     "incomplete until it is classified (S-323n)."),
            "verify": "grep -n 'DOMAIN_OF_SOURCE' -A 10 src/data/market/source_freshness.py",
        })
    return out


def _classify_books(producers: dict) -> list[dict]:
    """The forward record. This IS the product (ARCHITECTURE §validation)."""
    out: list[dict] = []
    # ⚠️ S-323z:`producers.tables` 可以整个不存在。2026-09-09 实测 Supabase
    # 503,端点**正确地**降级成 `{"verdict":"unknown","note":"producer_freshness
    # RPC 未返回 —— 读不到 ≠ 都健康"}`。上一版这里 `.get("tables") or {}`
    # 直接得到空 dict,于是**一次「读不到」被渲染成「一本账都没有问题」** ——
    # 端点诚实地降级,而我的台子把它洗成了绿色。
    if not isinstance(producers.get("tables"), dict):
        return [{
            "id": "producers:unreadable", "name": "producer freshness",
            "kind": "check", "verdict": "unknown",
            "remedy_class": "unregistered",
            "detail": str(producers.get("note") or producers.get("verdict") or "")[:300],
            "note": ("上游没能读到生产者判活 —— **这不是「都健康」**。"
                     "本轮所有 book 的状态未知,不要据此下结论。"),
            "verify": f"curl -s {BASE}{FRESHNESS} | python3 -m json.tool | head -40",
        }]
    for name, t in (producers.get("tables") or {}).items():
        if not name.endswith("_nav"):
            continue
        rows = t.get("n_rows") or 0
        verdict = t.get("verdict")
        last = (t.get("event") or {}).get("last") or (t.get("write") or {}).get("last")
        if verdict == "empty":
            cls = "act_now"
            note = "0 rows — a book with a writer that has never written"
        elif verdict == "dead":
            cls = "act_now"
            note = "stopped marking — a gap in the record cannot be backfilled (§3)"
        elif verdict == "stale":
            cls = "act_now"
            note = "writer alive, content stale"
        else:
            cls = "ok"
            note = (f"{PAPER_GATE_DAYS - rows} more marks to the "
                    f"{PAPER_GATE_DAYS}-day paper gate" if rows < PAPER_GATE_DAYS
                    else f"past the {PAPER_GATE_DAYS}-day paper gate")
        out.append({
            "id": f"book:{name}", "name": name, "kind": "book",
            "verdict": verdict, "remedy_class": cls,
            "rows": rows, "last": last,
            "detail": f"{rows} marks · last {last}",
            "note": note,
            "verify": f"select count(*), min(mark_date), max(mark_date) from {name};",
        })
    return sorted(out, key=lambda x: (SEV[x["remedy_class"]], -x["rows"]))


def _panel_symbol_reconciliation() -> dict | None:
    """S-323x: two RPCs now answer "which symbols are the panel". Reconcile them.

    `deep_panel_symbols_fast()` (loose index scan, ~200ms) serves the loop that
    only needs names; `deep_panel_symbol_list()` (full aggregate) still serves
    the healing window, which needs `latest`. That is a SECOND IMPLEMENTATION OF
    ONE QUANTITY, and S-323 is explicit that those drift — the wrapper existed
    in the first place to avoid exactly this.

    Splitting them was still right (paying a 386k-row aggregate for 262 strings
    is what put 53s on the console). The obligation that comes with it is that
    somebody compares them, every day, mechanically. Remembering they should
    agree is not a control.

    Needs SUPABASE_URL / SUPABASE_ANON_KEY in the environment; absent, this
    returns None and the console says the check did not run — **not** that it
    passed.
    """
    import json as _json
    import os
    import urllib.request as _rq

    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = (os.environ.get("SUPABASE_ANON_KEY")
           or os.environ.get("SUPABASE_KEY") or "")
    if not url or not key:
        return None

    def _rpc(fn: str) -> list:
        req = _rq.Request(
            f"{url}/rest/v1/rpc/{fn}", data=b"{}",
            headers={"apikey": key, "Authorization": f"Bearer {key}",
                     "Content-Type": "application/json"}, method="POST")
        with _rq.urlopen(req, timeout=TIMEOUT) as r:
            return _json.loads(r.read().decode())

    try:
        fast = {str(r.get("symbol", "")).upper() for r in _rpc("deep_panel_symbols_fast")}
        full = {str(r.get("symbol", "")).upper() for r in _rpc("deep_panel_symbol_list")}
    except Exception as e:                                   # noqa: BLE001
        return {"id": "panel:reconcile", "name": "panel symbol reconciliation",
                "kind": "check", "verdict": "unknown",
                "remedy_class": "unregistered",
                "detail": f"{type(e).__name__}: {str(e)[:160]}",
                "note": "the two panel RPCs could not be compared — unknown is "
                        "not agreement",
                "verify": "select count(*) from deep_panel_symbols_fast();"}

    only_fast, only_full = sorted(fast - full), sorted(full - fast)
    agree = not only_fast and not only_full
    return {
        "id": "panel:reconcile", "name": "panel symbol reconciliation",
        "kind": "check", "verdict": "ok" if agree else "DRIFT",
        "remedy_class": "ok" if agree else "act_now",
        "detail": f"fast={len(fast)} full={len(full)}"
                  + ("" if agree else f" · only_fast={only_fast[:6]}"
                                      f" only_full={only_full[:6]}"),
        "note": ("the two panel RPCs agree" if agree else
                 "TWO IMPLEMENTATIONS OF ONE QUANTITY HAVE DRIFTED (S-323x) — "
                 "the loop and the healing window are now looking at different "
                 "panels, and neither of them will say so"),
        "verify": "select count(*) from deep_panel_symbols_fast();",
    }


def build_state() -> dict:
    try:
        f = _get(FRESHNESS)
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        # An unreachable console must say so, not render an empty green board.
        return {"ok": False, "error": f"{type(e).__name__}: {e}",
                "note": "could not reach the API — this is NOT 'everything is fine'",
                "generated_at": _now().isoformat()}

    loops = _classify_loops(f.get("loops") or {})
    sources = _classify_sources(f.get("by_source") or {})
    books = _classify_books(f.get("producers") or {})
    items = loops + sources + books
    recon = _panel_symbol_reconciliation()
    if recon:
        items.append(recon)
    cov = f.get("coverage") or {}

    counts: dict[str, int] = {}
    for it in items:
        counts[it["remedy_class"]] = counts.get(it["remedy_class"], 0) + 1

    # ⚠️ S-323z:一个读不到的数,**不能渲染成一个数**。
    # 实测 2026-09-09 Supabase 503:`coverage` 降级成
    # `{"verdict":"unknown","reason":"watch_census RPC 未返回 —— 读不到 ≠ 全覆盖"}`,
    # 而这块牌子显示了大大的 `null`,底下还写着一句从 None 编出来的
    # **假话**:「None of them are track_record」。
    # **端点诚实地说了「我读不到」,我的台子把它印成了一个值和一个断言。**
    _ncov = cov.get("n_not_covered")
    if isinstance(_ncov, int):
        _cov_num = {"label": "无判决对象", "value": _ncov, "of": cov.get("n_total"),
                    "hint": f"{cov.get('n_blocking')} of them are track_record — "
                            f"the product itself"}
    else:
        _cov_num = {"label": "无判决对象", "value": "读不到",
                    "hint": str(cov.get("reason")
                               or "coverage unreadable — NOT the same as full coverage")[:120]}

    numbers = [
        {"label": "断路 loop 段", "value": sum(1 for i in loops if i["remedy_class"] == "act_now"),
         "hint": "loops broken on the CURRENT build (fossils and policy refusals excluded)"},
        _cov_num,
        {"label": "需要有人处理", "value": counts.get("act_now", 0) + counts.get("unregistered", 0),
         "hint": "act_now + unregistered; everything else is the system working"},
    ]

    return {
        "ok": True,
        "generated_at": _now().isoformat(),
        "source": BASE + FRESHNESS,
        "numbers": numbers,
        "counts": counts,
        "items": sorted(items, key=lambda x: (SEV[x["remedy_class"]], x["id"])),
        "legend": {
            "act_now": "broken now; a person must do something",
            "unregistered": "no rule for this object — a hole in the console, not a fact",
            "waiting": "failed earlier, has not retried yet; nothing is broken right now",
            "no_action": "a guard refused correctly — the system working",
            "ok": "healthy",
        },
    }


# ── HTML ────────────────────────────────────────────────────────────────────
PAGE = """<!doctype html><html><head><meta charset="utf-8">
<title>指挥台 · looloomi ops</title>
<style>
:root{--bg:#020208;--fg:#e8e8f0;--dim:#7a7a90;--line:#1e1e2e;
--act:#ff5c5c;--unreg:#ffb454;--wait:#5c9cff;--noact:#3ecf8e;--ok:#3ecf8e}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;padding:28px 32px}
h1{font-size:18px;font-weight:600;letter-spacing:.02em;margin:0 0 2px}
.sub{color:var(--dim);font-size:12px;margin-bottom:22px}
.nums{display:flex;gap:14px;flex-wrap:wrap;margin-bottom:26px}
.num{border:1px solid var(--line);border-radius:10px;padding:14px 18px;min-width:190px}
.num .v{font:600 30px/1.1 ui-monospace,"JetBrains Mono",monospace}
.num .l{color:var(--dim);font-size:12px;margin-top:5px}
.num .h{color:var(--dim);font-size:11px;margin-top:7px;opacity:.75}
h2{font-size:12px;text-transform:uppercase;letter-spacing:.09em;color:var(--dim);
margin:24px 0 9px;font-weight:600}
.row{border:1px solid var(--line);border-left-width:3px;border-radius:8px;
padding:11px 14px;margin-bottom:7px}
.row .t{display:flex;gap:10px;align-items:baseline;flex-wrap:wrap}
.nm{font:600 13px ui-monospace,"JetBrains Mono",monospace}
.badge{font-size:10px;letter-spacing:.06em;text-transform:uppercase;
padding:2px 7px;border-radius:4px;border:1px solid currentColor}
.d{color:var(--dim);font-size:12px;margin-top:6px;
font-family:ui-monospace,"JetBrains Mono",monospace;word-break:break-word}
.n{font-size:12px;margin-top:6px;opacity:.9}
.v{color:var(--dim);font-size:11px;margin-top:7px;
font-family:ui-monospace,monospace;opacity:.6;word-break:break-all}
.act_now{border-left-color:var(--act)}.act_now .badge{color:var(--act)}
.unregistered{border-left-color:var(--unreg)}.unregistered .badge{color:var(--unreg)}
.waiting{border-left-color:var(--wait)}.waiting .badge{color:var(--wait)}
.no_action{border-left-color:var(--noact)}.no_action .badge{color:var(--noact)}
.ok{border-left-color:#243}.ok .badge{color:var(--ok)}
.err{border:1px solid var(--act);color:var(--act);padding:14px;border-radius:8px}
button{background:#111120;color:var(--fg);border:1px solid var(--line);
border-radius:6px;padding:6px 13px;cursor:pointer;font-size:12px}
</style></head><body>
<h1>指挥台 <span style="color:var(--dim);font-weight:400">· looloomi ops</span></h1>
<div class="sub">按<b>处置方式</b>排序,不按颜色 —— 需要不同修法的状态绝不能长得一样。
<button onclick="load()">刷新</button> <span id="ts"></span></div>
<div id="app">loading…</div>
<script>
const ORDER=["act_now","unregistered","waiting","no_action","ok"];
const TITLE={act_now:"要处理 · 现在坏了",unregistered:"没有规则 · 这是台账的洞",
waiting:"在等 · 此刻并没有坏",no_action:"不用管 · 守卫正确地拒绝",ok:"健康"};
async function load(){
 const r=await fetch('/api/state'); const s=await r.json();
 const app=document.getElementById('app');
 document.getElementById('ts').textContent='· '+(s.generated_at||'').replace('T',' ').slice(0,19)+' UTC';
 if(!s.ok){app.innerHTML='<div class="err"><b>无法读取 API</b><br>'+s.error+
   '<br><span style="opacity:.8">'+s.note+'</span></div>';return;}
 let h='<div class="nums">';
 for(const n of s.numbers){h+='<div class="num"><div class="v">'+n.value+
   (n.of?'<span style="font-size:16px;color:var(--dim)">/'+n.of+'</span>':'')+
   '</div><div class="l">'+n.label+'</div><div class="h">'+(n.hint||'')+'</div></div>';}
 h+='</div>';
 for(const c of ORDER){
  const it=s.items.filter(i=>i.remedy_class===c); if(!it.length)continue;
  h+='<h2>'+TITLE[c]+' — '+it.length+'</h2>';
  for(const i of it){
   h+='<div class="row '+c+'"><div class="t"><span class="nm">'+i.name+
    '</span><span class="badge">'+i.kind+'</span><span class="badge">'+
    (i.verdict||'')+'</span>'+(i.n?'<span class="badge">×'+i.n+'</span>':'')+'</div>';
   if(i.detail)h+='<div class="d">'+i.detail+'</div>';
   if(i.note)h+='<div class="n">'+i.note+'</div>';
   if(i.verify&&(c==='act_now'||c==='unregistered'))h+='<div class="v">'+i.verify+'</div>';
   h+='</div>';}
 }
 app.innerHTML=h;
}
load(); setInterval(load,60000);
</script></body></html>"""


def _already_our_console(port: int) -> str | None:
    """Is the thing holding `port` this same console? Returns its timestamp.

    Asked rather than assumed, because "my own console is already up" and
    "some unrelated process owns this port" have opposite remedies — open the
    browser, versus go and look at what it is. Telling someone to `kill` a
    process we have not identified is how a console becomes a footgun.

    ⚠️ Probes /api/ping, NOT /api/state. The first version asked for
    /api/state with a 2s timeout — but /api/state fetches Railway and routinely
    takes longer than that, so a live console of our own timed out, returned
    None, and got reported as "some other process". **A slow answer became a
    wrong answer**, which is the same collapse this console exists to prevent,
    committed inside the console's own diagnostics. /api/ping touches nothing.
    """
    try:
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/ping")
        with urllib.request.urlopen(req, timeout=2) as r:
            payload = json.loads(r.read().decode()) or {}
        if payload.get("console") != "looloomi-ops":
            return None
        return payload.get("started_at")
    except Exception:                                        # noqa: BLE001
        return None


def serve(port: int) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):    # quiet
            pass

        def do_GET(self):
            if self.path.startswith("/api/ping"):
                # Deliberately touches NOTHING — no Railway call, no DB. Its
                # only job is to answer instantly so "is that my own console?"
                # is decidable. A liveness probe that can time out is not one.
                body = json.dumps({"console": "looloomi-ops",
                                   "started_at": _STARTED_AT}).encode()
                ct = "application/json; charset=utf-8"
            elif self.path.startswith("/api/state"):
                body = json.dumps(build_state(), ensure_ascii=False).encode()
                ct = "application/json; charset=utf-8"
            else:
                body, ct = PAGE.encode(), "text/html; charset=utf-8"
            self.send_response(200)
            self.send_header("Content-Type", ct)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    # S-323y: `Address already in use` has (at least) two causes with different
    # remedies — this console is already running, or something else took the
    # port — and a raw traceback renders them identically. Same defect this
    # whole chain is about, in the tool built to expose it.
    class _Server(HTTPServer):
        # A console restarted inside TIME_WAIT should just bind, not lecture.
        allow_reuse_address = True

    try:
        srv = _Server(("127.0.0.1", port), H)
    except OSError as e:
        if getattr(e, "errno", None) not in (48, 98):        # EADDRINUSE
            raise
        mine = _already_our_console(port)
        print(f"\n  端口 {port} 已被占用。")
        if mine:
            print(f"  → 那是**这个指挥台自己**,已经在跑了(generated_at="
                  f"{mine}).\n"
                  f"    直接开 http://127.0.0.1:{port} 就行,不用再起一个。")
        else:
            print("  → 占用它的**不是**这个指挥台。别盲目 kill,先看是谁:\n"
                  f"      lsof -nP -iTCP:{port} -sTCP:LISTEN")
        print(f"\n  换一个端口:  python3 scripts/ops_console.py --port {port + 1}")
        if mine:
            print(f"  或者停掉它:  lsof -ti:{port} | xargs kill\n")
        else:
            print()
        raise SystemExit(1)

    print(f"指挥台 → http://127.0.0.1:{port}    (agent surface: /api/state)")
    srv.serve_forever()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="print state once, exit")
    ap.add_argument("--port", type=int, default=8787)
    a = ap.parse_args()
    if a.json:
        st = build_state()
        print(json.dumps(st, ensure_ascii=False, indent=2))
        return 0 if st.get("ok") else 1
    serve(a.port)
    return 0


if __name__ == "__main__":
    sys.exit(main())
