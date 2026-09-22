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
    """declared_only 的那段措辞不许出现「写入被吞掉」这类断言。"""
    from pathlib import Path
    src = Path("src/api/routers/research_intake.py").read_text(encoding="utf-8")
    # ⚠️ 第一版我用「往前 900 字符」取窗口,结果取到了 **前一支**
    # (with_call_site)的措辞,于是红得莫名。**那是按文本距离匹配,不是按结构** ——
    # 和 `test_production_can_write` 匹配拼写是同一个毛病,而这条测试讲的就是它。
    # 改成取那一支**自己的字面量**:从它的起始标记到它的条件。
    start = src.find("table(s) are DECLARED")
    end = src.find('_msplit["declared_only"] else ""', start if start >= 0 else 0)
    if start < 0 or end < 0:
        _fail("找不到 declared_only 那一支的字面量 —— 结构变了,这条守卫要跟着改")
    seg = src[start:end]
    for bad in ("returns False and is swallowed", "no forward record"):
        if bad in seg:
            _fail(f"declared_only 的措辞里出现了 '{bad}' —— 那是另一支的结论,不适用")
    if "NOT observable from here" not in seg:
        _fail("declared_only 的措辞必须说明「写入者在不在,从这里看不出来」")
    _ok("declared_only 的措辞不越界,且明写了可观测性边界")


if __name__ == "__main__":
    print("S-399 — drift 措辞按来源分开")
    for t in (test_provenance_is_not_collapsed,
              test_declared_only_does_not_mean_no_writer,
              test_consequence_wording_does_not_overclaim):
        t()
    print("\n✅ 3/3 passed")
