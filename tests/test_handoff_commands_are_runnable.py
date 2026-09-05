"""交接块里的命令必须能直接粘贴运行 (S-289).

Jazz 说过「几次」:`git add` / `git commit` / `git push` 这些行后面不能跟注释,
终端认不到。它反复发生,不是因为没人记住,是因为 **CLAUDE.md 里那个模板自己带着注释**:

    bash scripts/preflight.sh          # green before anything below

规则写在模板下面,模板写在规则上面,而**被复制的是模板**。
这是本周第七次同一个形状 —— 规则存在,它旁边的例子和它矛盾。
(前六次:inception 只护 Postgres · mark_coverage 只在 ① · 列检查只查 api_keys ·
schema-drift 只查表 · 容差只被自己的测试读 · forward-fill 不可见。)

所以守卫的对象是 **CLAUDE.md 自己**。散文管不住散文,测试可以。
"""
from __future__ import annotations

import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_CLAUDE = _ROOT / "CLAUDE.md"

#: 一旦带注释就会被终端吃掉或误读的命令。
_COMMANDS = ("git add", "git commit", "git push", "git unlock",
             "bash scripts/", "curl ", "cd ~/")

_OK, _FAIL = [], []


def check(name: str, cond: bool, detail: str = "") -> None:
    (_OK if cond else _FAIL).append(name)
    print(f"  {'✓' if cond else '✗'} {name}" + (f" :: {detail}" if not cond and detail else ""))


def _bash_blocks(text: str) -> list[tuple[int, list[str]]]:
    """(起始行号, 块内各行)。只看 ```bash 围栏。"""
    out, cur, start = [], None, 0
    for i, line in enumerate(text.split("\n"), 1):
        if line.strip().startswith("```bash"):
            cur, start = [], i
        elif line.strip() == "```" and cur is not None:
            out.append((start, cur))
            cur = None
        elif cur is not None:
            cur.append(line)
    return out


def test_no_command_line_carries_a_trailing_comment() -> None:
    text = _CLAUDE.read_text(encoding="utf-8")
    offenders = []
    for start, lines in _bash_blocks(text):
        in_msg = False
        for off, raw in enumerate(lines):
            line = raw.rstrip()
            # -m "..." 的多行 body 里 `#` 是正文,不是注释。
            quotes = line.count('"') - line.count('\\"')
            if in_msg:
                if quotes % 2 == 1:
                    in_msg = False
                continue
            if 'commit -m "' in line and quotes % 2 == 1:
                in_msg = True
                continue
            if not any(line.lstrip().startswith(c) for c in _COMMANDS):
                continue
            if re.search(r"\s#", line):
                offenders.append(f"CLAUDE.md:{start + off + 1}: {line.strip()[:70]}")
    check("交接模板里没有行尾注释", not offenders,
          " · ".join(offenders) + " —— 注释放在围栏外面的正文里,围栏内只放能粘贴就跑的行")


def test_the_lock_is_cleared_after_preflight_not_before() -> None:
    """`rm -f .git/index.lock` 必须排在 preflight **之后**、第一个 `git add` 之前。

    2026-09-04 实测:交接块里写的是 `git unlock` → `preflight` → `git add`,
    结果三个 `git add` 全部 `Unable to create '.git/index.lock': File exists`,
    `git push` 回 `Everything up-to-date`,**16 个文件一个都没进去**。

    两个原因叠在一起:
      ① 沙箱跑过 `git status` —— 它是**读**命令,但会刷新 index 并因此建锁,
         而 FUSE 不让删。规则 4 原文只禁「写命令」,**作用域小了一格**(本轮第八次)。
      ② `scripts/preflight.sh:80` 有 `git ls-files`,它在 unlock **之后**跑。
         在 preflight 之前解锁,等于在重新上锁的那一步之前解锁。
    """
    text = _CLAUDE.read_text(encoding="utf-8")
    bad = []
    for start, lines in _bash_blocks(text):
        body = [l.strip() for l in lines if l.strip()]
        try:
            i_add = next(i for i, l in enumerate(body) if l.startswith("git add"))
        except StopIteration:
            continue
        i_rm = next((i for i, l in enumerate(body) if "index.lock" in l), None)
        i_pre = next((i for i, l in enumerate(body) if l.startswith("bash scripts/preflight")), None)
        if i_rm is None or i_rm > i_add:
            bad.append(f"CLAUDE.md:{start}: 第一个 git add 之前没有 rm -f .git/index.lock")
        elif i_pre is not None and i_rm < i_pre:
            bad.append(f"CLAUDE.md:{start}: 解锁排在 preflight 之前 —— preflight 会再上锁")
    check("解锁排在 preflight 之后、git add 之前", not bad, " · ".join(bad))


def test_verification_snippets_fail_loudly_on_a_wrong_field() -> None:
    """验证命令必须用 `d["k"]`,不能用 `d.get("k")` (S-297).

    2026-09-05:我给 Jazz 的两条验证 curl **字段全问错了** ——
    在 `/internal/loop-health` 上问 `n_failing`(心跳面板其实在
    `/internal/data-freshness` 的 `loops` 键下),在 `/internal/data-coverage`
    上问 `n_covered`(那个端点的键是 `n_symbols` / `n_pairs`)。

    两条都不报错,都打印 `None`。他看到的是:

        失败 None · 拒绝 None · 旧构建 None

    > **「这个字段不存在」和「系统健康,没什么可报」在 `None` 上完全同形。**

    这就是本周那个形状的第 N 次,而这次它长在**验证工具本身**上 ——
    一个测不出问题的探针,比没有探针更糟:没有探针你知道自己不知道。
    `d["k"]` 会抛 KeyError,吵,而吵正是这里要的。

    S-289 守的是这些命令的**语法**(行尾注释会被终端吃掉);
    这一条守的是**语义**。语法对、字段错的命令,粘贴进终端一样能跑。
    """
    bad = []
    for path in (_CLAUDE, _ROOT / "PROJECT_STATE.md"):
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        for start, lines in _bash_blocks(text):
            for off, line in enumerate(lines):
                if "json.load" not in line or ".get(" not in line:
                    continue
                bad.append(f"{path.name}:{start + off + 1}: {line.strip()[:60]}")
    check("验证命令用 d[\"k\"] 而不是 d.get(\"k\")", not bad,
          " · ".join(bad) + " —— .get 让问错的字段打印 None,"
          "而 None 和「健康且无事可报」同形;要 KeyError,要它吵")


def test_the_rule_itself_is_stated_next_to_the_template() -> None:
    """规则要和模板挨着。

    一条写在别处的规则,和一个就在眼前的反例,输的总是规则。"""
    text = _CLAUDE.read_text(encoding="utf-8")
    check("规则与模板同处一节",
          "NO TRAILING" in text and "Handoff format" in text,
          "CLAUDE.md 的 handoff 一节必须显式写明不许行尾注释")


if __name__ == "__main__":
    print("── 交接命令可直接粘贴 (S-289) ──")
    test_no_command_line_carries_a_trailing_comment()
    test_the_lock_is_cleared_after_preflight_not_before()
    test_verification_snippets_fail_loudly_on_a_wrong_field()
    test_the_rule_itself_is_stated_next_to_the_template()
    print()
    if _FAIL:
        print(f"🔴 {len(_FAIL)} FAILED: {_FAIL}")
        raise SystemExit(1)
    print(f"✅ {len(_OK)}/{len(_OK)} 交接块检查通过")
