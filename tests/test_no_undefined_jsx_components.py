"""
Undefined-component guard for JSX — the Python guard's missing half (S-171).

INCIDENT, 2026-08-18. Clicking "Asset Radar" in the sidebar produced a blank
page with the sidebar gone. Console:

    ReferenceError: AssetRadar is not defined
      at app-CdDDzl0s.js:104

`App.jsx:390` rendered `<AssetRadar onNavigate={navigate} />`, and App.jsx never
imported it. The import was lost in 227edcd (App.jsx 1046 -> 445 lines); the
same split dropped `DiagnoseHome`, which WAS noticed and fixed in e9c5b4d. One
of the two was caught by a human reading a diff. The other shipped.

WHY EVERY EXISTING GATE MISSED IT:

  · the BUILD stayed green — CISContent.jsx:17 lazy-imports the same component
    for its own tab, so Vite emitted the AssetRadar chunk and warned about
    nothing. **A module referenced somewhere is not a module in scope here**,
    the same distinction as "declared in a .sql file" vs "exists in the
    database" (S-166).
  · SectionErrorBoundary (added e9c5b4d) could not catch it. The name resolves
    while App itself renders, which is above every boundary inside App — so the
    whole tree unmounted instead of one section degrading.
  · tests/test_no_undefined_names.py is PYTHON ONLY. Its founding incident was
    `name 'market_cap' is not defined` silently killing T2. Identical shape, and
    the guard's scope stopped at the language boundary while the codebase did not.
  · a route-level smoke test would not have helped either: the crash needs a
    CLICK. `cis.radar` renders only after the user selects it.

So the check is static, and it is on the source rather than the bundle: by the
time it is a bundle, the evidence (which names were in scope in which module) has
been minified away.

DELIBERATELY CONSERVATIVE. It only flags a capitalised `<Component`, only when
the name is defined NOWHERE in the file, and it ignores member expressions
(`<Foo.Bar>`), lowercase tags and fragments. A JSX guard with false positives
gets muted, and a muted guard is worse than none — it also occupies the slot a
real one would have filled (S-167).

Run: python3 -m tests.test_no_undefined_jsx_components
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT))

_SRC = _ROOT / "dashboard" / "src"

# `<Foo` / `<Foo.Bar` — capitalised opening tags only. Lowercase is a DOM tag.
_USE = re.compile(r"<([A-Z][A-Za-z0-9_]*)(\.[A-Za-z0-9_]+)?[\s/>]")

# Every way a name can enter module scope.
_DEFS = (
    re.compile(r"^\s*import\s+([A-Za-z0-9_]+)\s*(?:,|from)", re.M),          # default
    re.compile(r"^\s*import\s+.*?\{([^}]*)\}", re.M | re.S),                  # named
    re.compile(r"^\s*import\s+\*\s+as\s+([A-Za-z0-9_]+)", re.M),              # namespace
    # Declarations are NOT anchored to line start. The first version used `^\s*`
    # and missed `const B` when it followed a `;` on the same line — caught by
    # this file's own negative control rather than in review. Anchoring made the
    # guard narrower than the language, which is how a checker starts reporting
    # real code as broken. Strings are stripped before this runs, so an
    # unanchored match cannot pick a name out of a literal.
    re.compile(r"\b(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*="),
    # `export default function Foo` — the first version omitted `default` and
    # flagged agent.jsx's own default export as undefined.
    re.compile(r"\b(?:export\s+(?:default\s+)?)?(?:async\s+)?function\s+([A-Za-z0-9_]+)"),
    # Destructured params: `({ Icon, children }) =>` and `function f({ A, B })`.
    # IntelligencePage.jsx renders `<Icon size={11} />` where Icon is a PROP.
    re.compile(r"\(\s*\{([^}]*)\}\s*\)\s*(?:=>|\{)", re.S),
    re.compile(r"\b(?:export\s+)?class\s+([A-Za-z0-9_]+)"),
    re.compile(r"\b(?:export\s+)?let\s+([A-Za-z0-9_]+)\s*="),
)

# Provided by the runtime or the JSX transform, never imported explicitly.
_AMBIENT = {"Fragment", "Suspense", "StrictMode", "Component", "Profiler",
            "Math", "Object", "Array", "JSON", "Date", "Promise", "Error",
            "Number", "String", "Boolean", "Map", "Set", "React"}

_FAILURES: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    if cond:
        print(f"  ✓ {name}")
    else:
        print(f"  ✗ {name} :: {detail}")
        _FAILURES.append(name)




def used_components(text: str) -> set[str]:
    return {m.group(1) for m in _USE.finditer(text) if not m.group(2)}


def undefined_in(raw: str) -> set[str]:
    """Names used as `<Component>` that appear NOWHERE ELSE in the file.

    ── WHY THIS AND NOT SOMETHING CLEVERER ──────────────────────────────────
    Three earlier attempts, all mine, all worse:

      1. regex for declarations, comments stripped first  → a trailing
         `// e.g. <WalletConnect />` read as a real reference.
      2. strings stripped first                           → an apostrophe in
         prose (`don't`) opened a fake literal that swallowed `const FlowStep`
         and `const Stat`, so the guard reported two correctly-declared
         components as undefined.
      3. hand-written single-pass tokenizer               → apostrophes inside
         JSX TEXT (`<p>don't</p>`) are not string quotes, and it ate them too.

    ESLint is the right tool and was checked before giving up on it: this
    project has eslint 9 configured, and `no-undef` does NOT flag
    `<AssetRadar />` — measured, exit 0 on a probe file. `react/jsx-no-undef`
    would, and it lives in `eslint-plugin-react`, which is not installed.
    **Adding that plugin is the correct long-term fix and is written down as
    such**; it needs an npm install this sandbox will not do.

    So the criterion drops to something that needs no parsing at all: does the
    name occur anywhere in the file OTHER than as an opening tag? An import, a
    const, a function, a prop destructure — any of them puts the name on
    another line. If the ONLY occurrences are `<Name`, nothing can have
    defined it.

    That is exactly the failure mode being guarded: an import deleted wholesale
    by a file split. App.jsx contained the string "AssetRadar" precisely once,
    as `<AssetRadar onNavigate={navigate} />`.

    KNOWN BLIND SPOT, stated rather than hidden: a component whose name also
    appears in a comment is invisible to this check. That is a deliberate trade
    — false negatives leave a bug findable, false positives get the guard muted
    and then it protects nothing (S-167).
    """
    # Comments are removed FOR COUNTING ONLY, with the minimum rule that works:
    # `//` to end of line unless preceded by `:` (which spares `https://`), plus
    # block comments. This is not tokenizing — a name that survives only inside a
    # comment now disappears from BOTH counts, so it is silently skipped rather
    # than falsely flagged. The error is pushed to the safe side on purpose.
    text = re.sub(r"/\*.*?\*/", " ", raw, flags=re.S)
    text = re.sub(r"(?<!:)//[^\n]*", " ", text)

    problems: set[str] = set()
    for name in used_components(text):
        as_tag = len(re.findall(rf"<{name}\b", text))
        anywhere = len(re.findall(rf"\b{name}\b", text))
        if anywhere <= as_tag and name not in _AMBIENT:
            problems.add(name)
    return problems


def test_every_jsx_component_used_is_in_scope() -> None:
    if not _SRC.is_dir():
        check("dashboard/src present", False, f"{_SRC} missing")
        return
    problems: list[str] = []
    n_files = 0
    for f in sorted(_SRC.rglob("*.jsx")):
        n_files += 1
        raw = f.read_text(encoding="utf-8", errors="replace")
        for name in sorted(undefined_in(raw)):
            line = next((i + 1 for i, l in enumerate(raw.splitlines())
                         if re.search(rf"<{name}[\s/>]", l)), "?")
            problems.append(f"{f.relative_to(_ROOT)}:{line}  <{name}> is not in scope")
    check(f"every <Component> across {n_files} .jsx files resolves", not problems,
          "\n      ".join(problems[:10]) +
          "\n      This is a blank page at runtime, not a build error: Vite emits "
          "the chunk if ANY module imports it, and React unmounts the whole tree "
          "when the name lookup fails above an error boundary.")


def test_the_guard_actually_catches_the_2026_08_18_shape() -> None:
    """A negative control. The guard must fail on the exact pattern that shipped,
    or it is decoration — and this repo has shipped decoration that read like a
    fallback before (S-160's try/except around a call that cannot raise)."""
    broken = 'import React from "react";\nexport default function A(){ return <AssetRadar x={1} />; }'
    fixed = ('import React from "react";\n'
             'const AssetRadar = lazy(() => import("./AssetRadar"));\n'
             'export default function A(){ return <AssetRadar x={1} />; }')
    check("flags a component used but never defined",
          "AssetRadar" in undefined_in(broken),
          "the guard cannot see the bug it was written for")
    check("does not flag it once the lazy import exists",
          "AssetRadar" not in undefined_in(fixed), "")


def test_it_does_not_fire_on_things_that_are_not_bugs() -> None:
    """False positives get a guard muted, and a muted guard occupies the slot a
    real one would have filled."""
    cases = [
        ('import { Foo } from "x";  <Foo />', "named import"),
        ('import Bar from "x";  <Bar />', "default import"),
        ('import * as NS from "x";  <NS.Thing />', "member expression"),
        ('const Baz = () => null;  <Baz />', "const in file"),
        ('function Qux(){}  <Qux />', "function in file"),
        ('<div />  <span />', "lowercase DOM tags"),
        ('<>  </>', "fragment shorthand"),
        ('// historic: <Missing /> used to crash here', "component named in a comment"),
        # The three the first version got wrong, pinned so they stay right.
        ('export default function AgentPage(){}  <AgentPage />', "export default function"),
        ('const L = ({ Icon }) => <Icon size={11} />', "destructured prop as component"),
        ('const a = 1;   // optional JSX, e.g. <WalletConnect />', "TRAILING comment"),
        ('const u = "https://x.com//y";  const B = () => null;  <B />', "// inside a string"),
    ]
    for src, label in cases:
        check(f"no false positive: {label}", not undefined_in(src),
              f"flagged {undefined_in(src)}")


def test_the_python_half_still_exists() -> None:
    """These two are one guard split across two languages. If the Python half is
    deleted, this docstring's cross-reference becomes a lie and the other half of
    the class goes unwatched."""
    check("tests/test_no_undefined_names.py present",
          (_ROOT / "tests/test_no_undefined_names.py").is_file(),
          "the Python half caught 'market_cap is not defined' killing T2; same "
          "class, other language")


if __name__ == "__main__":
    print("── every <Component> used in .jsx must be in scope (S-171) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED: {_FAILURES}")
        sys.exit(1)
    print("\n✅ no undefined JSX component references")
