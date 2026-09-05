"""
Looloomi AI — FastAPI Backend v0.6.1
Modular router architecture. God-file main.py split complete.

Routers:
  src/api/routers/market.py       — /api/v1/market/*, /api/v1/defi/*, /api/v1/mmi/*, /api/v1/signals
  src/api/routers/cis.py          — /api/v1/cis/*, /api/v1/agent/cis, /ws/cis, /internal/cis-scores
  src/api/routers/intelligence.py — /api/v1/intelligence/*, /api/v1/vc/*
  src/api/routers/vault.py        — /api/v1/vault/*, /api/v1/portfolio/*
  src/api/routers/onchain.py      — /api/v1/onchain/*
  src/api/routers/macro.py        — /api/v1/macro/*, /internal/macro-brief
  src/api/routers/quant.py        — /api/v1/quant/*, /internal/quant-push
  src/api/routers/auth.py         — /api/v1/auth/*
  src/api/routers/leads.py        — /api/v1/leads/*
  src/api/routers/social.py       — /api/v1/social/*
  src/api/routers/share.py        — /api/v1/share/og-image
  src/api/routers/factory.py      — /api/v1/factory/*
  src/api/routers/agent.py        — /api/v1/agent/tasks (A2A Phase 2.3)
  src/api/routers/keys.py         — /api/v1/keys/* (API key issuance + verification)
  src/api/routers/webhooks.py     — /api/v1/webhooks/* (grade-change push subscriptions)
  src/api/routers/trading.py      — /api/v1/trading/* (paper trading + signal queue + data mining)
  src/api/routers/vector.py       — /api/v1/cis/similar, /api/v1/cis/cluster, /api/v1/cis/embeddings,
                                     /api/v1/market/funding-rates, /api/v1/market/trending-overlay
  src/api/routers/factors.py      — /api/v1/factors/*, factor registry + §F-SEL + performance tracking
  src/api/routers/strategy_vector.py — /api/v1/strategy/* (strategy vector DB; do not confuse
                                     with strategies.py multi-factor router)
"""
import os, sys, json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi import FastAPI, Request, Header, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from src.api.routers.market import router as market_router
from src.api.routers.cis import router as cis_router
from src.api.routers.intelligence import router as intelligence_router
from src.api.routers.vault import router as vault_router
from src.api.routers.onchain import router as onchain_router
from src.api.routers.macro import router as macro_router
from src.api.routers.quant import router as quant_router
from src.api.routers.auth import router as auth_router
from src.api.routers.leads import router as leads_router
from src.api.routers.social import router as social_router
from src.api.routers.factory import router as factory_router
from src.api.routers.share import router as share_router
from src.api.routers.agent import router as agent_router
from src.api.routers.keys import router as keys_router
from src.api.routers.webhooks  import router as webhooks_router
from src.api.routers.analytics import router as analytics_router
from src.api.routers.trading import router as trading_router
from src.api.routers.vector import router as vector_router
from src.api.routers.research_intake import router as research_intake_router
from src.api.routers.mac_push import router as mac_push_router
from src.api.routers.factors import router as factors_router
from src.api.routers.discovery import router as discovery_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.signals import router as signals_router
from src.api.routers.portfolio_diagnosis import router as diagnosis_router
from src.api.routers.strategy_vector import router as strategy_vector_router
from src.api.routers.admin import router as admin_router
from src.api.routers.ohlcv import router as ohlcv_router
# Strategy intake — the write path that removes any need to share the DB key.
# Minimax-A asked for service_role to write beta-strategy records; this endpoint
# is strictly better than sharing it: the token is scoped and rotatable, AND
# StrategyRecord.validate() runs before the insert, so the discipline floor stops
# being a CI check the writer can route around.
from src.api.routers.strategy_intake import router as strategy_intake_router
from src.api.routers.mac_writes import router as mac_writes_router
from src.api.middleware.rate_limit import RateLimitMiddleware

# Legacy label, kept for /health and the staging banner. The AUTHORITY on
# whether this process may write is runtime_role.ROLE — see S-149. This line
# defaulting to "production" is what made any unset laptop a live writer.
from src.api.runtime_role import ROLE as APP_ROLE, banner as _role_banner
_ENV = os.environ.get("ENVIRONMENT", APP_ROLE)

app = FastAPI(title="Looloomi AI API", version="0.6.3")

app.add_middleware(GZipMiddleware, minimum_size=500)  # ~60% payload reduction for agents
app.add_middleware(RateLimitMiddleware)               # sliding-window rate limiter (Upstash Redis)
_frontend_origins = os.environ.get(
    "FRONTEND_ORIGINS",
    "https://looloomi.ai,https://looloomi.com,http://localhost:5173,http://localhost:8000"
).split(",")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_frontend_origins,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Security + LLM discoverability headers — applied to every response
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    # llms.txt discoverability — tells LLM crawlers where to find structured docs
    response.headers["Link"] = '</llms.txt>; rel="llms-txt"'
    response.headers["X-Llms-Txt"] = "/llms.txt"
    return response

app.include_router(market_router)
app.include_router(cis_router)
app.include_router(intelligence_router)
app.include_router(vault_router)
app.include_router(onchain_router)
app.include_router(macro_router)
app.include_router(quant_router)
app.include_router(auth_router)
app.include_router(leads_router)
app.include_router(social_router)
app.include_router(factory_router)
app.include_router(share_router)
app.include_router(agent_router)
app.include_router(keys_router)
app.include_router(webhooks_router)
app.include_router(analytics_router)
app.include_router(trading_router)
app.include_router(vector_router)
# S-164: the write path for lanes holding no service_role key. Registered here
# rather than under a prefix — /internal/* is flat by convention (cis-scores,
# macro-brief, quant-push) and the submitting lanes build URLs by hand.
app.include_router(research_intake_router)
# S-169: §NO-DIRECT-SUPABASE step 2 — the Mac lane's writes come through here
# instead of holding a service_role key. Both target tables were EMPTY when this
# was built: that path had never landed a row.
app.include_router(mac_push_router)
# ORDER IS LOAD-BEARING (2026-08-12, S-143). factors_router registers
# /api/v1/factors/{factor_id}, a single-segment parameter that matches
# /api/v1/factors/discovery — which lives in discovery_router. FastAPI
# matches in registration order, so including factors first made the whole
# discovery API unreachable, returning a plausible "Factor 'discovery' not
# found". CROSS-ROUTER shadowing is invisible when reading either file
# alone; only the assembled app shows it. Guarded by
# tests/test_no_route_is_shadowed.py.
app.include_router(discovery_router)
app.include_router(factors_router)
app.include_router(strategies_router)
app.include_router(signals_router)
app.include_router(diagnosis_router)
app.include_router(strategy_vector_router)
app.include_router(admin_router)
app.include_router(ohlcv_router)
app.include_router(strategy_intake_router)
# S-283:Mac 侧 4 个 daily writer 的代理写入 —— 这条 lane 欠了 18 天的债。
# 只立「不许直写 Supabase」的原则而不开口子,等于把对方逼回直写。
app.include_router(mac_writes_router)


# ── Hourly T2-only cis_scores snapshot (data-durability complement) ─────────
# The daily loop writes the full universe once/day — but the Mac Mini push
# has been T1-only since 2026-06-06, so T2 history has 1 datapoint/day. This
# hourly loop pulls the T2 subset from the same universe builder and writes
# additional snapshots, so T2 regains sub-day granularity without depending
# on Mac Mini. Cadence env-overridable: SNAPSHOT_HOURLY_INTERVAL_S.
_HOURLY_SNAPSHOT_S = int(os.environ.get("SNAPSHOT_HOURLY_INTERVAL_S", "3600"))


def _pillar_of(asset: dict, K: str):
    """Pillar value tolerant of every universe shape: nested pillars[K], flat lowercase a['k'],
    or a['pillar_k']. The T2 snapshot writer only read nested pillars[K] — so when the builder emits
    the FLAT shape it wrote NULL pillars every hour (latent since inception; exposed when the T1
    engine stalled 2026-07-19 and T2 became the only writer). This keeps pillars populated on the
    T2 fallback so v5 / risk-moments / edge_map survive a T1 outage."""
    p = asset.get("pillars") if isinstance(asset.get("pillars"), dict) else {}
    v = p.get(K)
    if v is None:
        # bare UPPERCASE — an already-extracted {F,M,O,S,A} dict. embedder._pillars_of
        # handled this and _pillar_of did not; the reverse was true for `pillar_k`.
        # Two resolvers, each incomplete, each believing itself the tolerant one.
        v = asset.get(K)
    if v is None:
        v = asset.get(K.lower())
    if v is None:
        v = asset.get(f"pillar_{K.lower()}")
    if v is None:
        v = asset.get(f"{K.lower()}_score")
    return v


async def _hourly_t2_snapshot_loop():
    await _asyncio.sleep(600)   # let caches warm; defer past daily loop's first run
    while True:
        try:
            from src.api.routers.cis import _build_cis_universe
            from src.api.store import supabase_insert_batch, _SB_TABLE as _SB_T
            from src.data.cis.cis_provider import canonical_regime_strict
            data = await _build_cis_universe(force_source=None)
            uni = (data or {}).get("universe", []) if isinstance(data, dict) else []
            regime = (data or {}).get("macro_regime") or (data or {}).get("regime")
            # T2-only — T1 already covered by Mac push + daily snapshot
            t2_rows = []
            for a in uni:
                tier = a.get("data_tier")
                tier_label = a.get("data_tier_label") or ("T1" if tier in (1, "1", "T1") else "T2")
                if tier_label != "T2":
                    continue
                sym = a.get("symbol") or a.get("asset_id")
                score = a.get("cis_score", a.get("score"))
                if not sym or score is None:
                    continue
                t2_rows.append({
                    "symbol":        sym,
                    "name":          a.get("name", ""),
                    "score":         score,
                    "raw_cis_score": a.get("raw_cis_score") or score,
                    "grade":         a.get("grade"),
                    "signal":        a.get("signal"),
                    "percentile":    a.get("percentile_rank"),
                    "pillar_f":      _pillar_of(a, "F"),
                    "pillar_m":      _pillar_of(a, "M"),
                    "pillar_o":      _pillar_of(a, "O"),
                    "pillar_s":      _pillar_of(a, "S"),
                    "pillar_a":      _pillar_of(a, "A"),
                    "asset_class":   a.get("asset_class", a.get("class", "")),
                    # S-123: strict. These rows ARE the series the ① book reads to
                    # size itself, so a fabricated NEUTRAL here returns as a sizing
                    # input two hops later — the loop closes.
                    "macro_regime":  canonical_regime_strict(regime),
                    "data_tier":     "T2",
                    "las":           a.get("las"),
                    "confidence":    a.get("confidence", 0.8),
                    "source":        "railway_t2_hourly",
                })
            # ── S-180: refuse to shadow a live T1 ────────────────────────────
            # `tier_label == "T2"` above is only as trustworthy as the tier
            # label, and on 2026-08-19 the label was wrong for the entire
            # universe at once (a failed Redis read read as "Mac has not
            # pushed"). These rows then landed six minutes after a T1 row for
            # the same symbol, carrying a different pillar set and a grade one
            # letter away — and cis_scores is the series the ratings history,
            # signal_outcomes and the forward record are all built on.
            #
            # So the writer checks the TABLE rather than trusting the payload.
            # Three-valued on purpose: None means Supabase could not be asked,
            # and not-knowing is not permission — we hold the write, because a
            # missing hour is recoverable and a corrupted hour is not.
            from src.api.store import supabase_fresh_t1_symbols
            fresh_t1 = await supabase_fresh_t1_symbols(max_age_minutes=90)
            shadowed = []
            if fresh_t1 is None:
                print("[SNAPSHOT] hourly T2 — HELD: could not read T1 occupancy; "
                      "declining to write rows that may shadow a live T1")
                t2_rows = []
            elif fresh_t1:
                kept = []
                for r in t2_rows:
                    if (r.get("symbol") or "").upper() in fresh_t1:
                        shadowed.append(r.get("symbol"))
                    else:
                        kept.append(r)
                t2_rows = kept

            if shadowed:
                print(f"[SNAPSHOT] hourly T2 — suppressed {len(shadowed)} rows that "
                      f"would have shadowed a fresh T1: {sorted(shadowed)[:12]}"
                      f"{' …' if len(shadowed) > 12 else ''}")
                # A large suppression is not routine housekeeping — it means the
                # builder believed the universe was T2 while the table says it is
                # T1, i.e. the S-180 misclassification is live again.
                if len(shadowed) >= 10:
                    print(f"[SNAPSHOT] ⚠️  {len(shadowed)} suppressions in one run — "
                          f"the tier resolver is misclassifying wholesale, not "
                          f"per-symbol. Check redis_status in /api/v1/cis/universe.")

            if t2_rows:
                ok = await supabase_insert_batch(t2_rows)
                print(f"[SNAPSHOT] hourly T2 — ok={ok} rows={len(t2_rows)}"
                      f" (suppressed={len(shadowed)})")
            else:
                print(f"[SNAPSHOT] hourly T2 — nothing to write "
                      f"(suppressed={len(shadowed)})")
        except Exception as _e:
            print(f"[SNAPSHOT] ⚠️  hourly T2 run failed: {_e}")
        await _asyncio.sleep(_HOURLY_SNAPSHOT_S)


@app.on_event("startup")
async def _start_hourly_t2_snapshot():
    if os.environ.get("DISABLE_HOURLY_SNAPSHOT", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_hourly_t2_snapshot_loop())
        print(f"[SNAPSHOT] ✅ hourly T2 snapshot loop scheduled (every {_HOURLY_SNAPSHOT_S}s)")


# ── Daily cis_regime_fitness compute (Simons feedback) ──────────────────────
# Runs the existing scripts/compute_regime_fitness.py logic inline — reads
# Supabase cis_scores, computes Pearson r(pillar, 7d_return) per regime,
# writes to cis_regime_fitness. Independent of Mac Mini cron.
async def _regime_fitness_loop():
    await _asyncio.sleep(900)   # let the daily snapshot land first
    while True:
        try:
            from src.api.routers.admin import trigger_regime_fitness
            # Simulate an internal call (skip auth — already in process)
            res = await trigger_regime_fitness(
                x_internal_token=os.environ.get("INTERNAL_TOKEN", "loop"),
                window_days=90,
                dry_run=False,
            )
            print(f"[REGIME_FITNESS] daily — ok={res.get('ok')} rows={res.get('rows')}")
        except Exception as _e:
            print(f"[REGIME_FITNESS] ⚠️  daily run failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_regime_fitness():
    if os.environ.get("DISABLE_REGIME_FITNESS", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_regime_fitness_loop())
        print("[REGIME_FITNESS] ✅ daily compute loop scheduled")


# ── Daily OHLCV collector (Railway safety net) ──────────────────────────────
# Pulls daily candles for all 84 CIS universe assets from CoinGecko Pro
# market_chart (geo-safe from Railway) and yfinance for TradFi. Mirrors the
# role of the Mac Mini /Volumes/.../ohlcv/ parquet library but persists to
# Supabase ohlcv_daily. Idempotent on (symbol, trade_date, source).
async def _ohlcv_collector_loop():
    await _asyncio.sleep(1800)   # defer past other daily loops
    while True:
        try:
            from src.api.routers.ohlcv import collect_ohlcv
            res = await collect_ohlcv(symbols=None, days=365)
            _rw = res.get("rows_written") or 0
            _ok = res.get("symbols_ok") or 0
            # rows=0 is a SILENT stall (both sources failing) — the exact failure that hid 06-18→07-23.
            # Make it LOUD so it surfaces in logs + can be alerted, instead of looking like a normal run.
            _warn = "  ⚠️⚠️ WROTE 0 ROWS — price feed DEGRADED (EODHD+yfinance+CG all empty?)" if _rw == 0 else ""
            print(f"[OHLCV] daily — rows={_rw} syms={_ok}/{res.get('symbols_total')} "
                  f"elapsed={res.get('elapsed_s')}s{_warn}")
        except Exception as _e:
            print(f"[OHLCV] ⚠️  daily run failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_ohlcv_collector():
    if os.environ.get("DISABLE_OHLCV", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_ohlcv_collector_loop())
        print("[OHLCV] ✅ daily collector loop scheduled")


async def _forward_record_loop():
    """Winds the forward-record clocks and pages when a book stops (S-175).

    WHY THIS EXISTS. `refresh_depth_divergence()` shipped 2026-08-18 with ZERO
    callers — its only two mentions in the repo were a test docstring and a
    preflight comment, both describing it, neither running it. And the ① book
    went 5 days without a mark in August while `/internal/beta-core-clock`
    reported that accurately to nobody, because a status endpoint only speaks
    when asked.

    Deferred 40 min past boot so it lands after the OHLCV collector: computing
    depth_z against a panel that is mid-refresh would write a thin day and then
    look like a quiet market.
    """
    await _asyncio.sleep(2400)
    while True:
        try:
            from src.data.signals.forward_record_keeper import run_once
            r = await run_once()
            flag = "" if r["ok"] else "  ⚠️"
            print(f"[FWD] depth={r['depth_divergence']['written']}w/"
                  f"{r['depth_divergence']['resolved']}r · "
                  f"books={[b['status'] for b in r['books']]}{flag}")
        except Exception as _e:
            # Loud: the whole point of this loop is that silence was the bug.
            print(f"[FWD] ⚠️  forward-record pass FAILED: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_forward_record_loop():
    _asyncio.create_task(_forward_record_loop())
    print("[FWD] ✅ forward-record keeper scheduled (writes the log, pages on a stalled book)")


async def _deep_panel_loop():
    """Keeps the 262-symbol research panel current (S-179).

    That panel is what every historical study runs on and it had NO daily
    collector — `collect_ohlcv` covers the 58-symbol CIS universe and always
    did. Measured 2026-08-19 it was 11 days stale, which silently blocked the
    depth-divergence forward record and any embedding rebuild.

    Binance, not CoinGecko, because nine years of this panel are Binance bars and
    bar convention is a property of the SOURCE (S-106/S-107: >1% open gaps run
    31.3% on Crypto vs 83.5% on DeFi). Splicing a second convention on from
    2026-08-08 would put a discontinuity in the middle of every study that
    crosses the join.

    Runs 20 min after the CIS collector so the two are not competing, and its
    result is LOGGED WITH THE FRACTION — a run that reaches 40 of 262 must not
    read like a normal day.
    """
    await _asyncio.sleep(3000)
    while True:
        try:
            from src.data.market.deep_panel_collector import collect_deep_panel
            r = await collect_deep_panel()
            flag = "" if r.get("ok") else "  ⚠️ " + r.get("diagnosis", "")
            print(f"[DEEP] {r.get('symbols_ok')}/{r.get('symbols_total')} symbols · "
                  f"{r.get('rows_upserted')} rows · {r.get('elapsed_s')}s{flag}")
            await _beat("_deep_panel_loop", ok=bool(r.get("ok")),
                        refused=bool(r.get("refused")),
                        error=r.get("diagnosis") or r.get("error"))
        except Exception as _e:
            print(f"[DEEP] ⚠️  deep-panel collection FAILED: {_e}")
            await _beat("_deep_panel_loop", ok=False, error=str(_e))
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_deep_panel_loop():
    if os.environ.get("DISABLE_DEEP_PANEL", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_deep_panel_loop())
        print("[DEEP] ✅ deep-panel daily collector scheduled (262 symbols, Binance, capped concurrency)")


async def _hyperliquid_loop():
    """场馆事实:资金费 / mark / oracle / 未平仓 —— **一次请求** (S-192 → S-296).

    Jazz, 2026-09-05:**「我们实时数据和前端应该优先走 coingecko 的付费 api,
    是接入交易生产的才读 hyperliquid。」**

    这条改掉了本循环的职责。原来它每 6 小时对 233 个永续各打一次
    `candleSnapshot` 取日线 —— 那是 market_data 用途走了 execution 源。
    S-205 的数量守卫从 **2026-08-23** 起一直正确地拦着它,于是:

        hyperliquid  177 个标的,最新 2026-08-23  ← 被拦了两周
        coingecko*    25 个标的,最新 2026-09-04  ← 活着,但只有 25 个

    **守卫只拦不导,违规就变成了缺口。** 而替代路径 `venue_snapshot()`
    早在 S-205 就写好了,`metaAndAssetCtxs` 一次请求覆盖全部永续 ——
    全仓调用点为零。自己买的卡,自己没插线。

    现在这个循环取的是 **CoinGecko 给不了的东西**:funding 决定永续 sleeve
    能不能成立(① 面板等权年化 +23.07%,毛 1.15 每年漏 ~26.5%),
    oracle-vs-mark 是基差,OI 是拥挤度。这些是场馆事实。

    面板日线不在这里 —— 走 CG Pro(付费,fan-out 是买来的权利)。
    成交标记的蜡烛也不在这里:那要一份**显式的成交名单**,而 ① 还是纸面,
    今天那份名单是空的(见 `source_policy.PURPOSE_SCOPE`)。

    每 6 小时一轮:funding 是 1 小时结算的,日频会错过 carry 的形状。
    """
    await _asyncio.sleep(2400)
    while True:
        try:
            from src.data.market.hyperliquid_collector import collect_venue_marks
            r = await collect_venue_marks()
            flag = "" if r.get("ok") else "  ⚠️ " + str(r.get("diagnosis", r.get("error", "")))
            print(f"[HL] {r.get('n_perps')} perps · {r.get('rows_written')} funding rows · "
                  f"@{r.get('funding_time')} · {r.get('elapsed_s')}s{flag}")
            # ⚠️ 这里**不接 `refused=`**。本循环没有覆盖率地板,它的失败只有
            # 两种:场馆不可达,或写库失败 —— 两种都是故障。S-294 那次我把
            # `refused` 接了上来,而它当时的失败是 `SourcePolicyError`:
            # **「按规矩拒绝写」和「这个任务的源选错了」是两个状态**,
            # 后者记成正常拒绝,就等于把设计错误伪装成健康。
            await _beat("_hyperliquid_loop", ok=bool(r.get("ok")),
                        error=None if r.get("ok") else str(r.get("diagnosis", r.get("error", ""))))
        except Exception as _e:
            print(f"[HL] ⚠️  venue marks FAILED: {_e}")
            await _beat("_hyperliquid_loop", ok=False, error=str(_e))
        await _asyncio.sleep(6 * 3600)


async def _t2_precompute_loop():
    """Compute the T2 universe OFF the request path and cache it (S-200).

    WHY. Measured 2026-08-23 in production: `railway_t2_ms = 110,390` against a
    12,000 ms budget, with every timed branch summing to 19,250 — so 91 seconds
    had no owner and the build was cancelled every single time. Only a COMPLETED
    build writes the response cache, so a build that always overruns means the
    cache can never fill; the next request rebuilds from zero and is cancelled
    again. That is a deadlock, not slowness, and it had `/cis/universe` serving
    43 T1-only assets with `macro_regime=None` while `/internal/loop-health`
    read `broken`.

    T1 stopped being computed on the request path months ago — the Mac builds it
    and pushes to Redis. This gives T2 the same shape. A fan-out to ten external
    providers does not belong behind a web request at ANY budget; the budget was
    only ever concealing that it was there.

    The loop gets a real budget because nobody is waiting on it. If it overruns
    even this, the failure is loud and the previous value keeps serving — which
    is the opposite of today, where overrunning silently produced a broken page.
    """
    import time as _time          # module-level alias lands later in this file;
                                  # importing locally removes the ordering
                                  # dependency rather than relying on it
    await _asyncio.sleep(90)          # let the app finish booting
    _interval = int(os.environ.get("CIS_T2_PRECOMPUTE_S", "600"))
    _budget = float(os.environ.get("CIS_T2_PRECOMPUTE_BUDGET_S", "240"))
    while True:
        try:
            from src.data.cis.cis_provider import calculate_cis_universe
            from src.api.store import redis_set_key
            _t0 = _time.time()
            result = await _asyncio.wait_for(calculate_cis_universe(), timeout=_budget)
            uni = (result or {}).get("universe") or []
            took = _time.time() - _t0
            if uni:
                await redis_set_key("cis:t2_universe", {
                    "universe": uni,
                    "computed_at": _time.time(),
                    "took_s": round(took, 1),
                    "branch_timing": result.get("_branch_timing") or {},
                }, ttl=7200)
                print(f"[T2] precomputed {len(uni)} assets in {took:.1f}s")
            else:
                # Empty is NOT a quiet day — it is a failed build. Do not
                # overwrite the last good copy with it (S-190).
                print(f"[T2] ⚠️  build returned 0 assets in {took:.1f}s — "
                      f"keeping the previous cached universe")
        except _asyncio.TimeoutError:
            print(f"[T2] ⚠️  precompute exceeded {_budget}s — previous value "
                  f"still serving. Check t2_branches in /health.")
        except Exception as _e:
            print(f"[T2] ⚠️  precompute failed: {_e}")
        await _asyncio.sleep(_interval)


async def _forward_return_backfill_loop():
    """Fill realized_return_7d as trades age past the horizon (S-203).

    This column being empty is what disabled the entire IC-weighting mechanism:
    234 of 234 rows NULL → compute_fitness returns [] → cis_regime_fitness stays
    at 0 rows → the IC multiplier cannot load → CIS scores on NEUTRAL weights.
    Four months, and the daily log said `ok=True rows=0` throughout.

    Hourly rather than daily on purpose. The gate that matters downstream is
    INDEPENDENT DAYS (MIN_INDEPENDENT_DAYS = 20 in compute_regime_fitness), and
    each calendar day contributes at most one regardless of how often this runs
    — so the cadence buys recovery from a missed run, not extra sample. Six days
    are measurable today; the mechanism energises at twenty.
    """
    import time as _time
    await _asyncio.sleep(1200)
    while True:
        try:
            from src.data.signals.forward_return_backfill import (
                backfill_forward_returns, coverage_report)
            r = await backfill_forward_returns()
            cov = await coverage_report()
            if r.get("ok"):
                print(f"[FWD] filled {r.get('filled')} rows · coverage "
                      f"{cov.get('coverage_pct')}% · independent_days="
                      f"{cov.get('independent_days')} (IC gate needs 20)")
            else:
                print(f"[FWD] ⚠️  {r.get('reason')}")
        except Exception as _e:
            print(f"[FWD] ⚠️  backfill failed: {_e}")
        await _asyncio.sleep(3600)


@app.on_event("startup")
async def _start_forward_return_backfill():
    if os.environ.get("DISABLE_FWD_BACKFILL", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_forward_return_backfill_loop())
        print("[FWD] ✅ forward-return backfill scheduled (IC weights energise at 20 days)")


# ── S-220: the asset_embeddings writer that never existed ────────────────────
# Measured 2026-08-24: 72 rows, last written 2026-07-24 — 31 days. Not a
# failure: there was NO scheduled writer. Embeddings were a side effect of the
# CIS cycle inside a broad except that degrades to a log line (S-144), and
# /internal/asset-vectors/rebuild is a manual trigger. The substrate MEMORY.md
# calls 「几何基底」 was a snapshot of one day in July, and every consumer kept
# reading rows — just old ones — so nothing errored.
async def _embedding_rebuild_loop():
    await _asyncio.sleep(900)          # let the CIS universe warm first
    while True:
        try:
            from src.data.vector.embedding_loop import (
                rebuild_once, INTERVAL_S, BUDGET_S)
            res = await _asyncio.wait_for(rebuild_once(), timeout=BUDGET_S)
            if res.ok:
                print(f"[VEC] rebuilt {res.written} embeddings · v{res.schema_version} "
                      f"· {res.dims}d · {res.elapsed_s}s · failed={len(res.failed_assets)}")
            else:
                # Printed as a REFUSAL, not an error: below the floor the loop is
                # working correctly by declining to overwrite a complete history
                # with a partial one. /internal/vdb-health is the observer that
                # says whether the table is actually advancing (S-188 — the alarm
                # does not live inside the thing that breaks).
                print(f"[VEC] ⚠️  no write: {res.reason}")
        except _asyncio.TimeoutError:
            print("[VEC] ⚠️  rebuild exceeded its budget — reporting, not hanging")
        except Exception as _e:
            print(f"[VEC] ⚠️  rebuild failed: {_e}")
        try:
            from src.data.vector.embedding_loop import INTERVAL_S as _iv
        except Exception:
            _iv = 24 * 3600
        await _asyncio.sleep(_iv)


@app.on_event("startup")
async def _start_embedding_rebuild():
    if os.environ.get("DISABLE_EMBEDDING_REBUILD", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_embedding_rebuild_loop())
        print("[VEC] ✅ embedding rebuild scheduled (the writer asset_embeddings never had)")


@app.on_event("startup")
async def _start_t2_precompute():
    if os.environ.get("DISABLE_T2_PRECOMPUTE", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_t2_precompute_loop())
        print("[T2] ✅ universe precompute scheduled (off the request path)")


@app.on_event("startup")
async def _start_hyperliquid_loop():
    if os.environ.get("DISABLE_HYPERLIQUID", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_hyperliquid_loop())
        print("[HL] ✅ hyperliquid daily collector scheduled (232 perps, 6h, the execution venue)")


# ── Daily signal-outcome resolver ─────────────────────────────────────────────
# Resolves 30-day directional outcomes (WIN/LOSS/EXPIRED) for matured signals.
# Runs ~once/day in-process so the LP track-record metrics stay current without
# depending on the Mac Mini OHLCV pipeline. Idempotent (only touches NULL rows).
import asyncio as _asyncio
import datetime as _dt

_OUTCOME_INTERVAL_S = 24 * 3600   # daily

# The elected valuation point, single-sourced from the ① book so the loop and the
# book can never disagree about when NAV is struck (docs/NAV_POLICY.md §3).
_NAV_VALUATION_POINT_UTC = (0, 5)   # 00:05 UTC, marking the 00:00 UTC observation


# ── S-283: SLEEP TO A WALL-CLOCK TIME, NOT FOR A DURATION ────────────────────
# `await sleep(24 * 3600)` anchors the schedule to PROCESS START. Railway redeploys
# on every push, so each deploy re-anchors every daily loop, and the mark time walks.
# Measured on the ① beta-core book over 12 marks: intervals of 10.6h to 35.9h —
# a 3.38x spread on rows that are labelled daily and feed realized_vol_30d, which
# feeds vol_target_scalar, which sets gross exposure. The unelected valuation point
# was not a reporting defect; it reached position size.
#
# Fund administration solved this a long time ago and the answer is a VALUATION
# POINT: one elected instant per day, the same instant every day, and a mark that
# cannot be struck near it is refused rather than struck late (docs/NAV_POLICY.md §3).
# Crypto has no close, so the instant must be chosen; `sleep(24h)` chose it by
# accident, differently after every deploy.
async def _sleep_until_utc(hour: int, minute: int = 0) -> None:
    """Sleep until the next occurrence of hour:minute UTC.

    Deliberately NOT jittered. Jitter is right for load-spreading and wrong for a
    valuation point: the whole property being bought is that two marks are exactly
    24h apart, so a book's daily return is a day of market.
    """
    now = _dt.datetime.now(_dt.timezone.utc)
    target = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if target <= now:
        target += _dt.timedelta(days=1)
    await _asyncio.sleep((target - now).total_seconds())


async def _await_valuation_point(tolerance_min: int = 30) -> None:
    """Wait for the valuation point BEFORE the first mark of a process (S-286).

    S-283 changed the *trailing* sleep to a wall-clock target and stopped there,
    so marks 2..N landed on the point and mark 1 — the one right after every
    deploy — did not. Railway redeploys on every push, so "mark 1" happens often.
    Measured: v5's inception row struck 07:00:52 UTC against a 00:05 point.

    Fixing the trailing sleep and leaving the leading one is the same partial
    move as scoping the inception filter to Postgres and not to Redis: the guard
    covers the path you were looking at, and the miss is on the path that runs
    first. **The first iteration of a loop is a path.**

    If the process happens to boot near the point, mark immediately — a restart
    at 00:03 should not cost the day. Otherwise wait for the next one.
    """
    if _minutes_from_valuation_point_utc(*_NAV_VALUATION_POINT_UTC) <= tolerance_min:
        return
    await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)


def _minutes_from_valuation_point_utc(hour: int, minute: int) -> float:
    """Absolute minutes to the NEAREST occurrence of the point (23:50 → 15, not 1425)."""
    now = _dt.datetime.now(_dt.timezone.utc)
    point = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    return min(abs((now - point).total_seconds()),
               abs((now - (point + _dt.timedelta(days=1))).total_seconds()),
               abs((now - (point - _dt.timedelta(days=1))).total_seconds())) / 60.0


# ── S-282:后台循环的心跳 —— 一个只进 stdout 的失败等于没有发生 ──────────
# 实测 39 个真实循环里 **28 个**的失败只 print(第一次报的 67/64 把
# `_start_*` 包装函数也数进去了 —— 夸大动机数字,今天第二次)。_outcome_tracker_loop 是最干净的
# 样本:循环活着、每天准时跑、每天失败,而 signal_outcomes 因此死了 123 天无人知。
# 心跳只记录,不重试不终止 —— 一个顺手改行为的记录器,下一个人就不敢用。
async def _beat(name: str, *, ok: bool, error: str | None = None,
                refused: bool = False) -> None:
    """转发到 `loop_beat.beat`。**签名必须与它一致。**

    ⚠️ S-294 的第二个错:我给 `beat()` 和**调用点**都加了 `refused`,
    唯独漏了中间这层薄包装 —— 线上立刻报
    `_beat() got an unexpected keyword argument 'refused'`。

    而我为此写的守卫只检查**调用点里有没有 `refused=` 这个字符串**,
    从没真的调用过 `_beat`。**一个只看调用方、不看被调方的守卫,
    作用域小于问题** —— 而它恰恰是我用来修「作用域小于问题」的那个守卫。

    `tests/test_loop_beat.py:t_the_wrapper_signature_matches_the_callee`
    现在真的调用它,三个关键字都传。
    """
    try:
        from src.api.loop_beat import beat
        await beat(name, ok=ok, error=error, refused=refused)
    except Exception:            # 心跳失败绝不能影响业务循环
        pass


_TREASURY_INTERVAL_S = 24 * 3600


async def _treasury_decisions_loop():
    """企业/主权持币的决策流 (S-292)。

    Jazz:「我们建了那么多东西,必须要连通呀,现在就像买了显卡、存储、网卡,
    但是服务器不是连通的。」所以这个循环**同时插进四个面**:心跳 (S-282)、
    判活 (S-278)、覆盖清册 (S-279)、Supabase 落库。任何一个不接就是没连线。
    """
    await _asyncio.sleep(300)
    while True:
        try:
            import httpx as _httpx

            from src.api.store import supabase_rpc, supabase_upsert_table
            from src.data.entity.writer import _cg_headers, run_once

            async def _q(table, cols):
                # 读走 RPC —— 仓里没有通用 select,而临时造一个通用读取
                # 会绕过 RLS 姿态。`treasury_known_entities` 与其余 RPC 同姿态
                # (SECURITY INVOKER,只授 service_role)。
                rows = await supabase_rpc("treasury_known_entities", {})
                return rows if isinstance(rows, list) else []

            async def _up(table, rows, on_conflict):
                return await supabase_upsert_table(table, rows, on_conflict)

            async with _httpx.AsyncClient(headers=_cg_headers(),
                                          timeout=30) as _c:
                res = await run_once(client=_c, supabase_query=_q,
                                     supabase_upsert=_up)
            print(f"[TREASURY] {res['reason'][:160]}")
            await _beat("_treasury_decisions_loop", ok=bool(res.get("ok")),
                        error=None if res.get("ok") else str(res.get("errors"))[:180])
        except Exception as _e:
            print(f"[TREASURY] ⚠️  run failed: {_e}")
            await _beat("_treasury_decisions_loop", ok=False, error=str(_e))
        await _asyncio.sleep(_TREASURY_INTERVAL_S)


@app.on_event("startup")
async def _start_treasury_loop():
    if os.environ.get("DISABLE_TREASURY_LOOP", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_treasury_decisions_loop())
        print("[TREASURY] ✅ decision-stream loop scheduled")


async def _outcome_tracker_loop():
    # small startup delay so the app is fully up before the first run
    await _asyncio.sleep(120)
    while True:
        try:
            from src.data.signals.outcome_tracker import run_outcome_tracker
            summary = await run_outcome_tracker(dry_run=False)
            print(f"[OUTCOME] daily run — resolved={summary.get('resolved')} "
                  f"win={summary.get('wins')} loss={summary.get('losses')} "
                  f"written={summary.get('rows_written')}")
            await _beat("_outcome_tracker_loop", ok=True)
        except Exception as _e:
            print(f"[OUTCOME] ⚠️  daily run failed: {_e}")
            await _beat("_outcome_tracker_loop", ok=False, error=str(_e))
        await _asyncio.sleep(_OUTCOME_INTERVAL_S)


@app.on_event("startup")
async def _start_outcome_tracker():
    if os.environ.get("DISABLE_OUTCOME_TRACKER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_outcome_tracker_loop())
        print("[OUTCOME] ✅ daily outcome-tracker loop scheduled")


# ── Prediction resolver loop — "resolve EVERY prediction" (causes/conviction/narrative) ──
# Generalises the signal outcome tracker to all sources → per-source hit rate + alpha
# written to prediction_outcomes. This is the read-back that mines the write-only logs
# (LOOP_ENGINEERING.md: turns the 88-insert/1-read imbalance around).
_PREDICTION_INTERVAL_S = 24 * 3600


async def _prediction_resolver_loop():
    await _asyncio.sleep(240)   # after the signal outcome tracker warms
    while True:
        try:
            from src.data.signals.prediction_resolver import resolve_all_predictions
            res = await resolve_all_predictions(dry_run=False)
            hr = {s: v.get("hit_rate_pct") for s, v in res.get("sources", {}).items()}
            print(f"[PRED] daily resolve — per-source hit_rate={hr}")
        except Exception as _e:
            print(f"[PRED] ⚠️  daily resolve failed: {_e}")
        await _asyncio.sleep(_PREDICTION_INTERVAL_S)


@app.on_event("startup")
async def _start_prediction_resolver_loop():
    if os.environ.get("DISABLE_PREDICTION_RESOLVER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_prediction_resolver_loop())
        print("[PRED] ✅ daily prediction-resolver loop scheduled")


# ── Causal paper book — DEMOTED 2026-08-08 to RESEARCH RECORD per OVERSIGHT §3 P0 #2 ──
# S-103 measured β-confounding; S-105 measured cost > edge. 25-day forward paper
# retained for signal-trajectory continuity, NOT as product evidence. Loop kept
# running — the graveyard is the asset. See src/data/signals/causal_paper.py.
# Daily mark, weekly rebalance (the cost-validated deployable cadence). Turns the
# walk-forward candidate into a real, honest, LP-showable number. Binance reachable
# from the Singapore region. See src/data/signals/causal_paper.py.
_CAUSAL_PAPER_INTERVAL_S = 24 * 3600


async def _causal_paper_loop():
    await _asyncio.sleep(360)   # 6 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.causal_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[CAUSAL-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
            await _beat("_causal_paper_loop", ok=True)
        except Exception as _e:
            print(f"[CAUSAL-PAPER] ⚠️  mark failed: {_e}")
            await _beat("_causal_paper_loop", ok=False, error=str(_e))
        await _asyncio.sleep(_CAUSAL_PAPER_INTERVAL_S)


@app.on_event("startup")
async def _start_causal_paper_loop():
    if os.environ.get("DISABLE_CAUSAL_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_causal_paper_loop())
        print("[CAUSAL-PAPER] ✅ daily causal paper-book loop scheduled")


# ── 顶格 RWA paper sleeve — live forward track record of the volume-gated rule ──
# Can't be backtest-validated (instrument class all-2026); accrues forward instead.
# See src/data/signals/dingge_paper.py.
async def _dingge_paper_loop():
    await _asyncio.sleep(420)   # 7 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.dingge_paper import mark_and_trade
            res = await mark_and_trade(dry_run=False)
            print(f"[DINGGE-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"open={res.get('open')} +{res.get('opened_today')}/-{res.get('closed_today')}")
            await _beat("_dingge_paper_loop", ok=True)
        except Exception as _e:
            print(f"[DINGGE-PAPER] ⚠️  mark failed: {_e}")
            await _beat("_dingge_paper_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_dingge_paper_loop():
    if os.environ.get("DISABLE_DINGGE_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_dingge_paper_loop())
        print("[DINGGE-PAPER] ✅ daily 顶格 RWA paper-sleeve loop scheduled")


# ── Combined book — DEMOTED 2026-08-08 to RESEARCH RECORD per OVERSIGHT §3 P0 #2 ────
# S-103 + S-105 refuted the L/S construction; 23-day forward paper retained for
# signal-trajectory continuity, NOT as product evidence. Loop kept running so the
# factory self-recalibration observation isn't dropped. Graveyard is the asset.
# Stage 3 of the loop-as-factory: one market-neutral book = the ensemble, marked daily.
async def _combined_book_loop():
    await _asyncio.sleep(480)   # 8 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.combined_book import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[COMBINED-BOOK] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
            await _beat("_combined_book_loop", ok=True)
        except Exception as _e:
            print(f"[COMBINED-BOOK] ⚠️  mark failed: {_e}")
            await _beat("_combined_book_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_combined_book_loop():
    if os.environ.get("DISABLE_COMBINED_BOOK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_combined_book_loop())
        print("[COMBINED-BOOK] ✅ daily combined-book NAV loop scheduled")


# ── Scalable book — DEMOTED 2026-08-08 to RESEARCH RECORD per OVERSIGHT §3 P0 #2 ──
# S-103 + S-105 refuted the L/S construction; 22-day forward paper retained for
# TREND-sleeve capacity verification (the only OVERSIGHT §2.3-surviving shape candidate
# for a DIRECTIONAL beta sleeve, not this market-neutral construction). Loop kept running.
# The high-capacity, vol-targeted book on the deepest instruments. See src/data/signals/scalable_paper.py.
async def _scalable_book_loop():
    await _asyncio.sleep(540)   # 9 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.scalable_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[SCALABLE-BOOK] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
            await _beat("_scalable_book_loop", ok=True)
        except Exception as _e:
            print(f"[SCALABLE-BOOK] ⚠️  mark failed: {_e}")
            await _beat("_scalable_book_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_scalable_book_loop():
    if os.environ.get("DISABLE_SCALABLE_BOOK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_scalable_book_loop())
        print("[SCALABLE-BOOK] ✅ daily scalable-book NAV loop scheduled")


# ── ① BETA CORE — the product book, and the benchmark for every book above ──
# Oversight review 2026-08-07: all five books accruing forward record were long/short,
# gross ~1.0, market neutral — the ④ construction CLAUDE.md says discards beta by
# construction, refuted again the same day by S-103 and S-105. Layer ①, which the return
# hierarchy calls the FoF core AND the benchmark every sleeve is measured against, had
# ZERO forward days. This loop exists because the 60-day gate is calendar-bound: the
# cheapest possible day to start is today, and every other book lacks a benchmark until
# this one runs. See src/data/signals/beta_core_paper.py.
async def _beta_core_loop():
    await _asyncio.sleep(600)   # 10 min warmup — after the panel loaders are warm
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.beta_core_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[BETA-CORE] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"bench={res.get('benchmark_nav')} excess={res.get('excess_pct')}% "
                  f"cap={res.get('exposure_cap')} regime={res.get('regime')}")
            await _beat("_beta_core_loop", ok=True)
        except Exception as _e:
            print(f"[BETA-CORE] ⚠️  mark failed: {_e}")
            await _beat("_beta_core_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


# ── USAGE METERING — the substrate an invoice stands on ──────────────────────
# Measured 2026-08-11: usage existed ONLY in Redis under a 24h TTL, and
# api_keys.request_count was incremented by nothing. There was no basis to bill
# from — not "billing is unbuilt", the usage itself did not survive a day. Same
# shape as S-105 (the strategy library in a 24h-TTL Redis key), on revenue.
#
# Redis stays the hot counter; this flushes it. Writing Postgres per request would
# put the database on the request path, which is the 2026-07-29 saturation P0.
async def _metering_flush_loop():
    from src.api.metering import FLUSH_INTERVAL_S, flush_usage
    await _asyncio.sleep(120)          # let the app settle before touching Redis
    while True:
        try:
            res = await flush_usage()
            if res.get("status") == "failed":
                print(f"[METERING] ⚠️  flush failed: {res}")
            elif res.get("status") == "ok":
                print(f"[METERING] flushed {res.get('n')} key-days for {res.get('date')}")
        except Exception as _e:
            print(f"[METERING] ⚠️  loop error: {_e}")
        await _asyncio.sleep(FLUSH_INTERVAL_S)


@app.on_event("startup")
async def _announce_role():
    """FIRST thing in the log. The alternative is learning the process's role
    and its missing credentials from a stack trace at 01:00, which is exactly
    how 2026-08-11→12 was spent."""
    print(_role_banner())


@app.on_event("startup")
async def _start_metering_loop():
    if os.environ.get("DISABLE_METERING", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_metering_flush_loop())
        print("[METERING] ✅ usage flush loop scheduled (Redis → api_usage)")


@app.on_event("startup")
async def _start_beta_core_loop():
    if os.environ.get("DISABLE_BETA_CORE", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_beta_core_loop())
        print("[BETA-CORE] ✅ daily ① beta-core NAV loop scheduled (the product book)")


# ── §5b two-layer book — forward OOS clock for the V5c core × C regime overlay ──
# R57 validated the ARCHITECTURE but found the V5c core structurally dead (2.7% engaged
# since 2025-11). This sleeve marks daily anyway — a flat day is a real observation — and
# holds ZERO size while core_state == dead. The §CORE-BAKEOFF winner hot-swaps in via the
# Redis key `two_layer_paper:core` with no code deploy. See src/data/signals/two_layer_paper.py.
async def _two_layer_paper_loop():
    await _asyncio.sleep(600)   # 10 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.two_layer_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[TWO-LAYER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"book_state={res.get('book_state')} gross={res.get('gross')}")
            await _beat("_two_layer_paper_loop", ok=True)
        except Exception as _e:
            print(f"[TWO-LAYER] ⚠️  mark failed: {_e}")
            await _beat("_two_layer_paper_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_two_layer_paper_loop():
    if os.environ.get("DISABLE_TWO_LAYER_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_two_layer_paper_loop())
        print("[TWO-LAYER] ✅ daily §5b two-layer paper-book loop scheduled")


# ── R65 fusion paper book — forward-committed live R64 cell (Seth, 2026-07-21) ──
# R64 verified the 2-sleeve fusion (25% R46 pillar_O + 75% R62 fade-the-crowd gated) passes
# 3/3 deployment gates. R65 deploys it as a live paper book so §P1's forward clock starts
# running, and replaces the CRUDE $5M capacity with a real number via fill-attribution as
# live price/ADV accumulates. Detector + cell constants are FROZEN at production time.
# See src/data/signals/fusion_paper.py for the §P1/§P2 architecture.
async def _fusion_paper_loop():
    await _asyncio.sleep(660)   # 11 min warmup
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.fusion_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[FUSION-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"gross={res.get('gross')} fill={res.get('fill_ratio_overall')} "
                  f"cap={res.get('capacity_status')} det={res.get('detector_fired_today')} "
                  f"n_days={res.get('n_days_marked')} validated={res.get('validated')}")
            await _beat("_fusion_paper_loop", ok=True)
        except Exception as _e:
            print(f"[FUSION-PAPER] ⚠️  mark failed: {_e}")
            await _beat("_fusion_paper_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_fusion_paper_loop():
    if os.environ.get("DISABLE_FUSION_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_fusion_paper_loop())
        print("[FUSION-PAPER] ✅ daily R64 fusion paper-book loop scheduled")


# ── R66 fusion paper tracking — daily monitoring of the deployed R64 cell ─────
# R65 starts the forward NAV clock; R66 adds the judgment layer: live-vs-OOS Sharpe
# gap, detector fire-rate, measured capacity evolution, validation countdown, and
# §P3 lifecycle events. Monitoring is read-only and never retunes the frozen cell.
async def _fusion_paper_tracking_loop():
    await _asyncio.sleep(900)   # 15 min warmup; let the first fusion mark settle
    while True:
        try:
            from src.research.validation.fusion_paper_tracking import compute_tracking_snapshot
            snap = await compute_tracking_snapshot()
            v = snap.get("validation_countdown", {})
            s = snap.get("sharpe_gap", {})
            d = snap.get("detector_fire", {})
            c = snap.get("capacity", {})
            events = snap.get("lifecycle_events", [])
            print(f"[FUSION-TRACK] day={v.get('n_days_marked')}/{v.get('validation_threshold_days')} "
                  f"validated={v.get('validated')} sharpe_gap={s.get('status')} "
                  f"det_fire={d.get('status')}({d.get('fire_rate')}) cap={c.get('status')} "
                  f"events={len(events)}({[e['event_type'] for e in events]})")
        except Exception as _e:
            print(f"[FUSION-TRACK] ⚠️  compute failed: {_e}")
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_fusion_paper_tracking_loop():
    if os.environ.get("DISABLE_FUSION_TRACK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_fusion_paper_tracking_loop())
        print("[FUSION-TRACK] ✅ daily R66 fusion-paper tracking loop scheduled")


# ── Strategy-2 R76 paper book — forward-committed live R76 cell (Seth, 2026-08-24) ──
# R76 verified as a standalone L/S clears 3/3 deployment gates on the 770-day panel
# (gross_t=+2.06, OOS_t=+2.47, 5/6 windows positive). R76 is the ONLY survivor of
# the cross-sectional funding-residual family (LEVEL=✓ / IVOL=PARTIAL / MOMENTUM=PARTIAL)
# and is the leg that made R77 fusion work. Mark-to-market from live Binance fapi
# close + funding data; file-based state to avoid Supabase auth complexity.
# See src/data/signals/r76_strategy2_paper.py for the §Strategy-2 architecture.
async def _r76_paper_loop():
    await _asyncio.sleep(720)   # 12 min warmup (stagger from fusion_paper's 11 min)
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.r76_strategy2_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[R76-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"gross={res.get('gross')} n={res.get('n')} "
                  f"n_days={res.get('n_days_marked')} validated={res.get('validated')}")
        except Exception as _e:
            print(f"[R76-PAPER] ⚠️  mark failed: {_e}")
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_r76_paper_loop():
    if os.environ.get("DISABLE_R76_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_r76_paper_loop())
        print("[R76-PAPER] ✅ daily R76 strategy-2 paper-book loop scheduled")


# ── ⓠ REGIME OVERRIDE paper track — parallel paper NAV under the enforcer (Seth, 2026-08-08) ──
# Per Jazz direction 2026-08-06: feed the ⓠ enforcer into the R64 fusion paper book as a
# PARALLEL paper-only NAV curve. This is NOT a live override — it's the 60-day forward
# paper test (per STRATEGY_PLAYBOOK.md §P3) that lets us evaluate the enforcer's value
# before any live promotion. Runs 12 min after boot (just after FUSION-PAPER's 11 min
# warmup, so today's R64 NAV is available) and daily thereafter.
async def _fusion_paper_regime_track_loop():
    await _asyncio.sleep(720)   # 12 min warmup — let FUSION-PAPER (11 min) mark first
    while True:
        try:
            from src.research.validation.fusion_paper_regime_track import compute_today_track
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).date().isoformat()
            row = compute_today_track(today_iso=today)
            if row is None:
                print(f"[FUSION-REGIME] no row for {today} (R64 NAV / signal missing) — skipping")
            else:
                print(f"[FUSION-REGIME] {today} band={row['band']} cap={row['exposure_cap']} "
                      f"r77_ret={row['r77_daily_return']:+.4f} regime_pnl={row['regime_pnl_usd']:+.2f} "
                      f"regime_nav={row['regime_nav_usd']:.2f}")
        except Exception as _e:
            print(f"[FUSION-REGIME] ⚠️  compute failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_fusion_paper_regime_track_loop():
    if os.environ.get("DISABLE_FUSION_REGIME", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_fusion_paper_regime_track_loop())
        print("[FUSION-REGIME] ✅ daily ⓠ regime override paper-track loop scheduled")


# ── Strategy 3 — Pod Aggregator paper book (Seth, 2026-08-23, M-79 frozen cell) ──
# Aggregates the three frozen cross-sectional legs (R46 pillar_O + R62 funding-z + R76
# funding residual) inside a single book with three safety properties the sandbox
# verdict cleared — cross-pod correlation gate (max |corr| < 0.30), vol targeting
# (12% ann), per-pod DD circuit breaker (-15%). Pure PAPER — no live orders.
# Daily mark + rebalance; idempotent per calendar day in pod_aggregator_paper.py.
# Spec: docs/STRATEGY_3_POD_AGGREGATOR.md · frozen cell: w_R46=0.34/w_R62=0.33/w_R76=0.33
async def _pod_aggregator_loop():
    await _asyncio.sleep(720)   # 12 min warmup — same offset as FUSION-REGIME
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.pod_aggregator_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[POD-AGG] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"weights={res.get('weights')} max_corr={res.get('max_corr_retained')} "
                  f"survivors={res.get('survivors')} breakers={res.get('breakers_tripped')} "
                  f"n_days={res.get('n_days_marked')}")
            await _beat("_pod_aggregator_loop", ok=True)
        except Exception as _e:
            print(f"[POD-AGG] ⚠️  mark failed: {_e}")
            await _beat("_pod_aggregator_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_pod_aggregator_loop():
    if os.environ.get("DISABLE_POD_AGGREGATOR", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_pod_aggregator_loop())
        print("[POD-AGG] ✅ daily pod-aggregator paper-book loop scheduled")


# ── Strategy 4 — Cross-Asset Factor Tilt paper book (Seth, 2026-08-23, M-80 frozen cell) ──
# Long-only tilt over the 58-asset universe (41 crypto + 17 TradFi ETFs) ranked by composite
# z_quality + z_momentum + z_lowrisk, sized by H3.2 conviction [0.5, 1.75], vol-targeted to
# 12% ann. Default long-only posture (CLAUDE.md canonical); zero shorts. Pure PAPER.
# Daily mark + rebalance; idempotent per calendar day in factor_tilt_paper.py.
# Spec: docs/STRATEGY_4_FACTOR_TILT.md · sandbox verdict NEUTRAL (gross_t=+3.86 ✓, OOS_t=+1.11 ✗)
async def _factor_tilt_loop():
    await _asyncio.sleep(780)   # 13 min warmup — one minute after POD-AGG
    # S-286: wait for the valuation point BEFORE the first mark, not only after it.
    await _await_valuation_point()
    while True:
        try:
            from src.data.signals.factor_tilt_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[FACTOR-TILT] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"today_ret={res.get('today_return')} "
                  f"factor_sharpe={res.get('factor_sharpe_attribution')} "
                  f"max_share={res.get('max_single_factor_sharpe_share')} "
                  f"n_days={res.get('n_days_marked')}")
            await _beat("_factor_tilt_loop", ok=True)
        except Exception as _e:
            print(f"[FACTOR-TILT] ⚠️  mark failed: {_e}")
            await _beat("_factor_tilt_loop", ok=False, error=str(_e))
        await _sleep_until_utc(*_NAV_VALUATION_POINT_UTC)   # S-283 valuation point


@app.on_event("startup")
async def _start_factor_tilt_loop():
    if os.environ.get("DISABLE_FACTOR_TILT", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_factor_tilt_loop())
        print("[FACTOR-TILT] ✅ daily factor-tilt paper-book loop scheduled")


# ── Signal factory recalibration — Stage 4: the loop's learning turn (weekly) ──
# Re-runs the factory, rewrites the nucleus blend to Redis (combined book self-recalibrates as
# signals decay), logs the batch to experiment_runs. This is what makes it a machine, not a script.
async def _factory_recalibrate_loop():
    await _asyncio.sleep(900)   # 15 min warmup (heavy: loads panel + all signals)
    while True:
        try:
            from src.research.factory.signal_factory import recalibrate_and_log
            res = await recalibrate_and_log()
            print(f"[FACTORY] recalibrated — nucleus={res.get('nucleus')} "
                  f"combined_sharpe={res.get('combined_sharpe')} enb={res.get('enb')}")
        except Exception as _e:
            print(f"[FACTORY] ⚠️  recalibrate failed: {_e}")
        await _asyncio.sleep(7 * 24 * 3600)   # weekly


@app.on_event("startup")
async def _start_factory_recalibrate_loop():
    if os.environ.get("DISABLE_FACTORY", "").lower() in ("1", "true", "yes"):
        return
    _asyncio.create_task(_factory_recalibrate_loop())
    print("[FACTORY] ✅ weekly signal-factory recalibration loop scheduled")


# ── Track-record refresh loop — self-tuning conviction ────────────────────────
# Recomputes signal_track_record (30d benchmark-relative outcomes from our own
# cis_scores × ohlcv_daily) daily → the Risk Meter's conviction tilt auto-recalibrates
# from fresh outcomes instead of a static snapshot. All in-DB (one RPC), idempotent.
_TRACKREC_INTERVAL_S = 24 * 3600


async def _track_record_loop():
    await _asyncio.sleep(300)   # 5 min warmup; let outcome-tracker land fresh outcomes first
    while True:
        try:
            from src.api.store import supabase_rpc
            res = await supabase_rpc("refresh_signal_track_record")
            print(f"[TRACK-REC] refreshed signal_track_record — rows={res}")
            await _beat("_track_record_loop", ok=True)
        except Exception as _e:
            print(f"[TRACK-REC] ⚠️  refresh failed: {_e}")
            await _beat("_track_record_loop", ok=False, error=str(_e))
        await _asyncio.sleep(_TRACKREC_INTERVAL_S)


@app.on_event("startup")
async def _start_track_record_loop():
    if os.environ.get("DISABLE_TRACK_RECORD", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_track_record_loop())
        print("[TRACK-REC] ✅ daily track-record refresh loop scheduled")


# ── Regime-band snapshot loop ─────────────────────────────────────────────────
# Persists the current edge-map band reading (BTC 30d gradient → band → per-tier
# expected alpha) to Supabase `regime_band_log` daily, so the band signal accrues
# its own track record. Flows to the Mac warehouse via the same sync as CIS scores
# (Railway can't write the Mac fs directly — Supabase is the bridge).
_BAND_LOG_INTERVAL_S = 24 * 3600   # daily snapshot


async def _band_log_loop():
    await _asyncio.sleep(420)   # 7 min warmup; let universe + edge map warm first
    while True:
        try:
            from src.api.routers.signals import log_regime_band
            await log_regime_band()
        except Exception as _e:
            print(f"[BAND-LOG] ⚠️  snapshot failed: {_e}")
        await _asyncio.sleep(_BAND_LOG_INTERVAL_S)


@app.on_event("startup")
async def _start_band_log_loop():
    if os.environ.get("DISABLE_BAND_LOG", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_band_log_loop())
        print("[BAND-LOG] ✅ daily regime-band snapshot loop scheduled")


# ── D3 holder-concentration refresh loop ──────────────────────────────────────
# Warms the Moralis holder-concentration map into Redis so cause_proximity serves the
# D3 (on-chain) tier without ever blocking the universe path on a Moralis fetch. Gated
# on MORALIS_API_KEY (no-ops cleanly without it). Holder concentration moves slowly →
# 6h cadence is plenty.
_HOLDER_REFRESH_INTERVAL_S = 6 * 3600


async def _holder_refresh_loop():
    await _asyncio.sleep(180)   # 3 min warmup
    while True:
        try:
            from src.data.cis.holder_provider import refresh_holder_map
            m = await refresh_holder_map()
            print(f"[HOLDER] map refreshed — {len(m)} tokens")
        except Exception as _e:
            print(f"[HOLDER] ⚠️  refresh failed: {_e}")
        await _asyncio.sleep(_HOLDER_REFRESH_INTERVAL_S)


@app.on_event("startup")
async def _start_holder_refresh_loop():
    if os.environ.get("MORALIS_API_KEY") and \
       os.environ.get("DISABLE_HOLDER_REFRESH", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_holder_refresh_loop())
        print("[HOLDER] ✅ D3 holder-concentration refresh loop scheduled")
    else:
        print("[HOLDER] ⏸ holder refresh disabled (no MORALIS_API_KEY)")


# ── Forward-supply refresh loop (the UPSTREAM cause) ──────────────────────────
# Warms {SYMBOL: forced-dilution overhang} into Redis from CoinGecko supply figures.
# Supply mechanics move slowly → 6h cadence. Feeds the conviction kernel as a cause factor.
_FWD_SUPPLY_INTERVAL_S = 6 * 3600


# Once-per-day guard so the cause SNAPSHOT (resolver input) is written once/day even
# though the live map refreshes every cycle. Upsert on (date,symbol) makes it redeploy-safe.
_cause_persist_state: dict = {}


async def _forward_supply_loop():
    await _asyncio.sleep(240)   # 4 min warmup
    while True:
        try:
            import datetime as _dt
            from src.data.cis.forward_supply import refresh_forward_supply
            m = await refresh_forward_supply()
            print(f"[FWD-SUPPLY] map refreshed — {len(m)} assets")
            # Persist ONE daily snapshot → cause_snapshots_daily. This is the resolver's
            # input for the `forward_supply` prediction source; without it that source
            # never resolves (was silently the case — table empty). See prediction_resolver.
            _today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
            if m and _cause_persist_state.get("fwd") != _today:
                from src.data.cis.cause_persistence import persist_forward_supply_daily
                _n = await persist_forward_supply_daily(m)
                if _n > 0:
                    _cause_persist_state["fwd"] = _today
                    print(f"[FWD-SUPPLY] 📸 daily cause snapshot persisted — {_n} rows")
        except Exception as _e:
            print(f"[FWD-SUPPLY] ⚠️  refresh failed: {_e}")
        await _asyncio.sleep(_FWD_SUPPLY_INTERVAL_S)


@app.on_event("startup")
async def _start_forward_supply_loop():
    if os.environ.get("DISABLE_FWD_SUPPLY", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_forward_supply_loop())
        print("[FWD-SUPPLY] ✅ upstream forward-supply refresh loop scheduled")


# ── Positioning refresh loop (UPSTREAM cause #2 — reflexive leverage) ─────────
_POSITIONING_INTERVAL_S = 30 * 60   # funding/OI move faster than supply → 30 min


async def _positioning_loop():
    await _asyncio.sleep(300)   # 5 min warmup
    while True:
        try:
            import datetime as _dt
            from src.data.cis.positioning import refresh_positioning
            m = await refresh_positioning()
            print(f"[POSITIONING] map refreshed — {len(m)} assets")
            # Daily cause snapshot (resolver input for the `positioning` source). Merges
            # into the same (date,symbol) row as forward_supply via on_conflict upsert.
            _today = _dt.datetime.now(_dt.timezone.utc).date().isoformat()
            if m and _cause_persist_state.get("pos") != _today:
                from src.data.cis.cause_persistence import persist_positioning_daily
                _n = await persist_positioning_daily(m)
                if _n > 0:
                    _cause_persist_state["pos"] = _today
                    print(f"[POSITIONING] 📸 daily cause snapshot persisted — {_n} rows")
        except Exception as _e:
            print(f"[POSITIONING] ⚠️  refresh failed: {_e}")
        await _asyncio.sleep(_POSITIONING_INTERVAL_S)


@app.on_event("startup")
async def _start_positioning_loop():
    if os.environ.get("DISABLE_POSITIONING", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_positioning_loop())
        print("[POSITIONING] ✅ upstream positioning refresh loop scheduled")


# ── Daily full-universe snapshot loop (data-durability guarantee) ─────────────
# Guarantees a daily cis_scores row for EVERY asset (T1 + T2), independent of the
# Mac Mini push. The push only carries the assets it chooses (T1 only since the
# 2026-06-06 engine change), which silently dropped the T2 half from history.
_SNAPSHOT_INTERVAL_S = 24 * 3600   # daily


async def _daily_snapshot_loop():
    await _asyncio.sleep(300)   # let caches + universe warm first
    while True:
        try:
            from src.api.routers.cis import snapshot_full_universe_to_supabase
            res = await snapshot_full_universe_to_supabase()
            print(f"[SNAPSHOT] daily — ok={res.get('ok')} rows={res.get('rows')} "
                  f"T1={res.get('t1')} T2={res.get('t2')}")
        except Exception as _e:
            print(f"[SNAPSHOT] ⚠️  daily run failed: {_e}")
        try:
            from src.api.routers.macro import daily_macro_brief_snapshot
            mres = await daily_macro_brief_snapshot()
            print(f"[SNAPSHOT] macro brief — ok={mres.get('ok')}")
        except Exception as _e:
            print(f"[SNAPSHOT] ⚠️  macro brief fallback failed: {_e}")
        try:
            # Daily conviction verdicts → conviction_verdicts_daily. This is the kernel's
            # own directional call (the deepest source per ARCHITECTURE.md) and the resolver's
            # input for the `conviction` prediction source — previously never persisted, so
            # that source could never accrue a track record. Upsert on (date,symbol).
            from src.api.routers.cis import get_cis_universe
            from src.api.routers.signals import compute_current_band
            from src.data.cis.conviction import rank_universe
            from src.data.cis.cause_persistence import persist_conviction_verdicts
            _cur = await compute_current_band()
            _u = (await get_cis_universe() or {}).get("universe", []) or []
            _rows = rank_universe(_u, _cur.get("tiers_now") or {}, _cur.get("current_band"))
            _cn = await persist_conviction_verdicts(
                _rows, band=_cur.get("current_band") or "?",
                regime=_cur.get("macro_regime") or "Unknown")
            print(f"[SNAPSHOT] conviction verdicts — {_cn} rows persisted")
        except Exception as _e:
            print(f"[SNAPSHOT] ⚠️  conviction persist failed: {_e}")
        try:
            # Daily narrative (NMA) snapshot → narrative_snapshots. 5th & final resolver
            # source; STRONG_NARRATIVE/NARRATIVE_FADE resolve, NEUTRAL is skipped. Bounded
            # to the 18 majors the engine maps to coin IDs.
            try:
                from src.data.narrative.narrative_engine import batch_narrative_signals
                from src.data.narrative import social_collector as _sc, orderflow_collector as _oc
            except ImportError:
                from data.narrative.narrative_engine import batch_narrative_signals
                from data.narrative import social_collector as _sc, orderflow_collector as _oc
            from src.data.cis.cause_persistence import persist_narrative_daily
            _nsyms = ["BTC","ETH","SOL","BNB","XRP","ADA","AVAX","DOT","NEAR",
                      "SUI","APT","HYPE","ARB","OP","LINK","UNI","AAVE","MKR"]
            _sigs = await batch_narrative_signals(_nsyms, _sc, _oc)
            _nmap = {s: (v.to_dict() if hasattr(v, "to_dict") else v) for s, v in (_sigs or {}).items()}
            _nn = await persist_narrative_daily(_nmap)
            print(f"[SNAPSHOT] narrative NMA — {_nn} rows persisted")
        except Exception as _e:
            print(f"[SNAPSHOT] ⚠️  narrative persist failed: {_e}")
        await _asyncio.sleep(_SNAPSHOT_INTERVAL_S)


@app.on_event("startup")
async def _start_daily_snapshot():
    if os.environ.get("DISABLE_DAILY_SNAPSHOT", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_daily_snapshot_loop())
        print("[SNAPSHOT] ✅ daily full-universe snapshot loop scheduled")


# ── D4 attention-diffusion (出圈) collector loop ──────────────────────────────
# Logs CoinGecko free Trending daily → trending_log (service_role write). Builds the
# attention-diffusion history forward (trending is a snapshot, not historical). Requires
# the trending_log table (scripts/trending_collector.py CREATE_SQL, run once).
async def _trending_loop():
    await _asyncio.sleep(420)
    while True:
        try:
            from scripts.trending_collector import collect_trending
            res = await collect_trending()
            print(f"[TRENDING] daily — ok={res.get('ok')} rows={res.get('rows')}")
        except Exception as _e:
            print(f"[TRENDING] ⚠️  daily run failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_trending():
    if os.environ.get("DISABLE_TRENDING", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_trending_loop())
        print("[TRENDING] ✅ daily attention-diffusion loop scheduled")


# ── Daily aged-position sweep (paper track-record bootstrapper) ────────────────
# Closes paper positions >7 days old with floating PnL in ±5% band, so the
# win-rate stat doesn't stay null forever in low-vol regimes where tightened
# SL/TP (2%/4%) still don't trigger. Paper-only — distinct exit_reason.
_AGE_SWEEP_INTERVAL_S = 24 * 3600   # daily


async def _age_sweep_loop():
    await _asyncio.sleep(3600)   # 1h warmup; never sweep on cold start
    while True:
        try:
            from src.api.routers.trading import sweep_aged_positions
            res = await sweep_aged_positions()
            swept = res.get("swept", 0)
            if swept > 0:
                syms = ", ".join(s["symbol"] for s in res.get("swept_symbols", []))
                print(f"[SWEEP] daily — swept={swept} ({syms}) "
                      f"skipped={res.get('skipped')} total_open={res.get('total_open')}")
        except Exception as _e:
            print(f"[SWEEP] ⚠️  daily run failed: {_e}")
        await _asyncio.sleep(_AGE_SWEEP_INTERVAL_S)


@app.on_event("startup")
async def _start_age_sweep():
    if os.environ.get("DISABLE_AGE_SWEEP", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_age_sweep_loop())
        print("[SWEEP] ✅ daily aged-position sweep loop scheduled")


# ── SL/TP auto-execution loop (Simons Upgrade P0.2) ──────────────────────────
# Until 2026-06-26, SL/TP was only a flag in trading.py — breached positions
# stayed open indefinitely (AAPL bled -6% past its -2% SL for 24h before this
# loop existed). Runs every 5min, scans all open positions for SL/TP breach,
# closes via close_position() (which writes to trade_results).
_SL_TP_INTERVAL_S = 5 * 60   # every 5 min


async def _sl_tp_loop():
    await _asyncio.sleep(180)   # 3 min warmup; let CIS scheduler push first
    while True:
        try:
            from src.api.routers.trading import _sl_tp_exit
            res = await _sl_tp_exit()
            closed = res.get("closed", 0)
            if closed > 0:
                print(f"[SL/TP] closed={closed} sl={res.get('sl')} tp={res.get('tp')} "
                      f"scanned={res.get('scanned')}")
        except Exception as _e:
            print(f"[SL/TP] ⚠️  run failed: {_e}")
        await _asyncio.sleep(_SL_TP_INTERVAL_S)


@app.on_event("startup")
async def _start_sl_tp_loop():
    if os.environ.get("DISABLE_SL_TP_LOOP", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_sl_tp_loop())
        print("[SL/TP] ✅ 5min SL/TP auto-execution loop scheduled")


# ── CIS-flip exit loop (Simons Upgrade P0.3) ──────────────────────────────────
# Closes positions whose CIS signal has flipped to UNDERPERFORM/UNDERWEIGHT
# (or score < 45 with NEUTRAL signal as defensive fallback). Reads latest
# scores from Supabase cis_scores — fail-soft if Supabase is unreachable.
_CIS_FLIP_INTERVAL_S = 5 * 60   # every 5 min (aligned with SL/TP loop)


async def _cis_flip_loop():
    await _asyncio.sleep(240)   # 4 min warmup (offset from SL/TP to avoid simultaneous calls)
    while True:
        try:
            from src.api.routers.trading import _cis_flip_exit
            res = await _cis_flip_exit()
            closed = res.get("closed", 0)
            if closed > 0:
                print(f"[CIS-FLIP] closed={closed} by_signal={res.get('by_signal')} "
                      f"by_score={res.get('by_score')} scanned={res.get('scanned')}")
        except Exception as _e:
            print(f"[CIS-FLIP] ⚠️  run failed: {_e}")
        await _asyncio.sleep(_CIS_FLIP_INTERVAL_S)


@app.on_event("startup")
async def _start_cis_flip_loop():
    if os.environ.get("DISABLE_CIS_FLIP_LOOP", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_cis_flip_loop())
        print("[CIS-FLIP] ✅ 5min CIS-flip exit loop scheduled")


# ── Meter-driven paper rebalance loop ─────────────────────────────────────────
# Full-universe, out-of-circle-haircut weights → live paper book. Low-frequency
# (the rebalance planner's own triggers gate actual trades). DISABLED by default:
# set REBAL_LOOP_ENABLED=1 on Railway to activate, after verifying the preview
# endpoint (GET /api/v1/trading/rebalance/preview).
_REBAL_INTERVAL_S = 6 * 60 * 60   # check 4x/day; planner decides if it actually trades


async def _paper_rebalance_loop():
    await _asyncio.sleep(360)   # 6 min warmup; let CIS push + universe warm first
    while True:
        try:
            from src.api.routers.trading import _run_paper_rebalance
            res = await _run_paper_rebalance(dry_run=False)
            # A refusal has to be louder than a no-op, not quieter. This loop used to
            # print only on `executed`, so the S-122 corrupt-side refusal would have
            # stopped the sleeve rebalancing indefinitely without a single line of
            # output — a safe decision made invisibly is how a stall becomes a finding.
            if res.get("status") == "refused":
                print(f"[REBAL] 🔴 REFUSED — {res.get('reason')} "
                      f"n_corrupt={res.get('n_corrupt')} {res.get('corrupt_positions')}")
            elif res.get("executed"):
                print(f"[REBAL] {res.get('reason')} opened={res.get('opened')} "
                      f"closed={res.get('closed')} regime={res.get('regime')}")
        except Exception as _e:
            print(f"[REBAL] ⚠️  run failed: {_e}")
        await _asyncio.sleep(_REBAL_INTERVAL_S)


@app.on_event("startup")
async def _start_paper_rebalance_loop():
    if os.environ.get("REBAL_LOOP_ENABLED", "").lower() in ("1", "true", "yes"):
        _asyncio.create_task(_paper_rebalance_loop())
        print("[REBAL] ✅ meter rebalance loop scheduled (6h cadence)")
    else:
        print("[REBAL] ⏸ loop disabled (set REBAL_LOOP_ENABLED=1 to activate)")


# ── Heartbeat / observability loop ────────────────────────────────────────────
# Polls the health verdict and alerts Telegram on a status transition (plus a
# once-daily digest). This is the loop that turns reactive firefighting into
# proactive alerts — it would have caught today's stale-push / drift / empty-
# universe incidents the moment they happened.
_HEARTBEAT_INTERVAL_S = 20 * 60   # every 20 min


async def _heartbeat_loop():
    await _asyncio.sleep(180)   # let the app + caches warm first
    while True:
        try:
            from src.api.health import heartbeat_tick
            summary = await heartbeat_tick()
            print(f"[HEARTBEAT] status={summary.get('status')}")
        except Exception as _e:
            print(f"[HEARTBEAT] ⚠️  tick failed: {_e}")
        await _asyncio.sleep(_HEARTBEAT_INTERVAL_S)


@app.on_event("startup")
async def _start_heartbeat():
    if os.environ.get("DISABLE_HEARTBEAT", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_heartbeat_loop())
        print("[HEARTBEAT] ✅ observability loop scheduled (Telegram alerts)")


# ── MCP Server (ROADMAP_A2A Phase 2.2) ───────────────────────────────────────
# Serves the CometCloud MCP tool server over BOTH transports:
#   • Streamable HTTP (MODERN, primary) at https://looloomi.ai/mcp  — POST /mcp
#       what current clients expect (Claude Desktop, Cursor, ChatGPT, Gemini).
#   • SSE (LEGACY, kept for back-compat) at https://looloomi.ai/mcp-sse/sse.
#
# Why the extra machinery: streamable HTTP runs on a session-manager task group
# that MUST be started inside the app's async lifecycle — a bare `app.mount(...)`
# 500s at request time with "Task group is not initialized" (the mounted sub-app's
# lifespan is not run by the parent). We run `session_manager.run()` inside a single
# long-lived task (anyio requires enter+exit in the same task) started on `startup`
# and stopped on `shutdown`. `stateless_http=True` = one task group, per-request
# sessions (no server-side session state to leak across Railway deploys).
# Fail-safe: if the mcp dep is missing the main app still boots.

_mcp_task = None
_mcp_stop = None
try:
    # Transport settings (stateless_http, streamable path, DNS-rebinding off) are
    # configured inside cometcloud_mcp.py — see note there re: sys.path shadowing.
    from src.mcp.cometcloud_mcp import mcp as _cometcloud_mcp

    app.mount("/mcp", _cometcloud_mcp.streamable_http_app())   # modern (primary)
    app.mount("/mcp-sse", _cometcloud_mcp.sse_app())           # legacy back-compat

    @app.on_event("startup")
    async def _start_mcp_streamable():
        global _mcp_task, _mcp_stop
        _mcp_stop = _asyncio.Event()
        _ready = _asyncio.Event()

        async def _run():
            # session_manager.run() opens the streamable task group; keep it open
            # for the app's lifetime, entered+exited in this one task (anyio rule).
            async with _cometcloud_mcp.session_manager.run():
                _ready.set()
                await _mcp_stop.wait()

        _mcp_task = _asyncio.create_task(_run())
        await _ready.wait()
        print("[MCP] ✅ streamable-HTTP live at /mcp  · legacy SSE at /mcp-sse/sse")

    @app.on_event("shutdown")
    async def _stop_mcp_streamable():
        if _mcp_stop:
            _mcp_stop.set()
        if _mcp_task:
            try:
                await _mcp_task
            except Exception:
                pass

    print("[MCP] ✅ Mounted /mcp (streamable) + /mcp-sse (sse) — ROADMAP_A2A Phase 2.2")
except Exception as _mcp_err:
    print(f"[MCP] ⚠️  Not mounted: {_mcp_err}")


# ── Agent Discovery (A2A v0.3) ────────────────────────────────────────────────

_AGENT_CARD_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    ".well-known", "agent.json"
)

# Load once at startup — static file, never changes at runtime
try:
    with open(_AGENT_CARD_PATH) as f:
        _AGENT_CARD: dict | None = json.load(f)
except Exception:
    _AGENT_CARD = None

@app.get("/.well-known/agent.json", include_in_schema=False)
async def agent_card():
    """A2A Agent Card — standard discovery document for agent-to-agent protocols."""
    if _AGENT_CARD is None:
        return JSONResponse(status_code=404, content={"error": "agent card not found"})
    return JSONResponse(content=_AGENT_CARD)


# ── Health ────────────────────────────────────────────────────────────────────
# Two endpoints: /health for Railway direct, /api/v1/health to bypass Cloudflare SPA cache.

def _writes_block() -> dict:
    """Can this process write the system of record? (S-168)

    WHY THIS IS ON /health AND NOT IN A LOG. Measured 2026-08-15: the live
    deployment reported `environment: replica`, which under S-149's role gate
    means `is_writer() == False`, which means every supabase_insert_table and
    supabase_upsert_table returns False on its first line. Production could not
    write to Supabase, and had not since 2026-08-12 — cis_scores, beta_core_nav
    and experiment_runs all stop on that date.

    The Mac T1 engine was pushing the whole time (last_cis_push age 38 min, 43
    assets, stale=false). The push arrived; the persistence was refused. Those
    two look identical from outside, which is the entire failure.

    runtime_role.py stated the assumption in a comment — "Railway sets
    ENVIRONMENT=production explicitly, so the mapping preserves the live
    deployment" — and the assumption was false. A load-bearing belief about
    another system's configuration, written down and never probed.

    `refuse_write()` logs once per target on purpose (an every-loop warning
    buries the boot banner), so nothing recurring said it. `environment:
    replica` WAS on /health the whole time and nobody read it as "writes are
    off", because it names the role rather than the consequence. So this block
    names the consequence, and the deploy-verifier fails on it.
    """
    from src.api.runtime_role import ROLE, is_writer
    ok = is_writer()
    return {
        "enabled": ok,
        "role": ROLE,
        "verdict": "ok" if ok else "READ-ONLY — nothing is being persisted",
        "why": None if ok else (
            "APP_ROLE is not 'production' on this deployment, so the S-149 role "
            "gate refuses every write to the shared record. Pushes still arrive "
            "and still return 200; they are simply not stored. Fix: set "
            "APP_ROLE=production in the Railway service variables."),
    }


_health_payload = {
    "status":  "healthy",
    "version": "0.6.3",
    "environment": _ENV,
    "sources": ["binance", "defillama", "alternative.me", "moralis", "etherscan"],
}

def _health_with_data_layer() -> dict:
    """Health that OBSERVES the data layer instead of asserting it.

    2026-07-29 incident: /health returned a hardcoded "healthy" while every
    /api/v1/cis/* endpoint hung — Supabase was resource-exhausted and the entire
    intelligence layer was dead for an unknown period. A check that cannot fail
    is not a check; it manufactures false assurance (same defect class as a CI
    test that asserts against a literal instead of the real artifact).

    Cheap and non-blocking: reads in-process breaker state, issues no I/O, so it
    stays safe to poll and cannot itself add load to a saturated backend.
    """
    from src.api.store import supabase_breaker_state
    cb = supabase_breaker_state()
    degraded = cb["open"] or cb["consecutive_failures"] > 0
    # Phase breakdown of the last universe rebuild (2026-07-31). The probe caught
    # a 12,602 ms response — exactly the build budget — and nothing could say
    # where the time went. Two hypotheses died on measurement afterwards. This
    # makes the next occurrence a one-glance answer instead of an investigation.
    try:
        from src.api.routers.cis import last_universe_build
        build = last_universe_build()
    except Exception:
        build = {}
    # Strategy-library durability (2026-08-07). The record library spent 12 days
    # persisted only to a 24h-TTL Redis key because its Postgres table had never
    # been created — every write took the fallback and logged a warning nobody
    # read. Deliberately NOT folded into `degraded`: losing durable research does
    # not make the API unhealthy, and conflating the two would either 503 a
    # perfectly serving API or bury a real data-loss signal under a green check.
    # It gets its own field so it can be alerted on separately.
    try:
        from src.data.vector.strategy_store import durability_state
        strat = durability_state()
    except Exception as e:
        strat = {"error": str(e)}
    # ① book clock: deliberately NOT here. This function's contract is "issues no I/O,
    # so it stays safe to poll and cannot itself add load to a saturated backend" — that
    # is the 2026-07-29 P0's fix, and the continuity check needs a Supabase read. Putting
    # it here would make /health the thing that saturates the backend it reports on.
    # It lives on /internal/beta-core-clock instead, polled by the EXTERNAL probe, which
    # is also the only observer that survives the deploy that breaks the marking loop.
    beta_core_note = "see /internal/beta-core-clock (kept off /health: no I/O here)"
    # 2026-09-04 B fix: 暴露 LAST_REGIME_QUORUM。这一信息以前**写在日志里、
    # 全 repo 0 reader** —— 「不可观测即不存在」,S-244 / S-263 的同一个形状。
    # 现在在 /health.data_layer.regime_quorum 同步露面,consumer 不必 import
    # beta_core_paper.py 也不必解析日志。注意:dict 空(无 `verdict` 键) =
    # "还没读历史",与"读过且裁决 ok"是不同的两个状态 —— 后者有 verdict。
    try:
        from src.data.signals.beta_core_paper import LAST_REGIME_QUORUM as _lrq
        regime_quorum_block = dict(_lrq) if _lrq else {}
    except Exception:
        regime_quorum_block = {}
    return {
        **_health_payload,
        # S-168. First-screen, because a read-only production is invisible from
        # every other field on this page — the API is genuinely healthy, it just
        # stores nothing.
        "writes": _writes_block(),
        "status": "degraded" if degraded else "healthy",
        "data_layer": {
            "supabase": "circuit_open" if cb["open"]
                        else ("failing" if cb["consecutive_failures"] else "ok"),
            "breaker": cb,
            "last_universe_build": build,
            "strategy_library": strat,
            "beta_core_clock": beta_core_note,
            # B fix (2026-09-04): 见上面注释。空 dict + `_measured=False` 让
            # consumer 一眼分辨"还没跑"与"跑了且裁决 ok"。
            "regime_quorum": regime_quorum_block,
        },
    }


@app.get("/internal/beta-core-clock")
async def beta_core_clock():
    """Is the ① book's 60-day clock actually running?

    Separate from /health on purpose: this reads Supabase, and /health is contractually
    I/O-free (the 2026-07-29 P0 was a health check sitting on top of a dead data layer;
    the fix must not become a health check that loads the data layer).

    This is the endpoint the external probe should watch, because the failure mode is
    the loop NOT running — and an in-process signal cannot report on a process that
    stopped, nor survive the deploy that broke it. 503 when stalled so an uptime monitor
    can see it without parsing the body."""
    try:
        from src.data.signals.beta_core_paper import continuity_state
        st = await continuity_state()
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:160]})
    stalled = bool(st.get("stalled") or st.get("started") is False)
    return JSONResponse(status_code=503 if stalled else 200, content=st)


@app.get("/internal/beta-core-clock-q")
async def beta_core_clock_q():
    """Is the C2 ⓠ regime override layer's 60-day clock actually running?

    Per §C2-SHIP-SPEC 2026-08-12. PARALLEL to /internal/beta-core-clock —
    the ① baseline keeps its own clock and continues independently. The ⓠ
    overlay has its own 60-day clock starting at the C2 ship date
    (target 2026-09-15, Day 60 = 2026-11-14).

    503 when stalled so an uptime monitor can see it without parsing the body.

    The endpoint reads from `beta_core_nav_q` (filtered by INCEPTION_ID and
    void_reason IS NULL) and reports the same shape as the ① endpoint:
    marks, inception, last_mark, days_since_mark, gate_days_remaining.
    """
    import datetime as _dt
    import os
    import httpx
    from src.data.signals.beta_core_q_overlay import (
        INCEPTION_ID,
        clock_q_continuity,
        state_as_of,
    )
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return JSONResponse(status_code=200, content={
            "configured": False,
            "note": "supabase unconfigured — C2 ⓠ clock cannot start until Railway env set",
        })
    # Two-table read: count rows for clock, count events from meta.
    # vdb_failure_count lives in beta_core_nav_q_meta (event log), not the main row.
    url_rows = (f"{base}/rest/v1/beta_core_nav_q?select=mark_date"
                f"&inception_id=eq.{INCEPTION_ID}&void_reason=is.null"
                f"&order=mark_date.asc&limit=500")
    url_meta = (f"{base}/rest/v1/beta_core_nav_q_meta?select=event_type"
                f"&inception_id=eq.{INCEPTION_ID}&event_type=eq.vdb_failure"
                f"&limit=500")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r1 = await c.get(url_rows, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            r2 = await c.get(url_meta, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r1.json() if r1.status_code == 200 else []
            meta = r2.json() if r2.status_code == 200 else []
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:160]})
    if not rows:
        return JSONResponse(status_code=200, content={
            "configured": True,
            "marks": 0,
            "started": False,
            "gate_days_remaining": 60,
            "inception_id": INCEPTION_ID,
            "day_60": "2026-11-14",
            "note": "ⓠ overlay has never marked — the clock is NOT running",
        })
    vdb_failure_count = len(meta)
    state = clock_q_continuity(rows=rows, vdb_failure_count=vdb_failure_count)
    payload = state_as_of(state)
    payload["inception_id"] = INCEPTION_ID
    payload["day_60"] = "2026-11-14"
    stalled = bool(state.stalled or state.started is False)
    return JSONResponse(status_code=503 if stalled else 200, content=payload)


@app.get("/internal/beta-core-clock-size")
async def beta_core_clock_size():
    """Is the C3 conviction-size 2D layer's 60-day clock actually running?

    Per §C3-SHIP-SPEC 2026-08-12. PARALLEL to /internal/beta-core-clock (C1)
    and /internal/beta-core-clock-q (C2). The C3 size layer ships 2026-09-10,
    Day 60 = 2026-11-09.

    503 when stalled so an uptime monitor can see it without parsing the body.

    The endpoint reads from `beta_core_nav_size` (filtered by INCEPTION_ID and
    void_reason IS NULL). Day 30 drift_audit and Day 45 cell_flip events
    are queried from `beta_core_nav_size_meta`.
    """
    import os
    import httpx
    from src.data.signals.beta_core_size import (
        INCEPTION_ID,
        DAY_60,
        clock_q_continuity,
        state_as_of,
    )
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return JSONResponse(status_code=200, content={
            "configured": False,
            "note": "supabase unconfigured — C3 size clock cannot start until Railway env set",
        })
    url_rows = (f"{base}/rest/v1/beta_core_nav_size?select=mark_date"
                f"&inception_id=eq.{INCEPTION_ID}&void_reason=is.null"
                f"&order=mark_date.asc&limit=500")
    url_meta = (f"{base}/rest/v1/beta_core_nav_size_meta?select=event_type"
                f"&inception_id=eq.{INCEPTION_ID}"
                f"&event_type=in.(drift_audit,cell_flip,size_lookup_failure)"
                f"&limit=500")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r1 = await c.get(url_rows, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            r2 = await c.get(url_meta, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r1.json() if r1.status_code == 200 else []
            meta = r2.json() if r2.status_code == 200 else []
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:160]})
    if not rows:
        return JSONResponse(status_code=200, content={
            "configured": True,
            "marks": 0,
            "started": False,
            "gate_days_remaining": 60,
            "inception_id": INCEPTION_ID,
            "day_60": DAY_60,
            "note": "C3 size layer has never marked — the clock is NOT running",
        })
    # Reuse the C2 continuity helper for the same shape (per §C3 §3 it has
    # the same 60-day gate, same stalled definition).
    events_count = len(meta)
    state = clock_q_continuity(rows=rows, vdb_failure_count=events_count)
    payload = state_as_of(state)
    payload["inception_id"] = INCEPTION_ID
    payload["day_60"] = DAY_60
    stalled = bool(state.stalled or state.started is False)
    return JSONResponse(status_code=503 if stalled else 200, content=payload)


@app.get("/internal/r77-forward-episodes")
async def r77_forward_episodes(x_internal_token: str = Header(None)):
    """Is the C5 R77 forward episode attribution clock actually running?

    Per §C5-SHIP-SPEC 2026-08-12. PARALLEL to /internal/beta-core-clock (C1),
    /internal/beta-core-clock-q (C2), and /internal/beta-core-clock-size (C3).
    The C5 episode layer ships 2026-09-15, Day 60 = 2026-11-14.

    503 when stalled so an uptime monitor can see it without parsing the body.

    The endpoint reads from `r77_forward_episodes` (filtered by INCEPTION_ID
    and void_reason IS NULL) and reports live forward episode attribution:
    total_episodes, positive_count, negative_count, pooled_t_mean, verdict.

    DEPENDS ON D2 push backfill (Minimax-A): r77_fwd_5d_alpha_pct labels
    must be present per day for alpha_count > 0 on episodes. Before D2 ships,
    rows land with alpha_count=0 and verdict defaults to C5_INSUFFICIENT_EPISODES.
    """
    # S-262:策略内部状态(起始日、第 60 天倒计时)不公开。
    # 查实无消费者:仓库 / Shadow / dashboard 全部 grep 无引用。
    # ⚠️ 这里【不能】写 `_INTERNAL_TOKEN` —— 那个常量只在 `src/api/routers/*.py` 里,
    # `main.py` 没有。我第一版从 routers 抄了模式,结果是 NameError,
    # **而且只在鉴权分支上抛** —— import 能过、py_compile 能过、正常路径能过,
    # 只有真的有人不带 token 来打时才炸,然后返回 500 而不是 401。
    # 今天第二次踩「只在错误路径上炸」(auth.py 的 _log vs _logger)。
    # `main.py` 也【没有】导入 HTTPException —— 它自己的 /internal/ 路由用的是
    # `JSONResponse(status_code=401, ...)`。这是同一个改动里第三次
    # 「只在错误路径上炸」:先是 _INTERNAL_TOKEN 不存在,再是 HTTPException 不存在。
    # 三次都是**跨模块抄惯用法而不查导入**,三次都是 import/py_compile 全过、
    # 正常路径全过,只有真的有人不带 token 来打时才 500。
    # 静态扫描抓不到任何一次 —— 抓到它们的是 TestClient 打了一次真请求。
    # ⚠️ 用 `_os` 别名,不用裸 `os`:这两个函数体里**后面有局部 `import os`**,
    # 那会让 `os` 在整个函数作用域内变成局部名,于是鉴权分支上的
    # `os.environ` 抛 `UnboundLocalError`。这是同一个改动里的**第四次**
    # 「只在错误路径上炸」:_INTERNAL_TOKEN 不存在 → HTTPException 不存在 →
    # os 被遮蔽。四次的共同点是**静态检查一次都抓不到**,
    # 而每一次都是 TestClient 打一个真请求抓到的。
    import os as _os
    _tok = _os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or not x_internal_token or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    import os
    import httpx
    import pandas as pd
    from src.research.validation.r77_episode_vdb_cluster import (
        INCEPTION_ID,
        C5_EPISODES_CLEAR,
        C5_INSUFFICIENT_EPISODES,
        C5_HETEROGENEOUS_REGIME,
    )
    base, key = os.environ.get("SUPABASE_URL"), os.environ.get("SUPABASE_KEY")
    if not base or not key:
        return JSONResponse(status_code=200, content={
            "configured": False,
            "note": "supabase unconfigured — C5 R77 forward episode clock cannot start",
        })
    url_rows = (f"{base}/rest/v1/r77_forward_episodes?select=episode_id,"
                f"mark_date,end_date,n_days,episode_sign,mean_daily_alpha,"
                f"episode_t_pooled,alpha_count,void_reason"
                f"&inception_id=eq.{INCEPTION_ID}&void_reason=is.null"
                f"&order=mark_date.asc&limit=500")
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r1 = await c.get(url_rows, headers={"apikey": key, "Authorization": f"Bearer {key}"})
            rows = r1.json() if r1.status_code == 200 else []
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:160]})
    if not rows:
        return JSONResponse(status_code=200, content={
            "configured": True,
            "marks": 0,
            "started": False,
            "gate_days_remaining": 60,
            "inception_id": INCEPTION_ID,
            "day_60": "2026-11-14",
            "total_episodes": 0,
            "positive_count": 0,
            "negative_count": 0,
            "pooled_t_mean": None,
            "verdict": C5_INSUFFICIENT_EPISODES,
            "note": "C5 R77 forward episode layer has never marked — clock NOT running",
        })
    total = len(rows)
    pos = sum(1 for r in rows if (r.get("episode_sign") or 0) > 0)
    neg = sum(1 for r in rows if (r.get("episode_sign") or 0) < 0)
    pooled_ts = [r["episode_t_pooled"] for r in rows
                 if r.get("episode_t_pooled") is not None]
    pooled_t_mean = round(sum(pooled_ts) / len(pooled_ts), 4) if pooled_ts else None
    # Verdict heuristic (mirror verify_episode_floor)
    if total < 8:
        verdict = C5_INSUFFICIENT_EPISODES
    elif pos / max(total, 1) < (2 / 3):
        verdict = C5_HETEROGENEOUS_REGIME
    elif pooled_t_mean is None or pooled_t_mean < 2.0:
        verdict = C5_HETEROGENEOUS_REGIME
    else:
        verdict = C5_EPISODES_CLEAR
    # Stalled = no marks in last 7d
    last_date = max(pd.Timestamp(r["mark_date"]) for r in rows) if rows else None
    stalled = last_date is None or (pd.Timestamp.now().normalize() - last_date).days > 7
    return JSONResponse(
        status_code=503 if stalled else 200,
        content={
            "configured": True,
            "started": True,
            "inception_id": INCEPTION_ID,
            "day_60": "2026-11-14",
            "total_episodes": total,
            "positive_count": pos,
            "negative_count": neg,
            "pooled_t_mean": pooled_t_mean,
            "verdict": verdict,
            "r77_status_unchanged": True,
            "note": (f"C5 verdict={verdict}; R77 status remains 'regime-specific "
                     "candidate' (frozen weights at w_R46=0.25/w_R62=0.75/w_R76=0.30)"),
        },
    )


@app.get("/api/v1/beta-core/curve")
async def beta_core_curve(limit: int = 400):
    """The ① book's forward curve, WITH hold-the-panel beside it.

    This endpoint did not exist until 2026-08-10 (S-132), which is worth stating
    plainly: the ① book is the layer-① claim — "we capture beta and draw down
    less" — and its curve is the evidence for it, but nothing served that curve.
    We had a running clock (/internal/beta-core-clock) and no way to read what the
    clock was counting. A forward record nobody can fetch is not a track record.

    Published in percent AND in dollars per $1m deployed. Berk & van Binsbergen
    (JFE 2015): percentage alpha does not predict itself; dollars extracted do.
    `deployable_notional_usd` is deliberately null — the ① book has no ADV wiring,
    and an assumed AUM would manufacture a dollar figure indistinguishable from a
    measured one.

    Read `days_to_gate` and `annualization_is_meaningful` before quoting anything:
    below 60 forward days the annualized number is arithmetic, not evidence."""
    try:
        from src.data.signals.beta_core_paper import get_curve
        return await get_curve(limit=limit)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:160]})


@app.get("/health")
async def health():
    payload = _health_with_data_layer()
    # 503 when degraded so uptime monitors and Railway see it, instead of a
    # green check sitting on top of a dead intelligence layer.
    return JSONResponse(status_code=503 if payload["status"] == "degraded" else 200,
                        content=payload)

@app.get("/api/v1/health")
async def health_api():
    """API-prefixed health check — bypasses Cloudflare SPA caching rules."""
    payload = _health_with_data_layer()
    return JSONResponse(status_code=503 if payload["status"] == "degraded" else 200,
                        content=payload)


# ── Build/deploy self-introspection ───────────────────────────────────────────
# Answers the question Jazz asks every session: "what's actually LIVE on Railway,
# and is my local HEAD ahead of it?" The running instance reports the git sha it
# was built from (Railway injects RAILWAY_GIT_COMMIT_SHA) so a local script can
# diff live-sha vs `git rev-parse HEAD` and count undeployed commits. Also surfaces
# the freshness + provenance of the last Mac Mini push, so deploy health and data
# health are visible in one place. Public read (git sha is non-sensitive).
import time as _time

_BOOT_TS = _time.time()


@app.post("/internal/telegram/webhook")
async def telegram_webhook(update: dict, request: Request):
    """Telegram bot webhook — conversational CIS agent. Verified via the secret
    token Telegram echoes in a header (set when registering the webhook).

    **Fail CLOSED when the secret is unset (S-262).** The previous guard read
    `if secret and header != secret: 403`, which collapses two states into one
    branch: *no secret configured* took the same path as *secret matched*. So a
    deploy that simply never set `TELEGRAM_WEBHOOK_SECRET` served an open
    endpoint that anyone could POST arbitrary Telegram updates to and puppet the
    bot with — and it looked identical, from the outside, to a correctly
    configured one. Found by sending a real anonymous POST, not by reading the
    line; three static scanners had passed over it.

    Unconfigured now answers 503, not 200: a bot that is down is a visible
    problem, a bot anyone can drive is an invisible one.
    """
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if not secret:
        return JSONResponse(status_code=503, content={
            "ok": False,
            "error": "TELEGRAM_WEBHOOK_SECRET is not configured",
            "detail": ("Refusing to accept unverified updates. Set the variable and "
                       "re-register the webhook with the same secret_token."),
        })
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return JSONResponse(status_code=403, content={"ok": False})
    try:
        from src.api.telegram_bot import handle_update
        await handle_update(update)
    except Exception as e:
        print(f"[TG] webhook error: {e}")
    return {"ok": True}


@app.get("/internal/data-coverage")
async def data_coverage(symbol: str | None = None):
    """每个 symbol×source 我们**实际**持有多深 —— 跨 lane 的共享基线 (S-276).

    ## 为什么存在:一次可查证的重复劳动

    M-118(minimax-c,2026-09-02)用 CG Pro 回填 5 个标的,报「PENDLE +820 天,
    大赢家」。查证:Supabase 里 `coingecko` 源的 PENDLE **1940 行、2021-04-28 起**
    —— 与他抓到的起始日一模一样。那 820 天我们早就有了。

    根因不是粗心:**minimax-c 读不到 Supabase**,只能拿 Mac 侧单一个源
    (`binance_hist`,PENDLE 2023-07-03 起)当基线。于是两个状态在他那里同形 ——
    「我们真的只有 2023 年起的数据」和「有更深的源,只是不是他在看的那个」。

    **让他更小心解决不了;给他一个可查的基线才能。**

    所以本端点回答的是他真正的问题:*如果我去回填 X,实际能新增多少?*
    答案取**跨源并集的最深起点**(`deepest_start`),不是任一个源的。

    与 `/internal/data-freshness` 的分工:那个回答「哪个管道死了」,
    这个回答「我们有多深」。**两个问题,两个答案** —— S-272 的教训是
    一个响应里若有两个裁决而顶层没有,告警会挑更眼熟的那个。

    无凭证可读(与该族其余端点一致,见 tests/test_internal_routes_reject_anonymous
    的 PUBLIC_BY_DESIGN):它只有覆盖形状,没有价格数值,而 minimax-c 需要它
    且不该拿到 service_role(Jazz 2026-08-30)。
    """
    import time as _t
    from src.api.store import redis_get_key, redis_set_key, supabase_rpc
    from src.data.market.coverage import CONSUMER_NOTE, as_json, build, lookup

    CACHE_KEY = "ohlcv:symbol_coverage"

    cached = None
    try:
        cached = await redis_get_key(CACHE_KEY)
    except Exception:                                             # noqa: BLE001
        cached = None

    rows, served_from = None, None
    if isinstance(cached, dict) and cached.get("rows"):
        rows, served_from = cached["rows"], "cache"
    else:
        try:
            raw = await supabase_rpc("ohlcv_symbol_coverage", {})
            if isinstance(raw, list):
                rows = [{"symbol": r.get("symbol"), "source": r.get("source"),
                         "n": r.get("n"),
                         "first": r.get("first_date"), "last": r.get("last_date")}
                        for r in raw]
                served_from = "upstream"
                try:
                    # 6h TTL:覆盖度是慢变量,而 Supabase 是免费档
                    # (Jazz:「能不增加用量就不增加」)。一次全表聚合,不按标的 fan-out。
                    await redis_set_key(CACHE_KEY, {"rows": rows}, ttl=21600)
                except Exception:                                 # noqa: BLE001
                    pass
        except Exception as e:                                    # noqa: BLE001
            # **读不到 ≠ 没有数据** (S-180)。RPC 未部署时必须说出来,
            # 否则下游会把空当成「这些标的都不存在」—— 而那正是
            # 本端点要修的那个误读。
            return {"verdict": "unavailable", "served_from": None,
                    "error": f"{type(e).__name__}",
                    "note": ("ohlcv_symbol_coverage RPC 读取失败 —— "
                             "**读不到不等于库里没有**。在它恢复之前,"
                             "不要把任何标的当成缺失来回填"),
                    "consumer_note": CONSUMER_NOTE}

    if not rows:
        return {"verdict": "unavailable", "served_from": served_from,
                "note": "RPC 返回空 —— 读不到 ≠ 库里没有",
                "consumer_note": CONSUMER_NOTE}

    cov = build(rows)
    if symbol:
        c = lookup(cov, symbol.upper())
        return {"verdict": c.verdict, "served_from": served_from,
                "symbol": c.symbol, "deepest_start": c.deepest_start,
                "best_source": c.best_source, "latest": c.latest,
                "per_source": [
                    {"source": s.source, "n": s.n, "first": s.first, "last": s.last}
                    for s in c.per_source],
                "reason": c.reason, "consumer_note": CONSUMER_NOTE}

    j = as_json(cov)
    return {
        "verdict": "ok", "served_from": served_from,
        "checked_at": int(_t.time()),
        "n_symbols": len(j),
        "n_pairs": sum(x["n_sources"] for x in j.values()),
        "consumer_note": CONSUMER_NOTE,
        "coverage": j,
    }


@app.get("/internal/data-freshness")
async def data_freshness(x_internal_token: str = Header(None, alias="X-Internal-Token")):
    """Age of every pipeline that can die silently. One cheap query per table.

    Built 2026-07-31 for the external probe. The probe needs price-feed freshness
    but can no longer read `ohlcv_daily` anonymously (RLS closed that on 2026-07-30,
    correctly), and routing it through `/internal/loop-health` coupled a
    fast tripwire to a slow 8–25 s sweep — the precise coupling the tripwire exists
    to avoid. So: a dedicated endpoint that is cheap by construction.

    Silent pipeline death is the failure class that has now cost us three times
    (T2 pillars all-NULL for months; signal_outcomes dead 80 days; ohlcv_daily
    stalled 4 days and found only by accident). Freshness must be a first-class,
    queryable fact — not something inferred from whether some other thing looks OK.
    """
    # Reuses the existing §BETA-METRIC-AGG freshness helper (5 min cached, already
    # honest about failure) rather than adding a second way to ask the same
    # question — a duplicate freshness path is how two sources of truth start.
    # Public by design (external probe), so the token only ADDS detail — it
    # never gates the verdict. A probe that starts 401-ing is a probe that
    # gets deleted, and then nothing watches the pipelines at all.
    _expected_tok = os.environ.get("INTERNAL_TOKEN")
    _tok_ok = bool(_expected_tok) and x_internal_token == _expected_tok

    from src.api.store import supabase_ohlcv_daily_freshness

    async def _ohlcv_source_coverage() -> list | None:
        """调 `ohlcv_source_coverage()` RPC。**返回 None 表示读不到,不是"都健康"。**

        RPC 是 SECURITY INVOKER 且只授给 service_role —— 同一天 S-247 刚把 8 个
        SECURITY DEFINER 视图翻回 invoker(它们让 anon 绕过 RLS 读到 485,352 行
        价格),不要再造一个。
        """
        from src.api.store import supabase_rpc
        from src.data.market.source_freshness import COVERAGE_PARAMS
        try:
            rows = await supabase_rpc("ohlcv_source_coverage", {
                "recent_crypto": COVERAGE_PARAMS["recent_crypto"],
                "recent_tradfi": COVERAGE_PARAMS["recent_tradfi"],
                "base_lo": COVERAGE_PARAMS["base_lo"],
                "base_hi": COVERAGE_PARAMS["base_hi"],
            })
        except Exception:                                         # noqa: BLE001
            return None
        return rows if isinstance(rows, list) else None

    out: dict = {"checked_at": int(_time.time())}

    # ── S-278:生产者表判活 —— 数据源活着不代表生产者活着 ──────────────────
    # 本端点原本只看 ohlcv_daily 的【数据源】。而静默死亡这个失败类
    # (下面 docstring 说「已经代价三次」)大多发生在【生产者表】上。
    # 实测 2026-09-02:signal_outcomes 停 122 天、market_state_vectors 停 27 天、
    # risk_meter_history 有一行 d=2099-12-31 —— **未来日期让 max() 永远报新鲜**。
    try:
        from src.api.store import supabase_rpc
        from src.data.market.producer_freshness import assess as _p_assess
        from src.data.market.producer_freshness import overall as _p_overall
        _rows = await supabase_rpc("producer_freshness", {})
        if isinstance(_rows, list) and _rows:
            out["producers"] = _p_overall([
                _p_assess(r.get("t"), int(r.get("n") or 0),
                          r.get("w"), r.get("e"),
                          n_future=int(r.get("n_future") or 0))
                for r in _rows])
        else:
            out["producers"] = {"verdict": "unknown",
                                "note": "producer_freshness RPC 未返回 —— "
                                        "**读不到 ≠ 都健康** (S-180)"}
    except Exception as _pe:                                      # noqa: BLE001
        out["producers"] = {"verdict": "unknown",
                            "note": f"{type(_pe).__name__} —— 读不到 ≠ 都健康"}


    # ── S-251:全表 max 看不见管道死亡,补一层按源的覆盖率判活 ──────────────
    # 上面那句 `order=trade_date.desc limit 1` 取的是**混合总体上的一个 max**。
    # 实测 2026-08-27:binance_hist 自 08-09 起每天只写 BCH 一个标的,连写 19 天,
    # 于是 max 天天前进,而 260 个标的已经停了;这个端点照报 verdict="fresh"。
    # 一个还活着的写入者掩护了 260 个死掉的。
    #
    # 不替换上面的判据(它对"这一轮跑完没有"仍然有效,而且 caveat 说得对),
    # 而是**并排给出第二个维度**:每个源最近还在写几个标的,对比它一个月前的常态。
    # 「某个东西是新的」和「这个管道是活的」从此是两个字段。
    try:
        from src.data.market.source_freshness import (
            from_rows, overall as _src_overall)
        _cov = await _ohlcv_source_coverage()
        out["by_source"] = (_src_overall(from_rows(_cov)) if _cov is not None else
                            {"verdict": "unknown",
                             "note": "覆盖率查询没有返回 —— 读不到 ≠ 都健康 (S-180)"})
    except Exception as _e:                                       # noqa: BLE001
        out["by_source"] = {"verdict": "unknown", "note": f"{type(_e).__name__}"}

    try:
        f = await supabase_ohlcv_daily_freshness()
        age_s = f.get("age_seconds")
        out["ohlcv_daily"] = {
            "last_trade_date": f.get("last_trade_date"),
            "age_days": round(age_s / 86400, 1) if age_s is not None else None,
            "verdict": f.get("verdict"),
            "error": f.get("error"),
            # `max(trade_date)` is a POOR staleness signal for this feed and the
            # caveat belongs next to the number, not in someone's memory:
            # collect_ohlcv re-pulls 365 days every run and upserts, so the feed is
            # self-healing — a missed run is backfilled by the next one. That makes
            # max(trade_date) look catastrophic mid-run and healthy minutes later.
            # Measured 2026-07-31 as "4 days stale" and 2026-08-06 as "10.3 days",
            # yet a per-day breakdown showed every day 07-24 → 08-06 populated: both
            # readings were transients, and one of them became a false 🔴 in
            # PROJECT_STATE. Weekends legitimately drop to crypto-only (~25 symbols)
            # because EODHD is TradFi and markets are shut — a symbol-count check
            # that ignores that will cry wolf every Saturday, and a check that cries
            # wolf gets muted, which is the failure this whole layer exists to avoid.
            "caveat": "self-healing feed: collect_ohlcv upserts 365d per run, so "
                      "max(trade_date) is transient. Judge on run completion, not on "
                      "this date. Weekends are crypto-only by design.",
            # S-272:声明自己回答的是哪个问题。两块并排是有意的(见上面 S-251
            # 的注释),错的是**它们看起来在回答同一个问题** —— 这一块的
            # `verdict:"fresh"` 用了一个像整体健康判断的词。
            "answers": "这一轮跑完没有(max(trade_date) 是否新鲜)—— "
                       "**不回答「这个管道是活的吗」**,那个在 by_source 里",
        }
    except Exception as e:
        out["ohlcv_daily"] = {"verdict": "unknown", "error": str(e)[:80],
                              "answers": "这一轮跑完没有 —— 本次读取失败"}

    # ── S-272:顶层裁决,因为消费者读的是顶层 ────────────────────────────────
    # 实测 2026-09-02:这个响应有两个嵌套裁决而**顶层一个都没有**。
    #
    #     by_source.verdict    "domain_without_usable_source"   ← 权威
    #     ohlcv_daily.verdict  "fresh"                          ← 更浅、词更眼熟
    #
    # 于是告警只能在两者里挑一个,而 "fresh" 更像一个整体健康判断。
    # 那天的真实状态是:coingecko 25/25 连续 12 天健康、eodhd 33/33,
    # 而 hyperliquid 停 10 天、binance_hist 停 13 天 ⇒ **加密域没有可用于收益的源**,
    # 且这个状态自 08-23 起就在,不是新发生的。两个裁决都没说错,
    # **错的是没有一个字段回答「所以我该担心吗」。**
    #
    # 与 S-265 的 `tier` 同一个做法:一个字段,封闭取值,放在消费者真正读的层级。
    _bs = out.get("by_source") or {}
    _bs_verdict = _bs.get("verdict")
    out["verdict"] = _bs_verdict or "unknown"
    out["verdict_source"] = "by_source"

    # S-278:生产者死了也必须能把顶层拉红。**否则又回到 S-272 那个毛病** ——
    # 一个响应里有两个裁决,而顶层只反映其中一个。
    _pv = (out.get("producers") or {}).get("verdict")
    if _pv in ("dead", "future_dated"):
        out["verdict"] = f"producers_{_pv}"
        out["verdict_source"] = "producers"

    # ── S-279:裁决必须申报自己的适用范围 ────────────────────────────────────
    # Jazz:「怎么都说健康,但就是有东西停了?」查下来端点没撒谎 —— 是覆盖缺口:
    # 它们回答的是一个比「系统健康吗」小得多的问题,而名字承诺了全景。
    # 库里 67 张表,被判活的 11 张;**9 张 NAV 表只有 1 张在看**。
    #
    # 覆盖不全**不把裁决压红** —— 那会造出一盏永久红灯,而常亮的灯等于坏灯,
    # 正是这里要修的病本身。改为:裁决照旧,但带上 `covers` 与 `unqualified`。
    # ── S-282:循环心跳 —— 「循环还在」和「循环还在成功」是两件事 ─────────────
    # signal_outcomes 死 123 天的机制:循环活着、每天跑、每天失败,
    # 而失败只进 stdout。**一个只进 stdout 的失败等于没有发生。**
    try:
        from src.api.loop_beat import overall as _b_overall
        from src.api.loop_beat import read_beats
        out["loops"] = _b_overall(await read_beats())
        _lv = out["loops"].get("verdict")
        if _lv == "failing" and out.get("verdict_source") != "producers":
            out["verdict"] = "loops_failing"
            out["verdict_source"] = "loops"
    except Exception as _be:                                      # noqa: BLE001
        out["loops"] = {"verdict": "unknown",
                        "note": f"{type(_be).__name__} —— 读不到 ≠ 都在跑"}

    try:
        from src.api.store import supabase_rpc as _srpc
        from src.data.market.watch_census import census as _census
        from src.data.market.watch_census import qualify_verdict as _qual
        _tbls = await _srpc("watch_census", {})
        if isinstance(_tbls, list) and _tbls:
            _c = _census([r.get("table_name") for r in _tbls if r.get("table_name")])
            out["coverage"] = {k: _c[k] for k in (
                "n_not_covered", "n_blocking", "n_total", "n_covered",
                "not_covered_by_tier", "verdict", "reason")}
            out["verdict_scope"] = _qual(out.get("verdict", "unknown"), _c)
        else:
            out["coverage"] = {"verdict": "unknown",
                               "reason": "watch_census RPC 未返回 —— 读不到 ≠ 全覆盖"}
    except Exception as _ce:                                      # noqa: BLE001
        out["coverage"] = {"verdict": "unknown",
                           "reason": f"{type(_ce).__name__} —— 读不到 ≠ 全覆盖"}
    out["verdict_note"] = (
        "**顶层裁决取自 by_source(每源 × 覆盖标的数),不是 ohlcv_daily。**"
        "后者回答的是「这一轮跑完没有」,它的 max(trade_date) 在自愈式回填下是"
        "瞬态值 —— 两块并排是有意的(S-251),但只有这一个回答"
        "「我该担心吗」。取值见 by_source.by_domain。")

    # ── §BOOKS: 每本 paper book 的最后一次 mark(S-288)────────────────────
    # 2026-09-04,Minimax-C 审计交易模块,判定「没有任何 book 在 live/paper trade
    # 跑」。实测当天:6 本在 mark,而**他没点名的两本真的死了** ——
    # `two_layer_paper_nav` 停在 08-22,`pod_aggregator_nav` / `factor_tilt_nav`
    # 各 0 行(表建了,writer 从未生效)。三条事实错、两条真缺陷漏掉。
    #
    # 原因不是他不小心:**他没有 Supabase 读权限**,只能从端点反推,而他抽查的
    # 那一小时恰好是 ① 熄火的窗口(S-285),于是从一本推广到十本。S-276 同款 ——
    # 一条 lane 只能判断它看得见的东西,答案是给视野,不是要求更谨慎。
    #
    # 这块用 X-Internal-Token 就能读,不需要发数据库凭证,所以它是**最低成本的
    # 那条视野**。`n_rows` 与 `last_mark` 并列:0 行和「停更」是两种病,一个是
    # writer 从未接通,一个是接通后死了,混在一起会把前者当成后者去重启。
    #
    # ⚠️ TOKEN-GATED, and I nearly shipped it ungated. **This endpoint is
    # deliberately PUBLIC** — its docstring says so: it was built 2026-07-31 for
    # an external uptime probe that cannot authenticate. Book names and their
    # health are architecture, and CLAUDE.md #8 keeps architecture off surfaces a
    # competitor reads. So the freshness verdict stays public and the book roster
    # appears only with the internal token.
    #
    # Worth naming the near-miss: I was adding VISIBILITY, which felt like a pure
    # good, and "who else can see this" is not a question visibility work prompts
    # you to ask. The same shape as every other defect this week — the change was
    # right and its SCOPE was wrong.
    # ⚠️ `books` 永远存在,哪怕被 token 挡住。
    #
    # 第一版是 `if _tok_ok:` 包住整块 —— 于是没带 token 时字段**不存在**,而一个
    # 还没部署这段代码的旧版本同样**不存在**。Jazz 2026-09-04 跑 `jq '.books'`
    # 拿到 `null`,而那个 null 无法区分三件事:没部署 / token 不对 / RPC 失败。
    #
    # 这正是我这一整轮在修的 miss-vs-error 塌缩(S-180 · S-185 · S-194 · S-285),
    # **由我在修它的同一天亲手又造了一个**。写守卫的人不会自动免疫于守卫防的东西;
    # 唯一有效的是把「三值」当默认反射,而不是当一条要想起来的规则。
    _books_key = "books"
    if not _tok_ok:
        out[_books_key] = {
            "verdict": "gated",
            "reason": ("book 名册需要 X-Internal-Token —— 本端点对外部探针公开,"
                       "而 book 名字与存活状态是架构信息(规则 8)。"
                       "**看到这一行就说明这段代码已经部署**;字段整个缺失才是没部署。"),
        }
    else:
        try:
            from src.api.store import supabase_rpc as _srpc2
            _books = await _srpc2("paper_book_freshness", {})
            out[_books_key] = _books if isinstance(_books, list) else {
                "verdict": "unknown",
                "reason": "paper_book_freshness RPC 未返回 —— 读不到 ≠ 都在跑"}
        except Exception as _bfe:                                 # noqa: BLE001
            out[_books_key] = {"verdict": "unknown",
                               "reason": f"{type(_bfe).__name__} —— 读不到 ≠ 都在跑"}
    return out


@app.get("/internal/health-summary")
async def health_summary():
    """One health verdict over Mac Mini push freshness, universe, contract drift,
    and MacroBrief. Read by the heartbeat loop + ops. Public read (no secrets)."""
    from src.api.health import compute_health_summary
    return await compute_health_summary()


@app.get("/internal/prediction-track-record")
async def prediction_track_record(x_internal_token: str = Header(None)):
    """Per-source predictive track record (hit rate + directional alpha).

    ── S-262:原本是 "Public read",现在收进 token 门 ────────────────────────
    实测 2026-08-29,我用浏览器不带任何凭证拿到:

        {"status":"ok","sources":{"signal":{"n":99,"scored":91,
         "hit_rate_pct":28.6,"avg_directional_alpha_pct":-2.817}}}

    **它把命中率和负超额公开在一个 `/internal/` 路径上。**

    收它不是因为难看 —— 是因为**它和我们刚定的展示口径矛盾**。
    Jazz 2026-08-30 对 `/quant` 的决定是「跑得不好的可以先不展示」,
    而那块面板现在会在可测样本不足时整块不渲染(S-257)。
    同一批数字在这里却是**无鉴权公开**的。

    > 一个地方说「不能声称就不声称」,另一个地方把同类数字裸奔 ——
    > 不一致本身就是问题,无论选哪一边。

    这里选与 S-257 一致的那边。查实无消费者后收口:
    仓库 / `Shadow/`(Mac 侧)/ `dashboard/src` 全部 grep 无引用,
    只有 `main.py` 自身和一份 transcript。
    """
    # ⚠️ 这里【不能】写 `_INTERNAL_TOKEN` —— 那个常量只在 `src/api/routers/*.py` 里,
    # `main.py` 没有。我第一版从 routers 抄了模式,结果是 NameError,
    # **而且只在鉴权分支上抛** —— import 能过、py_compile 能过、正常路径能过,
    # 只有真的有人不带 token 来打时才炸,然后返回 500 而不是 401。
    # 今天第二次踩「只在错误路径上炸」(auth.py 的 _log vs _logger)。
    # `main.py` 也【没有】导入 HTTPException —— 它自己的 /internal/ 路由用的是
    # `JSONResponse(status_code=401, ...)`。这是同一个改动里第三次
    # 「只在错误路径上炸」:先是 _INTERNAL_TOKEN 不存在,再是 HTTPException 不存在。
    # 三次都是**跨模块抄惯用法而不查导入**,三次都是 import/py_compile 全过、
    # 正常路径全过,只有真的有人不带 token 来打时才 500。
    # 静态扫描抓不到任何一次 —— 抓到它们的是 TestClient 打了一次真请求。
    # ⚠️ 用 `_os` 别名,不用裸 `os`:这两个函数体里**后面有局部 `import os`**,
    # 那会让 `os` 在整个函数作用域内变成局部名,于是鉴权分支上的
    # `os.environ` 抛 `UnboundLocalError`。这是同一个改动里的**第四次**
    # 「只在错误路径上炸」:_INTERNAL_TOKEN 不存在 → HTTPException 不存在 →
    # os 被遮蔽。四次的共同点是**静态检查一次都抓不到**,
    # 而每一次都是 TestClient 打一个真请求抓到的。
    import os as _os
    _tok = _os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or not x_internal_token or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    from src.data.signals.prediction_resolver import source_track_record
    return await source_track_record()


@app.get("/api/v1/signals/causal-paper")
async def causal_paper(response: Response = None):
    """Live PAPER track record of the causal positioning sleeve (walk-forward + cost
    validated market-neutral edge). NAV curve + Sharpe/DD from causal_paper_nav.
    See src/data/signals/causal_paper.py."""
    from fastapi import Response as _Response  # defensive (also imported at module top)
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.causal_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "causal_paper_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/two-layer-paper")
async def two_layer_paper(response: Response = None):
    """Live PAPER track record of the §5b two-layer book (V5c core × C regime overlay).
    Starts the FORWARD out-of-sample clock R57 flagged as the missing piece. Reports
    days_engaged vs days_flat honestly — the book holds ZERO size while the core is
    structurally dead rather than fabricating exposure. See src/data/signals/two_layer_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.two_layer_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "two_layer_paper_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/fusion-paper")
async def fusion_paper(response: Response = None):
    """Live PAPER track record of the R64 fusion cell (25% R46 pillar_O + 75% R62
    fade-the-crowd gated). §P1 forward commitment + §P2 binding capacity declaration
    are pre-declared and locked at production time. Reports NAV curve + per-day fill
    ratio + slippage + capacity status so the CRUDE $5M ceiling becomes a real number
    as live price/ADV data accumulates. `validated` flag flips true after ≥60 forward
    days. See src/data/signals/fusion_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.fusion_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "fusion_paper_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/r76-paper")
async def r76_paper(response: Response = None):
    """Strategy 2 — Live PAPER track record of the R76 standalone funding-residual L/S
    cell (5d/0bps, k=3, sign=high_fund_long). The only survivor of the cross-sectional
    funding-residual family on the 770-day panel (R76 LEVEL ✓ / R95 IVOL PARTIAL /
    R96 MOMENTUM PARTIAL). R76 is the leg that made R77 fusion's lesson #43 work
    in the first place. §Strategy-2 forward commitment + §P2 binding capacity
    declaration (start: $1M) are pre-declared and locked at production time.
    Reports NAV curve + cell config + validation countdown. `validated` flag
    flips true after ≥60 forward days. See src/data/signals/r76_strategy2_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.r76_strategy2_paper import get_curve
    try:
        return get_curve()
    except Exception as e:
        return {"error": "r76_paper_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/pod-aggregator")
async def pod_aggregator(response: Response = None):
    """Strategy 3 — Live PAPER track record of the pod aggregator book (frozen cell
    w_R46=0.34/w_R62=0.33/w_R76=0.33). Three safety properties the sandbox verdict
    cleared: cross-pod correlation gate (max |corr| < 0.30), 12% ann vol target,
    per-pod -15% DD circuit breaker (monotonic disable). Returns NAV curve +
    surviving pods + dropped pods + tripped breakers + max retained correlation.
    `validated` flag flips true after ≥60 forward days. See
    src/data/signals/pod_aggregator_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.pod_aggregator_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "pod_aggregator_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/factor-tilt")
async def factor_tilt(response: Response = None):
    """Strategy 4 — Live PAPER track record of the cross-asset factor tilt book.
    Long-only tilt over the 58-asset universe (41 crypto + 17 TradFi ETFs) ranked by
    composite z_quality + z_momentum + z_lowrisk, sized by H3.2 conviction [0.5, 1.75],
    vol-targeted to 12% ann. Zero shorts (CLAUDE.md canonical default long-only).
    Returns NAV curve + per-factor Sharpe attribution + max single-factor share
    + today return + today excess vs hold-the-bench. `validated` flag flips true
    after ≥60 forward days. See src/data/signals/factor_tilt_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.factor_tilt_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "factor_tilt_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/fusion-paper-tracking")
async def fusion_paper_tracking(response: Response = None):
    """R66 monitoring surface for the live R64 fusion cell.

    Returns the live-vs-OOS Sharpe gap, detector fire-rate, measured capacity
    evolution, validation countdown, max drawdown, and §P3 lifecycle events.
    The monitor is informational only; frozen R64 cell constants are unchanged.
    See src/research/validation/fusion_paper_tracking.py.
    """
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.research.validation.fusion_paper_tracking import compute_tracking_snapshot
    try:
        return await compute_tracking_snapshot()
    except Exception as e:
        return {"error": "fusion_paper_tracking_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/nav-monitor")
async def nav_monitor(response: Response = None):
    """R66 live NAV gap monitor — every committed paper book is checked against the
    OOS expectation pinned in its source report. Returns a per-book gap (live
    annualized Sharpe − OOS Sharpe) + status (warming_up / on_track / DRIFT /
    BREAKING / OVERPERFORM). Honest read of whether the live book is tracking what
    the report said, applied to both fusion_paper (R64/R65) and two_layer_paper
    (C-S4 §5b). See src/data/signals/nav_monitor.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.nav_monitor import run_monitor
    try:
        return await run_monitor()
    except Exception as e:
        return {"error": "nav_monitor_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/dingge-paper")
async def dingge_paper(response: Response = None):
    """Live PAPER track record of the 顶格 RWA volume-gated sleeve. Cannot be backtest-
    validated (instrument class all-2026) → accrues forward instead. NAV curve from
    dingge_paper_nav. See src/data/signals/dingge_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.dingge_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "dingge_paper_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/combined-book")
async def combined_book(response: Response = None):
    """Live NAV of the signal factory's walk-forward-validated nucleus — one market-neutral
    ensemble book. Provenance: nucleus signals + backtest reference (combined Sharpe ~1.56,
    ENB ~3.7) + the live curve, so a consumer can verify, not just trust.
    See src/data/signals/combined_book.py + src/research/factory/signal_factory.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.combined_book import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "combined_book_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/scalable-book")
async def scalable_book(response: Response = None):
    """Live NAV of the profit-max, high-capacity multi-strategy book (FACTOR + TREND + CARRY,
    vol-targeted, on the deepest instruments). Candidate — accruing an honest, capacity-honest
    track record. See src/data/signals/scalable_paper.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=600, stale-while-revalidate=1200"
    from src.data.signals.scalable_paper import get_curve
    try:
        return await get_curve()
    except Exception as e:
        return {"error": "scalable_book_unavailable", "detail": str(e)[:120]}


# ── Conviction Engine — daily watchlist compute → cache (heavy: ~20 network calls) ──
async def _conviction_loop():
    await _asyncio.sleep(600)   # 10 min warmup
    while True:
        try:
            from src.data.narrative.conviction_engine import get_watchlist, persist_watchlist, resolve_and_track
            from src.data.market.data_layer import _redis_set
            wl = get_watchlist()      # narrative events (LLM half) wired in P2
            await _redis_set("conviction:watchlist", wl, ttl=2 * 24 * 3600)
            n_logged = await persist_watchlist(wl)                    # P4: accrue candidates as predictions
            tr = await resolve_and_track()                           # P4: resolve matured + score the conjunction
            await _redis_set("conviction:track_record", tr, ttl=2 * 24 * 3600)
            print(f"[CONVICTION] watchlist {wl.get('n')} cands (logged {n_logged}), "
                  f"top={wl['candidates'][0]['symbol'] if wl.get('candidates') else None}; "
                  f"track_record={tr.get('status')} resolved={tr.get('total_resolved')}")
        except Exception as _e:
            print(f"[CONVICTION] ⚠️  loop failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_conviction_loop():
    if os.environ.get("DISABLE_CONVICTION", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_conviction_loop())
        print("[CONVICTION] ✅ daily conviction-watchlist loop scheduled")


# ── AI briefing loop — LLM (MiniMax/LM Studio) writes the signal-feed prose over the
# deterministic facts, cached to Redis so the feed request never blocks on the model.
# No-op when no LLM endpoint is configured (feed falls back to template narrative). ──
async def _ai_briefing_loop():
    await _asyncio.sleep(300)   # 5 min warmup — let conviction/positioning caches populate
    while True:
        try:
            from src.api.routers.signals import refresh_ai_briefing
            r = await refresh_ai_briefing()
            print(f"[AI-BRIEFING] {r.get('status')} — {r.get('coverage') or r.get('reason') or ''}")
        except Exception as _e:
            print(f"[AI-BRIEFING] ⚠️  loop failed: {_e}")
        await _asyncio.sleep(30 * 60)   # every 30 min


@app.on_event("startup")
async def _start_ai_briefing_loop():
    _asyncio.create_task(_ai_briefing_loop())
    print("[AI-BRIEFING] ✅ signal-feed narrative loop scheduled (LLM over facts)")


@app.get("/api/v1/conviction/watchlist")
async def conviction_watchlist(response: Response = None):
    """AI-augmented conviction watchlist — ranked structural-winner candidates (L1 moat × L2
    catalyst × L3 fundamental momentum × L4 trend) for DISCRETIONARY conviction, NOT a signal.
    Served from the daily cache. See docs/CONVICTION_ENGINE_PLAN.md."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
    from src.data.market.data_layer import _redis_get
    try:
        wl = await _redis_get("conviction:watchlist")
        return wl if isinstance(wl, dict) else {"status": "warming_up", "note": "watchlist computes daily; not yet cached"}
    except Exception as e:
        return {"error": "conviction_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/conviction/track-record")
async def conviction_track_record(response: Response = None):
    """P4 self-verification: does the conviction CONJUNCTION (L1∧L2∧L3∧L4) predict forward alpha
    even though no single layer does (R21)? IC of the conviction score + each layer vs resolved
    30d benchmark-relative outcomes. Accrues forward. See docs/CONVICTION_ENGINE_PLAN.md."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=1800, stale-while-revalidate=3600"
    from src.data.market.data_layer import _redis_get
    try:
        tr = await _redis_get("conviction:track_record")
        return tr if isinstance(tr, dict) else {"status": "accruing", "note": "candidates logged daily; resolves at 30d horizon"}
    except Exception as e:
        return {"error": "conviction_track_record_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/portfolio")
async def portfolio(response: Response = None):
    """The assimilated top-level book — one coherent hierarchy over all the sleeves/books:
    CORE (scalable, deployable) · COMPONENTS (inside core) · CANDIDATES (orthogonal, accruing) ·
    breadth · discipline. Read-only composition. See src/data/signals/portfolio.py."""
    from fastapi import Response as _Response
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=300, stale-while-revalidate=900"
    from src.data.signals.portfolio import get_portfolio
    try:
        return await get_portfolio()
    except Exception as e:
        return {"error": "portfolio_unavailable", "detail": str(e)[:120]}


@app.get("/api/v1/signals/dingge-board")
async def dingge_board(response: Response = None):
    """Live 顶格 board — tokenized-RWA perps whose funding pinned the cap (24/7-on-chain vs
    closed-underlying blowoff), with the 量能/volume read + direction lean. Jazz-derived,
    validated (experiment_runs: funding_dingge_reversal). See src/data/signals/dingge_rwa.py."""
    from fastapi import Response as _Response  # defensive (also imported at module top)
    if response is None:
        response = _Response()
    if response:
        response.headers["Cache-Control"] = "public, max-age=900, stale-while-revalidate=1800"
    import asyncio as _a, datetime as _d
    from src.data.signals.dingge_rwa import scan_live
    try:
        board = await _a.to_thread(scan_live)
        active = [b for b in board if b.get("at_cap") or (b.get("days_since_cap") is not None and b["days_since_cap"] <= 45)]
        return {"board": board, "active_or_recent": len(active), "as_of": _d.datetime.now(_d.timezone.utc).isoformat()}
    except Exception as e:
        return {"error": "dingge_board_unavailable", "detail": str(e)[:120]}


@app.get("/internal/loop-health")
async def loop_health():
    """Per-stage flow check over the whole loop (ingest→compute→store→measure→feedback).
    Makes an orphaned stage impossible to hide. Public read (no secrets). See loop_health.py."""
    from src.api.loop_health import check_loop_health
    base = os.environ.get("PUBLIC_BASE_URL", "https://looloomi.ai")
    return await check_loop_health(base)


@app.post("/internal/notify/test")
async def notify_test(payload: dict = None, x_internal_token: str = Header(None)):
    """Send a test Telegram alert. INTERNAL_TOKEN guarded. Confirms env wiring."""
    _tok = os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    from src.api.notify import notify_telegram, telegram_configured
    msg = (payload or {}).get("text") or "✅ CometCloud alerts wired — Telegram is live."
    ok = await notify_telegram(msg)
    return {"configured": telegram_configured(), "sent": ok}


@app.get("/internal/beta-core-probe")
async def beta_core_probe(x_internal_token: str = Header(None)):
    """What WOULD the ① book do right now? Dry run — computes regime, cap and gross
    without writing a row or touching state.

    WHY THIS EXISTS (2026-08-11). A mark is written once per day and
    `mark_and_rebalance` returns `already_marked` on re-entry, so a fix deployed
    after the day's mark cannot show up until tomorrow's mark, and its EFFECT on
    excess cannot show up until the day after — returns are booked off the previous
    mark's weights. That is correct behaviour: rewriting a booked mark would make
    the forward record retroactively editable, which is the one property this book
    cannot lose.

    But it left a two-day blind spot in which the only way to learn whether layer ③
    is biting was to wait. That is the wrong trade — the deploy is cheap to verify
    and expensive to be wrong about. This endpoint reads the same code path the loop
    will run tomorrow and reports its decision, so a regime-plumbing regression is
    caught in seconds instead of after two days of flat curve.

    Token-guarded: it is diagnostic, not investor-facing, and it names internals."""
    _tok = os.environ.get("INTERNAL_TOKEN", "")
    if not _tok or x_internal_token != _tok:
        return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    try:
        from src.data.signals.beta_core_paper import (
            _current_regime, _exposure_cap, _regime_history)
        hist = await _regime_history()
        regime, raw = await _current_regime()
        cap, cap_source = _exposure_cap(regime)
    except Exception as e:
        return JSONResponse(status_code=503, content={"error": str(e)[:200]})
    return {
        "would_size_at_cap": cap,
        "cap_source": cap_source,
        "regime_confirmed": regime,
        "regime_raw": raw,
        "regime_history_days": len(hist),
        "regime_history_tail": hist[-7:],
        # The two failures this probe is meant to separate, named rather than left
        # for the reader to infer from a null.
        "diagnosis": (
            "regime feed empty — daily_macro_regime returned nothing or is stale; "
            "check the Railway log for 'daily_macro_regime read failed'"
            if not hist else
            "history too short to run the 5-day dwell filter; the book is sizing off "
            "the raw label, not the confirmed one"
            if len(hist) < 5 else
            "③ is live and biting — cap below 1.0"
            if cap < 1.0 else
            "③ is live and chose full exposure — this is a decision, not a fallthrough"
            if cap_source == "regime_map" else
            f"③ fell through: cap_source={cap_source}"),
        "note": ("dry run — no row written, no state touched. Today's already-booked "
                 "mark is NOT retroactively corrected by design."),
    }


@app.get("/internal/build-state")
async def build_state():
    try:
        from src.api.contracts.cis_push import SCHEMA_VERSION
    except Exception:
        SCHEMA_VERSION = "unknown"

    git_sha = (
        os.environ.get("RAILWAY_GIT_COMMIT_SHA")
        or os.environ.get("GIT_COMMIT_SHA")
        or os.environ.get("SOURCE_COMMIT")
        or ""
    )

    # Last Mac Mini push: freshness + provenance (from the CIS hot cache)
    last_push = {"present": False}
    try:
        from src.api.store import redis_get
        cached = await redis_get()
        if cached:
            age = _time.time() - float(cached.get("last_updated") or 0)
            uni = cached.get("universe") or []
            prov = cached.get("provenance") or {}
            last_push = {
                "present":         True,
                "age_seconds":     round(age, 1),
                "stale":           age > 3600,   # pushes are ~30min; >1h = problem
                "asset_count":     len(uni),
                "schema_version":  cached.get("schema_version"),
                "engine_git_sha":  prov.get("engine_git_sha"),
                "config_hash":     prov.get("config_hash"),
                "drift_warnings":  len(cached.get("contract_warnings") or []),
            }
    except Exception as _e:
        last_push = {"present": False, "error": str(_e)}

    return {
        "service":         "looloomi-api",
        "version":         app.version,
        "environment":     _ENV,
        "git_sha":         git_sha,
        "git_sha_short":   git_sha[:8] if git_sha else None,
        "git_branch":      os.environ.get("RAILWAY_GIT_BRANCH"),
        "deployment_id":   os.environ.get("RAILWAY_DEPLOYMENT_ID"),
        "contract_schema_version": SCHEMA_VERSION,
        "route_count":     len(app.routes),
        "uptime_seconds":  round(_time.time() - _BOOT_TS, 1),
        "last_cis_push":   last_push,
        # ⚠️ ROLE 是决定这个进程能不能写系统记录的唯一开关,而在今天之前它在生产里
        # 完全不可见 (S-228)。`APP_ROLE` 未设 ⇒ fail-closed 成 `replica` ⇒ 每一次
        # 经过 role gate 的写入都被【静默拒绝】,只在 Railway 日志里留下一行、
        # 而且每个目标只留一次。
        #
        # 于是两个世界从外面看一模一样:
        #   (a) primary,而某张表空是因为没人调那个写入端点
        #   (b) replica,而每一次写入都在被拒
        # 修法毫不相干。凭证只报存在与否,值永远不出现。
        "runtime_role":    _role_echo(),
        "as_of":           _time.time(),
    }


def _role_echo() -> dict:
    """角色 + 写入能力 + 拒绝计数。不含任何凭证值。"""
    try:
        from src.api.runtime_role import ROLE, is_writer, refusal_counts
        counts = refusal_counts()
        return {
            "role": ROLE,
            "may_write_shared_record": is_writer(),
            "write_refusals": counts,
            # 空字典有两个意思,所以把它们分开写出来,不要让读的人去猜。
            "refusals_note": ("no write has been refused" if not counts else
                              f"{sum(counts.values())} refusals across "
                              f"{len(counts)} targets — gated writes are NOT landing"),
        }
    except Exception as e:                                        # noqa: BLE001
        return {"role": "unknown", "error": f"{type(e).__name__}: {str(e)[:80]}"}


# ── Serve React SPA ───────────────────────────────────────────────────────────

dashboard_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "dashboard", "dist"
)
if os.path.exists(dashboard_path):
    app.mount("/assets", StaticFiles(directory=os.path.join(dashboard_path, "assets")), name="assets")

    @app.get("/")
    async def serve_dashboard():
        return FileResponse(os.path.join(dashboard_path, "index.html"))

    @app.get("/{full_path:path}")
    async def serve_spa(full_path: str):
        # API/internal/ws/mcp paths that don't match any router → 404 JSON (not SPA fallback)
        _api_prefixes = ("api/", "internal/", "ws/", "mcp/", "mcp-sse", ".env", "config", "secrets", "admin", ".git")
        if any(full_path.startswith(p) for p in _api_prefixes):
            return JSONResponse(status_code=404, content={"detail": "Not found"})
        # EXISTENCE IS CHECKED, NOT CAUGHT (S-160, 2026-08-13).
        #
        # This read:
        #     try:    return FileResponse(file_path)
        #     except FileNotFoundError: pass
        #     return FileResponse(index.html)
        #
        # Starlette's FileResponse is LAZY — it does not stat the file when
        # constructed, it stats when the response is sent. So a missing file
        # raises nothing here, the `except` never fires, the index.html line is
        # dead code, and the error surfaces AFTER the handler returned, as a
        # RuntimeError that FastAPI turns into a 500.
        #
        # Measured 2026-08-13: every SPA deep link was 500 —
        #     /  200 · /cis 500 · /intelligence 500 · /strategies 500
        #     /vault 500 · /diagnose 500
        # Only "/" worked, because it has its own explicit route. The app was
        # usable only if you landed on "/" and navigated client-side; a refresh
        # or a shared link showed a blank shell whose panels then rendered
        # "API error: 500" — which sent two people hunting the API for hours
        # while every API endpoint was returning 200.
        #
        # A try/except around a call that cannot raise the exception being
        # caught is indistinguishable from no error handling at all, and reads
        # like more.
        safe = os.path.normpath(os.path.join(dashboard_path, full_path))
        # normpath collapses "..", so a request for /../../etc/passwd resolves
        # outside the build directory. Serve the SPA shell instead of the file.
        if safe.startswith(dashboard_path) and os.path.isfile(safe):
            return FileResponse(safe)
        return FileResponse(os.path.join(dashboard_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
