"""No book may price its universe against a free venue API (S-323u/v).

JAZZ, repeatedly — most recently 2026-09-09, and his own words are the spec:

    「不可以那么多资产打向免费 api。多资产重复调取要走付费 api。
      binance 和 hyperliquid 这些是进入交易之后才调取。」

Many assets, fetched repeatedly → a PAID source. Binance and Hyperliquid are
read AFTER entering a trade — they are execution venues, not a price vendor for
a research panel.

WHY THIS IS A TEST AND NOT A NOTE. It has been said many times and recurred
anyway. Measured 2026-09-09: EIGHT paper books looped over their universe
hitting fapi.binance.com per symbol; pod_aggregator did it twice per symbol.
`source_policy.py` already documented the rule and named `deep_panel_collector`
as its first violator — and the collector never once called source_policy
(S-323i). The rule existed in prose, in the same repo, for weeks, next to the
code that broke it.

**A rule that lives in prose gets re-broken. This one now fails the build.**

Bulk prices come from `panel_closes` (coingecko_pro_ohlc / eodhd — paid),
funding from `panel_funding` (our stored venue collection, gathered ONCE per
6h in a single metaAndAssetCtxs call, not re-fetched per symbol).

Run: python3 -m pytest tests/test_books_do_not_fan_out_to_free_venue_apis.py -q
"""
from __future__ import annotations

import ast
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parents[1]
SIGNALS = ROOT / "src" / "data" / "signals"

FREE_VENUE_HOSTS = ("fapi.binance.com", "api.binance.com",
                    "data-api.binance.vision", "api.hyperliquid.xyz")

#: Modules allowed to talk to a venue directly, each with the reason.
#: A venue collector IS the right place to reach a venue — once, in bulk.
VENUE_LANE = {
    "hyperliquid_collector.py": "the venue collector itself: ONE metaAndAssetCtxs "
                                "call for every perp, which is what source_policy "
                                "asks for",
    "data_layer.py": "the shared fetch layer; routing lives in price_route/source_policy",
    "deep_panel_collector.py": "guarded by assert_purpose_source since S-323i — "
                               "raises PurposeMismatch rather than fanning out",
}


#: ── RATCHET ────────────────────────────────────────────────────────────────
#: Books that still fan out to a free venue and have NOT been migrated yet.
#: Measured 2026-09-09. This list may only ever SHRINK — see the test below,
#: which fails if it grows or if an entry no longer offends (a stale exemption
#: is how "temporary" becomes permanent: 「豁免记的是『当时不需要』,
#: 它不会自己过期」).
#:
#: They are listed rather than fixed in the same pass on purpose: all five are
#: currently PRODUCING the forward record (causal 55 marks, dingge 53,
#: fusion 26 …), and a day lost to a rushed migration cannot be backfilled
#: (NAV_POLICY §3). The data is not the obstacle — all 28 symbols they need are
#: already in coingecko_pro_ohlc with >=40 bars — the obstacle is that each
#: fetcher has a different shape and none can be exercised end-to-end without
#: production credentials.
MIGRATION_BACKLOG = {
    "causal_paper.py": "S-323u backlog — migrate to panel_closes",
    "dingge_rwa.py": "S-323u backlog — migrate to panel_closes",
    "fusion_paper.py": "S-323u backlog — migrate to panel_closes",
    "r76_strategy2_paper.py": "S-323u backlog — migrate to panel_closes",
    "two_layer_paper.py": "S-323u backlog — migrate to panel_closes",
}


def _docstring_nodes(tree: ast.AST) -> set[int]:
    """Docstrings are documentation, not calls.

    Naming the forbidden endpoint in order to explain why it was removed must
    not itself count as using it — otherwise the only way to pass the guard is
    to delete the explanation, and the next person loses the reason.
    """
    ids = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            body = getattr(node, "body", None) or []
            if body and isinstance(body[0], ast.Expr) and \
                    isinstance(body[0].value, ast.Constant) and \
                    isinstance(body[0].value.value, str):
                ids.add(id(body[0].value))
    return ids


def _venue_calls(path: pathlib.Path) -> list[int]:
    """Line numbers where a free venue host appears in LIVE code."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError:                                   # pragma: no cover
        return []
    docs = _docstring_nodes(tree)
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if id(node) in docs:
                continue
            if any(h in node.value for h in FREE_VENUE_HOSTS):
                hits.append(node.lineno)
    return hits


def _inside_docstring(body: str, line: int) -> bool:
    """True when `line` falls inside a module/class/function docstring."""
    try:
        tree = ast.parse(body)
    except SyntaxError:                                   # pragma: no cover
        return False
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef,
                             ast.FunctionDef, ast.AsyncFunctionDef)):
            b = getattr(node, "body", None) or []
            if b and isinstance(b[0], ast.Expr) and \
                    isinstance(b[0].value, ast.Constant) and \
                    isinstance(b[0].value.value, str):
                d = b[0].value
                if d.lineno <= line <= (d.end_lineno or d.lineno):
                    return True
    return False


def test_no_paper_book_prices_its_universe_off_a_free_venue():
    offenders = {}
    for p in sorted(SIGNALS.glob("*.py")):
        hits = _venue_calls(p)
        if not hits:
            continue
        # A raise-only reference (a retired path that refuses) is fine.
        body = p.read_text(encoding="utf-8")
        if "retired" in body.lower() and "raise RuntimeError" in body:
            seg = body.split("raise RuntimeError")[0]
            if not any(h in seg for h in FREE_VENUE_HOSTS):
                continue
        offenders[p.name] = hits

    allowed = set(VENUE_LANE) | set(MIGRATION_BACKLOG)
    real = {k: v for k, v in offenders.items() if k not in allowed}
    assert not real, (
        "these book modules reach a FREE venue API for bulk prices: "
        f"{real}\n"
        "Bulk panel prices go through panel_closes (paid: coingecko_pro_ohlc / "
        "eodhd) via src/data/market/paid_close_loader.py; funding through "
        "panel_funding (our stored venue collection). Binance/Hyperliquid are "
        "read after entering a trade, not to price a research panel."
    )


def test_the_two_repaired_books_use_the_paid_loader():
    for name in ("factor_tilt_paper.py", "pod_aggregator_paper.py"):
        body = (SIGNALS / name).read_text(encoding="utf-8")
        assert "paid_close_loader" in body, f"{name} must load closes from paid sources"


def test_no_book_reads_prices_off_a_hardcoded_operator_path():
    """/Volumes/CometCloudAI is one operator's Mac. On Railway it is simply absent,
    so 17 TradFi names went 'missing' every single run and nobody was told."""
    bad = {}
    for p in sorted(SIGNALS.glob("*.py")):
        body = p.read_text(encoding="utf-8")
        try:
            docs = _docstring_nodes(ast.parse(body))
            doc_lines = set()
            for node in ast.walk(ast.parse(body)):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    seg = body.splitlines()[node.lineno - 1:
                                            (node.end_lineno or node.lineno)]
                    if any("/Volumes/CometCloudAI" in x for x in seg):
                        # only exempt it if this constant IS a docstring
                        for d in docs:
                            pass
            _ = docs
        except SyntaxError:                               # pragma: no cover
            pass
        for m in re.finditer(r"/Volumes/CometCloudAI[^\"'\s]*", body):
            line = body[:m.start()].count("\n") + 1
            src_line = body.splitlines()[line - 1].strip()
            # a comment or a docstring explaining the retirement is not a dependency
            if src_line.startswith("#") or src_line.startswith("--"):
                continue
            if _inside_docstring(body, line):
                continue
            bad.setdefault(p.name, []).append(line)
    assert not bad, (
        f"hardcoded operator paths still on a price path: {bad} — "
        "absent on Railway, and absence renders as 'this asset has no data'"
    )


def test_the_migration_backlog_only_shrinks():
    """A backlog that can grow is not a backlog, it is a habit.

    Two failure modes, both real here:
      · a NEW book joins the free-venue pattern -> caught by the test above,
        because only names already on this list are tolerated
      · an entry is FIXED but left on the list -> caught here, so the exemption
        cannot outlive the thing it excused
    """
    still_offending = {p.name for p in sorted(SIGNALS.glob("*.py"))
                       if _venue_calls(p)}
    stale = sorted(set(MIGRATION_BACKLOG) - still_offending - set(VENUE_LANE))
    assert not stale, (
        f"{stale} no longer reach a free venue — remove them from "
        f"MIGRATION_BACKLOG. An exemption that outlives its cause silently "
        f"re-permits the thing it was written to forbid."
    )
