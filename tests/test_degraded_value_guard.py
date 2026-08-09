"""
Degraded-value guard — the shape that produced five separate bugs in one day.

THE PATTERN. A value cannot be measured, so the code substitutes something
plausible: a string, a neutral level, a majority category. The substitute is then
stored, and every downstream consumer reads it as an observation because nothing
in the value says otherwise.

  I1        max(0, min(1, nan)) == 1.0        unmeasured mcap  -> trillion-dollar asset
  S-116     exposure_cap = 1.0                layer 3 absent   -> layer 3 chose neutral
  tiers     backfill returns 0                not monitored    -> market had no data
  S-120     canonical_regime(None) -> NEUTRAL missing regime   -> observed NEUTRAL
  S-121     timeout -> "UNKNOWN" -> NEUTRAL   58 fabricated rows, once a day

WHY A GUARD AND NOT A LESSON. Four of the five were found after they had already
written data, and three were found only because the substituted value happened to
be WRONG in a visible way - S-121 surfaced because the table said NEUTRAL while the
engine said TIGHTENING. That is luck, and it runs out precisely where the damage is
worst: **a default equal to the MAJORITY value is undetectable forever.**
`trade_results.side` defaults to "LONG" and 82% of rows are LONG, so a short that
lost its side field is indistinguishable from a long - while the shorts average
-2.28% against the longs' +0.26%, meaning the failure mode quietly moves the worst
trades into the long bucket of the track record we intend to sell.

Note what this implies about verification: "zero nulls in the column" is NOT
evidence the default never fired. The default is what removed the nulls.

WHAT IS FLAGGED. A constant fallback (`x or "LIT"`, `d.get(k, "LIT")`) in a dict
value position, inside a function that also persists. Read-side rendering is
exempt by construction - a renderer legitimately needs something to show - and
that exemption is the whole reason this is scoped to writers rather than global,
where the same regex returns 296 hits and therefore nobody runs it.

Run: python3 -m tests.test_degraded_value_guard
"""
import ast
import os
import pathlib
import sys

REPO = pathlib.Path(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

# Calls that put a payload somewhere it will be read back as fact.
_WRITERS = (
    "supabase_insert_table", "supabase_upsert", "insert", "upsert",
    "_save_positions", "_save_balance", "_save_rebal_state",
    "setex", "hset", "rpush",
)

# Substitutes that a consumer cannot distinguish from a reading. `0` and `""` and
# `None` are deliberately NOT here: falsy values do not masquerade as measurements,
# and `"?"` / `"n/a"` are self-announcing. The danger is a value in the SAME domain
# as the real one.
_NEUTRAL_NUMBERS = {1.0, 0.5, 1, 100.0}
_SELF_ANNOUNCING = {"?", "n/a", "N/A", "-", "--", "", "unset", "MISSING", "NOT_MEASURED"}


def _suspect_constant(node):
    """Return a printable form if this constant could be mistaken for an observation."""
    if not isinstance(node, ast.Constant):
        return None
    v = node.value
    if isinstance(v, bool):
        return None
    if isinstance(v, str):
        return None if v.strip() in _SELF_ANNOUNCING else repr(v)
    if isinstance(v, (int, float)) and v in _NEUTRAL_NUMBERS:
        return repr(v)
    return None


def _called_names(fn: ast.AST):
    for n in ast.walk(fn):
        if isinstance(n, ast.Call):
            f = n.func
            yield f.attr if isinstance(f, ast.Attribute) else getattr(f, "id", None)


def _persists(fn: ast.AST) -> bool:
    """Direct writer call inside this function."""
    return any(name in _WRITERS for name in _called_names(fn))


def _persisting_functions(tree: ast.AST) -> set:
    """Functions that persist, directly OR by building a payload for one that does.

    The one-hop version of this check missed `_paper_position_to_row`, which
    assembles the trade_results row while `_write_closed_trade_to_supabase` does the
    insert - i.e. it missed the `side or "LONG"` case that motivated the guard. A
    scanner that only sees the function holding the insert cannot see the common
    shape where row-building is factored out, which is most of them. So propagate
    backwards through the module call graph to a fixed point.
    """
    fns = {n.name: n for n in ast.walk(tree)
           if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    persisting = {name for name, fn in fns.items() if _persists(fn)}
    changed = True
    while changed:                       # fixed point: callee of a persister persists
        changed = False
        for name, fn in fns.items():
            if name in persisting:
                continue
            for caller in persisting:
                if name in set(_called_names(fns[caller])):
                    persisting.add(name)
                    changed = True
                    break
    return persisting


# Calls that pass the value through unchanged as far as this analysis cares. The
# original scan missed `(pos.get("side") or "LONG").upper()` — the exact line that
# motivated the guard — because .upper() lifted the fallback out of dict-value
# position. A guard that any normalisation call defeats is decoration.
_TRANSPARENT = {"upper", "lower", "strip", "title", "round", "float", "int", "str"}


def _unwrap(node):
    """Strip transparent wrappers until the load-bearing expression is exposed."""
    for _ in range(8):
        if isinstance(node, ast.Call):
            fname = (node.func.attr if isinstance(node.func, ast.Attribute)
                     else getattr(node.func, "id", None))
            if fname in _TRANSPARENT:
                if isinstance(node.func, ast.Attribute):
                    node = node.func.value          # x.upper() -> x
                    continue
                if node.args:
                    node = node.args[0]             # round(x, 2) -> x
                    continue
        return node
    return node


def _fallbacks_in_payloads(fn: ast.AST):
    """Yield (lineno, key, description) for constant fallbacks in dict-value position."""
    for n in ast.walk(fn):
        if not isinstance(n, ast.Dict):
            continue
        for k, raw in zip(n.keys, n.values):
            if not (isinstance(k, ast.Constant) and isinstance(k.value, str)):
                continue
            v = _unwrap(raw)
            if isinstance(v, ast.BoolOp) and isinstance(v.op, ast.Or):
                c = _suspect_constant(v.values[-1])
                if c:
                    yield v.lineno, k.value, f"or {c}"
            if (isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute)
                    and v.func.attr == "get" and len(v.args) == 2):
                c = _suspect_constant(v.args[1])
                if c:
                    yield v.lineno, k.value, f".get(..., {c})"


def _scan(root="src"):
    out = []
    for p in sorted((REPO / root).rglob("*.py")):
        s = str(p)
        if ".venv" in s or "/research/" in s:
            continue
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        src_lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
        persisting = _persisting_functions(tree)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if fn.name not in persisting:
                continue
            for lineno, key, desc in _fallbacks_in_payloads(fn):
                line = src_lines[lineno - 1] if lineno <= len(src_lines) else ""
                if "read-side:" in line:          # explicit, justified exemption
                    continue
                out.append((str(p.relative_to(REPO)), lineno, fn.name, key, desc))
    return out


def test_no_constant_fallbacks_on_write_paths():
    """A stored field must never carry a value the reader cannot distinguish from a
    measurement. If the value is genuinely unavailable, store NULL and let the
    consumer decide - that decision belongs to the consumer, who knows what the
    absence means, not to the writer, who only knows the field was empty."""
    hits = _scan()
    assert not hits, (
        "constant fallback in a persisted payload — the reader cannot tell this "
        "from an observation:\n  " + "\n  ".join(
            f"{h[0]}:{h[1]} in {h[2]}()  key={h[3]!r}  {h[4]}" for h in hits[:20]))


def test_guard_detects_a_synthetic_offender():
    """A scanner narrowed until it is quiet is worth nothing. Prove it still fires
    on the exact shape it was built for - this is the check that failed to exist
    when the L0 class-filter scan was first written and passed for the wrong reason."""
    src = (
        "async def save_it(row):\n"
        "    payload = {'side': row.get('side') or 'LONG',\n"
        "               'regime': row.get('regime', 'NEUTRAL')}\n"
        "    await supabase_insert_table('t', [payload])\n"
    )
    fn = ast.parse(src).body[0]
    assert _persists(fn), "writer detection failed on a supabase_insert_table call"
    found = {k: d for _, k, d in _fallbacks_in_payloads(fn)}
    assert found.get("side") == "or 'LONG'", found
    assert found.get("regime") == ".get(..., 'NEUTRAL')", found


def test_guard_follows_the_payload_across_functions():
    """The motivating false negative. `_paper_position_to_row` holds the `side or
    "LONG"` default and persists nothing; the insert is one call away. Factoring the
    row builder out of the writer must not launder the fallback."""
    tree = ast.parse(
        "def to_row(pos):\n"
        "    return {'side': (pos.get('side') or 'LONG').upper()}\n"
        "async def write(pos):\n"
        "    await supabase_insert_table('trade_results', [to_row(pos)])\n"
    )
    persisting = _persisting_functions(tree)
    assert "to_row" in persisting, (
        "row builders reached from a writer must be scanned, or the guard only ever "
        "catches the inline case")
    found = {k: d for _, k, d in _fallbacks_in_payloads(tree.body[0])}
    assert found.get("side") == "or 'LONG'", (
        f"the .upper() wrapper must not hide the fallback: {found}")


def test_guard_does_not_fire_on_read_side_rendering():
    """A response builder may substitute freely: nothing is stored, and the caller
    sees the payload as a view rather than as a record. Flagging these is how a
    guard becomes noise and then becomes ignored."""
    src = (
        "def get_it(result):\n"
        "    return {'status': result.get('status', 'success'),\n"
        "            'regime': result.get('macro_regime', 'UNKNOWN')}\n"
    )
    fn = ast.parse(src).body[0]
    assert not _persists(fn), "a pure response builder must not count as a writer"


def test_self_announcing_placeholders_are_allowed():
    """'?' and '' cannot be mistaken for a grade or a regime. The rule is about
    ambiguity, not about the presence of a default - a guard that banned every
    default would be routed around within a week."""
    for lit in ("'?'", "''", "'n/a'"):
        fn = ast.parse(
            f"async def w(r):\n"
            f"    await supabase_insert_table('t', [{{'g': r.get('g') or {lit}}}])\n"
        ).body[0]
        assert not list(_fallbacks_in_payloads(fn)), f"{lit} should be permitted"


def test_majority_value_defaults_are_the_dangerous_case():
    """Pins the reasoning, because it is the part that will be argued with. A default
    that is WRONG gets caught (S-121: table said NEUTRAL, engine said TIGHTENING).
    A default equal to the majority value is never wrong-looking and so is never
    caught - which is why detection cannot be the control, and prevention must be."""
    doc = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert "majority" in doc.lower() and "undetectable" in doc.lower(), (
        "the rationale must stay in the file — a guard whose reason is only in a "
        "ledger entry gets deleted by the next person who finds it inconvenient")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = f = 0
    for t in TESTS:
        try:
            t(); print(f"  ✓ {t.__name__}"); p += 1
        except AssertionError as e:
            print(f"  ✗ {t.__name__}\n      {e}"); f += 1
    print(f"\n{'✅' if not f else '🔴'} {p}/{len(TESTS)} degraded-value checks passed")
    sys.exit(1 if f else 0)
