"""Jev regime gate — Pattern A pre-filter for paper trading.

Per `docs/jev_nautilus_integration_plan_2026-09-21.md` Pattern A:
Jev answers "is this regime tradeable?" BEFORE the strategy fires. The decision
is a **veto** — if `regime_ok=False`, the strategy skips this bar/day entirely.

**This module is veto-only.** Risk gates, position sizing, stops, and doctrine
checks stay in `spec_runner.decide_*`. Jev is ONE input among many; never trust
its reported probabilities for sizing (no published Brier/ECE per Jev caveats —
see `~/.claude/projects/-Users-sbb/memory/jev-typesafe-community-research-2026-09-21.md`).

Public surface (canonical, what callers import):
- `JevRegimeDecision` — frozen dataclass, the output of every evaluate()
- `JevRegimeBackend`  — Protocol, pluggable inference source
- `MockJevRegimeBackend` — deterministic backend for paper track + tests
- `JevRegimeActor`    — wraps a backend; the thing paper runners hold

Backends available:
- `MockJevRegimeBackend(mode="always_ok")`     — default; vetoes nothing
- `MockJevRegimeBackend(mode="always_veto")`   — for veto-path tests
- `MockJevRegimeBackend(mode="deterministic", fn=...)` — fn(state) -> bool
- (future) `TypesafeJevRegimeBackend`          — when `JEV_API_KEY` arrives

Why no real backend yet: TypeSafe is in early-access closed beta (Jev launched
2026-09-15); key not in Seth lane. Until it is, mock backend logs decisions to
JSONL so the 60d validation framework (Gate 1 Brier, Gate 3 frequency) has
something to ingest without a live API.

Why separate from `spec_runner.py`: spec_runner is the strategy contract
(decide_*, Spec, Decision). Jev is a **pre-strategy input** — it doesn't decide
what to trade, it decides whether trading is OK at all. Mixing them would
make spec_runner carry a stateful actor it doesn't own.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol


# ── Output type (frozen — every evaluate() call produces one of these) ──────


@dataclass(frozen=True)
class JevRegimeDecision:
    """One bar's worth of Jev gate decision.

    `regime_ok=False` is the **veto signal**. Strategy-side code checks ONLY
    this field. Other fields are telemetry / 60d validation inputs.
    """

    bar_ts: str                          # ISO date the decision applies to
    regime_ok: bool                      # the veto signal
    direction_bias: str                  # "long" | "short" | "neutral"
    confidence: str                      # "low" | "med" | "high"
    jev_latency_ms: float                # wall-clock from request to result
    jev_input_tokens: int                # tokens billed by the backend
    backend_name: str                    # which backend produced this decision
    mock: bool                           # True if from a mock backend
    #: Optional structured explanation (TypesafeBackend may attach; mocks leave None)
    raw: Optional[Mapping[str, Any]] = None


# ── Backend contract ────────────────────────────────────────────────────────


class JevRegimeBackend(Protocol):
    """Pluggable inference source. Implementations MUST be deterministic
    OR have a documented random seed; otherwise 60d validation (Gate 1 Brier)
    is unreproducible.

    `evaluate()` MUST NOT raise on transient network errors — return a
    `JevRegimeDecision` with `regime_ok=True` (fail-open) and `mock=False`
    plus a `raw={"error": ...}` field. **Fail-open is the safe default for
    veto-only gates**: skipping one decision because the vendor hiccuped is
    strictly worse than running one extra day of paper track.
    """

    name: str

    def evaluate(self, state_payload: Mapping[str, Any]) -> JevRegimeDecision:
        ...


# ── Mock backend (the only one shipped today) ──────────────────────────────


#: Allowed `direction_bias` values — mirrors the Jev `Choice` schema
_VALID_BIASES = ("long", "short", "neutral")
#: Allowed `confidence` values — mirrors the Jev `Score` levels
_VALID_CONFIDENCES = ("low", "med", "high")


class MockJevRegimeBackend:
    """Deterministic backend for paper track + tests.

    Modes:
    - `"always_ok"`      — every call returns regime_ok=True. DEFAULT. Use for
                           real paper track (we want Jev to learn, not block).
    - `"always_veto"`    — every call returns regime_ok=False. Use for veto
                           path tests + "what if Jev blocked today" drill.
    - `"deterministic"`  — user-supplied `fn(state_payload) -> bool`. Use for
                           60d validation (Gate 1) — replay historical state
                           payloads through a known function and measure Brier.

    Latency / tokens are fake-but-realistic (Typesafe measured p50 ~150ms /
    ~5KB per call for jev-trader-style state). Real TypesafeBackend should
    overwrite both.
    """

    name = "mock_jev_regime"

    def __init__(
        self,
        mode: str = "always_ok",
        *,
        fn: Optional[Callable[[Mapping[str, Any]], bool]] = None,
        direction_bias: str = "neutral",
        confidence: str = "med",
        fake_latency_ms: float = 150.0,
        fake_input_tokens: int = 1250,
    ) -> None:
        if mode not in ("always_ok", "always_veto", "deterministic"):
            raise ValueError(
                f"MockJevRegimeBackend mode={mode!r} unknown; "
                f"expected always_ok|always_veto|deterministic"
            )
        if mode == "deterministic" and fn is None:
            raise ValueError(
                "mode='deterministic' requires `fn` — a callable "
                "(state_payload) -> bool. Use it for 60d validation replays."
            )
        if direction_bias not in _VALID_BIASES:
            raise ValueError(
                f"direction_bias={direction_bias!r} not in {_VALID_BIASES}"
            )
        if confidence not in _VALID_CONFIDENCES:
            raise ValueError(
                f"confidence={confidence!r} not in {_VALID_CONFIDENCES}"
            )
        self._mode = mode
        self._fn = fn
        self._direction_bias = direction_bias
        self._confidence = confidence
        self._fake_latency_ms = float(fake_latency_ms)
        self._fake_input_tokens = int(fake_input_tokens)

    def evaluate(self, state_payload: Mapping[str, Any]) -> JevRegimeDecision:
        bar_ts = str(state_payload.get("bar_ts") or "")
        if not bar_ts:
            # bar_ts is the canonical "what day is this decision for" field.
            # Without it, downstream logging can't correlate decisions to bars.
            raise ValueError(
                "state_payload 必须带 bar_ts (ISO date) —— 没有它,"
                "Jev decision 就无法对应到具体的 bar/decision log 行"
            )
        if self._mode == "always_ok":
            regime_ok = True
        elif self._mode == "always_veto":
            regime_ok = False
        else:  # deterministic
            regime_ok = bool(self._fn(state_payload))  # type: ignore[misc]
        return JevRegimeDecision(
            bar_ts=bar_ts,
            regime_ok=regime_ok,
            direction_bias=self._direction_bias,
            confidence=self._confidence,
            jev_latency_ms=self._fake_latency_ms,
            jev_input_tokens=self._fake_input_tokens,
            backend_name=self.name,
            mock=True,
            raw=None,
        )


# ── Actor (the thing runners hold) ─────────────────────────────────────────


@dataclass
class JevRegimeActor:
    """Wraps a backend with a single `decide()` method + lightweight stats.

    Why stats: 60d validation framework (Gate 1 Brier / Gate 3 frequency / Gate 4
    cost realism) needs call-count + cumulative latency + cumulative tokens to
    run without re-reading JSONL every time. Stats are in-memory (per process);
    the JSONL log is the durable record.

    NOT a Nautilus DataActor — the paper-track runner is a CLI script, not the
    Nautilus engine. The Nautilus-side analog lives in
    `src/research/nautilus/sleeve_a/jev_regime_actor.py` (future ship, blocked
    on Nautilus wiring per M-121).
    """

    backend: JevRegimeBackend
    name: str = "jev_regime_actor"
    n_calls: int = 0
    cum_latency_ms: float = 0.0
    cum_input_tokens: int = 0

    def decide(self, state_payload: Mapping[str, Any]) -> JevRegimeDecision:
        d = self.backend.evaluate(state_payload)
        self.n_calls += 1
        self.cum_latency_ms += d.jev_latency_ms
        self.cum_input_tokens += d.jev_input_tokens
        return d

    # Sugar so callers can write `actor(state_payload)` instead of
    # `actor.decide(state_payload)`. Both work; the runner uses decide() to
    # make the boundary explicit at the call site.
    __call__ = decide  # type: ignore[assignment]

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "backend": self.backend.name,
            "n_calls": self.n_calls,
            "cum_latency_ms": round(self.cum_latency_ms, 3),
            "avg_latency_ms": (
                round(self.cum_latency_ms / self.n_calls, 3)
                if self.n_calls else 0.0
            ),
            "cum_input_tokens": self.cum_input_tokens,
        }


# ── State payload helper (so runners don't reinvent the wheel) ─────────────


def build_state_payload(
    *,
    bar_ts: str,
    regime: Optional[str],
    panel_age_days: Optional[int],
    panel_n_symbols: int,
    vol_20d: Optional[float] = None,
    breadth_200ma: Optional[float] = None,
    extra: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build a state payload for the Jev backend.

    Keep it small (< 50 fields per Jev cardinality caveat 255). The schema
    below is the **minimum** for Pattern A's regime question. Future Pattern D
    (multi-primitive batch) may add per-symbol features.

    `bar_ts` is REQUIRED — every other field is optional and may be None if
    upstream data is missing (MockBackend ignores them; future TypesafeBackend
    should treat None as "insufficient evidence" and bias toward neutral).
    """
    payload: dict[str, Any] = {
        "bar_ts": bar_ts,
        "regime": regime,
        "panel_age_days": panel_age_days,
        "panel_n_symbols": panel_n_symbols,
        "vol_20d": vol_20d,
        "breadth_200ma": breadth_200ma,
    }
    if extra:
        # Surface extras under their own namespace so Jev schema can reference
        # them without colliding with the canonical fields above.
        payload["extra"] = dict(extra)
    return payload
