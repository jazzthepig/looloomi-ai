"""`docs/SPINE.md` 必须描述**现在**的代码,不是写下它那天的代码 (S-360)。

为什么需要这个测试
==================
实测 2026-09-16:仓库里 10 个文件、12 行注释断言 `signal_outcomes` 死了
80/122/123/125 天。**每一条在写下时都是真的,今天全部是假的。**
它们当天把一次排查误导到了一个不存在的 P0 上,花掉半天。

    一条描述状态的注释,如果没有任何东西会在状态改变时改它,
    它就是一颗延时错误。

SPINE.md 是同一类文件 —— 一份描述"哪条路是活的"的状态文档。
没有这个测试,它会以完全相同的方式过期,而且因为它被指定为
"agent 重组记忆时的方向基准",它过期的代价比一条注释高得多。

这个测试检查什么 —— **诚实,不是完美**
======================================
一个要求「代码已经干净」的检查,会在世界还脏的时候天天红,然后被关掉
(preflight 是推送门,一条永远红的检查等于没有门)。
所以本测试**不要求旧路已经清空**,只要求:

    SPINE.md 的「已知未清偿」表 == 代码里实际还在读旧路的地方

漂移分两种,都是红:

  1. **未登记的回归** —— 代码里读了一条旧路,而 SPINE 没登记它。
     这是"又绕过了一次,没留痕"。
  2. **过期的登记** —— SPINE 登记了一条未清偿,而代码里已经没有了。
     这是"清干净了但文档还在喊狼来了" —— 正是那 12 行注释的病。

第 2 种和第 1 种同等重要。只查第 1 种,就会养出一份只增不减的欠债清单,
而那份清单会像那 12 行注释一样,最终误导读它的人。

注释不算命中
============
`strip_comments()` 去掉 `#` 之后的内容和三引号块。这是**刻意**的:
一行抱怨旧表的注释不是"还在读旧路",它是历史记录。
本测试要区分的正是这两者 —— 而混淆它们就是 S-360 那半天的成因。
"""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPINE = ROOT / "docs" / "SPINE.md"

#: `src/` 里这些子树不是生产代码,命中不算数。
_SKIP_PARTS = (".venv", "site-packages", "worktrees", "node_modules", "__pycache__")


def strip_comments(src: str) -> str:
    """去掉三引号块与行内 `#` 之后的内容。**不追求完美的 Python 词法**——
    追求的是"提到"和"使用"的区分,而字符串字面量里的表名是使用。"""
    src = re.sub(r'"""(?:.|\n)*?"""', "", src)
    src = re.sub(r"'''(?:.|\n)*?'''", "", src)
    return "\n".join(line.split("#", 1)[0] for line in src.splitlines())


def production_sources() -> list[tuple[str, str]]:
    out = []
    for p in (ROOT / "src").rglob("*.py"):
        if any(part in str(p) for part in _SKIP_PARTS):
            continue
        try:
            out.append((str(p.relative_to(ROOT)), strip_comments(
                p.read_text(encoding="utf-8", errors="replace"))))
        except OSError:
            continue
    return out


def _table_rows(section_heading: str, text: str) -> list[list[str]]:
    """取某个小节标题之后的第一张 markdown 表的数据行(已拆成单元格)。"""
    idx = text.find(section_heading)
    assert idx != -1, f"SPINE.md 里找不到小节 {section_heading!r}"
    rows, seen_header = [], False
    for line in text[idx:].splitlines()[1:]:
        s = line.strip()
        if not s.startswith("|"):
            if rows:
                break
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if set("".join(cells)) <= set("-: "):
            seen_header = True
            continue
        if not seen_header:
            continue
        rows.append(cells)
    assert rows, f"{section_heading} 下面没有解析到表格行"
    return rows


def _names(cell: str) -> list[str]:
    """从单元格里取所有反引号标识符,归一到可 grep 的裸名。"""
    out = []
    for raw in re.findall(r"`([^`]+)`", cell):
        name = raw.split("(")[0].strip()
        name = name.split(".")[-1] if name.startswith("market_state_vectors.") else name
        name = name.replace("()", "").strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name):
            out.append(name)
    return out


def _hits(name: str, sources: list[tuple[str, str]]) -> list[str]:
    """**必须按词边界匹配。**

    第一版用的是 `name in body`,于是 `vec`(来自 `market_state_vectors.vec`)
    命中了 `vec_full` / `vector` / `vecs`,让一条"还有读者"的断言以错误的理由通过。
    一个因为错误的理由而变绿的检查,比红的更坏 —— 它看起来在守卫,实际没有。
    `\\bvec\\b` 不会命中 `vec_full`,因为 `_` 是词字符。
    """
    pat = re.compile(rf"\b{re.escape(name)}\b")
    return [path for path, body in sources if pat.search(body)]


def _consumer_hits(name: str, sources: list[tuple[str, str]]) -> list[str]:
    """看起来像**真的在用**,而不是名字出现在某段文本里。

    两个方向的误判代价不同,所以两个函数刻意不对称:

      `_hits`(松)    —— 回答"还有人在读旧路吗"。宁可多报:多报一条会被登记,
                         漏报一条就是一次没留痕的绕过。
      `_consumer_hits`(紧) —— 回答"这段真的有消费者吗"。必须严:

    实测 `similar_market_states` 在 `src/` 里有 1 处"命中",内容是

        f"similar_market_states returns is a number without a "

    —— 一条**错误消息里的散文**。松匹配把它算成消费者,于是
    「🔴 零调用者」被标成 🟢 也照样绿。这是本次会话第四次「因错误的理由变绿」。

    真消费者长这样:`name(` 调用、`import name`、或作为精确的引号 token
    (`"name"` —— PostgREST 的表名/RPC 名就是这样传的)。
    """
    n = re.escape(name)
    pat = re.compile(rf"""(?x)
        \b{n}\s*\(          # 调用
      | \b{n}\s*=           # 绑定
      | import\s+[\w.,\s]*\b{n}\b
      | from\s+[\w.]*\b{n}\b
      | ["']{n}["']         # 精确引号 token(表名 / RPC 名)
      | /rest/v\d+/{n}\b    # PostgREST 路径 —— 这就是读一张表的样子
    """)
    return [path for path, body in sources if pat.search(body)]


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"  {'✓' if ok else '✗'} {label}" + (f" :: {detail}" if detail and not ok else ""))
    return ok


def main() -> int:
    text = SPINE.read_text(encoding="utf-8")
    sources = production_sources()
    print(f"\nSPINE 漂移检查 — 扫描 {len(sources)} 个生产源文件\n")
    ok = True

    # ── 1. 未清偿登记表:登记 == 现实 ───────────────────────────────────
    print("【已知未清偿】登记必须与代码一致")
    registered: dict[str, list[str]] = {}
    for row in _table_rows("### 已知未清偿", text):
        if "[DB]" in row[0]:
            # 表上的某个列,裸名不可 grep(`vec` 在 src/ 里是通用局部变量名,90+ 处)。
            # 不假装能查 —— 只要求这一行写明一条可跑的 SQL 判据。
            ok &= check(f"{row[0].strip()} 的 VERIFY 是一条可跑的 SQL",
                        "select" in row[-1].lower(), f"VERIFY 栏没有 SQL: {row[-1][:60]}")
            continue
        for n in _names(row[0]):
            registered[n] = _hits(n, sources)

    assert registered, "未清偿表里没有解析到任何名字 —— 解析器坏了,不是代码干净了"

    for name, hits in sorted(registered.items()):
        # 过期登记:文档说还欠着,代码里已经没有了 → 该把它从表里删掉
        ok &= check(f"{name} 仍有未清偿读者(否则应从表中移除)",
                    bool(hits), "代码里已零命中,登记过期了")

    # ── 2. 退役表里的名字必须要么零命中,要么已登记 ─────────────────────
    print("\n【已退役】要么代码零命中,要么在未清偿表里登记")
    for row in _table_rows("### 已退役", text):
        if "[DB]" in row[0]:
            continue  # 列名不可 grep,判据在未清偿表的 SQL 里(见上)
        for n in _names(row[0]):
            hits = _hits(n, sources)
            ok &= check(f"{n} 无未登记的读者",
                        (not hits) or (n in registered),
                        f"{len(hits)} 个文件仍在读且未登记: {hits[:3]}")

    # ── 3. 主干表:🟢 的段不允许零消费者 ────────────────────────────────
    print("\n【主干】标 🟢 的段必须真的有消费者")
    for row in _table_rows("## §2 主干", text):
        status = row[-1]
        if "🟢" not in status:
            continue
        impls = _names(row[2])
        if not impls:
            continue
        ok &= check(f"§2「{row[1]}」的实现有真消费者",
                    any(_consumer_hits(n, sources) for n in impls),
                    f"{impls} 在 src/ 没有调用/导入/引号 token,却标着 🟢 "
                    f"(裸提及不算消费者)")

    # ── 3b. 反方向:🔴 声称「零调用者」而实际已经有消费者 = 文档过期 ─────
    # S-365:本文件一度落后两批 —— 5a/5b 已接进 `/api/v1/regime/similar`,
    # 第 8 段的 edge_map 已改读统一视图,而 §2 还写着 🔴 零调用者,**测试全绿**。
    #
    # 因为原来只查一个方向:🟢 必须真有消费者。**一个过期的 🔴 畅通无阻。**
    # 那正是这个文件今天到处在挑的单向性 —— 出现在它自己身上。
    # 「已知未清偿」表两个方向都判红(未登记的回归 + 过期的登记),§2 也该如此。
    print("\n【主干】标 🔴「无/零调用者」的段,不能实际已有消费者")
    for row in _table_rows("## §2 主干", text):
        status, consumer = row[-1], row[3]
        if "🔴" not in status:
            continue
        # 只查那些**明确声称没有消费者**的行;声称「停 N 天」的不在此列。
        if not any(w in consumer for w in ("无", "零", "**无**")):
            continue
        # **只看主实现**(单元格里第一个反引号名)。括号里的是细节,不是第二个实现:
        # 第 6 段写的是 `regime_override_enforcer`(`EXPOSURE_BANDS_V1`)——
        # 后者有导入者、前者没有,而这一段的状态由前者决定。
        # 第一版把两个都算进去,于是报了一个假红。**判据宽一格,就换了一个被测对象。**
        impls = _names(row[2])[:1]
        live = [n for n in impls if _consumer_hits(n, sources)]
        ok &= check(f"§2「{row[1]}」确实还没有消费者",
                    not live,
                    f"{live} 在 src/ 已经有调用/导入 —— **活干完了,文档没改**")

    # ── 4. 🔴/🟡 的段必须在 §5 断点里有交代 ─────────────────────────────
    print("\n【主干】标 🔴/🟡 的段必须在 §5 断点里出现")
    breakpoints = text[text.find("## §5 当前断点"):]
    assert breakpoints, "找不到 §5"
    for row in _table_rows("## §2 主干", text):
        if "🔴" not in row[-1] and "🟡" not in row[-1]:
            continue
        seg = row[0].strip()
        ok &= check(f"第 {seg} 段(非绿)在 §5 有交代",
                    re.search(rf"第\s*{re.escape(seg)}\s*段", breakpoints) is not None
                    or any(n in breakpoints for n in _names(row[2])),
                    f"「{row[1]}」标着 {row[-1][:6]} 但 §5 没说它怎么办")

    print()
    if not ok:
        print("SPINE.md 与代码不一致。**这不是让你改测试,是让你改那张表或那段代码。**")
        print("哪一边错了要自己判断 —— 但两边必须重新说同一件事。\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
