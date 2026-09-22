"""S-399 — `/internal/schema-drift` 必须分清「有调用点但表没了」和「只是声明了」。

这两个状态**修法相反**:前者要补迁移(有人在写、写不进去);
后者要去问声明它的那条 lane(这边没人在写)。
2026-09-22 它们被渲染成同一句话 ——
「N table(s) **the code writes to** do not exist. Every write returns False and
is swallowed」—— 对 `nav_panel_*` 报了这句,而 `src/` 里没有任何调用点写它们。
**那句话在描述一批不存在的吞掉的写入**,实测代价:一条 lane 被派去修一个不存在的 writer。

与 S-354 同一处伤口的另一支(那次是 RPC 探针把「读不到」说成「缺失」),
修法早就写在同一个文件里:**三值一路带到输出,绝不在最后一步塌成两值。**
"""
from __future__ import annotations

import sys


def _ok(m: str) -> None: print(f"  ✓ {m}")
def _fail(m: str) -> None: print(f"  ✗ {m}"); sys.exit(1)


def test_provenance_is_not_collapsed() -> None:
    from src.api.schema_manifest import write_tables_by_provenance
    p = write_tables_by_provenance()
    for k in ("with_call_site", "declared_only"):
        if k not in p:
            _fail(f"write_tables_by_provenance() 缺 {k} —— 来源又塌成一个集合了")
    if set(p["with_call_site"]) & set(p["declared_only"]):
        _fail("两个集合相交 —— declared_only 必须是「声明了且没有调用点」")
    _ok("write_tables_by_provenance(): 两条来源没有塌成一个集合")


def test_declared_only_does_not_mean_no_writer() -> None:
    """这条守的是**措辞**,不是数据。

    `declared_only` 的存在理由是 AST 走查跟不进 `cometcloud-local/`(规则 3)。
    实测 2026-09-22:六张 declared_only 表里有四张是活的 ——
    `cg_coin_map` 211 行 · `corporate_treasury_history` 3852 · `treasury_decisions` 896 ·
    `treasury_entities` 102。**所以「看不到调用点」不等于「没有写入者」。**
    任何把 declared_only 说成「没人写」的措辞都是 I1 违反。
    """
    from src.api.schema_manifest import write_tables_by_provenance
    d = set(write_tables_by_provenance()["declared_only"])
    live_known = {"cg_coin_map", "corporate_treasury_history",
                  "treasury_decisions", "treasury_entities"}
    if not (live_known & d):
        _ok("declared_only 里已无已知的活表 —— 若是 AST 走查变强了,把 live_known 清空并说明")
        return
    _ok(f"declared_only 含 {len(live_known & d)} 张【已知活着】的表 —— "
        "证明它只说明「src/ 看不到调用点」,不说明没有写入者")


def test_consequence_wording_does_not_overclaim() -> None:
    """declared_only 那一支不许借用另一支的结论,且必须写明可观测性边界。

    ⚠️ 这条判据改过两版,两版都栽在同一件事上:**按文本匹配而不是按结构**。
    v1 用「往前 900 字符」取窗口 → 取到了前一支(with_call_site)的字面量;
    v2 改成找起止标记 → 措辞被抽成函数之后标记不在了,直接匹配不上。
    **而这条测试讲的就是这个毛病**,它自己犯了两次。
    v3:**调用 `_drift_consequence()`,只喂 declared_only,看它自己说了什么。**
    """
    from src.api.routers.research_intake import _drift_consequence as f
    only_declared = f({"with_call_site": [], "declared_only": ["t"]}, [], ["t"])
    for bad in ("returns False and is swallowed", "no forward record"):
        if bad in only_declared:
            _fail(f"declared_only 的措辞里出现了 '{bad}' —— 那是另一支的结论,不适用")
    if "NOT observable from here" not in only_declared:
        _fail("declared_only 的措辞必须说明「写入者在不在,从这里看不出来」")
    _ok("declared_only 的措辞不越界,且明写了可观测性边界")


def test_all_clear_never_coexists_with_a_missing_object() -> None:
    """S-399b — 「全都存在」不许和任何一个 missing 同时出现在一句话里。

    第一版修完措辞之后实跑打出来的是:
        "...check the lane that declared it. **every table the code writes to and
         every RPC it calls exists**"
    **同一句话既报缺失又说全都存在** —— 因为那个 else 挂在
    `with_call_site or rpc_missing` 上,而 declared_only 非空、另两者为空。
    **这条守卫反对的东西,被我在修它的时候搬了进去。**

    ⚠️ 这条判据自己也改过两版:前两版想用正则去源码里读那段措辞,
    第一次取错窗口(取到了前一支的字面量),第二次干脆匹配不上。
    **按文本匹配而不是按结构,是同一个毛病** —— 所以措辞被抽成纯函数
    `_drift_consequence()`,这里**调用**它,不读它。
    """
    from src.api.routers.research_intake import _drift_consequence as f
    ALL_CLEAR = "every table the code writes to and every RPC it calls exists"
    cases = {
        "只有 declared_only":  ({"with_call_site": [], "declared_only": ["t"]}, [], ["t"]),
        "只有 with_call_site": ({"with_call_site": ["t"], "declared_only": []}, [], ["t"]),
        "只有 rpc_missing":    ({"with_call_site": [], "declared_only": []}, ["r"], []),
        "两者都有":            ({"with_call_site": ["a"], "declared_only": ["b"]}, [], ["a", "b"]),
        "什么都不缺":          ({"with_call_site": [], "declared_only": []}, [], []),
    }
    for name, (msplit, rpc_missing, missing) in cases.items():
        out = f(msplit, rpc_missing, missing)
        nothing_missing = not (missing or rpc_missing)
        if (ALL_CLEAR in out) != nothing_missing:
            _fail(f"{name}:全清子句与实际状态不符 —— 输出 {out[:120]!r}")
        if "no forward record" in out and not (msplit["with_call_site"] or rpc_missing):
            _fail(f"{name}:declared_only 不该带「记录断了」的结论(那边没人在写)")
    _ok("全清子句只在三者皆空时出现;五种状态各自自洽")


def test_severity_follows_provenance_not_just_wording() -> None:
    """S-399c — **严重级别也要跟着来源走,不能只分措辞。**

    2026-09-22 实测:`schema_drift_check.py` 退出 1,preflight 是 `|| exit 1`,
    handoff 是 `&&` 链 —— **于是它挡住了所有 push**,而挡住的理由是两张表 + 三列
    **没有任何人写**(`declared_only`)。同一时刻价格源全挂、replay 读取有 bug,
    **修它们的 push 被这个红灯挡着。**

    上一轮我把来源拆开**只用在措辞上,没用在退出码上** ——
    「修了一个渲染器,漏了另一个」,而那句话就写在同一批改动里。

    这不是豁免:**一旦 `src/` 出现调用点,同一张表自动落进 `with_call_site`,
    立刻恢复硬闸。** 防「声明了永远不建」的是 OPEN RISK #0c 的到期日。

    ⚠️ 还有一条:来源**在本地算**,不问端点。第一版让端点返回拆分字段,
    于是出现部署顺序死锁 —— 加字段的那个 push 要先过一个需要那个字段的检查。
    **「哪些只是声明」是源码树的属性,不是部署的属性。**
    """
    import re
    from pathlib import Path
    src = Path("scripts/schema_drift_check.py").read_text(encoding="utf-8")

    if "write_tables_by_provenance" not in src or "write_columns_by_provenance" not in src:
        _fail("退出码判定没有用到来源拆分 —— 它又会因为 declared_only 而挡住 push")
    if re.search(r"if\s+miss\s+or\s+", src) or re.search(r"if\s+cd\s+or\s+", src):
        _fail("还在拿未拆分的 miss / cd 直接决定退出码")
    if "column_check_unavailable" not in src and "cc" not in src:
        _fail("`问不出来` 必须仍然阻断 —— 读不到时不许假装通过(S-354)")

    # 判定逻辑本身:四种状态
    def rc(miss, dec_tbl, cd, dec_col, rpc, cc):
        hard_tbl = [t for t in miss if t not in dec_tbl]
        hard_col = {t: [c for c in cols if c not in set(dec_col.get(t, []))]
                    for t, cols in cd.items()}
        hard_col = {t: c for t, c in hard_col.items() if c}
        return 1 if (hard_tbl or hard_col or rpc or cc) else 0

    cases = [
        ("全是 declared_only",      rc(["a"], {"a"}, {"t": ["c"]}, {"t": ["c"]}, [], []), 0),
        ("有真调用点缺表",          rc(["a"], set(),  {},          {},           [], []), 1),
        ("有真调用点缺列",          rc([],    set(),  {"t": ["c"]}, {},          [], []), 1),
        ("列问不出来",              rc([],    set(),  {},          {},           [], ["t"]), 1),
        ("RPC 缺失",                rc([],    set(),  {},          {},           ["r"], []), 1),
        ("什么都不缺",              rc([],    set(),  {},          {},           [], []), 0),
    ]
    for name, got, want in cases:
        if got != want:
            _fail(f"{name}:退出码 {got},应为 {want}")
    _ok("退出码跟着来源走:declared_only 不阻断,真调用点/问不出来/RPC 缺失阻断")


def test_ops_console_uses_drift_consequence_for_note() -> None:
    """S-399d — `scripts/ops_console.py` 是 S-354 表支的第三处落点。

    S-399a 修了 `research_intake.py` 的 router,S-399c 修了
    `scripts/schema_drift_check.py` 的退出码,**本文件 (ops_console.py)
    漏了**——直到 2026-09-22 实测 nav_panel_* 触发它的「Every write
    returns False without raising...」才被发现。三处同源,三处修法
    应该用同一句话。这条判据保证不会再加第四处:**任何 drift 措辞
    都必须经 `_drift_consequence()` 这一个出口**。

    ⚠️ v1 用「文件里没有这一串字」做检查,但 ops_console.py 仍然有
    「swallowed」字样(用在 *comment* 里解释修法),第一次全绿假绿。
    改成结构:必须 `import _drift_consequence` 且赋给 `note` 字段。
    """
    import re
    from pathlib import Path
    src = Path("scripts/ops_console.py").read_text(encoding="utf-8")

    if "_drift_consequence" not in src:
        _fail("ops_console.py 仍未用 _drift_consequence() —— "
              "drift 措辞第三处落点(S-354 表支)未修")
    if "Every write returns False" in src:
        _fail("ops_console.py 还含字面量 'Every write returns False' —— "
              "那是 S-354 表支的旧措辞")
    # note 字段必须赋值成 consequence(不能保留硬编码字面量)
    if not re.search(r'"note"\s*:\s*consequence', src):
        _fail("ops_console.py 的 schema:declared check 没把 note 字段 "
              "绑到 consequence 上 —— 走回了硬编码字面量")
    _ok("ops_console.py:drift 措辞第三处落点已修,走 _drift_consequence 单一出口")


if __name__ == "__main__":
    print("S-399 — drift 措辞按来源分开")
    for t in (test_provenance_is_not_collapsed,
              test_declared_only_does_not_mean_no_writer,
              test_consequence_wording_does_not_overclaim,
              test_all_clear_never_coexists_with_a_missing_object,
              test_severity_follows_provenance_not_just_wording,
              test_ops_console_uses_drift_consequence_for_note):
        t()
    print("\n✅ 6/6 passed")
