"""
Hyperliquid SPOT read-only adapter (UBTC / UETH).

WHY THIS MODULE EXISTS (S-600+, 2026-10-18):
    X1V (TRADE_PATH §3c) needs to size orders within 1 hour of the daily close
    and estimate slippage BEFORE entering. Hyperliquid's spot venue hosts the
    canonical UBTC / UETH pairs; getting order sizing right means (a) rounding
    to the venue's szDecimals, (b) refusing orders that fall below the venue's
    minimum notional, and (c) walking the L2 book to estimate bps-of-mid
    slippage at four reference notionals ($3k / $30k / $300k / $3M).

    Built READ-ONLY on the public info endpoint ONLY:
        POST https://api.hyperliquid.xyz/info
        {"type": "spotMeta"} | "spotMetaAndAssetCtxs" | "l2Book" | "allMids"
    No private key is touched in this module. The exchange action surface
    (orders / cancels / signing) lives behind `type: "action"` + signed
    payloads — not imported here, not called here, not stubbed in tests.

DESIGN (T-123 acceptance):
    * Pure-function core (`round_size`, `min_notional_ok`,
      `estimate_slippage_bps`, `slippage_scan`). No I/O; they take
      parsed Python data and return numbers.
    * A thin `HlSpotClient` validates the request type and hands the POST to
      `hyperliquid_collector.info_post_sync` — the repo's one Hyperliquid
      network path (S-302: fetch entry points only shrink). Tests pass in
      fixture JSON instead, so no network access during CI.
    * Currency conventions explicit: quantities are in BASE coin (UBTC /
      UETH), notionals in USDC. We never confuse the two; doing so was a
      class of bug noted in Hard Rule #9 (no fabricated numbers).
    * Slippage bps computed against the SAME mid as the user sees at
      order time, not the fill mid. If mid moves while the order is
      walking the book, the estimate is stale on arrival — that is
      intrinsic to L2 walk and is called out by `estimate_slippage_bps`.

NOT IN SCOPE:
    * Signing / order submission (`type: "action"`). Refusing to add that
      here is the explicit deliverable — see `forbidden_actions`.
    * Perp side. See `src/data/venues/registry.py` for the existing
      `hyperliquid` perp venue spec; spot is a separate adapter.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Optional


# ── Public constants ──────────────────────────────────────────────────────────
HYPERLIQUID_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_TIMEOUT_S = 20
# HL spot has a "minimum order size" of $10 USDC notional on the UI; we expose
# this as a parameter because the server has been seen accepting slightly
# smaller orders in low-liquidity pairs. Source: Hyperliquid docs as of
# 2026-10; treat as a soft floor, raise the floor at the call site if your
# strategy needs it.
DEFAULT_MIN_NOTIONAL_USDC = 10.0
# Reference notionals the X1V sleeve asks about (card acceptance).
REFERENCE_NOTIONALS_USDC = (3_000.0, 30_000.0, 300_000.0, 3_000_000.0)


# Public endpoints we will call. Anything else must be deliberate.
ALLOWED_INFO_TYPES = frozenset({
    "spotMeta",
    "spotMetaAndAssetCtxs",
    "l2Book",
    "allMids",
})


@dataclass(frozen=True)
class HlSpotToken:
    """One base/quote token as listed in `spotMeta.tokens`."""
    name: str
    index: int
    sz_decimals: int
    token_id: str          # on-chain hex address; informational, not used
    wei_decimals: int      # on-chain precision

    @classmethod
    def from_meta_entry(cls, raw: dict[str, Any]) -> "HlSpotToken":
        # HL renamed the keys at least once across SDK versions; be explicit.
        name = raw.get("name") or raw.get("token") or ""
        idx = raw.get("index")
        if idx is None:
            # `spec` in some responses has token index; fall back to scan.
            idx = -1
        return cls(
            name=name,
            index=int(idx),
            sz_decimals=int(raw.get("szDecimals", 0)),
            token_id=str(raw.get("tokenId", "")),
            wei_decimals=int(raw.get("weiDecimals", 0)),
        )


@dataclass(frozen=True)
class HlSpotPair:
    """A canonical SPOT pair: UBTC/USDC or UETH/USDC. Indexed by `universe_index`."""
    universe_index: int
    name: str                # canonical pair symbol, e.g. "@142" or "UBTC/USDC"
    base_token_index: int
    quote_token_index: int
    is_canonical: bool
    sz_decimals: int
    mark_px: Optional[float]
    mid_px: Optional[float]
    prev_day_px: Optional[float]
    day_ntl_vlm: Optional[float]


@dataclass(frozen=True)
class L2Level:
    price: float
    size: float
    n_orders: int


@dataclass(frozen=True)
class L2Book:
    coin: str                # universe pair name, e.g. "@142"
    time_ms: int
    bids: tuple[L2Level, ...]
    asks: tuple[L2Level, ...]

    @property
    def mid_px(self) -> Optional[float]:
        """Microprice (top-of-book mid). None if either side is empty."""
        if not self.bids or not self.asks:
            return None
        return (self.bids[0].price + self.asks[0].price) / 2.0

    @property
    def best_bid(self) -> Optional[float]:
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Optional[float]:
        return self.asks[0].price if self.asks else None


# ── Helper: forbidden actions ────────────────────────────────────────────────
def forbidden_actions() -> tuple[str, ...]:
    """
    The deliberate STOP-LIST for this adapter.

    Anything involving a signed action, a wallet, or sending money belongs
    outside this module. Tests call this to confirm the surface did not
    drift into `exchange.submit(...)` territory.
    """
    return (
        "order", "cancel", "batchModify", "updateLeverage", "usdClassTransfer",
        "withdraw", "vaultTransfer", "spotTransfer", "approveBuilderFee",
        "registerReferrer", "sign", "private_key", "nonce",
    )


# ── Pure-function core ────────────────────────────────────────────────────────
def round_size(qty_base: float, sz_decimals: int) -> float:
    """
    Round a base-coin quantity DOWN to the venue's szDecimals.

    HL convention: spot orders are rounded DOWN (size >= rounded is OK,
    size < rounded is rejected). Using Decimal so 0.1 + 0.2 style
    float artefacts don't push the rounded size below spec.
    """
    from decimal import Decimal, ROUND_DOWN
    if qty_base < 0:
        raise ValueError(f"qty_base must be non-negative, got {qty_base}")
    if sz_decimals < 0:
        raise ValueError(f"sz_decimals must be non-negative, got {sz_decimals}")
    q = Decimal(str(qty_base))
    quant = Decimal(1).scaleb(-sz_decimals)        # 10^-sz_decimals
    rounded = q.quantize(quant, rounding=ROUND_DOWN)
    return float(rounded)


def min_notional_ok(notional_usdc: float, min_notional_usdc: float = DEFAULT_MIN_NOTIONAL_USDC) -> bool:
    """True iff `notional_usdc >= min_notional_usdc`. NaN fails closed."""
    if notional_usdc != notional_usdc:    # NaN check
        return False
    return notional_usdc >= min_notional_usdc


def walk_book_for_qty(
    levels: Iterable[L2Level],
    qty_base: float,
    side: str,
) -> tuple[float, float]:
    """
    Walk L2 levels, fill `qty_base` base coins, return
    `(filled_qty_base, spent_or_received_quote)`.

    BUY walks the ask side (sorted ascending). SELL walks the bid side
    (sorted descending). If the book cannot fully fill the qty, returns
    whatever was drained and the caller decides what that means (a
    partial fill is a `PartialFill` below — slipping is reported as
    infinite bps, a strong "don't go" signal).

    Levels with `size <= 0` are skipped (defensive — HL has been seen
    emitting zero-size resting orders during aborts).
    """
    if side not in ("buy", "sell"):
        raise ValueError(f"side must be 'buy' or 'sell', got {side!r}")
    if qty_base <= 0:
        raise ValueError(f"qty_base must be positive, got {qty_base}")

    remaining = float(qty_base)
    spent = 0.0
    for lvl in levels:
        if lvl.size <= 0:
            continue
        if remaining <= 0:
            break
        take = min(lvl.size, remaining)
        spent += take * lvl.price
        remaining -= take
    filled = float(qty_base) - remaining
    return filled, spent


def estimate_slippage_bps(
    book: L2Book,
    side: str,
    qty_base: float,
    mid_px: Optional[float] = None,
) -> float:
    """
    Slippage in bps vs the (top-of-book) mid, positive = adverse.

    BUY: avg fill px vs mid → (avg / mid - 1) * 10_000.
    SELL: mid vs avg fill px → (mid / avg - 1) * 10_000.

    Returns math.inf if the book cannot fully fill (cleaner than NaN;
    a strategy layer can compare against a limit). Returns NaN if no
    mid is computable AND the caller did not pass one.
    """
    if mid_px is None:
        mid_px = book.mid_px
    if mid_px is None or mid_px <= 0:
        # Without a mid, bps vs mid is undefined. The caller chose this
        # by not passing `mid_px`; surface that explicitly.
        return float("nan")

    levels = book.asks if side == "buy" else book.bids
    filled, spent = walk_book_for_qty(levels, qty_base, side=side)
    if filled <= 0:
        return float("inf")
    if filled < qty_base - 1e-12:
        # Could not drain the book at the requested size → effectively
        # infinite slippage; refuse to mislead with a small finite number.
        return float("inf")
    avg = spent / filled
    if side == "buy":
        return (avg / mid_px - 1.0) * 10_000.0
    return (mid_px / avg - 1.0) * 10_000.0


def slippage_scan(
    book: L2Book,
    side: str,
    mid_px: Optional[float] = None,
    notionals_usdc: Iterable[float] = REFERENCE_NOTIONALS_USDC,
) -> dict[float, float]:
    """
    Estimate slippage at a list of reference notionals.

    Notional → qty_base = notional / mid_px (so all four points share
    the same mid-relative definition). Returns {notional: slippage_bps};
    infinity for any notional the book can't drain.
    """
    if mid_px is None:
        mid_px = book.mid_px
    if mid_px is None or mid_px <= 0:
        return {n: float("nan") for n in notionals_usdc}
    return {
        float(n): estimate_slippage_bps(
            book, side=side, qty_base=float(n) / mid_px, mid_px=mid_px
        )
        for n in notionals_usdc
    }


# ── Parsing the four official info responses ─────────────────────────────────
def parse_spot_meta(raw: dict[str, Any]) -> dict[int, HlSpotToken]:
    """Index `spotMeta.tokens` by `index` for O(1) lookup by callers."""
    out: dict[int, HlSpotToken] = {}
    for t in raw.get("tokens", []):
        tok = HlSpotToken.from_meta_entry(t)
        if tok.index >= 0:
            out[tok.index] = tok
    return out


def parse_universe(raw: dict[str, Any]) -> list[dict[str, Any]]:
    """Raw `universe` list (each entry: name, tokens=[base_idx, quote_idx], …)."""
    return list(raw.get("universe", []))


def find_pair_by_name(
    meta_raw: dict[str, Any],
    pair_name: str,
) -> Optional[dict[str, Any]]:
    """Locate the universe entry whose `name` matches exactly."""
    for u in parse_universe(meta_raw):
        if u.get("name") == pair_name:
            return u
    return None


def find_token_by_name(
    tokens: dict[int, HlSpotToken], name: str
) -> Optional[HlSpotToken]:
    """Resolve a base token (e.g. 'UBTC') from the parsed token map."""
    for t in tokens.values():
        if t.name == name:
            return t
    return None


def parse_spot_meta_and_asset_ctxs(
    meta_raw: dict[str, Any],
    ctx_raw: Any,
) -> list[HlSpotPair]:
    """
    `spotMetaAndAssetCtxs` returns `[meta, [ctx_for_universe_i]]`. Each ctx
    has `coin` (universe name), `markPx`, `midPx`, `prevDayPx`, `dayNtlVlm`.
    """
    tokens = parse_spot_meta(meta_raw)
    if not isinstance(ctx_raw, list):
        return []
    pairs: list[HlSpotPair] = []
    for i, ctx in enumerate(ctx_raw):
        if not isinstance(ctx, dict):
            continue
        coin = ctx.get("coin") or ""
        # Match to a universe entry to learn base token + canonical flag.
        u = find_pair_by_name(meta_raw, coin) or {}
        base_idx, quote_idx = (u.get("tokens") or [-1, -1])[:2]
        base_tok = tokens.get(int(base_idx)) if base_idx is not None else None
        pairs.append(HlSpotPair(
            universe_index=int(u.get("index", i)),
            name=str(coin),
            base_token_index=int(base_idx) if base_idx is not None else -1,
            quote_token_index=int(quote_idx) if quote_idx is not None else -1,
            is_canonical=bool(u.get("isCanonical", False)),
            sz_decimals=base_tok.sz_decimals if base_tok else 0,
            mark_px=_f(ctx.get("markPx")),
            mid_px=_f(ctx.get("midPx")),
            prev_day_px=_f(ctx.get("prevDayPx")),
            day_ntl_vlm=_f(ctx.get("dayNtlVlm")),
        ))
    return pairs


def parse_l2_book(raw: dict[str, Any]) -> L2Book:
    """Parse `l2Book` (one pair; coin = universe name like '@142')."""
    levels = raw.get("levels") or [[], []]
    bids_raw, asks_raw = (levels + [[], []])[:2]

    def _lvl(d: Any) -> L2Level:
        return L2Level(
            price=_f(d.get("px")) or 0.0,
            size=_f(d.get("sz")) or 0.0,
            n_orders=int(d.get("n") or 0),
        )

    return L2Book(
        coin=str(raw.get("coin", "")),
        time_ms=int(raw.get("time") or 0),
        bids=tuple(_lvl(x) for x in bids_raw),
        asks=tuple(_lvl(x) for x in asks_raw),
    )


def _f(x: Any) -> Optional[float]:
    """Forgiving float parse — None / '' / 'NaN' → None."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v


# ── Thin HTTP client (only used by tests / on-demand fetch scripts) ──────────
class HlSpotClient:
    """
    Synchronous read-only client for the four official info endpoints.

    Keep this class thin. All real logic lives in the parse_* and pure-fn
    helpers above. Tests use `HlSpotClient.from_fixture(...)` so they
    do not touch the network (Hard Rule: tests must not require internet).
    """

    def __init__(
        self,
        url: str = HYPERLIQUID_INFO_URL,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        poster: Optional[Any] = None,
    ) -> None:
        self.url = url
        self.timeout_s = timeout_s
        # Merger 10-18: the POST goes through the existing Hyperliquid client
        # instead of a private urllib call, so this adapter is not a new fetch
        # entry point (tests/test_sense_entrypoints.py, budget only shrinks).
        self._poster = poster

    # ── Network call (gated; tests skip this path entirely) ──────────────
    def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        info_type = payload.get("type")
        if info_type not in ALLOWED_INFO_TYPES:
            raise ValueError(
                f"refusing info type {info_type!r}: this client only handles "
                f"{sorted(ALLOWED_INFO_TYPES)}"
            )
        poster = self._poster
        if poster is None:
            from src.data.market.hyperliquid_collector import info_post_sync as poster
        out = poster(payload, timeout=self.timeout_s)
        # `null` is a valid HL response (e.g. l2Book of an unknown pair).
        return {} if out is None else out

    def spot_meta(self) -> dict[str, Any]:
        return self._post({"type": "spotMeta"})

    def spot_meta_and_asset_ctxs(self) -> Any:
        return self._post({"type": "spotMetaAndAssetCtxs"})

    def l2_book(self, coin: str) -> dict[str, Any]:
        return self._post({"type": "l2Book", "coin": coin})

    def all_mids(self) -> dict[str, Any]:
        return self._post({"type": "allMids"})

    # ── Fixture-driven entry point (test path) ───────────────────────────
    @classmethod
    def from_fixture(cls, fixture_dir: str | Path) -> "HlSpotFixture":
        """
        Build a no-network HlSpotFixture from JSON files in `fixture_dir`.

        The four files we expect, named exactly:
            spotMeta.json
            spotMetaAndAssetCtxs.json
            allMids.json
            l2Book_UBTC.json
            l2Book_UETH.json
        """
        return HlSpotFixture.from_dir(fixture_dir)


# ── Fixture-backed handle for tests ──────────────────────────────────────────
class HlSpotFixture:
    """Read-only bundle backed by JSON fixtures. No network access."""

    def __init__(
        self,
        spot_meta_raw: dict[str, Any],
        spot_ctx_raw: Any,
        all_mids_raw: dict[str, Any],
        books: dict[str, dict[str, Any]],
    ) -> None:
        self._spot_meta_raw = spot_meta_raw
        self._spot_ctx_raw = spot_ctx_raw
        self._all_mids_raw = all_mids_raw
        self._books = books

    @classmethod
    def from_dir(cls, fixture_dir: str | Path) -> "HlSpotFixture":
        d = Path(fixture_dir)

        def _load(name: str) -> Any:
            return json.loads((d / name).read_text())

        def _loads_optional(name: str) -> Any:
            p = d / name
            if not p.exists():
                return {}
            return json.loads(p.read_text())

        return cls(
            spot_meta_raw=_load("spotMeta.json"),
            spot_ctx_raw=_load("spotMetaAndAssetCtxs.json"),
            all_mids_raw=_load("allMids.json"),
            books={
                "UBTC": _loads_optional("l2Book_UBTC.json"),
                "UETH": _loads_optional("l2Book_UETH.json"),
            },
        )

    # ── Parsed views (mirror HlSpotClient but no I/O) ────────────────────
    def tokens(self) -> dict[int, HlSpotToken]:
        return parse_spot_meta(self._spot_meta_raw)

    def pairs(self) -> list[HlSpotPair]:
        # spotMetaAndAssetCtxs is [meta, [ctx,...]] — meta is redundant here.
        ctx_list = (
            self._spot_ctx_raw[1]
            if isinstance(self._spot_ctx_raw, list) and len(self._spot_ctx_raw) >= 2
            else []
        )
        return parse_spot_meta_and_asset_ctxs(self._spot_meta_raw, ctx_list)

    def find_pair_by_token(self, base_name: str) -> Optional[HlSpotPair]:
        """Find the canonical SPOT pair whose base token name == `base_name`."""
        tokens = self.tokens()
        target = find_token_by_name(tokens, base_name)
        if target is None:
            return None
        usdc = find_token_by_name(tokens, "USDC")
        cands = [p for p in self.pairs() if p.base_token_index == target.index]
        # 10-30:XAUT0 同时有 XAUT0/USDC(@182)与 XAUT0/USDT0(@209)—— 只认 USDC 计价的那一对,不靠排序碰运气
        for p in cands:
            if usdc is not None and p.quote_token_index == usdc.index:
                return p
        return cands[0] if cands and usdc is None else None

    def l2_book_for(self, base_name: str) -> L2Book:
        """L2Book for a UBTC / UETH pair, parsed from the matching fixture."""
        raw = self._books.get(base_name.upper())
        if not raw:
            raise KeyError(f"no fixture l2Book for base token {base_name}")
        return parse_l2_book(raw)

    def all_mids(self) -> dict[str, str]:
        """`allMids` returns `{NAME: midPx}`; both SPOT and PERP symbols."""
        return dict(self._all_mids_raw or {})

    # ── Convenience: directly answer the four X1V questions ─────────────
    def answer_x1v(
        self,
        base_name: str,
        notionals_usdc: Iterable[float] = REFERENCE_NOTIONALS_USDC,
    ) -> dict[str, Any]:
        """
        Build the exact payload T-123 acceptance asks for, for one base:

            {
              "pair": HlSpotPair,
              "sz_decimals": int,
              "min_size_base": float,         # 10 USD / mid_px (by floor)
              "min_size_rounded": float,      # szDecimals rounded
              "slippage_bps_by_notional": {notional: bps, ...},
              "is_book_drainable_at_3M": bool,
            }

        `min_size_base` is the smallest tradeable size in BASE coin that
        clears the $10 USDC floor at the current mid. If even that
        minimum cannot drain the book, the venue is effectively
        untradeable for X1V's notional ladder.
        """
        pair = self.find_pair_by_token(base_name)
        if pair is None:
            raise KeyError(f"no SPOT pair found for {base_name}")
        book = self.l2_book_for(base_name)
        mid = book.mid_px
        if mid is None or mid <= 0:
            mid = pair.mid_px

        # Minimum BASE size that clears $10 USDC at `mid`, rounded DOWN
        # to szDecimals so the rounded size is always <= raw size.
        if mid and mid > 0:
            raw_min = DEFAULT_MIN_NOTIONAL_USDC / mid
            min_size_rounded = round_size(raw_min, pair.sz_decimals)
        else:
            min_size_rounded = 0.0

        scan = slippage_scan(book, side="buy", mid_px=mid,
                             notionals_usdc=notionals_usdc)
        drainable_3m = (
            max(notionals_usdc, default=0.0) <= 0.0
            or estimate_slippage_bps(book, side="buy",
                                     qty_base=float(max(notionals_usdc)) / (mid or 1.0),
                                     mid_px=mid) != float("inf")
        )
        return {
            "pair": pair,
            "sz_decimals": pair.sz_decimals,
            "min_size_base_raw": (DEFAULT_MIN_NOTIONAL_USDC / mid) if (mid and mid > 0) else None,
            "min_size_base": min_size_rounded,
            "slippage_bps_by_notional": scan,
            "is_book_drainable_at_max_notional": bool(drainable_3m),
        }


__all__ = [
    "HYPERLIQUID_INFO_URL",
    "DEFAULT_TIMEOUT_S",
    "DEFAULT_MIN_NOTIONAL_USDC",
    "REFERENCE_NOTIONALS_USDC",
    "ALLOWED_INFO_TYPES",
    "HlSpotToken",
    "HlSpotPair",
    "L2Level",
    "L2Book",
    "HlSpotClient",
    "HlSpotFixture",
    "forbidden_actions",
    "round_size",
    "min_notional_ok",
    "walk_book_for_qty",
    "estimate_slippage_bps",
    "slippage_scan",
    "parse_spot_meta",
    "parse_spot_meta_and_asset_ctxs",
    "parse_l2_book",
    "find_pair_by_name",
    "find_token_by_name",
]
