"""对外文本的边界(硬规则 1 与 8;Jazz 2026-11-14「措辞与内部信息」)。

11-14 把线上 121 个公开 GET 接口逐个抓了一遍:22 个的响应里带着内部的东西 —— 台账编号(S-581、R57)、仓库路径
(`src/data/market/beta_adjust.py`、`docs/NAV_POLICY.md`)、基础设施名字(Railway、Redis)、甚至一条本机路径
(`/Users/…/memory/…`);`crowd-clock` 的五句「姿态」全是祈使句(trim into it / reduce gross / do not chase)。
原有的合规守卫只扫 `src/api/routers` 与 `dashboard/src` 的字面量,而这些字符串大多定义在数据层,再被路由原样端出去
—— **守卫圈的是「字符串写在哪」,漏的是「字符串从哪出去」。**

这里放三样,全是纯函数:
- `strip_refs` / `scrub`:把「(S-581 / S-584)」这类括号里的台账编号拿掉、把不该出门的键丢掉。只给**来自登记表或库里的行**用
  (那些文本内部也在读,编号对内有用);写在路由里的字面量直接改字面量,不靠它兜。
- `internal_findings`:一段响应里还有哪些内部痕迹(给测试和 `scripts/public_surface_scan.py` 用 —— 判据是「出去的是什么」)。
- `wording_findings`:祈使 / 交易指令式的说法。
"""
from __future__ import annotations

import re
from typing import Any, Iterable

_ID = r"[RSM]-?\d{1,3}(?:-[A-Z])?"
#: 「(S-581 / S-584)」「(R57)」「(S-472/S-473/S-556)」—— 括号里只有台账编号
REF_PAREN = re.compile(rf"\s*[((]\s*{_ID}(?:\s*[/,、–-]\s*{_ID})*\s*[))]")

INTERNAL = re.compile(
    r"freqtrade|fastapi|railway|ollama|supabase|upstash|\bredis\b|mac[ _]?mini|lm studio|gemma|minimax|/internal/|"
    r"[((][RSM]-?\d{1,3}[^))]{0,24}[))]|\b[SM]-\d{2,3}\b|\bR\d{2,3}\b(?![a-z0-9%$:_])|\bT-\d{3}\b|"
    r"refutation[_ ]ledger|\w\.py\b|\bsrc/|docs/[A-Za-z_]+\.md|/Users/|/Volumes/|localhost", re.I)

#: 指令式说法:祈使动词对着读者的仓位。只列构造,不列词 —— 「reduce」「entry」单独出现到处都是。
WORDING = re.compile(
    r"\b(?:optimal entry|entry zone|contrarian entry|size the\b|wait for its\b|trim into|do not chase|chase it|"
    r"reduce (?:gross|exposure|risk|size|your)|press (?:confirmed|strength|the)|build the core|"
    r"take profit at|hedge[;,.]|defend[;,.]|fade (?:strength|the|this|rallies)|dip[- ]buys?|"
    r"go long|go short|(?:long|short) the\b|we recommend|you should|investors should|price target|top pick)", re.I)


def strip_refs(s: str) -> str:
    return REF_PAREN.sub("", s)


def scrub(obj: Any, drop_keys: Iterable[str] = ()) -> Any:
    """递归:字符串去掉括号里的台账编号;`drop_keys` 里的键整个不出门。不改数字、不改键名。"""
    drop = frozenset(drop_keys)
    if isinstance(obj, str):
        return strip_refs(obj)
    if isinstance(obj, list):
        return [scrub(x, drop) for x in obj]
    if isinstance(obj, dict):
        return {k: scrub(v, drop) for k, v in obj.items() if k not in drop}
    return obj


def _walk(obj: Any, path: str, pattern: re.Pattern, out: list[str], cap: int) -> None:
    if len(out) >= cap:
        return
    if isinstance(obj, str):
        m = pattern.search(obj) if len(obj) >= 8 else None
        if m:
            out.append(f"{path}: …{obj[max(0, m.start() - 40):m.end() + 40]}…")
    elif isinstance(obj, list):
        for i, x in enumerate(obj[:80]):
            _walk(x, f"{path}[{i}]", pattern, out, cap)
    elif isinstance(obj, dict):
        for k, v in obj.items():
            _walk(v, f"{path}.{k}", pattern, out, cap)


def internal_findings(obj: Any, cap: int = 8) -> list[str]:
    out: list[str] = []
    _walk(obj, "", INTERNAL, out, cap)
    return out


def wording_findings(obj: Any, cap: int = 8) -> list[str]:
    out: list[str] = []
    _walk(obj, "", WORDING, out, cap)
    return out
