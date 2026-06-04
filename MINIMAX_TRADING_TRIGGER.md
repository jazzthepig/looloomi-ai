# Auto Paper Trading Trigger — Minimax Action Required

Add this block to `cis_scheduler.py` immediately after the Railway push block (after line ~548).

## Where to insert

Find this line in `run_cis_job()`:
```python
    logger.info(f"CIS job completed: {len(scores)} assets in {duration:.1f}s")
```

Insert the block ABOVE that line.

---

## The code block

```python
    # ── Auto paper trading — submit orders based on fresh CIS scores ─────────
    if RAILWAY_URL and scores:
        try:
            import urllib.request, json as _json

            REGIME_THRESHOLD = {
                "TIGHTENING": 52, "RISK_OFF": 55, "EASING": 48,
                "RISK_ON": 48, "STAGFLATION": 58, "GOLDILOCKS": 46,
            }
            # Read regime from the scores payload (top-level macro_regime)
            regime = "TIGHTENING"  # fallback
            for s in scores:
                if hasattr(s, "macro_regime") and s.macro_regime:
                    regime = s.macro_regime
                    break
                if isinstance(s, dict) and s.get("macro_regime"):
                    regime = s["macro_regime"]
                    break

            threshold = REGIME_THRESHOLD.get(regime, 52)

            orders_placed = 0
            for asset in scores:
                # Normalise — score objects may be dataclass or dict
                sym    = getattr(asset, "symbol",    None) or (asset.get("symbol")    if isinstance(asset, dict) else None)
                score  = getattr(asset, "cis_score", None) or (asset.get("cis_score") if isinstance(asset, dict) else None)
                signal = getattr(asset, "signal",    None) or (asset.get("signal")    if isinstance(asset, dict) else None)
                tier   = getattr(asset, "data_tier", 2)    or (asset.get("data_tier", 2) if isinstance(asset, dict) else 2)

                if not sym or score is None:
                    continue

                # Gate: CIS above regime threshold + positive signal + T1 preferred
                if score >= threshold and signal in ("OUTPERFORM", "STRONG OUTPERFORM"):
                    # Size in bps: scale with conviction above threshold
                    conviction_bps = min(800, int((score - threshold) / (100 - threshold) * 600 + 200))
                    if tier == 2:
                        conviction_bps = int(conviction_bps * 0.6)  # discount T2

                    order = {
                        "symbol":   sym,
                        "side":     "buy",
                        "size_bps": conviction_bps,
                        "strategy": f"CIS_AUTO_{regime}",
                        "reason":   f"CIS={score:.1f} >= {threshold} ({regime}) | {signal}",
                        "time_horizon": "7D",
                    }

                    try:
                        req = urllib.request.Request(
                            f"{RAILWAY_URL}/api/v1/trading/order",
                            data=_json.dumps(order).encode(),
                            headers={"Content-Type": "application/json"},
                            method="POST",
                        )
                        with urllib.request.urlopen(req, timeout=10) as resp:
                            result = _json.loads(resp.read())
                            if result.get("status") == "filled":
                                orders_placed += 1
                                logger.info(f"[TRADING] {sym} {conviction_bps}bps | {signal} | CIS={score:.1f}")
                    except Exception as order_err:
                        logger.debug(f"[TRADING] order skip {sym}: {order_err}")

            if orders_placed:
                logger.info(f"[TRADING] {orders_placed} paper orders placed | regime={regime} threshold={threshold}")
            else:
                logger.info(f"[TRADING] no qualifying assets | regime={regime} threshold={threshold}")

        except Exception as trading_err:
            logger.warning(f"[TRADING] auto-trading block failed: {trading_err}")
    # ── End auto paper trading ────────────────────────────────────────────────
```

---

## Verify it's working

After next scheduler run, check:
```bash
# Should see TRADING log lines
tail -f /Volumes/CometCloudAI/cometcloud-local/logs/cis_scheduler_*.log | grep TRADING

# Or hit the Railway endpoint
curl https://looloomi.ai/api/v1/trading/metrics
```

Expected: `open_positions > 0`, `portfolio_usd` moving from $10,000 baseline.
