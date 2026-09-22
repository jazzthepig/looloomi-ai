"""Jev multi-primitive decision kernel — S-397 §5b ④ L/S overlay.

Per `s397-jev-ls-overlay-redesign-2026-09-21.md` (Seth-side, JAZZ-pivoted 2026-09-21):
Jev is NOT a regime filter (that's `jev_regime.py`). Jev IS a decision kernel that
returns **calibrated multi-primitive batches** for bound answer spaces — Choice
(pick from options) + Score (level on a scale) + Noul (yes/no probability) — all
evaluated IN PARALLEL over the same state, in ONE call.

The killer feature: 13 questions in 1 call = **12.2× cheaper + 10× faster**
than 13 sequential calls (datacamp / flaviocopes community-validated).
Per-case cost ~$0.0004, $7/hr Doom @ 10Hz = latency budget 70–500ms.

## Why this module, why not just extend `jev_regime.py`?

`jev_regime.py` is **veto-only** (Noul-style boolean regime_ok). §5b ④ L/S overlay
needs 30 calibrated judgments per cadence (10 pairs × Choice+Score+Noul). The
two surfaces are different enough to keep them in separate modules — same actor
plumbing, different decision shape, different payload builder.

## Public surface (canonical)

- `JevDecision` — frozen dataclass, the output of every `evaluate_batch()` call
- `JevDecisionBackend` — Protocol, pluggable inference source
- `MockJevDecisionBackend` — deterministic for tests + 60d paper-track
- `TypesafeJevDecisionBackend` — real `api.typesafe.ai` client (JEV_API_KEY)
- `JevDecisionActor` — wraps a backend; the thing runners hold
- `build_ls_state_payload` — 30-field L/S context builder (see ls_state_builder.py)

## Fail-open discipline

Per `jev_regime.py` JevRegimeBackend Protocol contract:
- `evaluate()` MUST NOT raise on transient errors — return a decision with
  `mock=False` + `raw={"error": ...}` and **regime_ok=True (fail-open)**.
- Same applies here: if the vendor hiccups, the strategy runs without Jev's
  input rather than freezing the book. One missed decision < one missed day.

## Cardinality cap (Jev caveat #6)

Jev has a **255-field cardinality cap** on the state payload. We build
~30 fields per call. Per-symbol features scale with universe size; if universe
expands past ~12 symbols we need to chunk into multiple calls (Pattern D batched
with SGLang radix cache ~150ms).
"""
from __future__ import annotations

import json
import logging
import os
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping, Optional, Protocol, Sequence

log = logging.getLogger(__name__)


# ── Output type (frozen — every batch() produces one of these) ──────────────


@dataclass(frozen=True)
class JevDecision:
    """One batch's worth of Jev multi-primitive decisions.

    `answers` is a flat dict from question name → primitive payload:
        - Choice:  {"choice": str, "probabilities": dict[str, float], "confidence": float}
        - Score:   {"score": float, "legend": dict[str, str], "probabilities": dict[str, float]}
        - Noul:    {"noul": float}

    Strategy-side code reads ONLY `answers` (and `error` if present). Other
    fields are telemetry / 60d validation / ⓪ OVERRIDE gate inputs.
    """

    bar_ts: str                              # ISO date the batch applies to
    answers: Mapping[str, Mapping[str, Any]]  # question name → primitive payload
    jev_latency_ms: float                    # wall-clock from request to result
    jev_input_tokens: int                    # tokens billed by the backend
    backend_name: str                        # which backend produced this batch
    mock: bool                               # True if from a mock backend
    #: Optional error info if the call failed-open (raw={"error": "..."})
    error: Optional[str] = None
    raw: Optional[Mapping[str, Any]] = None


# ── Question spec (what we ask Jev) ─────────────────────────────────────────


@dataclass(frozen=True)
class JevQuestion:
    """One question in a multi-primitive batch.

    primitive ∈ {"Choice", "Score", "Noul"}. `criteria` shape depends on primitive:
        - Choice: dict[str, str]  — option name → human-readable description
        - Score:  list[str]       — ordered levels (low → high)
        - Noul:   None            — single yes/no probability
    """

    name: str
    primitive: str
    instructions: str
    criteria: Any = None  # see above


def build_ls_questions(universe: Sequence[str]) -> list[JevQuestion]:
    """Build the 30-question L/S batch for `universe` (5 symbols → 10 pairs × 3 prims).

    Pair construction: C(n, 2). For 5 symbols = 10 pairs. Per pair we ask:
        - Choice:  direction (long_a / long_b / no_edge)
        - Score:   conviction -1↔+1 (mapped to weight)
        - Noul:    thesis still intact? (used as exit trigger)

    Cardinality: 30 questions for 5 symbols. Cap at 12 symbols before chunking
    (12 → 66 pairs × 3 = 198 questions, near Jev's 255 limit).

    Returns a frozen list of JevQuestion objects the backend serializes to API.
    """
    from itertools import combinations
    if len(universe) < 2:
        raise ValueError(
            f"universe must have ≥ 2 symbols for L/S pairs, got {len(universe)}"
        )
    questions: list[JevQuestion] = []
    for i, (sym_a, sym_b) in enumerate(combinations(universe, 2)):
        pair_id = f"pair_{i:02d}_{sym_a}_{sym_b}"
        # Choice: which leg wins next 7d?
        questions.append(JevQuestion(
            name=f"{pair_id}_direction",
            primitive="Choice",
            instructions=(
                f"Which leg of the {sym_a}/{sym_b} pair will outperform over the "
                f"next 7 trading days, given the L/S state context? Answer "
                f"`long_{sym_a}` if {sym_a} beats {sym_b}; `long_{sym_b}` if the "
                f"opposite; `no_edge` if the pair has no reliable 7d direction."
            ),
            criteria={
                f"long_{sym_a}": f"{sym_a} outperforms {sym_b} by ≥1pp over 7d",
                f"long_{sym_b}": f"{sym_b} outperforms {sym_a} by ≥1pp over 7d",
                "no_edge": "Pair has no statistically meaningful 7d direction",
            },
        ))
        # Score: conviction strength -1↔+1
        questions.append(JevQuestion(
            name=f"{pair_id}_conviction",
            primitive="Score",
            instructions=(
                f"How strong is your conviction in the {sym_a}/{sym_b} pair "
                f"direction? -1 = strong short conviction, 0 = neutral, "
                f"+1 = strong long conviction. Used as the weight input."
            ),
            criteria=[
                "-1 (strong short)",
                "-0.5 (weak short)",
                "0 (neutral)",
                "+0.5 (weak long)",
                "+1 (strong long)",
            ],
        ))
        # Noul: thesis still valid? (exit trigger)
        questions.append(JevQuestion(
            name=f"{pair_id}_thesis_valid",
            primitive="Noul",
            instructions=(
                f"Is the structural thesis behind the {sym_a}/{sym_b} pair "
                f"trade still intact? Answer yes if the macro/micro conditions "
                f"that motivated entry still hold; no if they have reversed."
            ),
            criteria=None,
        ))
    return questions


# ── Backend contract ────────────────────────────────────────────────────────


class JevDecisionBackend(Protocol):
    """Pluggable inference source. Implementations MUST be deterministic OR
    have a documented random seed; otherwise 60d validation (Gate 1 Brier,
    Gate 2 ECE) is unreproducible.

    `evaluate_batch()` MUST NOT raise on transient errors — return a `JevDecision`
    with `error="..."`, `mock=False`, and the answer map populated with
    `{"noul": 0.5}` (Noul-fail-open) or `{"choice": "no_edge", "confidence": 0}`
    for Choice/Score questions. **Fail-open is the safe default for §5b ④ L/S**:
    one missed batch is strictly less harmful than freezing the book for an
    entire cadence.
    """

    name: str

    def evaluate_batch(
        self,
        state_payload: Mapping[str, Any],
        questions: Sequence[JevQuestion],
    ) -> JevDecision:
        ...


# ── Mock backend (the test-only one) ───────────────────────────────────────


class MockJevDecisionBackend:
    """Deterministic backend for tests + 60d paper track.

    Modes:
    - `"always_no_edge"` — every Choice returns "no_edge", Score = 0, Noul = 0.5.
      Default. Use for the "Jev wire works but adds no L/S signal" baseline.
    - `"deterministic"`  — user-supplied `fn(state, question_name, primitive)`
      returns a per-question answer dict. Use for 60d validation replays
      (Brier / ECE against known distribution).

    Latency / tokens are fake-but-realistic (Typesafe measured p50 ~150ms /
    ~5KB per call for 30-question state). Real TypesafeBackend overwrites both.
    """

    name = "mock_jev_decision"

    def __init__(
        self,
        mode: str = "always_no_edge",
        *,
        fn: Optional[Callable[[Mapping[str, Any], str, str], Mapping[str, Any]]] = None,
        fake_latency_ms: float = 150.0,
        fake_input_tokens: int = 5000,
    ) -> None:
        if mode not in ("always_no_edge", "deterministic"):
            raise ValueError(
                f"MockJevDecisionBackend mode={mode!r} unknown; "
                f"expected always_no_edge|deterministic"
            )
        if mode == "deterministic" and fn is None:
            raise ValueError(
                "mode='deterministic' requires `fn` — a callable "
                "(state, question_name, primitive) -> answer dict"
            )
        self._mode = mode
        self._fn = fn
        self._fake_latency_ms = float(fake_latency_ms)
        self._fake_input_tokens = int(fake_input_tokens)

    def evaluate_batch(
        self,
        state_payload: Mapping[str, Any],
        questions: Sequence[JevQuestion],
    ) -> JevDecision:
        bar_ts = str(state_payload.get("bar_ts") or "")
        if not bar_ts:
            raise ValueError(
                "state_payload 必须带 bar_ts (ISO date) —— 没有它,"
                "Jev batch 就无法对应到具体的 bar/decision log 行"
            )

        answers: dict[str, dict[str, Any]] = {}
        for q in questions:
            if self._mode == "always_no_edge":
                if q.primitive == "Choice":
                    # Always pick the no_edge option if it exists, else first.
                    criteria = q.criteria or {}
                    no_edge_key = next(
                        (k for k in criteria if "no_edge" in k.lower()),
                        next(iter(criteria), "no_edge"),
                    )
                    answers[q.name] = {
                        "choice": no_edge_key,
                        "probabilities": {no_edge_key: 1.0},
                        "confidence": 0.0,
                    }
                elif q.primitive == "Score":
                    answers[q.name] = {
                        "score": 0.0,
                        "legend": {str(c): c for c in (q.criteria or [])},
                        "probabilities": {},
                    }
                elif q.primitive == "Noul":
                    answers[q.name] = {"noul": 0.5}
                else:
                    raise ValueError(f"unknown primitive {q.primitive!r}")
            else:  # deterministic
                ans = self._fn(state_payload, q.name, q.primitive)  # type: ignore[misc]
                if not isinstance(ans, dict):
                    raise ValueError(
                        f"deterministic fn for {q.name} must return dict, got {type(ans)}"
                    )
                answers[q.name] = ans

        return JevDecision(
            bar_ts=bar_ts,
            answers=answers,
            jev_latency_ms=self._fake_latency_ms,
            jev_input_tokens=self._fake_input_tokens,
            backend_name=self.name,
            mock=True,
            error=None,
            raw=None,
        )


# ── Real backend (Typesafe) — #219 S-397 ship-ready, gated on JEV_API_KEY ──


class TypesafeJevDecisionBackend:
    """Real `api.typesafe.ai` client for Jev multi-primitive batch.

    **Security rule (CLAUDE.md + memory): JEV_API_KEY is read from env at
    `evaluate_batch()` time, NEVER hardcoded, NEVER logged, NEVER written
    to .py / .md / .json / .env (committed).** If a future refactor accidentally
    leaks the key into a log line / test output / commit message → rotate the
    key immediately per project rule.

    Endpoint contract (best-effort based on TypeSafe blog + community SDKs):
        POST {base_url}/v1/experimental_evaluate
        Headers: Authorization: Bearer $JEV_API_KEY
                 Content-Type: application/json
        Body: {
          "state": {...},
          "questions": [
            {"name": "...", "primitive": "Choice|Score|Noul",
             "instructions": "...", "criteria": {...} | [...] | null}
          ]
        }
        Response: {
          "answers": {
            "<name>": {"choice": "...", ...} | {"score": ..., ...} | {"noul": ...}
          },
          "usage": {"input_tokens": N}
        }

    If the real schema differs, override `_request()` in a subclass or PR the
    fix here — `evaluate_batch()` MUST keep its current signature (state_payload,
    questions) so callers don't break.

    **Fail-open**: any HTTP error (4xx/5xx), timeout, or JSON parse error
    returns a JevDecision with `error=str(exc)` and answers populated with
    Noul=0.5 / Score=0 / Choice="no_edge" (safe defaults). Per the contract
    in JevDecisionBackend Protocol, the strategy keeps running.
    """

    name = "typesafe_jev_v1"

    DEFAULT_BASE_URL = "https://api.typesafe.ai"
    DEFAULT_TIMEOUT_S = 5.0
    DEFAULT_MODEL = "jev-1"  # vendor's default model id (per community SDKs)

    def __init__(
        self,
        *,
        api_key: Optional[str] = None,    # explicit override (test-only)
        base_url: Optional[str] = None,
        timeout_s: Optional[float] = None,
        model: Optional[str] = None,
    ) -> None:
        # NOTE: if `api_key` is provided, it's used as-is. Production callers
        # should leave this None and let the env-var lookup happen at call time
        # — that way key rotation only requires re-deploying with a new env var,
        # not re-deploying code.
        self._api_key_override = api_key
        self._base_url = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._timeout_s = float(timeout_s if timeout_s is not None else self.DEFAULT_TIMEOUT_S)
        self._model = model or self.DEFAULT_MODEL

    # Public surface ──────────────────────────────────────────────────────────

    def evaluate_batch(
        self,
        state_payload: Mapping[str, Any],
        questions: Sequence[JevQuestion],
    ) -> JevDecision:
        """Run one multi-primitive batch. Fail-open on any error."""
        bar_ts = str(state_payload.get("bar_ts") or "")
        if not bar_ts:
            raise ValueError(
                "state_payload 必须带 bar_ts (ISO date) —— 没有它,"
                "Jev batch 就无法对应到具体的 bar/decision log 行"
            )

        api_key = self._api_key_override or os.environ.get("JEV_API_KEY")
        if not api_key:
            # No key → fail-open with a clear error marker so 60d validation
            # can distinguish "vendor hiccup" from "not configured yet".
            return self._fail_open(bar_ts, questions,
                                   error="JEV_API_KEY not set in env")

        body = self._build_request_body(state_payload, questions)
        t0 = time.monotonic()
        try:
            response_body = self._request(api_key, body)
            latency_ms = (time.monotonic() - t0) * 1000.0
        except Exception as e:                              # noqa: BLE001
            latency_ms = (time.monotonic() - t0) * 1000.0
            log.warning(
                "JEV batch fail-open at %s after %.1fms: %s: %s",
                bar_ts, latency_ms, type(e).__name__, str(e)[:120],
            )
            return self._fail_open(bar_ts, questions,
                                   error=f"{type(e).__name__}: {str(e)[:120]}",
                                   latency_ms=latency_ms)

        try:
            answers, input_tokens = self._parse_response(response_body, questions)
        except Exception as e:                              # noqa: BLE001
            log.warning(
                "JEV batch response parse fail-open at %s: %s: %s",
                bar_ts, type(e).__name__, str(e)[:120],
            )
            return self._fail_open(bar_ts, questions,
                                   error=f"parse: {type(e).__name__}: {str(e)[:120]}",
                                   latency_ms=latency_ms)

        return JevDecision(
            bar_ts=bar_ts,
            answers=answers,
            jev_latency_ms=round(latency_ms, 3),
            jev_input_tokens=int(input_tokens),
            backend_name=self.name,
            mock=False,
            error=None,
            raw=response_body if isinstance(response_body, dict) else None,
        )

    # Internals ───────────────────────────────────────────────────────────────

    def _build_request_body(
        self,
        state_payload: Mapping[str, Any],
        questions: Sequence[JevQuestion],
    ) -> dict[str, Any]:
        """Serialize the request to TypeSafe's expected schema."""
        return {
            "model": self._model,
            "state": dict(state_payload),
            "questions": [
                {
                    "name": q.name,
                    "primitive": q.primitive,
                    "instructions": q.instructions,
                    "criteria": q.criteria,
                }
                for q in questions
            ],
        }

    def _request(self, api_key: str, body: dict[str, Any]) -> Any:
        """POST to TypeSafe. Uses httpx (already a project dep)."""
        import httpx
        url = f"{self._base_url}/v1/experimental_evaluate"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        with httpx.Client(timeout=self._timeout_s) as client:
            r = client.post(url, headers=headers, json=body)
        if r.status_code != 200:
            raise RuntimeError(
                f"HTTP {r.status_code}: {r.text[:200]}"
            )
        # Don't log the response body — it may echo back state with
        # potentially-sensitive derived features in the future.
        return r.json()

    def _parse_response(
        self,
        response_body: Any,
        questions: Sequence[JevQuestion],
    ) -> tuple[dict[str, dict[str, Any]], int]:
        """Parse the API response. Raises on schema mismatch."""
        if not isinstance(response_body, dict):
            raise ValueError(f"response is not a dict: {type(response_body)}")
        answers_raw = response_body.get("answers")
        if not isinstance(answers_raw, dict):
            raise ValueError(
                f"response['answers'] missing or not a dict: "
                f"{type(answers_raw)}"
            )
        usage = response_body.get("usage") or {}
        input_tokens = int(usage.get("input_tokens") or 0)

        # Coerce each answer to the expected primitive shape. We accept the
        # vendor's natural shape (e.g. {"choice": "x", "probabilities": {...}})
        # without rewriting — that way changes to the vendor schema surface
        # immediately here.
        answers: dict[str, dict[str, Any]] = {}
        for q in questions:
            ans = answers_raw.get(q.name)
            if not isinstance(ans, dict):
                raise ValueError(
                    f"answer for {q.name!r} missing or not a dict: {type(ans)}"
                )
            if q.primitive == "Choice" and "choice" not in ans:
                raise ValueError(
                    f"Choice answer for {q.name} missing 'choice' key: {ans}"
                )
            if q.primitive == "Score" and "score" not in ans:
                raise ValueError(
                    f"Score answer for {q.name} missing 'score' key: {ans}"
                )
            if q.primitive == "Noul" and "noul" not in ans:
                raise ValueError(
                    f"Noul answer for {q.name} missing 'noul' key: {ans}"
                )
            answers[q.name] = ans
        return answers, input_tokens

    def _fail_open(
        self,
        bar_ts: str,
        questions: Sequence[JevQuestion],
        *,
        error: str,
        latency_ms: float = 0.0,
    ) -> JevDecision:
        """Return a no-signal JevDecision when the API call fails.

        Strategy-side: no_edge Choice / Score=0 / Noul=0.5 → no L/S position
        opened, base ①/②/③ still runs (the spec_runner Pattern A ⓪ OVERRIDE
        is on `regime_ok`, not on this).
        """
        answers: dict[str, dict[str, Any]] = {}
        for q in questions:
            if q.primitive == "Choice":
                criteria = q.criteria or {}
                no_edge_key = next(
                    (k for k in criteria if "no_edge" in k.lower()),
                    next(iter(criteria), "no_edge"),
                )
                answers[q.name] = {
                    "choice": no_edge_key,
                    "probabilities": {no_edge_key: 1.0},
                    "confidence": 0.0,
                }
            elif q.primitive == "Score":
                answers[q.name] = {
                    "score": 0.0,
                    "legend": {str(c): c for c in (q.criteria or [])},
                    "probabilities": {},
                }
            else:  # Noul
                answers[q.name] = {"noul": 0.5}
        return JevDecision(
            bar_ts=bar_ts,
            answers=answers,
            jev_latency_ms=round(latency_ms, 3),
            jev_input_tokens=0,
            backend_name=self.name,
            mock=False,
            error=error,
            raw={"error": error},
        )


# ── Actor (the thing runners hold) ──────────────────────────────────────────


@dataclass
class JevDecisionActor:
    """Wraps a backend with a single `decide_batch()` method + lightweight stats.

    Mirrors `JevRegimeActor` discipline: in-memory stats for Gate 3 (frequency)
    + Gate 4 (cost), JSONL for durable record.

    NOT a Nautilus DataActor — paper track is a CLI script. The Nautilus-side
    analog lives in `src/research/nautilus/sleeve_a/jev_decision_actor.py`
    (future ship, blocked on Nautilus wiring per M-121).
    """

    backend: JevDecisionBackend
    name: str = "jev_decision_actor"
    n_calls: int = 0
    cum_latency_ms: float = 0.0
    cum_input_tokens: int = 0
    cum_n_questions: int = 0

    def decide_batch(
        self,
        state_payload: Mapping[str, Any],
        questions: Sequence[JevQuestion],
    ) -> JevDecision:
        d = self.backend.evaluate_batch(state_payload, questions)
        self.n_calls += 1
        self.cum_latency_ms += d.jev_latency_ms
        self.cum_input_tokens += d.jev_input_tokens
        self.cum_n_questions += len(questions)
        return d

    __call__ = decide_batch  # type: ignore[assignment]

    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "backend": self.backend.name,
            "n_calls": self.n_calls,
            "n_questions_per_call": (
                round(self.cum_n_questions / self.n_calls, 1)
                if self.n_calls else 0
            ),
            "cum_latency_ms": round(self.cum_latency_ms, 3),
            "avg_latency_ms": (
                round(self.cum_latency_ms / self.n_calls, 3)
                if self.n_calls else 0.0
            ),
            "cum_input_tokens": self.cum_input_tokens,
        }


# ── State payload helper ────────────────────────────────────────────────────


def build_ls_state_payload(
    *,
    bar_ts: str,
    universe: Sequence[str],
    per_symbol_features: Optional[Mapping[str, Mapping[str, Any]]] = None,
    cross_asset_features: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Build the state payload for the L/S batch.

    `per_symbol_features`: dict[symbol, dict[field, value]]. Per-symbol fields
    typically include close, mom_30, mom_60, vol_30, breadth_position.
    `cross_asset_features`: flat dict of cross-asset fields (regime, BTC
    dominance, funding_rate, etc.). Keep total field count < 50 (cardinality
    cap = 255; 5 symbols × 5 fields + 10 cross = 35 fields).

    The actual feature engineering lives in `ls_state_builder.py`. This helper
    just shapes the payload.
    """
    payload: dict[str, Any] = {
        "bar_ts": bar_ts,
        "universe": list(universe),
    }
    if per_symbol_features:
        payload["per_symbol"] = {
            str(sym): dict(feats) for sym, feats in per_symbol_features.items()
        }
    if cross_asset_features:
        payload["cross_asset"] = dict(cross_asset_features)
    return payload


__all__ = [
    "JevDecision",
    "JevQuestion",
    "JevDecisionBackend",
    "MockJevDecisionBackend",
    "TypesafeJevDecisionBackend",
    "JevDecisionActor",
    "build_ls_questions",
    "build_ls_state_payload",
]
