#!/usr/bin/env python3
"""
CometCloud CIS v4.0 - Scheduler
=================================
Scheduled CIS scoring jobs with:
- Configurable schedules (hourly, daily)
- Async execution
- Error handling and retry
- Logging to file
- JSON output with metadata

Author: CometCloud AI
Version: 1.0.0
"""

import os
import sys
import json
import logging
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass, asdict
import threading
import signal
import atexit

# Add parent to path
sys.path.insert(0, str(Path(__file__).parent))

from config import (
    BASE_DIR, CACHE_DIR, DATA_DIR, LOG_DIR,
    ALL_ASSETS, ASSET_UNIVERSE,
    CACHE_TTL_HOURS, DEFAULT_SCHEDULE,
    RAILWAY_URL, INTERNAL_TOKEN,
)


# ═══════════════════════════════════════════════════════════════════════════
# LOGGING SETUP
# ═══════════════════════════════════════════════════════════════════════════

def setup_logging(name: str = "cis_scheduler") -> logging.Logger:
    """Setup logging to file and console"""
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    # File handler
    log_file = LOG_DIR / f"cis_scheduler_{datetime.now().strftime('%Y%m%d')}.log"
    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.INFO)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    ))

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    ch.setFormatter(logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(message)s",
        datefmt="%H:%M:%S"
    ))

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger


logger = setup_logging()


# ═══════════════════════════════════════════════════════════════════════════
# DATA STRUCTURES
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class JobResult:
    """Result of a scheduled job"""
    job_id: str
    job_type: str
    success: bool
    timestamp: str
    data_freshness: str
    assets_processed: int
    error: Optional[str]
    duration_seconds: float


@dataclass
class CISScore:
    """CIS score for a single asset"""
    asset: str
    asset_name: str
    asset_class: str
    cis_score: float
    grade: str
    signal: str
    recommended_weight: float
    pillars: Dict[str, float]
    percentile: float
    class_rank: int
    global_rank: int
    timestamp: str
    data_freshness: str


# ═══════════════════════════════════════════════════════════════════════════
# CIS ENGINE INTERFACE
# ═══════════════════════════════════════════════════════════════════════════

# Global CIS Engine instance
_cis_engine = None


def get_cis_engine():
    """Get or create CIS engine instance"""
    global _cis_engine

    if _cis_engine is None:
        try:
            # Import cis_v4_engine
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "cis_v4_engine",
                str(Path(__file__).parent / "cis_v4_engine.py")
            )
            cis_module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(cis_module)

            # Create engine with default macro snapshot
            _cis_engine = cis_module.CISEngine()
            logger.info("CIS Engine v4.0 loaded successfully")

        except Exception as e:
            logger.warning(f"Failed to load CIS Engine: {e}, using simplified scoring")
            _cis_engine = None

    return _cis_engine


def calculate_cis_score(asset: str, price_data: Dict) -> Optional[CISScore]:
    """Calculate CIS score for a single asset using full CIS Engine"""
    try:
        asset_info = ASSET_UNIVERSE.get(asset, {})
        asset_class = asset_info.get("class", "Unknown")
        asset_name = asset_info.get("name", asset)

        # Try using full CIS Engine
        engine = get_cis_engine()

        if engine is None:
            # Fallback to simplified scoring
            return _simplified_scoring(asset, asset_class, asset_name, price_data)

        # Generate price array from price_data
        import numpy as np
        from data_fetcher import fetch_klines_as_prices, fetch_fundamental_data

        price = price_data.get("price", 0)

        # Fetch fundamental data for F Pillar (TVL, Market Cap, etc.)
        fundamental_data = fetch_fundamental_data(asset)

        # Map asset symbol to Binance pair
        symbol_map = {
            "BTC": "BTCUSDT", "ETH": "ETHUSDT", "BNB": "BNBUSDT",
            "SOL": "SOLUSDT", "XRP": "XRPUSDT", "ADA": "ADAUSDT",
            "DOGE": "DOGEUSDT", "AVAX": "AVAXUSDT", "DOT": "DOTUSDT",
            "POL": "POLUSDT", "ARB": "ARBUSDT", "OP": "OPUSDT",
            "LINK": "LINKUSDT", "UNI": "UNIUSDT", "AAVE": "AAVEUSDT",
            "MKR": "MKRUSDT", "SNX": "SNXUSDT", "CRV": "CRVUSDT",
        }
        binance_symbol = symbol_map.get(asset, f"{asset}USDT")

        # Fetch BTC benchmark (90-day) once and cache
        if not hasattr(calculate_cis_score, '_btc_prices'):
            calculate_cis_score._btc_prices = fetch_klines_as_prices("BTCUSDT", limit=90)
        btc_prices = calculate_cis_score._btc_prices

        # Fetch SPY benchmark for BTC's alpha calculation (BTC vs SPY, not BTC vs BTC)
        if not hasattr(calculate_cis_score, '_spy_prices'):
            calculate_cis_score._spy_prices = fetch_klines_as_prices("SPY", limit=90)
        spy_prices = calculate_cis_score._spy_prices

        # Fetch real 90-day klines
        prices = fetch_klines_as_prices(binance_symbol, limit=90)

        if prices is None or len(prices) < 30:
            # Skip asset if klines unavailable — don't generate synthetic data
            logger.warning(f"[CIS] Skipping {asset}: insufficient kline data (Binance unavailable)")
            return None

        # Score using engine with benchmark + real fundamental data
        # BTC uses SPY as benchmark (cross-asset alpha), others use BTC
        benchmark = spy_prices if asset == "BTC" else btc_prices
        result = engine.score_asset(asset, prices, benchmark_prices=benchmark,
                                     fundamental_data=fundamental_data)

        return CISScore(
            asset=result.symbol,
            asset_name=result.name,
            asset_class=result.asset_class,
            cis_score=result.cis_score,
            grade=result.cis_grade,
            signal=result.signal,
            recommended_weight=result.recommended_weight,
            pillars=result.pillar_scores,
            percentile=result.cross_asset_percentile,
            class_rank=result.class_rank,
            global_rank=result.global_rank,
            timestamp=result.timestamp,
            data_freshness="live",
        )

    except Exception as e:
        logger.warning(f"Full engine failed for {asset}, using fallback: {e}")
        # Fallback to simplified
        return _simplified_scoring(asset, asset_class, asset_name, price_data)


def _simplified_scoring(asset: str, asset_class: str, asset_name: str, price_data: Dict) -> Optional[CISScore]:
    """Simplified scoring fallback"""
    logger.info(f"[FALLBACK] Using simplified scoring for {asset}")
    try:
        change_24h = price_data.get("change_24h", 0)

        # Basic score based on momentum
        base_score = 50.0
        momentum = min(max(change_24h, -10), 10) * 2
        base_score += momentum

        if asset_class == "Crypto":
            base_score += 5
        elif asset_class == "US Equity":
            base_score += 3

        base_score = max(0, min(100, base_score))

        # Determine grade
        if base_score >= 90:
            grade, signal, weight = "A+", "STRONG OVERWEIGHT", 0.15
        elif base_score >= 80:
            grade, signal, weight = "A", "STRONG OVERWEIGHT", 0.15
        elif base_score >= 70:
            grade, signal, weight = "B+", "OVERWEIGHT", 0.10
        elif base_score >= 60:
            grade, signal, weight = "B", "OVERWEIGHT", 0.10
        elif base_score >= 50:
            grade, signal, weight = "C+", "NEUTRAL", 0.05
        elif base_score >= 40:
            grade, signal, weight = "C", "UNDERWEIGHT", 0.02
        elif base_score >= 25:
            grade, signal, weight = "D", "AVOID", 0.00
        else:
            grade, signal, weight = "F", "AVOID", 0.00

        pillars = {
            "F": base_score * 0.9,
            "M": base_score,
            "R": base_score * 0.8,
            "S": base_score * 0.85,
            "A": base_score * 0.95,
        }

        return CISScore(
            asset=asset,
            asset_name=asset_name,
            asset_class=asset_class,
            cis_score=round(base_score, 1),
            grade=grade,
            signal=signal,
            recommended_weight=weight,
            pillars=pillars,
            percentile=0.0,
            class_rank=0,
            global_rank=0,
            timestamp=datetime.now().isoformat(),
            data_freshness="live",
        )

    except Exception as e:
        logger.error(f"Error in simplified scoring for {asset}: {e}")
        return None


def calculate_ranks(scores: List[CISScore]) -> List[CISScore]:
    """Calculate percentile and rank for all scores"""
    if not scores:
        return scores

    # Sort by CIS score
    sorted_scores = sorted(scores, key=lambda x: x.cis_score, reverse=True)
    n = len(sorted_scores)

    # Assign global rank
    for i, score in enumerate(sorted_scores):
        score.global_rank = i + 1
        score.percentile = round((n - i) / n * 100, 1)

    # Group by asset class and assign class rank
    by_class: Dict[str, List[CISScore]] = {}
    for score in sorted_scores:
        if score.asset_class not in by_class:
            by_class[score.asset_class] = []
        by_class[score.asset_class].append(score)

    for class_name, class_scores in by_class.items():
        class_scores.sort(key=lambda x: x.cis_score, reverse=True)
        for i, score in enumerate(class_scores):
            score.class_rank = i + 1

    return sorted_scores


# ═══════════════════════════════════════════════════════════════════════════
# JOB EXECUTION
# ═══════════════════════════════════════════════════════════════════════════

def run_cis_job(assets: List[str] = None, full_universe: bool = False) -> JobResult:
    """
    Run CIS scoring job

    Args:
        assets: Specific assets to score (None = all)
        full_universe: If True, score all 53 assets
    """
    start_time = time.time()
    job_id = f"cis_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    logger.info(f"Starting CIS job: {job_id}")

    # Import data fetcher
    try:
        from data_fetcher import fetch_prices_batch
    except ImportError:
        logger.error("data_fetcher.py not found")
        return JobResult(
            job_id=job_id,
            job_type="cis_scoring",
            success=False,
            timestamp=datetime.now().isoformat(),
            data_freshness="error",
            assets_processed=0,
            error="data_fetcher not found",
            duration_seconds=time.time() - start_time,
        )

    # Determine assets to process
    if assets:
        target_assets = assets
    elif full_universe:
        target_assets = ALL_ASSETS
    else:
        # Default: Crypto + top TradFi
        target_assets = ALL_ASSETS[:25]  # First 25 = mostly Crypto

    # Fetch prices
    logger.info(f"Fetching prices for {len(target_assets)} assets...")
    price_result = fetch_prices_batch(target_assets)

    if not price_result.success or not price_result.data:
        return JobResult(
            job_id=job_id,
            job_type="cis_scoring",
            success=False,
            timestamp=datetime.now().isoformat(),
            data_freshness=price_result.data_freshness,
            assets_processed=0,
            error=price_result.error or "No price data",
            duration_seconds=time.time() - start_time,
        )

    # Calculate scores
    scores: List[CISScore] = []
    for asset, price_data in price_result.data.items():
        score = calculate_cis_score(asset, price_data)
        if score:
            scores.append(score)

    # Calculate ranks
    scores = calculate_ranks(scores)

    # Prepare output
    output_data = {
        "job_id": job_id,
        "timestamp": datetime.now().isoformat(),
        "data_freshness": price_result.data_freshness,
        "sources": price_result.sources_used,
        "assets_processed": len(scores),
        "scores": [asdict(s) for s in scores],
    }

    # Save to file
    output_file = DATA_DIR / f"cis_scores_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    # Also save latest
    latest_file = DATA_DIR / "cis_scores_latest.json"
    with open(latest_file, "w") as f:
        json.dump(output_data, f, indent=2)

    # ── Write to local SQLite history DB ─────────────────────────────────────
    try:
        from db_writer import write_cis_snapshot, init_db
        init_db()   # no-op if tables already exist
        # Detect macro regime if engine exposed it
        regime = None
        engine = get_cis_engine()
        if engine and hasattr(engine, "current_regime"):
            try:
                regime = str(engine.current_regime)
            except Exception:
                pass
        write_cis_snapshot(
            scores=scores,
            job_id=job_id,
            regime=regime,
            duration_seconds=time.time() - start_time,
            data_freshness=price_result.data_freshness,
        )
    except Exception as _db_err:
        logger.warning(f"DB write skipped: {_db_err}")
    # ─────────────────────────────────────────────────────────────────────────

    # Push to Railway if URL is configured
    if RAILWAY_URL:
        import subprocess
        try:
            push_result = subprocess.run(
                [sys.executable, "cis_push.py", "--url", RAILWAY_URL],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=60
            )
            if push_result.returncode == 0:
                logger.info("Successfully pushed scores to Railway")
            else:
                logger.warning(f"Push failed: {push_result.stderr}")
        except Exception as e:
            logger.warning(f"Failed to push to Railway: {e}")

    duration = time.time() - start_time
    logger.info(f"CIS job completed: {len(scores)} assets in {duration:.1f}s")

    return JobResult(
        job_id=job_id,
        job_type="cis_scoring",
        success=True,
        timestamp=datetime.now().isoformat(),
        data_freshness=price_result.data_freshness,
        assets_processed=len(scores),
        error=None,
        duration_seconds=duration,
    )


# ═══════════════════════════════════════════════════════════════════════════
# SCHEDULER
# ═══════════════════════════════════════════════════════════════════════════

class CISScheduler:
    """Scheduler for CIS scoring jobs"""

    def __init__(self, schedule: str = DEFAULT_SCHEDULE):
        self.schedule = schedule
        self.running = False
        self.thread: Optional[threading.Thread] = None
        self.interval_seconds = self._get_interval(schedule)
        self.last_run: Optional[datetime] = None

        # Register cleanup
        atexit.register(self.stop)

    def _get_interval(self, schedule: str) -> int:
        """Get interval in seconds for schedule"""
        intervals = {
            "hourly": 3600,
            "daily_6am": 86400,
            "daily_12pm": 86400,
            "daily_6pm": 86400,
            "daily_midnight": 86400,
        }
        return intervals.get(schedule, 3600)

    def _run_job(self):
        """Execute a single job"""
        logger.info("=" * 50)
        logger.info("CIS Scheduler: Running scheduled job")
        logger.info("=" * 50)

        try:
            result = run_cis_job(full_universe=True)
            self.last_run = datetime.now()

            # Log result
            if result.success:
                logger.info(f"Job SUCCESS: {result.assets_processed} assets scored")
            else:
                logger.error(f"Job FAILED: {result.error}")

        except Exception as e:
            logger.error(f"Job EXCEPTION: {e}")
            logger.error(traceback.format_exc())

    def _scheduler_loop(self):
        """Main scheduler loop"""
        logger.info(f"Scheduler started: {self.schedule}, interval={self.interval_seconds}s")

        while self.running:
            try:
                self._run_job()

                # Sleep until next interval
                for _ in range(self.interval_seconds):
                    if not self.running:
                        break
                    time.sleep(1)

            except Exception as e:
                logger.error(f"Scheduler error: {e}")
                logger.error(traceback.format_exc())
                time.sleep(60)  # Wait 1 min on error

        logger.info("Scheduler stopped")

    def start(self):
        """Start the scheduler"""
        if self.running:
            logger.warning("Scheduler already running")
            return

        self.running = True
        self.thread = threading.Thread(target=self._scheduler_loop, daemon=True)
        self.thread.start()
        logger.info("Scheduler started in background")

    def stop(self):
        """Stop the scheduler"""
        if not self.running:
            return

        self.running = False
        if self.thread:
            self.thread.join(timeout=5)
        logger.info("Scheduler stopped")

    def run_once(self):
        """Run a single job immediately"""
        return run_cis_job(full_universe=True)


# ═══════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """CLI entry point"""
    import argparse

    parser = argparse.ArgumentParser(description="CIS Scheduler")
    parser.add_argument("--run-once", action="store_true", help="Run once and exit")
    parser.add_argument("--schedule", default=DEFAULT_SCHEDULE, help="Schedule to use")
    parser.add_argument("--assets", nargs="+", help="Specific assets to score")
    parser.add_argument("--full", action="store_true", help="Score full universe (53 assets)")

    args = parser.parse_args()

    if args.run_once:
        # Run once
        if args.assets:
            result = run_cis_job(assets=args.assets)
        elif args.full:
            result = run_cis_job(full_universe=True)
        else:
            result = run_cis_job()

        print(f"\n{'='*60}")
        print(f"Job Result: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"Assets: {result.assets_processed}")
        print(f"Duration: {result.duration_seconds:.1f}s")
        if result.error:
            print(f"Error: {result.error}")
        print(f"{'='*60}")

    else:
        # Start scheduler
        scheduler = CISScheduler(schedule=args.schedule)
        scheduler.start()

        # Keep running
        try:
            while True:
                time.sleep(60)
        except KeyboardInterrupt:
            print("\nStopping scheduler...")
            scheduler.stop()


if __name__ == "__main__":
    main()
