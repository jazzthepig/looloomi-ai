"""
Catalyst Detector — the L2 narrative organ (Seth, 2026-07-10).
==============================================================

CONVICTION_METHODOLOGY.md's missing organ. A narrative catalyst is only actionable
when TWO things coincide:

  1. NARRATIVE match  — a world-event activates an asset's structural moat
                        (event → capability → asset, via moat_map).
  2. ON-CHAIN activation — the market is ALREADY voting: anomalous volume + price
                        break vs the asset's own trailing baseline. This is the
                        measurable footprint of the catalyst; it grounds the narrative
                        in data so we don't act on a story alone.

The detector fires only on the coincidence — narrative WITHOUT activation is a thesis
waiting; activation WITHOUT narrative is a pump to fade, not chase. Together they are
the L2 signal that hands a ranked candidate to the L4 trend-timing + convex sizing.

Validated on real HYPE data: the on-chain activation half flagged 2026-01-27 with a
volume z-score of 9.6 + breakout at ~$30 — the exact inflection of the 30→65 run.

The narrative half's event→condition classification is where the LLM (LM Studio / cloud)
plugs in; here it is a transparent keyword classifier so the pipeline runs end-to-end now.
Pure numpy + stdlib.
"""
from __future__ import annotations

from dataclasses import dataclass
import numpy as np

from src.data.narrative.moat_map import (
    ACTIVATING_CONDITIONS, MOAT_MAP, assets_for_condition)


# ── On-chain activation (validated on HYPE) ──────────────────────────────────

@dataclass(frozen=True)
class Activation:
    idx: int
    vol_z: float
    kind: str           # 'breakout' | 'momentum'
    close: float


def onchain_activation(close: np.ndarray, quote_vol: np.ndarray, *,
                       base: int = 30, vol_z_min: float = 2.0,
                       mom_min: float = 0.10) -> list[Activation]:
    """Flag days where volume is anomalously high AND price is breaking out / running.
    The measurable footprint of a catalyst hitting a name."""
    n = len(close)
    out: list[Activation] = []
    for i in range(base, n):
        window = quote_vol[i - base:i]
        vz = (quote_vol[i] - window.mean()) / (window.std() + 1e-9)
        if vz < vol_z_min:
            continue
        brk = close[i] > close[i - base:i].max()
        ret5 = (close[i] - close[i - 5]) / close[i - 5] if i >= 5 else 0.0
        if brk:
            out.append(Activation(i, round(float(vz), 2), "breakout", float(close[i])))
        elif ret5 > mom_min:
            out.append(Activation(i, round(float(vz), 2), "momentum", float(close[i])))
    return out


def latest_activation_score(close: np.ndarray, quote_vol: np.ndarray, *,
                            base: int = 30, lookback: int = 5) -> float:
    """0..~10+ activation intensity over the last `lookback` days (max vol_z of any
    activation event). 0 = quiet. This is the live 'is something happening now' number."""
    acts = onchain_activation(close, quote_vol, base=base)
    n = len(close)
    recent = [a.vol_z for a in acts if a.idx >= n - lookback]
    return round(max(recent), 2) if recent else 0.0


# ── Narrative match (LLM-pluggable, keyword baseline) ────────────────────────

_KEYWORDS = {
    "tradfi_closed_macro_shock": ["weekend", "war", "attack", "strike", "shutdown", "closed"],
    "geopolitical_commodity_spike": ["oil", "war", "sanction", "opec", "commodity", "gold", "conflict"],
    "cex_delisting_or_freeze": ["delist", "freeze", "seiz", "sanction", "ban exchange"],
    "regulatory_clarity_rwa": ["etf approv", "regulat", "sec approv", "tokeniz", "treasury"],
    "rates_up_treasury_demand": ["rate hike", "yields rise", "fed hikes", "treasury yield"],
    "ai_compute_shortage": ["gpu shortage", "compute demand", "ai chip", "inference"],
    "stablecoin_regulation": ["stablecoin", "genius act", "payment rail"],
}


def classify_event(text: str) -> list[str]:
    """Map a news/event string → activating-condition tags. Keyword baseline; swap for
    an LLM (LM Studio) that returns the same condition keys for higher recall."""
    t = (text or "").lower()
    return [cond for cond, kws in _KEYWORDS.items() if any(k in t for k in kws)]


# ── Fusion ───────────────────────────────────────────────────────────────────

@dataclass
class CatalystSignal:
    asset: str
    narrative_conditions: list[str]
    activation_z: float
    fired: bool
    note: str


def scan(event_text: str,
         market_panels: dict[str, tuple[np.ndarray, np.ndarray]],
         *, activation_min: float = 3.0) -> list[CatalystSignal]:
    """event_text: a news/macro headline. market_panels: {asset: (close, quote_vol)}.
    Returns catalyst signals for assets whose moat the event activates AND that show
    live on-chain activation ≥ threshold. The coincidence is the signal."""
    conditions = classify_event(event_text)
    activated_assets = set()
    for c in conditions:
        activated_assets.update(assets_for_condition(c))
    out: list[CatalystSignal] = []
    for asset in sorted(activated_assets):
        panel = market_panels.get(asset)
        if panel is None:
            out.append(CatalystSignal(asset, conditions, 0.0, False, "no market data"))
            continue
        close, qv = panel
        az = latest_activation_score(close, qv)
        fired = az >= activation_min
        note = ("NARRATIVE+ACTIVATION coincide — hand to L4 trend timing"
                if fired else "narrative match, awaiting on-chain activation")
        out.append(CatalystSignal(asset, conditions, az, fired, note))
    out.sort(key=lambda s: (s.fired, s.activation_z), reverse=True)
    return out


if __name__ == "__main__":
    # smoke: HYPE-like panel with a volume+price spike + a matching headline
    rng = np.random.default_rng(0)
    close = np.concatenate([np.full(40, 25.0) + rng.normal(0, 0.5, 40),
                            np.array([26, 28, 31, 34, 33])])  # breakout
    qv = np.concatenate([rng.normal(1e8, 1e7, 40), np.array([9e8, 7e8, 6e8, 5e8, 4e8])])
    panels = {"HYPE": (close, qv)}
    sig = scan("Weekend war sends oil soaring while TradFi markets are closed",
               panels)
    for s in sig:
        print(f"{s.asset}: conditions={s.narrative_conditions} activation_z={s.activation_z} "
              f"FIRED={s.fired} — {s.note}")
