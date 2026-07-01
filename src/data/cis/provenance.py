"""
Provenance layer — decision-complete substrate (ARCHITECTURE.md: we are judgment
infrastructure for other agents). A consuming agent must be able to DEFEND a decision it
made on our data: where did each number come from, how fresh is it, how confident are we,
and where's the methodology. This attaches a compact `provenance` block to every universe
asset so the answer travels with the data — not in a separate doc the agent won't fetch.

Honest by construction: it labels the real engine (T1 Mac full vs T2 Railway estimation),
the per-pillar sources, the confidence the engine already computed, an as-of timestamp, and
the methodology + compliance basis. No fabricated precision.
"""
from __future__ import annotations

_METHODOLOGY_URL = "https://looloomi.ai/methodology.html"
_COMPLIANCE = "Positioning language only (STRONG OUTPERFORM…UNDERWEIGHT); not investment advice."

# Per-pillar data sources (what actually feeds each pillar). Kept honest + generic;
# the engine field distinguishes the full T1 computation from the T2 estimate.
_PILLAR_SOURCES = {
    "F": "DeFiLlama TVL + fundamentals (crypto) / EODHD fundamentals (TradFi)",
    "M": "CoinGecko price & volume (crypto) / EODHD prices (TradFi)",
    "O": "on-chain / risk-adjusted quality",
    "S": "Alternative.me Fear&Greed + VIX (sentiment)",
    "A": "BTC 30d divergence (crypto) / SPY 30d divergence (TradFi)",
}


def _tier_of(a: dict) -> str:
    dt = str(a.get("data_tier") or "").upper()
    return "T1" if dt in ("1", "T1") else "T2"


def attach_provenance(universe: list, as_of: str | None = None) -> None:
    """Mutate each asset in place with a compact `provenance` block. Never raises per-asset."""
    for a in universe:
        if not isinstance(a, dict):
            continue
        try:
            tier = _tier_of(a)
            conf = a.get("confidence")
            a["provenance"] = {
                "engine": "mac_mini_T1_full" if tier == "T1" else "railway_T2_estimate",
                "data_tier": tier,
                "confidence": round(float(conf), 3) if isinstance(conf, (int, float)) else None,
                "pillar_sources": _PILLAR_SOURCES,
                "as_of": as_of,
                "refresh": "~30 min",
                "methodology": _METHODOLOGY_URL,
                "compliance": _COMPLIANCE,
            }
        except Exception:
            a["provenance"] = {"engine": "unknown", "methodology": _METHODOLOGY_URL}


def _selftest():
    u = [{"symbol": "BTC", "data_tier": "T1", "confidence": 0.91},
         {"symbol": "SPY", "data_tier": "T2", "confidence": 0.5}]
    attach_provenance(u, as_of="2026-07-01T00:00:00Z")
    for a in u:
        p = a["provenance"]
        print(f"{a['symbol']:5} engine={p['engine']:20} tier={p['data_tier']} conf={p['confidence']} as_of={p['as_of']}")
    assert u[0]["provenance"]["engine"] == "mac_mini_T1_full"
    assert u[1]["provenance"]["engine"] == "railway_T2_estimate"
    print("✓ provenance: T1/T2 labeled, confidence carried, methodology + compliance attached.")


if __name__ == "__main__":
    _selftest()
