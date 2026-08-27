"""Paper-trade 执行器:拒绝比成交更有信息 (S-254).

每条断言对着一个**今天实测过的现实**:

    binance_hist 最近 3 天 0/212 标的(S-251)  → 面板过期必须 BLOCKED,不能用旧价开仓
    三个 spec 是三种 schema                     → 未接线的 family 必须明确拒绝
    缺字段填默认值查不出来(S-122)              → 缺字段抛异常
    "规则拒绝" vs "规则跑不起来"(S-207)         → SKIPPED ≠ BLOCKED,且都必须带原因
"""
from __future__ import annotations

import json
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_trading.spec_runner import (                            # noqa: E402
    FAMILIES, MAX_PANEL_AGE_DAYS, Decision, Spec, UnwiredFamily, Verdict,
    build_panel, decide, exit_due, should_run_today)

SPEC_DIR = ROOT / "Shadow" / "cometcloud-local" / "paper_trading_specs"
M86 = SPEC_DIR / "m86_r22_k1_hold14_ret3d.json"

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _rows(n_days: int, last: str, syms=("BTC", "ETH", "SOL"), src="binance_hist"):
    out = []
    end = date.fromisoformat(last)
    for i in range(n_days):
        d = (end - timedelta(days=n_days - 1 - i)).isoformat()
        for j, s in enumerate(syms):
            out.append({"symbol": s, "trade_date": d, "close": 100 + i * (j + 1),
                        "source": src})
    return out


def test_stale_panel_blocks_instead_of_trading_on_old_prices():
    """**本文件的核心。** 面板过期 → BLOCKED,不是照常开仓。

    实测 2026-08-27:M-86 的 `data_source.primary = "binance_hist"`,
    而该源最近 3 天 **0/212 个标的**,自 08-09 起每天只写 BCH 一个(S-251)。
    一个照 spec 跑的 runner 会拿到历史面板、排序、**开一笔仓** ——
    那笔仓按 7 天前的价排,而 paper 记录里不会写"这天的价是 7 天前的"。

    **污染的不是这一笔,是整条曲线,而且不可分辨。**
    """
    if not M86.exists():
        _check("M-86 spec 存在", False, str(M86))
        return
    spec = Spec.load(M86)

    fresh = build_panel(_rows(10, "2026-08-27"), source="binance_hist")
    d_fresh = decide(spec, fresh, as_of=date(2026, 8, 27), regime="TIGHTENING", n_open=0)
    _check("面板新鲜 → ENTERED", d_fresh.verdict == Verdict.ENTERED,
           f"{d_fresh.verdict} {d_fresh.reason[:60]}")

    stale = build_panel(_rows(10, "2026-08-20"), source="binance_hist")
    d_stale = decide(spec, stale, as_of=date(2026, 8, 27), regime="TIGHTENING", n_open=0)
    _check("面板停在 7 天前 → BLOCKED(不是照常开仓)",
           d_stale.verdict == Verdict.BLOCKED, f"{d_stale.verdict}")
    _check("BLOCKED 的原因写出了 bar 日期与天数",
           "2026-08-20" in d_stale.reason and "7" in d_stale.reason,
           d_stale.reason[:80])
    _check("BLOCKED 时没有腿", not d_stale.legs)

    # 边界:恰好在阈值上必须还能跑,阈值+1 必须挡 —— 否则这条守卫要么永不触发
    # 要么永远触发,两种都等于没有。
    on_edge = build_panel(_rows(10, (date(2026, 8, 27)
                                     - timedelta(days=MAX_PANEL_AGE_DAYS)).isoformat()),
                          source="binance_hist")
    _check(f"恰好 {MAX_PANEL_AGE_DAYS} 天仍可开仓(阈值不是常闭)",
           decide(spec, on_edge, as_of=date(2026, 8, 27), regime=None,
                  n_open=0).verdict == Verdict.ENTERED)
    over = build_panel(_rows(10, (date(2026, 8, 27)
                                  - timedelta(days=MAX_PANEL_AGE_DAYS + 1)).isoformat()),
                       source="binance_hist")
    _check(f"{MAX_PANEL_AGE_DAYS + 1} 天 → BLOCKED",
           decide(spec, over, as_of=date(2026, 8, 27), regime=None,
                  n_open=0).verdict == Verdict.BLOCKED)


def test_blocked_is_not_skipped():
    """「规则说不开」和「我们算不了」是两件事 (S-207)。

    把它们压成"今天没开仓",纸面账就分不出策略在纪律地空仓、还是价源死了。
    前者是产品在工作,后者是我们瞎了。
    """
    spec = Spec.load(M86)
    fresh = build_panel(_rows(10, "2026-08-27"), source="binance_hist")

    d_open = decide(spec, fresh, as_of=date(2026, 8, 27), regime=None, n_open=99)
    _check("已达 max_open → SKIPPED(规则在工作)", d_open.verdict == Verdict.SKIPPED,
           d_open.verdict)

    thin = build_panel(_rows(10, "2026-08-27", syms=("BTC", "ETH")), source="binance_hist")
    d_thin = decide(spec, thin, as_of=date(2026, 8, 27), regime=None, n_open=0)
    _check("universe 缺标的 → BLOCKED(我们算不了)", d_thin.verdict == Verdict.BLOCKED,
           d_thin.verdict)
    _check("两者的 verdict 不同(没有被压成一个)", d_open.verdict != d_thin.verdict)

    # 空面板不是"今天没有机会"
    empty = build_panel([{"symbol": "BTC", "trade_date": "2026-08-27",
                          "close": None, "source": "binance_hist"}], source="binance_hist")
    d_empty = decide(spec, empty, as_of=date(2026, 8, 27), regime=None, n_open=0)
    _check("空面板 → BLOCKED,原因点明'不等于没有机会'",
           d_empty.verdict == Verdict.BLOCKED and "不等于" in d_empty.reason,
           d_empty.reason[:70])


def test_decision_refuses_to_exist_without_a_reason():
    """没有原因的 SKIPPED/BLOCKED 在构造时就抛 —— 不给它存在的机会。"""
    for v in (Verdict.SKIPPED, Verdict.BLOCKED):
        try:
            Decision(d="2026-08-27", spec_name="X", verdict=v)
            _check(f"{v} 无原因必须抛", False, "没抛")
        except ValueError:
            _check(f"{v} 无原因必须抛", True)
    try:
        Decision(d="2026-08-27", spec_name="X", verdict=Verdict.ENTERED)
        _check("ENTERED 无腿必须抛", False, "没抛")
    except ValueError:
        _check("ENTERED 无腿必须抛", True)


def test_unwired_families_refuse_loudly():
    """三个 spec 是三种 schema。**没接线的必须明确拒绝,不能用别的逻辑凑合。**

    M-88 是 regime 开关(按 BTC 21d 收益符号切两个子策略),
    不是横截面排名。硬吃会产生语法成功、语义错误的成交。
    """
    _check("FAMILIES 表里 cross_sectional_momentum_ls 已接",
           FAMILIES.get("cross_sectional_momentum_ls") is True)
    unwired = sorted(k for k, v in FAMILIES.items() if not v)
    _check(f"已知未接的 family 被明确登记({unwired})", len(unwired) >= 2, str(FAMILIES))

    for name in ("m87_beta_plus_cluster_tilt", "m88_beta_multiplier_btc_regime_switch"):
        p = SPEC_DIR / f"{name}.json"
        if not p.exists():
            continue
        try:
            Spec.load(p)
            _check(f"{name} 必须拒绝", False, "居然加载成功了 —— 那说明它被当成了别的 family")
        except UnwiredFamily as e:
            _check(f"{name} → UnwiredFamily", True)
            _check(f"  {name} 的拒绝说明了原因", "尚未接线" in str(e) or "还没有接线" in str(e),
                   str(e)[:60])


def test_missing_field_raises_instead_of_defaulting():
    """缺字段抛异常,不填默认值 (S-122)。

    一个默认的 `cost_bps_rt = 0` 会让每条曲线都好看一点,而且**不会有人发现** ——
    「默认值越接近多数类越查不出,危害与可发现性成反比」。
    """
    base = json.loads(M86.read_text())
    for missing in ("cost_bps_rt", "dd_stop_pct", "hold"):
        bad = json.loads(json.dumps(base))
        bad["parameters"].pop(missing, None)
        with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
            json.dump(bad, f)
            path = f.name
        try:
            Spec.load(path)
            _check(f"缺 {missing} 必须抛", False, "没抛 —— 它被默认了")
        except ValueError as e:
            _check(f"缺 {missing} 必须抛", "S-122" in str(e), str(e)[:60])
        finally:
            Path(path).unlink(missing_ok=True)

    # 负控制:完整的 spec 必须能加载,否则这条守卫等于把 runner 关死
    _check("负控制:完整 spec 能加载", Spec.load(M86).name == "M86_R22_K1_HOLD14_RET3D")


def test_dry_run_defaults_to_true():
    """`execution.dry_run` 缺失时必须是 True。**默认不能是实盘。**"""
    base = json.loads(M86.read_text())
    base.get("execution", {}).pop("dry_run", None)
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(base, f)
        path = f.name
    try:
        _check("dry_run 缺失 → True(默认不实盘)", Spec.load(path).dry_run is True)
    finally:
        Path(path).unlink(missing_ok=True)


def test_exit_reasons_are_distinguishable():
    """持满 vs 触止损是两件事,`exit_due` 必须说出是哪一个。"""
    spec = Spec.load(M86)
    e = date(2026, 8, 1)
    _check("止损触发时说 dd_stop",
           "dd_stop" in (exit_due(spec, entry_date=e, as_of=date(2026, 8, 2),
                                  pnl_pct=-20.0) or ""))
    _check("持满时说 hold",
           "hold" in (exit_due(spec, entry_date=e, as_of=e + timedelta(days=spec.hold),
                               pnl_pct=1.0) or ""))
    _check("都不满足时返回 None(继续持有)",
           exit_due(spec, entry_date=e, as_of=e + timedelta(days=1), pnl_pct=1.0) is None)


def test_cadence_gate():
    spec = Spec.load(M86)
    _check("首次运行总是跑", should_run_today(spec, as_of=date(2026, 8, 27), last_entry=None))
    _check(f"cadence {spec.cadence}d 未到 → 不跑",
           not should_run_today(spec, as_of=date(2026, 8, 27),
                                last_entry=date(2026, 8, 27) - timedelta(days=spec.cadence - 1)))
    _check("cadence 到了 → 跑",
           should_run_today(spec, as_of=date(2026, 8, 27),
                            last_entry=date(2026, 8, 27) - timedelta(days=spec.cadence)))


if __name__ == "__main__":
    print("── paper-trade 执行器:拒绝比成交更有信息 (S-254) ──")

    # ── 三值:通过 / 失败 / 没检查 ────────────────────────────────────────────
    # spec 住在 `Shadow/`(规则 #2:只读、非权威),而 Shadow 在 CI 或别人的机器上
    # 可能根本没挂载。一个"看不到就当通过"的守卫,会从一台从没检查过的机器上
    # 报绿 —— 那正是 S-163 记的 vacuous-pass,也是今天 S-244 的同一个形状。
    # **没检查不是通过,而且必须大声说出来。**
    if not M86.exists():
        print(f"  ⓘ NOT CHECKED —— spec 目录不存在:{SPEC_DIR}")
        print("     Shadow/ 未挂载(规则 #2:只读、非权威)。这【不是】通过。")
        print("     要真正检查这条,在挂了 Mac 卷的机器上跑。")
        sys.exit(0)

    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 执行器守卫全绿")
