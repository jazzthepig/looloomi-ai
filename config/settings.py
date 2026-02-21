"""
Looloomi AI - Configuration
"""
import os
from dotenv import load_dotenv

load_dotenv()

# API Keys (add to .env file, never commit)
COINGECKO_API_KEY = os.getenv("COINGECKO_API_KEY", "")
DEFILLAMA_API = "https://api.llama.fi"
ALTERNATIVE_ME_API = "https://api.alternative.me"

# Supported Assets (Major Liquid Only - as per design)
MAJOR_ASSETS = {
    "crypto": ["BTC", "ETH", "SOL", "BNB", "XRP", "ADA", "AVAX", "DOT", "MATIC", "LINK"],
    "stablecoins": ["USDT", "USDC", "DAI"],
    "defi_blue_chips": ["UNI", "AAVE", "MKR", "LDO", "CRV"]
}

# Exchange Configuration
EXCHANGES = {
    "binance": {"enabled": True, "api_key": os.getenv("BINANCE_API_KEY", "")},
    "okx": {"enabled": True, "api_key": os.getenv("OKX_API_KEY", "")},
}

# MMI Configuration
MMI_WEIGHTS = {
    "social": 0.30,
    "onchain": 0.30,
    "sentiment": 0.20,
    "historical": 0.20
}

# Risk Parameters
RISK_CONFIG = {
    "max_drawdown_alert": -0.15,  # -15%
    "var_confidence": 0.95,
    "lookback_days": 90
}
