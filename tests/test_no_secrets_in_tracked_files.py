"""S-502:仓库是 public —— 被跟踪的文件里不许有任何 key。

怎么发现的:S-501 改写历史前扫全部 5,973 个历史 blob,`run_reconstruction.command` 在 **HEAD** 上
把一把 CoinGecko key 写成了环境变量的默认值(`${COINGECKO_API_KEY:-CG-…}`),05-03 起公开。
06-25 那次「anon-key removal」删了 Supabase anon key,却留下了这把 —— 那次清理是按一种 key 找的,
不是按「任何 key」找的。

Supabase anon JWT 例外:它按设计就是公开的(浏览器里也有),RLS 才是权限边界(S-167)。
service_role JWT 不例外。输出只打印路径和类型,**永不打印 key 本身**。
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

PATTERNS = {
    "coingecko": re.compile(rb"\bCG-[A-Za-z0-9]{20,}\b"),
    "anthropic": re.compile(rb"\bsk-ant-[A-Za-z0-9_-]{20,}"),
    "openai": re.compile(rb"\bsk-(?:proj-)?[A-Za-z0-9]{32,}"),
    "github": re.compile(rb"\b(?:ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{30,}"),
    "aws": re.compile(rb"\bAKIA[0-9A-Z]{16}\b"),
    "telegram": re.compile(rb"\b\d{8,10}:AA[A-Za-z0-9_-]{33}\b"),
    "private_key": re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "postgres_password": re.compile(rb"postgres(?:ql)?://[^\s:'\"/]+:[^\s@'\"]{8,}@"),
}
JWT = re.compile(rb"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}")
PUBLIC_JWT_ROLES = {"anon"}


def _jwt_role(tok: bytes) -> str:
    try:
        payload = tok.split(b".")[1]
        payload += b"=" * (-len(payload) % 4)
        return str(json.loads(base64.urlsafe_b64decode(payload)).get("role") or "?")
    except Exception:  # noqa: BLE001 — 解不开的 JWT 当作非公开处理
        return "undecodable"


def scan(data: bytes) -> list[str]:
    """纯函数:返回命中的类型(不含 key 本身)。"""
    found = [name for name, rx in PATTERNS.items() if rx.search(data)]
    found += [f"jwt:{_jwt_role(m.group(0))}" for m in JWT.finditer(data)
              if _jwt_role(m.group(0)) not in PUBLIC_JWT_ROLES]
    return found


def test_scanner_catches_each_kind_without_echoing_it() -> None:
    def jwt(role: str) -> bytes:
        enc = lambda d: base64.urlsafe_b64encode(json.dumps(d).encode()).rstrip(b"=")  # noqa: E731
        return enc({"alg": "HS256"}) + b"." + enc({"role": role, "iss": "supabase"}) + b".sig_" + b"x" * 20
    assert scan(b'X="${K:-CG-' + b"a1" * 12 + b'}"') == ["coingecko"]
    assert scan(b"k=" + jwt("service_role")) == ["jwt:service_role"]
    assert scan(b"k=" + jwt("anon")) == []
    assert scan(b"postgresql://postgres:hunter2hunter2@db.example:5432/x") == ["postgres_password"]
    assert scan(b"see https://docs.coingecko.com, header x-cg-pro-api-key") == []


def test_no_secrets_in_tracked_files() -> None:
    files = subprocess.run(["git", "--no-optional-locks", "ls-files", "-z"], cwd=ROOT, check=True,
                           capture_output=True).stdout.decode().split("\0")
    bad = []
    for rel in filter(None, files):
        p = ROOT / rel
        if not p.is_file() or p.is_symlink() or p.stat().st_size > 3_000_000:
            continue
        kinds = scan(p.read_bytes())
        if kinds:
            bad.append(f"{rel}: {', '.join(sorted(set(kinds)))}")
    assert not bad, ("被跟踪的文件里有 key(仓库是 public,推送即公开)—— 改成从环境读,并让 Jazz 换 key:\n  "
                     + "\n  ".join(bad))


if __name__ == "__main__":
    print("── S-502 被跟踪文件里没有 key ──")
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print(f"  ✓ {name}")
    print("\n✅ passed")
