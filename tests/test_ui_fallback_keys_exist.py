"""S-550:`MAP[x] || MAP.KEY` 的兜底键必须真的在 MAP 里。

S-541 让没有 CIS 代币的协议 signal = null,ProtocolIntelligence 的兜底写的是 `SIGNAL_COLORS.HOLD` —— 表里从来没有
HOLD(合规枚举里也不该有),于是第一行这样的协议就让整个 Protocols 区块渲染失败,页面只剩
「This section failed to render」。兜底分支平时走不到,所以只有静态检查能在上线前抓住它。
"""
import pathlib
import re

SRC = pathlib.Path(__file__).resolve().parents[1] / "dashboard" / "src"
FALLBACK = re.compile(r"\b([A-Z][A-Z0-9_]*)\[[^\]]+\]\s*\|\|\s*\1\.([A-Za-z_][A-Za-z0-9_]*)\b")


def _object_keys(txt: str, name: str) -> set[str] | None:
    m = re.search(rf"\bconst\s+{name}\s*=\s*\{{", txt)
    if not m:
        return None
    depth, i = 0, m.end() - 1
    for j in range(i, len(txt)):
        if txt[j] == "{":
            depth += 1
        elif txt[j] == "}":
            depth -= 1
            if depth == 0:
                body = txt[i + 1:j]
                break
    else:
        return None
    keys, d = set(), 0
    for line in body.splitlines():
        if d == 0:
            k = re.match(r'\s*(?:"([^"]+)"|([A-Za-z_][A-Za-z0-9_]*))\s*:', line)
            if k:
                keys.add(k.group(1) or k.group(2))
        d += line.count("{") - line.count("}")
    return keys


def test_every_map_fallback_key_exists():
    bad = []
    for f in sorted(SRC.rglob("*.jsx")):
        txt = f.read_text(encoding="utf-8")
        for m in FALLBACK.finditer(txt):
            name, key = m.group(1), m.group(2)
            keys = _object_keys(txt, name)
            if keys is not None and key not in keys:
                line = txt.count("\n", 0, m.start()) + 1
                bad.append(f"{f.name}:{line} {name}.{key} (keys: {sorted(keys)})")
    assert not bad, "fallback key missing from its map — the fallback itself would be undefined:\n  " + "\n  ".join(bad)
