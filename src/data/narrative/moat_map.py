"""
Moat Map — the L1 structural-value ontology (Seth, 2026-07-10).
================================================================

Per CONVICTION_METHODOLOGY.md L1: "what can ONLY this asset do?" A move without a
moat is a pump. This is the curated ontology that lets the L2 catalyst detector turn
a real-world event into an actionable asset list: an event activates a CAPABILITY, and
the moat map says which assets hold that capability.

Human+AI authored and maintained — this is durable knowledge, not a live feed. The
LLM (LM Studio / cloud) can PROPOSE additions from news + docs; a human ratifies.
Deliberately small and honest: only assets with a defensible, articulable moat belong.
"""
from __future__ import annotations

from dataclasses import dataclass, field


# Capability tags — what structural thing the asset uniquely provides.
CAPABILITIES = {
    "onchain_24_7_derivatives": "24/7 leveraged perp/derivatives trading fully on-chain",
    "permissionless_listing":   "anyone can list a market (long-tail / event markets)",
    "onchain_commodity_exposure": "on-chain exposure to commodities/RWA the CEX/TradFi world gates",
    "real_yield_buyback":       "protocol revenue → token via buyback / fee-share (reflexive loop)",
    "censorship_resistant":     "cannot be frozen / delisted / KYC-gated",
    "compliant_rwa":            "regulated tokenized real-world assets (treasuries, credit)",
    "settlement_rail":          "high-throughput settlement / stablecoin rail",
    "data_or_compute_market":   "decentralized data / compute / inference marketplace",
}

# World-event conditions → the capabilities they make URGENT (the L2 activation keys).
ACTIVATING_CONDITIONS = {
    "tradfi_closed_macro_shock": ["onchain_24_7_derivatives", "onchain_commodity_exposure"],
    "geopolitical_commodity_spike": ["onchain_commodity_exposure", "onchain_24_7_derivatives"],
    "cex_delisting_or_freeze":   ["censorship_resistant", "permissionless_listing"],
    "regulatory_clarity_rwa":    ["compliant_rwa", "real_yield_buyback"],
    "rates_up_treasury_demand":  ["compliant_rwa"],
    "ai_compute_shortage":       ["data_or_compute_market"],
    "stablecoin_regulation":     ["settlement_rail", "compliant_rwa"],
}


@dataclass(frozen=True)
class Moat:
    asset: str
    capabilities: tuple[str, ...]
    thesis: str
    reflexive_loop: bool = False          # does usage → token demand structurally?


# The curated map. Small on purpose — earn your way in with a real moat.
MOAT_MAP: dict[str, Moat] = {
    "HYPE": Moat("HYPE",
                 ("onchain_24_7_derivatives", "permissionless_listing",
                  "onchain_commodity_exposure", "real_yield_buyback"),
                 "24/7 on-chain leveraged perp/commodity venue w/ permissionless HIP-3 "
                 "markets; 99% of fees fund an open-market buyback (usage→revenue→buyback).",
                 reflexive_loop=True),
    # archetypes — extend as the map is ratified
    "ONDO": Moat("ONDO", ("compliant_rwa", "real_yield_buyback"),
                 "tokenized US treasuries / regulated RWA rail.", reflexive_loop=False),
    "GMX":  Moat("GMX", ("onchain_24_7_derivatives", "real_yield_buyback"),
                 "on-chain perp DEX with fee-share to stakers.", reflexive_loop=True),
}


def assets_with_capability(cap: str) -> list[str]:
    return [m.asset for m in MOAT_MAP.values() if cap in m.capabilities]


def assets_for_condition(condition: str) -> list[str]:
    """Given a world-event condition, return assets whose moat it activates."""
    caps = ACTIVATING_CONDITIONS.get(condition, [])
    out = []
    for m in MOAT_MAP.values():
        if any(c in m.capabilities for c in caps):
            out.append(m.asset)
    return sorted(set(out))


if __name__ == "__main__":
    print("Moat map:", {a: m.capabilities for a, m in MOAT_MAP.items()})
    print("\nWeekend war / TradFi closed → activates:",
          assets_for_condition("tradfi_closed_macro_shock"))
    print("Rates up / treasury demand → activates:",
          assets_for_condition("rates_up_treasury_demand"))
