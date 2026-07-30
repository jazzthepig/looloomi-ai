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
from src.api.routers.factors import router as factors_router
from src.api.routers.discovery import router as discovery_router
from src.api.routers.strategies import router as strategies_router
from src.api.routers.signals import router as signals_router
from src.api.routers.portfolio_diagnosis import router as diagnosis_router
from src.api.routers.strategy_vector import router as strategy_vector_router
from src.api.routers.admin import router as admin_router
from src.api.routers.ohlcv import router as ohlcv_router
from src.api.middleware.rate_limit import RateLimitMiddleware

_ENV = os.environ.get("ENVIRONMENT", "production")

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
app.include_router(factors_router)
app.include_router(discovery_router)
app.include_router(strategies_router)
app.include_router(signals_router)
app.include_router(diagnosis_router)
app.include_router(strategy_vector_router)
app.include_router(admin_router)
app.include_router(ohlcv_router)


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
            from src.data.cis.cis_provider import canonical_regime
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
                    "macro_regime":  canonical_regime(regime),
                    "data_tier":     "T2",
                    "las":           a.get("las"),
                    "confidence":    a.get("confidence", 0.8),
                    "source":        "railway_t2_hourly",
                })
            if t2_rows:
                ok = await supabase_insert_batch(t2_rows)
                print(f"[SNAPSHOT] hourly T2 — ok={ok} rows={len(t2_rows)}")
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


# ── Daily signal-outcome resolver ─────────────────────────────────────────────
# Resolves 30-day directional outcomes (WIN/LOSS/EXPIRED) for matured signals.
# Runs ~once/day in-process so the LP track-record metrics stay current without
# depending on the Mac Mini OHLCV pipeline. Idempotent (only touches NULL rows).
import asyncio as _asyncio

_OUTCOME_INTERVAL_S = 24 * 3600   # daily


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
        except Exception as _e:
            print(f"[OUTCOME] ⚠️  daily run failed: {_e}")
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


# ── Causal paper book — live NAV track record of the validated market-neutral sleeve ──
# Daily mark, weekly rebalance (the cost-validated deployable cadence). Turns the
# walk-forward candidate into a real, honest, LP-showable number. Binance reachable
# from the Singapore region. See src/data/signals/causal_paper.py.
_CAUSAL_PAPER_INTERVAL_S = 24 * 3600


async def _causal_paper_loop():
    await _asyncio.sleep(360)   # 6 min warmup
    while True:
        try:
            from src.data.signals.causal_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[CAUSAL-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
        except Exception as _e:
            print(f"[CAUSAL-PAPER] ⚠️  mark failed: {_e}")
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
    while True:
        try:
            from src.data.signals.dingge_paper import mark_and_trade
            res = await mark_and_trade(dry_run=False)
            print(f"[DINGGE-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"open={res.get('open')} +{res.get('opened_today')}/-{res.get('closed_today')}")
        except Exception as _e:
            print(f"[DINGGE-PAPER] ⚠️  mark failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_dingge_paper_loop():
    if os.environ.get("DISABLE_DINGGE_PAPER", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_dingge_paper_loop())
        print("[DINGGE-PAPER] ✅ daily 顶格 RWA paper-sleeve loop scheduled")


# ── Combined book — live NAV of the factory's walk-forward-validated nucleus ───
# Stage 3 of the loop-as-factory: one market-neutral book = the ensemble, marked daily.
async def _combined_book_loop():
    await _asyncio.sleep(480)   # 8 min warmup
    while True:
        try:
            from src.data.signals.combined_book import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[COMBINED-BOOK] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
        except Exception as _e:
            print(f"[COMBINED-BOOK] ⚠️  mark failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_combined_book_loop():
    if os.environ.get("DISABLE_COMBINED_BOOK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_combined_book_loop())
        print("[COMBINED-BOOK] ✅ daily combined-book NAV loop scheduled")


# ── Scalable book — live NAV of the profit-max multi-strategy book (FACTOR+TREND+CARRY) ──
# The high-capacity, vol-targeted book on the deepest instruments. See src/data/signals/scalable_paper.py.
async def _scalable_book_loop():
    await _asyncio.sleep(540)   # 9 min warmup
    while True:
        try:
            from src.data.signals.scalable_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[SCALABLE-BOOK] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"rebal={res.get('rebalanced')}")
        except Exception as _e:
            print(f"[SCALABLE-BOOK] ⚠️  mark failed: {_e}")
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_scalable_book_loop():
    if os.environ.get("DISABLE_SCALABLE_BOOK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_scalable_book_loop())
        print("[SCALABLE-BOOK] ✅ daily scalable-book NAV loop scheduled")


# ── §5b two-layer book — forward OOS clock for the V5c core × C regime overlay ──
# R57 validated the ARCHITECTURE but found the V5c core structurally dead (2.7% engaged
# since 2025-11). This sleeve marks daily anyway — a flat day is a real observation — and
# holds ZERO size while core_state == dead. The §CORE-BAKEOFF winner hot-swaps in via the
# Redis key `two_layer_paper:core` with no code deploy. See src/data/signals/two_layer_paper.py.
async def _two_layer_paper_loop():
    await _asyncio.sleep(600)   # 10 min warmup
    while True:
        try:
            from src.data.signals.two_layer_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[TWO-LAYER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"book_state={res.get('book_state')} gross={res.get('gross')}")
        except Exception as _e:
            print(f"[TWO-LAYER] ⚠️  mark failed: {_e}")
        await _asyncio.sleep(24 * 3600)


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
    while True:
        try:
            from src.data.signals.fusion_paper import mark_and_rebalance
            res = await mark_and_rebalance(dry_run=False)
            print(f"[FUSION-PAPER] mark — status={res.get('status')} nav={res.get('nav')} "
                  f"gross={res.get('gross')} fill={res.get('fill_ratio_overall')} "
                  f"cap={res.get('capacity_status')} det={res.get('detector_fired_today')} "
                  f"n_days={res.get('n_days_marked')} validated={res.get('validated')}")
        except Exception as _e:
            print(f"[FUSION-PAPER] ⚠️  mark failed: {_e}")
        await _asyncio.sleep(24 * 3600)


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
        await _asyncio.sleep(24 * 3600)


@app.on_event("startup")
async def _start_fusion_paper_tracking_loop():
    if os.environ.get("DISABLE_FUSION_TRACK", "").lower() not in ("1", "true", "yes"):
        _asyncio.create_task(_fusion_paper_tracking_loop())
        print("[FUSION-TRACK] ✅ daily R66 fusion-paper tracking loop scheduled")


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
        except Exception as _e:
            print(f"[TRACK-REC] ⚠️  refresh failed: {_e}")
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
            if res.get("executed"):
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
    return {
        **_health_payload,
        "status": "degraded" if degraded else "healthy",
        "data_layer": {
            "supabase": "circuit_open" if cb["open"]
                        else ("failing" if cb["consecutive_failures"] else "ok"),
            "breaker": cb,
        },
    }


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
    token Telegram echoes in a header (set when registering the webhook)."""
    secret = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "")
    if secret and request.headers.get("X-Telegram-Bot-Api-Secret-Token") != secret:
        return JSONResponse(status_code=403, content={"ok": False})
    try:
        from src.api.telegram_bot import handle_update
        await handle_update(update)
    except Exception as e:
        print(f"[TG] webhook error: {e}")
    return {"ok": True}


@app.get("/internal/health-summary")
async def health_summary():
    """One health verdict over Mac Mini push freshness, universe, contract drift,
    and MacroBrief. Read by the heartbeat loop + ops. Public read (no secrets)."""
    from src.api.health import compute_health_summary
    return await compute_health_summary()


@app.get("/internal/prediction-track-record")
async def prediction_track_record():
    """Per-source predictive track record (hit rate + directional alpha) from
    prediction_outcomes — the read-back that mines the write-only logs. Public read."""
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
        "as_of":           _time.time(),
    }


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
        file_path = os.path.join(dashboard_path, full_path)
        try:
            return FileResponse(file_path)
        except FileNotFoundError:
            pass
        return FileResponse(os.path.join(dashboard_path, "index.html"))


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
