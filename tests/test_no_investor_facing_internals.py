"""规则 #8:投资人看得见的地方,不出现实现细节 (S-237).

CLAUDE.md 硬规则 #8 写着「No investor-facing internals — strategy.html 等
must not mention FastAPI/Railway/Ollama/hardware/architecture」。**写了几个月,
从来没有任何东西检查它。**

Minimax-A 的审计发现 `QuantMonitor.jsx` 里有 4 处模型名。查实:其中**两处是
真的上屏文本** ——

    "Weak IC detected · Awaiting Gemma4-26b analysis"
    "|r| < 0.05 × 3 mine runs → Gemma4-26b hypothesis generation → test → evolve"

而 `App.jsx:154` 把 QuantMonitor 渲染在「Section 1 — Live Trading Engine — FIRST」,
**主面板首屏**。没有任何 devMode 门控。

### 这条守卫怎么写才不会自己变成噪音

**注释必须剥掉。** 一个说明"这里不能出现模型名"的注释本身含有模型名 ——
`tests/_source.py` 记的就是这个失败,今天已经踩到第五次。JSX 不能用 Python AST,
所以先做括号安全的注释剥离,再匹配。

**代码里合法出现的值要冻结,不要一刀切。** `CISLeaderboard.jsx` 里
`engineSource === "local_engine" ? ... : ...` 的 `"railway"` 是一个**内部枚举值**,
实测只用于配色和 `"FULL MODEL"/"ESTIMATED"` 两值标签,**原值不上屏**。
一刀切会把它判成违规,而人会学会忽略这条守卫。所以:冻结名单 + 原因,只能减。
"""
from __future__ import annotations

import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
DASH = ROOT / "dashboard" / "src"

#: 实现细节 —— 模型、厂商、基础设施、硬件。投资人不需要知道,而知道了只会
#: 把"我们做了什么"换成"我们用了什么"。
BANNED = (r"gemma\w*", r"ollama", r"lm\s?studio", r"qwen\w*", r"\bllm\b",
          r"fastapi", r"\brailway\b", r"supabase", r"mac\s?mini", r"upstash")

#: 冻结:代码里合法出现、且实测不上屏。附原因,名单只能减。
KNOWN_CODE_ONLY = {
    ("dashboard/src/components/CISLeaderboard.jsx", "railway"):
        '内部枚举值,只用于配色与 "FULL MODEL"/"ESTIMATED" 两值标签;原值不渲染(实测 2026-08-25)',
    # MobileApp.jsx 曾在名单里 —— 实测它的三处 railway 全在 // 注释里,剥掉后
    # 不存在。守卫的"只能减"条款第一次跑就自己抓到了这条多余的豁免。
}


def strip_comments(src: str) -> str:
    """去掉 // 和 /* */ —— 保留行数,便于报位置。

    ⚠️ 注释必须先剥。一条解释"此处禁止出现模型名"的注释本身含有模型名,
    而守卫会命中它 —— 于是注释写得越清楚,误报越多,守卫越快被删掉。
    """
    src = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"), src, flags=re.S)
    return re.sub(r"(?m)//.*$", "", src)


def main() -> int:
    if not DASH.exists():
        print("  ⓘ dashboard/src 不存在,跳过")
        return 0

    hits: list[tuple[str, int, str, str]] = []
    seen_known: set[tuple[str, str]] = set()

    for p in sorted(DASH.rglob("*.jsx")) + sorted(DASH.rglob("*.tsx")):
        if "node_modules" in p.parts:
            continue
        rel = str(p.relative_to(ROOT))
        body = strip_comments(p.read_text())
        for i, line in enumerate(body.split("\n"), start=1):
            for pat in BANNED:
                m = re.search(pat, line, re.I)
                if not m:
                    continue
                term = m.group(0).lower().strip()
                key = (rel, "railway" if "railway" in term else term)
                if key in KNOWN_CODE_ONLY:
                    seen_known.add(key)
                    continue
                hits.append((rel, i, term, line.strip()[:90]))

    # 名单只能减:已经清掉的还留着 → fail,否则冻结名单会变成永久豁免。
    stale = set(KNOWN_CODE_ONLY) - seen_known
    for key in sorted(stale):
        hits.append((key[0], 0, key[1],
                     "已不再出现 —— 从 KNOWN_CODE_ONLY 里删掉这一行"))

    if hits:
        print(f"✗ 规则 #8:{len(hits)} 处实现细节出现在投资人可见的前端:")
        for rel, ln, term, ctx in hits[:15]:
            print(f"   · {rel}:{ln} [{term}] {ctx}")
        print("  规则 #8:描述我们做到了什么,不描述我们用了什么。")
        return 1

    print(f"  ✓ 规则 #8:前端无实现细节({len(KNOWN_CODE_ONLY)} 处冻结的代码内枚举值)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
