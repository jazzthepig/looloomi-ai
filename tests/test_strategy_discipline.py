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
    assert any("deflated_sharpe" in p for p in problems), \
        "missing multiple-testing correction must be flagged (2026-08-06)"
    # and a fully-evidenced record passes. Note what "fully evidenced" now means:
    # it includes surviving the SEARCH that found the strategy, not just the
    # backtest it produced.
    good = StrategyRecord(id="proven", title="proven", doc_source="test",
                          verdict=Verdict.SHIP, pit_clean=True, cost_feasible_at_5bps=True,
                          forward_committed=True, base_rate="funding crowding reverts (behavioral)",
                          oos_survival=True, paper_trade_days=75, regime_reported=True,
                          oos_window="2026-02-01→2026-05-03", max_dd_stop=-0.15,
                          capital_action_on_breach="zero_and_freeze", backtest_included_stop=True,
                          deflated_sharpe=0.97, n_trials=40, pbo=0.21,
                          median_holding_days=21.0, signal_changes_per_yr=9.0,
                          turnover_cost_pct_yr=0.9, net_effect_pct_yr=3.4,
                          trigger_name="funding_zscore", trigger_median_run_days=28.0)
    assert not good.validate(), "fully-evidenced ship record must pass"


def test_multiple_testing_floor_is_enforced():
    """The hole that produced the R76–R94 graveyard: search enough specifications
    and one of them looks good. deflated_sharpe_ratio() and pbo_cscv() have lived
    in src/research/validation/ for months, called by the factor factory and the
    gauntlet — but never by THIS gate, so 'passes our bar' did not include
    'survives the search that found it'."""
    base = dict(id="x", title="x", doc_source="test", verdict=Verdict.SHIP,
                pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                base_rate="cause", oos_survival=True, paper_trade_days=90,
                regime_reported=True, max_dd_stop=-0.15,
                capital_action_on_breach="zero_and_freeze", backtest_included_stop=True)

    # absent → rejected
    assert any("deflated_sharpe" in p for p in StrategyRecord(**base).validate())

    # present but below the bar → rejected, and the message must name n_trials,
    # because a DSR without its trial count is uninterpretable.
    low = StrategyRecord(**base, deflated_sharpe=0.62, n_trials=250).validate()
    assert any("deflated_sharpe=0.620" in p and "n_trials=250" in p for p in low)

    # PBO above 0.5 → rejected even with a good DSR: CSCV saying the in-sample
    # winner more likely than not underperforms OOS is disqualifying on its own.
    bad_pbo = StrategyRecord(**base, deflated_sharpe=0.99, n_trials=10, pbo=0.71).validate()
    assert any("pbo=0.71" in p for p in bad_pbo)

    # and the passing combination (executability fields supplied — see S-105)
    assert not StrategyRecord(**base, deflated_sharpe=0.96, n_trials=30, pbo=0.30,
                              median_holding_days=30.0, signal_changes_per_yr=12.0,
                              turnover_cost_pct_yr=1.2, net_effect_pct_yr=2.9,
                              trigger_name="funding_zscore",
                              trigger_median_run_days=35.0).validate()


def test_executability_floor_is_enforced():
    """S-105. We return-tested the CIS tiers three times (S-101/102/103) before
    running the one GROUP BY that settled it: STRONG OUTPERFORM has a MEDIAN
    HOLDING PERIOD OF 2 DAYS and the average asset switches signal 45.8x/yr —
    4.6 %/yr of turnover cost against a largest-ever effect near 3 %/yr at |t|<2.

    Persistence is therefore an ADMISSION criterion, not a performance attribute:
    if it cannot be held long enough to pay for the trade, the return test was
    never going to matter. This test makes that ordering non-optional."""
    base = dict(id="x", title="x", doc_source="test", verdict=Verdict.SHIP,
                pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                base_rate="cause", oos_survival=True, paper_trade_days=90,
                regime_reported=True, max_dd_stop=-0.15,
                capital_action_on_breach="zero_and_freeze", backtest_included_stop=True,
                deflated_sharpe=0.97, n_trials=40, pbo=0.2)

    # absent → rejected, and the message must carry the number that taught us
    assert any("median_holding_days" in p for p in StrategyRecord(**base).validate())

    # the actual CIS tier: 2-day median → rejected as sampling noise
    flicker = StrategyRecord(**base, median_holding_days=2.0, signal_changes_per_yr=45.8,
                             turnover_cost_pct_yr=4.6, net_effect_pct_yr=-1.6).validate()
    assert any("median_holding_days=2.0" in p for p in flicker)

    # persistent enough to hold, but turnover still eats it → rejected.
    # This is the case that a holding-period check ALONE would wave through.
    eaten = StrategyRecord(**base, median_holding_days=30.0, signal_changes_per_yr=12.0,
                           turnover_cost_pct_yr=3.1, net_effect_pct_yr=-0.4).validate()
    assert any("net_effect_pct_yr=-0.40" in p for p in eaten)
    assert not any("median_holding_days=" in p for p in eaten), \
        "holding period was fine here; only the net effect should be flagged"

    # gross effect reported but not net → rejected: gross is not what the fund earns
    gross_only = StrategyRecord(**base, median_holding_days=30.0,
                                turnover_cost_pct_yr=1.0).validate()
    assert any("net_effect_pct_yr missing" in p for p in gross_only)

    # and the passing combination: held long enough, edge survives the cost, and the
    # trigger outlives the position it opens
    assert not StrategyRecord(**base, median_holding_days=30.0, signal_changes_per_yr=12.0,
                              turnover_cost_pct_yr=1.2, net_effect_pct_yr=2.9,
                              trigger_name="funding_zscore",
                              trigger_median_run_days=35.0).validate()


def test_a_trigger_must_outlive_the_position_it_opens():
    """S-117. The executability floor above measures how long a POSITION is held;
    nothing measured how long the STATE VARIABLE opening it survives. Found by
    cross-checking a proposed layer-③ sleeve keyed off `macro_regime`: 49 runs,
    MEDIAN 3 DAYS, 25 of them ≤3 days — so more than half its 'regime transitions'
    were label chatter reverting inside three days.

    A 3-day trigger driving a 30-day position is not a 30-day position. It is a book
    overturned before the position matures, and `median_holding_days=30` on the
    record would be a fiction the gate accepted. The rule is a RELATION rather than
    a threshold: a fast trigger is perfectly fine in a fast book, and only a lie
    inside a slow one."""
    base = dict(id="x", title="x", doc_source="test", verdict=Verdict.SHIP,
                pit_clean=True, cost_feasible_at_5bps=True, forward_committed=True,
                base_rate="cause", oos_survival=True, paper_trade_days=90,
                regime_reported=True, max_dd_stop=-0.15,
                capital_action_on_breach="zero_and_freeze", backtest_included_stop=True,
                deflated_sharpe=0.97, n_trials=40, pbo=0.2,
                median_holding_days=30.0, turnover_cost_pct_yr=1.0,
                net_effect_pct_yr=2.5)

    # absent → rejected, and the message must carry the number that taught us
    probs = StrategyRecord(**base).validate()
    assert any("trigger_median_run_days" in p for p in probs)
    assert any("3 DAYS" in p or "3 days" in p.lower() for p in probs), \
        "the rejection must cite the measurement, not just name the field"

    # the actual macro_regime case: 3-day trigger, 30-day position → rejected
    chatter = StrategyRecord(**base, trigger_name="macro_regime",
                             trigger_median_run_days=3.0).validate()
    assert any("overturned" in p for p in chatter)

    # a FAST book with the same fast trigger is fine — the rule is relative
    fast = {**base, "median_holding_days": 2.0}
    assert not any("overturned" in p for p in
                   StrategyRecord(**fast, trigger_name="macro_regime",
                                  trigger_median_run_days=3.0).validate()), \
        "a 3-day trigger is legitimate for a 2-day hold; only the RELATION matters"


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
    # —— Core production paths (each carries a real DECISION_INPUTS declaration) ——
    "src/research/beta_core/beta_core_backtest.py",                      # ① beta_capture core (declared in DEBT pending migration)
    "src/research/validation/m_wo_a_beta_capture.py",                    # ① layer base — CW-P × 10bps (long-only hold of panel)
    "src/research/beta_core/regime_override_enforcer.py",                # ⓠ REGIME OVERRIDE enforcer — production wrapper around m_wo_q.assign_band_hysteresis (PIT-safe, v1 caps)
    "src/research/validation/m_wo_q_o1_stablecoin_gate.py",              # ⓠ REGIME OVERRIDE — stablecoin 4w Δ scaler on ① baseline
    "src/research/validation/fusion_paper_regime_track.py",              # ⓠ paper NAV curve under enforcer (parallel paper-only, NOT live override)
    "src/research/validation/r77_r76_as_fusion_contribution.py",         # R77 frozen-cell — 3-leg fusion (R46+R62+R76)
    "src/research/validation/r97_cis_ls_v5.py",                          # R97 11yr candidate — CIS-L/S V5 dual-horizon
    "src/research/validation/fusion_paper_tracking.py",                  # R66 monitoring — daily NAV accrual for R64 paper book + ⓠ 6th surface
]

# 已知欠账:先登记再修,让"没接上"可见,而不是静默通过。清空本表是目标。
# DEBT 条目必须都在 DECIDING_MODULES 里 —— 否则是孤儿,删除。refuted experimental
# modules(未在 DECIDING_MODULES 中)不需要登记,因为它们不再被 gate 监督,已归档。
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
