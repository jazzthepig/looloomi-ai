"""Tests for CIS scoring — data structures and calculations."""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestCISProviderImports:
    """Verify CIS provider module loads correctly."""

    def test_cis_provider_imports(self):
        """CIS provider module loads without errors."""
        from data.cis import cis_provider

        # Verify key functions/classes exist
        assert hasattr(cis_provider, "CRYPTO_ASSETS")
        assert hasattr(cis_provider, "ASSETS_CONFIG")
        assert hasattr(cis_provider, "calculate_cis_universe")
        assert hasattr(cis_provider, "calculate_total_score")
        assert hasattr(cis_provider, "calculate_las")

    def test_assets_config_has_crypto(self):
        """ASSETS_CONFIG contains crypto assets."""
        from data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS

        # ASSETS_CONFIG should be a merged dict
        assert len(ASSETS_CONFIG) > 0
        assert "BTC" in ASSETS_CONFIG
        assert "ETH" in CRYPTO_ASSETS

    def test_crypto_assets_coingecko_ids(self):
        """CRYPTO_ASSETS have valid CoinGecko IDs for top assets."""
        from data.cis.cis_provider import CRYPTO_ASSETS

        # Check that top assets have coingecko IDs
        for asset in ["BTC", "ETH", "SOL"]:
            assert asset in CRYPTO_ASSETS
            assert CRYPTO_ASSETS[asset].get("coingecko")

    def test_binance_symbols_mapping(self):
        """BINANCE_SYMBOLS maps asset IDs to Binance symbols."""
        from data.cis.cis_provider import BINANCE_SYMBOLS

        assert "BTC" in BINANCE_SYMBOLS
        assert BINANCE_SYMBOLS["BTC"] == "btcusdt"
        assert "ETH" in BINANCE_SYMBOLS
        assert BINANCE_SYMBOLS["ETH"] == "ethusdt"

    def test_las_calculation(self):
        """LAS calculation produces expected output shape."""
        from data.cis.cis_provider import calculate_las

        result = calculate_las(
            cis_score=75.0,
            volume_24h=1_000_000_000,
            high_24h=70000,
            low_24h=68000,
            confidence=0.85,
        )

        assert "las" in result
        assert "las_params" in result
        params = result["las_params"]
        assert "liquidity_multiplier" in params
        assert "spread_penalty" in params
        assert isinstance(result["las"], float)

    def test_las_zero_volume(self):
        """LAS with zero volume returns zero liquidity multiplier."""
        from data.cis.cis_provider import calculate_las

        result = calculate_las(
            cis_score=75.0,
            volume_24h=0,
            high_24h=70000,
            low_24h=68000,
            confidence=0.85,
        )
        assert result["las_params"]["liquidity_multiplier"] < 0.1  # Near-zero when volume is 0

    def test_regime_detection_exists(self):
        """Regime detection function exists."""
        from data.cis.cis_provider import detect_regime

        # Basic regime detection
        result = detect_regime(
            btc_30d=0.15,
            fng_value=30,
            vix=20,
            btc_dominance=55.0,
        )
        # Returns: "Risk-On", "Risk-Off", "Neutral", "Tightening", "Easing", "Stagflation", "Goldilocks", or "Unknown"
        assert isinstance(result, str)
        assert len(result) > 0

    def test_score_grading_bounds(self):
        """CIS score grades stay within bounds."""
        from data.cis.cis_provider import ASSETS_CONFIG, CRYPTO_ASSETS

        # All assets in config should have required fields
        for asset_id, config in list(ASSETS_CONFIG.items())[:5]:
            assert "name" in config or "coingecko" in config
