"""Secret scan: no Supabase service-role or secret key may sit in a tracked file or in a pushed commit.

Why (2026-10-20): a lane wrote the service_role JWT into a research script, split across three string
literals, and pushed it to a branch of this PUBLIC repo. The same day we found GET /api/v1/auth/config
had been returning SUPABASE_KEY (service_role on Railway) since 2026-03-26. Both bypass RLS.

Patterns are built at runtime so this file never contains a match for itself:
  - the base64 / base64url encodings of `service_role` at all three byte alignments. They sit inside any
    service_role JWT payload, and they survive the key being split across string literals unless a split
    falls inside those ~14 characters;
  - `sb_secret_…` (new-style secret keys), `sbp_…` (Supabase personal access tokens), and real-length
    `sb_publishable_…` keys (anon reads research tables, so the publishable key is not public for us);
  - any whole JWT whose payload role is not `anon` (working-tree mode only; needs decoding).

Usage:
  python3 scripts/secret_scan.py                tracked files in the working tree (CI / preflight)
  python3 scripts/secret_scan.py --rev <sha>    the tree of a commit (pre-push hook)
Exit 1 with `path:line` for each hit; key material is never printed.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 3_000_000


def b64_alignments(word: str) -> list[str]:
    """Substrings that appear in ANY base64(url) encoding containing `word`, at each of the 3 alignments."""
    raw = word.encode()
    out: set[str] = set()
    for pad in range(3):
        enc = base64.b64encode(b"\0" * pad + raw + b"\0\0\0").decode()
        lo = -(-8 * pad // 6)
        hi = (8 * (pad + len(raw)) - 6) // 6
        frag = enc[lo:hi + 1]
        out.add(frag)
        out.add(frag.replace("+", "-").replace("/", "_"))
    return sorted(out)


ROLE_FRAGMENTS = b64_alignments("service_role") + b64_alignments("supabase_admin")
#: publishable 也算:anon 能读研究表(2026-10-20),而那把 key 自 06-19 起写在公开的 docs/SUPABASE_SETUP.md 里。
#: 只认长度像真 key 的(前缀后 ≥ 20 位),测试里的 sb_publishable_abc123 这类假值不算。
TOKEN_RES = [re.compile(r"sb_" + r"secret_[A-Za-z0-9_\-]{8,}"), re.compile(r"\bsb" + r"p_[0-9a-f]{40}\b"),
             re.compile(r"sb_" + r"publishable_[A-Za-z0-9_\-]{20,}")]
JWT_RE = re.compile(r"eyJ[A-Za-z0-9_\-]{8,}\.(eyJ[A-Za-z0-9_\-]{8,})\.[A-Za-z0-9_\-]{8,}")


def _jwt_role(payload_b64: str) -> str | None:
    try:
        pad = payload_b64 + "=" * (-len(payload_b64) % 4)
        return json.loads(base64.urlsafe_b64decode(pad)).get("role")
    except Exception:                                                # noqa: BLE001
        return None


def scan_text(text: str) -> list[tuple[int, str]]:
    """Pure. → [(line_no, reason)]. Reasons name the kind of hit, never the value."""
    hits: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), 1):
        if any(f in line for f in ROLE_FRAGMENTS):
            hits.append((i, "service_role / admin JWT fragment"))
        for rx in TOKEN_RES:
            if rx.search(line):
                hits.append((i, "Supabase secret / personal token"))
        for m in JWT_RE.finditer(line):
            role = _jwt_role(m.group(1))
            if role not in (None, "anon"):
                hits.append((i, f"JWT with role={role}"))
    if not hits:
        # A key split across adjacent string literals ("abc"\n    "def", or "abc" + "def"): glue them back.
        joined = _SPLIT_RE.sub("", text)
        if joined != text and (any(f in joined for f in ROLE_FRAGMENTS)
                               or any(_jwt_role(m.group(1)) not in (None, "anon") for m in JWT_RE.finditer(joined))):
            hits.append((0, "service_role / admin JWT split across string literals"))
    return hits


_SPLIT_RE = re.compile(r"[\"']\s*\+?\s*\\?\n\s*[\"']|[\"']\s*\+\s*[\"']")


def tracked_files() -> list[Path]:
    r = subprocess.run(["git", "--no-optional-locks", "ls-files", "-z"], cwd=ROOT, capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(f"git ls-files failed: {r.stderr.decode()[:200]}")
    return [ROOT / p for p in r.stdout.decode().split("\0") if p]


def scan_tree() -> list[str]:
    out: list[str] = []
    for p in tracked_files():
        try:
            if not p.is_file() or p.stat().st_size > MAX_BYTES:
                continue
            blob = p.read_bytes()
        except OSError:
            continue
        if b"\0" in blob[:8192]:
            continue
        for line, why in scan_text(blob.decode("utf-8", "replace")):
            out.append(f"{p.relative_to(ROOT)}:{line}  {why}")
    return out


def _git_grep(args: list[str], rev: str) -> list[list[str]]:
    """git grep exits 0 = matches, 1 = none, anything else = it did not look (bad rev ...) ⇒ raise, never 'clean'."""
    r = subprocess.run(["git", "--no-optional-locks", "grep", "-I", "-n", *args, rev, "--"], cwd=ROOT,
                       capture_output=True)
    if r.returncode not in (0, 1):
        raise RuntimeError(f"git grep on {rev} failed ({r.returncode}): {r.stderr.decode()[:200]}")
    return [ln.split(":", 3) for ln in r.stdout.decode("utf-8", "replace").splitlines()]


def scan_rev(rev: str) -> list[str]:
    pats: list[str] = []
    for f in ROLE_FRAGMENTS:
        pats += ["-e", f]
    out = [f"{h[1]}:{h[2]}  service_role / admin JWT fragment" for h in _git_grep(["-F", *pats], rev) if len(h) >= 3]
    for rx in TOKEN_RES:
        out += [f"{h[1]}:{h[2]}  Supabase secret / personal token"
                for h in _git_grep(["-P", rx.pattern], rev) if len(h) >= 3]
    return out


def main(argv: list[str]) -> int:
    hits = scan_rev(argv[argv.index("--rev") + 1]) if "--rev" in argv else scan_tree()
    if hits:
        print("✗ secret scan: key material in the tree — remove it, read the key from the environment, "
              "and rotate the key if it was ever pushed:")
        for h in hits[:50]:
            print("  " + h)
        return 1
    print("✓ secret scan: clean")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
