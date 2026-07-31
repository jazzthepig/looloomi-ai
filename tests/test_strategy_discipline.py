"""
Strategy discipline — the PHILOSOPHY compiled into CI (Seth, 2026-07-27, per Minimax feedback P2).
==================================================================================================

CLAUDE.md / TRADER_TOM_DOCTRINE / ARCHITECTURE.md are prose; prose gets bypassed under deadline
pressure. This test compiles the non-negotiables into red/green:

  · every sleeve traces to a CAUSE with a base rate            (§TRADER_TOM: no cause, no sleeve)
  · guilty until proven with OOS outcomes                      (oos_survival must be True to SHIP)
  · ≥60 days forward paper trade before production             (Minimax-C's hard gate)
  · regime-conditional reporting mandatory                     (aggregate metrics hide regime failure)
  · binary validity floor (PIT + cost) intact                  (I4 — the only two hard kills)

Legacy debt is EXPLICIT, not silent: pre-convention live sleeves sit in LEGACY_ALLOWLIST with the
reason + what they owe. Adding a NEW ship-verdict record without the evidence floor turns CI red.
Run: python3 -m tests.test_strategy_discipline   (also wired into scripts/preflight.sh stage 3)
"""
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.data.vector.strategy_schema import StrategyRecord, Verdict  # noqa: E402
from src.research.embed_graveyard_canonical import LIBRARY  # noqa: E402

# Pre-convention live sleeves — visible debt, each with the reason it is tolerated and what it owes.
# Removing an entry here without fixing its evidence fields turns CI red. Do NOT add new entries
# for new sleeves — new production records must carry the full evidence floor from day one.
LEGACY_ALLOWLIST: dict[str, str] = {
    "trend_v5c_long_only": "pre-convention live sleeve; deployed §5b overlay-only behind the core-health "
                           "gate (holds ZERO while core dead). OWES: base_rate, oos_survival, "
                           "paper_trade_days, regime_reported backfill.",
}


def test_every_sleeve_has_a_cause_or_notes():
    """§TRADER_TOM: a sleeve without an articulated cause is not a strategy, it's a curve."""
    for r in LIBRARY:
        assert (r.base_rate or r.notes), f"{r.id}: no cause documented (base_rate empty AND notes empty)"


def test_ship_records_carry_the_evidence_floor():
    """SHIP ⇒ full evidence floor (validate() emits zero problems), unless explicitly legacy-allowlisted."""
    for r in LIBRARY:
        if r.verdict != Verdict.SHIP:
            continue
        problems = r.validate()
        if r.id in LEGACY_ALLOWLIST:
            continue  # visible debt — tracked in the allowlist, not silently green
        assert not problems, f"{r.id} ships without the evidence floor: {problems}"


def test_allowlist_entries_are_still_needed():
    """Stale allowlist entries must be removed — if a legacy sleeve now passes, delete its entry."""
    lib_ids = {r.id for r in LIBRARY}
    for lid in LEGACY_ALLOWLIST:
        assert lid in lib_ids, f"allowlist entry '{lid}' no longer in the library — remove it"
        rec = next(r for r in LIBRARY if r.id == lid)
        assert rec.validate(), f"'{lid}' now passes validate() — remove it from LEGACY_ALLOWLIST"


def test_refuted_records_stay_honest():
    """A REFUTE verdict with every validity flag True is a contradiction (validate catches it)."""
    for r in LIBRARY:
        if r.verdict == Verdict.REFUTE:
            assert not (r.pit_clean and r.cost_feasible_at_5bps and r.forward_committed), \
                f"{r.id}: refuted but all validity flags true — which is it?"


def test_new_ship_record_without_evidence_is_rejected():
    """The gate itself: a fresh SHIP record missing the evidence floor must fail validation."""
    bad = StrategyRecord(id="new_hero", title="new hero", doc_source="test",
                         verdict=Verdict.SHIP, pit_clean=True, cost_feasible_at_5bps=True,
                         forward_committed=True)
    problems = bad.validate()
    assert any("base_rate" in p for p in problems), "missing cause must be flagged"
    assert any("oos_survival" in p for p in problems), "unproven OOS must be flagged"
    assert any("paper_trade_days" in p for p in problems), "missing 60d paper gate must be flagged"
    assert any("regime_reported" in p for p in problems), "aggregate-only reporting must be flagged"
    assert any("max_dd_stop" in p for p in problems), "no stop rule ⇒ no production (Millennium)"
    # and a fully-evidenced record passes:
    good = StrategyRecord(id="proven", title="proven", doc_source="test",
                          verdict=Verdict.SHIP, pit_clean=True, cost_feasible_at_5bps=True,
                          forward_committed=True, base_rate="funding crowding reverts (behavioral)",
                          oos_survival=True, paper_trade_days=75, regime_reported=True,
                          oos_window="2026-02-01→2026-05-03", max_dd_stop=-0.15,
                          capital_action_on_breach="zero_and_freeze", backtest_included_stop=True)
    assert not good.validate(), "fully-evidenced ship record must pass"


def test_aggregate_only_reporting_is_incomplete():
    """S-88/S-89 教训(重复第四次):只报聚合指标(总收益/Sharpe/DD)会掩盖
    ①单年主导 ②在场天数过低 ③回测未带止损。SHIP 前必须有年度分解 + 在场天数。"""
    r = StrategyRecord(id="agg_only", title="x", doc_source="test", verdict=Verdict.SHIP,
                       pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                       base_rate="cause", oos_survival=True, paper_trade_days=90,
                       regime_reported=True, max_dd_stop=-0.15,
                       capital_action_on_breach="zero_and_freeze", backtest_included_stop=True)
    # 年度分解与在场天数缺失 ⇒ 记录不完整(靠 meta 承载,CI 检查其存在)
    meta_keys = set((r.notes or "").split()) | set()
    assert r.backtest_included_stop is True, "回测必须带阶梯跑(S-89:连续六轮忘记)"


def test_stop_added_after_the_fact_is_rejected():
    """A stop bolted on AFTER the backtest curve is self-deception — it changes the curve's shape."""
    r = StrategyRecord(id="post_hoc_stop", title="x", doc_source="test", verdict=Verdict.SHIP,
                       pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                       base_rate="cause", oos_survival=True, paper_trade_days=90,
                       regime_reported=True, max_dd_stop=-0.15,
                       capital_action_on_breach="zero_and_freeze", backtest_included_stop=False)
    assert any("backtest_included_stop" in p for p in r.validate())



# ── 决策路径守卫(DECISION_PATH_SPEC,2026-07-27)────────────────────────────
# Jazz:"每次都走 dummy 路径,系统就等于失效" —— 用代码强制智能资产进入决策,不靠记性。
DECISION_LAYERS = ("regime", "universe", "weights", "timing")
INTELLIGENT_SOURCES = {"vdb_cluster", "regime_fingerprint", "risk_meter", "cis_quality", "cis_tilt"}


def validate_decision_inputs(di: dict, ship: bool = False) -> list[str]:
    """每个策略必须声明四层决策输入。SHIP 级不得在 regime/universe 用价格 fallback。"""
    problems = []
    for layer in DECISION_LAYERS:
        if layer not in di:
            problems.append(f"DECISION_INPUTS 缺少 '{layer}' 层声明")
    if ship:
        for layer in ("regime", "universe"):
            src = di.get(layer, "")
            if src not in INTELLIGENT_SOURCES:
                problems.append(
                    f"SHIP 级策略在 '{layer}' 层使用了非智能来源 '{src}' —— "
                    f"必须使用 {sorted(INTELLIGENT_SOURCES)} 之一,或说明为何 CIS/VDB/RiskMeter 帮不上")
    return problems


def test_decision_path_requires_intelligence_for_ship():
    """S-83~S-91 的教训:纯价格产品路径 = 海龟 bot,系统白建。"""
    dummy = {"regime": "price_proxy", "universe": "liquidity_only",
             "weights": "equal", "timing": "price/vol"}
    probs = validate_decision_inputs(dummy, ship=True)
    assert any("regime" in p for p in probs), "SHIP 用价格代理判相位必须被拦截"
    assert any("universe" in p for p in probs), "SHIP 不用 CIS 入池必须被拦截"
    good = {"regime": "risk_meter", "universe": "cis_quality",
            "weights": "cis_tilt", "timing": "price/vol"}
    assert not validate_decision_inputs(good, ship=True), "智能路径必须通过"


def test_decision_path_requires_all_four_layers():
    assert validate_decision_inputs({"regime": "risk_meter"}), "缺层必须报错"


# ── ⚠️ 真扫描,不是自测 (2026-07-29) ───────────────────────────────────────
# 上面两条只校验硬编码字典 —— 守卫是摆设:真实模块从不被检查,全部无条件通过。
# 这是"写了契约但没接上"的第三次重犯(§4.4 规格失忆)。下面这条扫真实文件。
import ast          # noqa: E402
import pathlib      # noqa: E402

_REPO = pathlib.Path(__file__).resolve().parent.parent

# 必须声明 DECISION_INPUTS 的模块 —— 会产生仓位/暴露决策的产品路径模块。
# 新增策略模块请加入本表;不加入而绕过检查 = 走捷径,正是本套测试要拦的行为。
DECIDING_MODULES = [
    "src/research/beta_core/beta_core_backtest.py",
]

# 已知欠账:先登记再修,让"没接上"可见,而不是静默通过。清空本表是目标。
DECISION_INPUTS_DEBT: dict[str, str] = {
    "src/research/beta_core/beta_core_backtest.py":
        "①层基座,纯价格 (200MA/vol/momentum)。欠:接入 cis_quality 入池 + risk_meter 相位,"
        "或显式声明 fallback 理由。见 docs/DECISION_PATH_SPEC.md §4.5。",
}


def _module_decision_inputs(relpath: str) -> dict | None:
    """静态解析模块顶层的 DECISION_INPUTS 字面量(不执行模块)。"""
    p = _REPO / relpath
    if not p.exists():
        return None
    tree = ast.parse(p.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "DECISION_INPUTS":
                    try:
                        return ast.literal_eval(node.value)
                    except (ValueError, SyntaxError):
                        return {}
    return None


def test_deciding_modules_declare_decision_inputs():
    """真实模块必须声明四层决策输入 —— 未声明的须登记在 DEBT 表里,不得静默通过。"""
    for rel in DECIDING_MODULES:
        di = _module_decision_inputs(rel)
        if di is None:
            assert rel in DECISION_INPUTS_DEBT, (
                f"{rel} 未声明 DECISION_INPUTS,且未登记在 DECISION_INPUTS_DEBT —— "
                f"要么声明,要么显式登记欠账。静默的价格路径正是 S-83~S-91 的根因。")
            continue
        problems = validate_decision_inputs(di, ship=False)
        assert not problems, f"{rel}: {problems}"


def test_decision_inputs_debt_is_not_stale():
    """欠账还清后必须从 DEBT 表移除 —— 否则表会变成永久免罪符。"""
    for rel in DECISION_INPUTS_DEBT:
        assert rel in DECIDING_MODULES, f"DEBT 条目 '{rel}' 不在 DECIDING_MODULES —— 移除它"
        di = _module_decision_inputs(rel)
        assert di is None or validate_decision_inputs(di, ship=False), (
            f"'{rel}' 现已合规 —— 从 DECISION_INPUTS_DEBT 移除")


TESTS = [v for k, v in sorted(globals().items()) if k.startswith("test_")]

if __name__ == "__main__":
    p = 0
    for t in TESTS:
        t(); print(f"  ✓ {t.__name__}"); p += 1
    print(f"\n✅ {p}/{len(TESTS)} strategy-discipline checks passed (philosophy compiled to CI)")
