"""The scheduled writer `asset_embeddings` never had (S-220).

MEASURED 2026-08-24: 72 rows, last written 2026-07-24, **31 days stale**. And
that is not a failure — it is the designed behaviour, which is worse. There was
no writer on a schedule at all:

  · embeddings were produced as a SIDE EFFECT of the CIS cycle, inside one broad
    `except Exception` that degrades to a log line (`rebuild_asset_vectors`'
    own docstring says so, S-144);
  · `/internal/asset-vectors/rebuild` exists but is a MANUAL trigger;
  · `main.py` scheduled nothing.

So the substrate MEMORY.md calls 「几何基底」 was a snapshot of one day in July,
and every consumer kept reading rows — just old ones — so nothing errored.

WHY THE REBUILD LIVES HERE AND NOT IN THE ROUTER. The endpoint had the only copy
of the logic. Adding a loop that re-implemented it would have produced two
versions of one rule, which this session already paid for once (two prompts, two
template generators, two mark-coverage guards). One function; the endpoint and
the loop both call it.

WHAT THIS LOOP REFUSES TO DO.

  · NO PARTIAL WRITE ON A THIN UNIVERSE. Below `MIN_UNIVERSE` it returns without
    writing. S-190: `deep_panel_collector`'s floor annotated the return value
    while the write went ahead anyway, so a 1-of-262 run still made
    `max(trade_date)` read as current.
  · NO SWALLOWED FAILURE. The result is returned AND recorded, because a loop
    whose only failure channel is a log line is the exact thing that produced
    the 31 days. `vdb_health` is the independent observer — the alarm does not
    live inside the thing that breaks (S-188).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

_log = logging.getLogger("embedding_loop")

#: Daily. The substrate describes a market state; a weekly vector would be
#: describing a different market than the one the consumer is asking about.
INTERVAL_S = 24 * 3600

#: Below this many embeddable assets, do not write. The panel runs 43–58; a run
#: that produces a handful means the universe call degraded, and overwriting a
#: complete history with a partial one is not a smaller update, it is a worse one.
MIN_UNIVERSE = 20

#: One run's ceiling. A rebuild that hangs holds no lock, but a loop that never
#: returns also never reports, and "never reported" reads identically to
#: "reported healthy" in a log-shaped world.
BUDGET_S = 180.0


@dataclass
class RebuildResult:
    ok: bool
    written: int = 0
    reason: str = ""
    schema_version: int | None = None
    dims: int | None = None
    failed_assets: list[str] = field(default_factory=list)
    elapsed_s: float = 0.0

    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "status": "ok" if self.ok else "degraded",
            "written": self.written,
            "schema_version": self.schema_version,
            "dims": self.dims,
            "n_failed": len(self.failed_assets),
            "failed_assets": self.failed_assets[:10],
            "elapsed_s": round(self.elapsed_s, 2),
        }
        if not self.ok:
            out["reason"] = self.reason or "unknown"
        # Stated because a rebuild that wrote 58 rows and a rebuild that wrote 58
        # rows OF THE WRONG SHAPE look identical in a row count.
        out["verify"] = ("select schema_version, dims, count(*) from asset_embeddings "
                         "where superseded_reason is null group by 1,2")
        return out


async def rebuild_once() -> RebuildResult:
    """Re-embed the live universe at the CURRENT schema version. Never raises."""
    started = datetime.now(timezone.utc)

    def _elapsed() -> float:
        return (datetime.now(timezone.utc) - started).total_seconds()

    try:
        from src.data.vector.embedder import SCHEMA_VERSION, generate_embedding
        from src.data.vector.pgvector_store import upsert_embeddings
    except Exception as e:                                        # noqa: BLE001
        return RebuildResult(False, reason=f"import failed: {type(e).__name__}: {e}",
                             elapsed_s=_elapsed())

    try:
        from src.data.cis.cis_provider import calculate_cis_universe
        uni = (await calculate_cis_universe()).get("universe") or []
    except Exception as e:                                        # noqa: BLE001
        return RebuildResult(False, reason=f"universe unavailable: {str(e)[:160]}",
                             elapsed_s=_elapsed())

    if len(uni) < MIN_UNIVERSE:
        # Return BEFORE the write. See the module docstring — a floor that only
        # annotates the return value is not a floor.
        return RebuildResult(
            False, reason=f"universe has {len(uni)} assets, below MIN_UNIVERSE "
                          f"({MIN_UNIVERSE}) — refusing to overwrite a complete "
                          f"history with a partial one",
            elapsed_s=_elapsed())

    embeddings: dict[str, list[float]] = {}
    failed: list[str] = []
    regime = None
    for a in uni:
        sym = str(a.get("symbol") or "").upper()
        if not sym:
            continue
        regime = regime or a.get("macro_regime")
        try:
            embeddings[sym] = generate_embedding(a)
        except Exception as e:            # per-asset, never abort the batch
            failed.append(f"{sym}:{str(e)[:60]}")

    if len(embeddings) < MIN_UNIVERSE:
        return RebuildResult(
            False, reason=f"embedder produced {len(embeddings)} of {len(uni)} "
                          f"(below MIN_UNIVERSE) — not writing",
            failed_assets=failed, elapsed_s=_elapsed())

    ameta = {str(a.get("symbol")).upper(): {"asset_class": a.get("asset_class")}
             for a in uni if a.get("symbol")}
    try:
        ok = upsert_embeddings(embeddings, asset_meta=ameta, macro_regime=regime)
    except Exception as e:                                        # noqa: BLE001
        return RebuildResult(False, reason=f"write raised: {type(e).__name__}: {e}",
                             failed_assets=failed, elapsed_s=_elapsed())

    if not ok:
        return RebuildResult(False, reason="upsert_embeddings returned False",
                             failed_assets=failed, elapsed_s=_elapsed())

    return RebuildResult(
        True, written=len(embeddings), schema_version=SCHEMA_VERSION,
        dims=len(next(iter(embeddings.values()))),
        failed_assets=failed, elapsed_s=_elapsed())
