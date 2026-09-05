"""Paper-trade 多 sleeve book —— regime_quorum 闸 (S-284 C fix).

`decide_gated` 是 `decide` 的 wrapper,在 book / sleeve 决定仓位之前先看
regime 标签本身可不可信。一个「全票通过」的 TIGHTENING 如果**票数已经塌了**
(`verdict=COLLAPSED`),它通过 SKIPPED 看起来像「regime 在 TIGHTENING 不开仓」
—— 真相是「regime 这个标签今天不可信,不该用来定仓位」(S-263)。

五值裁决(参 src/data/market/regime_quorum.py):
    ok / thin       → usable=True  → 放行
    COLLAPSED       → usable=False → 闸住
    frozen          → usable=False → 闸住
    no_baseline     → usable=False → 闸住(没量过 ≠ 健康, S-246)
    no_data         → usable=False → 闸住

每条裁决 + 一条 mutation 测试(改 verdict → 翻转);同时测家族分派
(book family 路由到 decide_survivors_book,非 book family 路由到 decide)。
"""
from __future__ import annotations

import sys
import tempfile
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from paper_trading.spec_runner import (                            # noqa: E402
    Spec, Verdict, build_panel, decide, decide_gated, decide_survivors_book)
from src.data.market.regime_quorum import (                        # noqa: E402
    RegimeQuorum, OK, THIN, COLLAPSED, FROZEN, NO_BASELINE, NO_DATA)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _rows(n_days: int, last: str, syms, src: str = "binance_hist") -> list[dict]:
    out = []
    end = date.fromisoformat(last)
    for i in range(n_days):
        d = (end - timedelta(days=n_days - 1 - i)).isoformat()
        for j, s in enumerate(syms):
            out.append({"symbol": s, "trade_date": d, "close": 100 + i * (j + 1),
                        "source": src})
    return out


def _book_spec(universe=("BTC", "ETH", "SOL", "AVAX"),
               k_long: int = 2, k_short: int = 2) -> Spec:
    raw = {
        "spec_name": "M115_BOOK_B_QUORUM_TEST",
        "spec_family": "survivors_only_lag1_book",
        "universe": list(universe),
        "data_source": {"primary": "binance_hist"},
        "parameters": {
            "sleeve_weights": {"m93": 0.5, "xs": 0.5},
            "sleeve_M93": {"cash_when_regime_in": ["RISK_OFF"]},
            "sleeve_R14-Lite": {
                "rank_by": "ret_14d", "K_long": k_long, "K_short": k_short,
                "cadence_days": 7, "hold_days": 7, "weight_per_leg": 0.05,
            },
            "cost_bps_rt_max": 5.0,
            "dd_stop_pct": -0.20,
            "max_open_trades": 10,
        },
        "execution": {"dry_run": True},
    }
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump(raw, f)
        path = f.name
    try:
        return Spec.load(path)
    finally:
        Path(path).unlink(missing_ok=True)


def _panel(last: str = "2026-09-01", syms=("BTC", "ETH", "SOL", "AVAX")):
    return build_panel(_rows(20, last, syms), source="binance_hist")


def _rq(verdict: str, *, reason: str = "test fixture") -> RegimeQuorum:
    """Build a RegimeQuorum with given verdict; rest of fields are placeholders."""
    return RegimeQuorum(
        d="2026-09-01", regime="TIGHTENING",
        n_obs=100, n_sources=2, verdict=verdict, reason=reason,
    )


def test_quorum_none_passes_through():
    """`quorum=None` → 不加闸,与原 decide()/decide_survivors_book() 一致。

    现有 caller 不变(S-284 向后兼容)。
    """
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)

    # book family
    d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                     quorum=None)
    _check("book + quorum=None → ENTERED(原行为)",
           d.verdict == Verdict.ENTERED, d.verdict)
    _check("路由到 decide_survivors_book(5 条腿)",
           len(d.legs) == 5, f"{len(d.legs)} legs")

    # 模拟直接调 decide() 应得到相同结果(因为 decide_gated(None) 直接走 decide())
    d_via_decide = decide(spec, panel, as_of=as_of, regime="EASING", n_open=0)
    _check("quorum=None 透传(verdict 同)",
           d.verdict == d_via_decide.verdict,
           f"gated={d.verdict} vs decide={d_via_decide.verdict}")


def test_quorum_ok_thin_pass_through():
    """verdict=ok / thin → 放行(usable=True)。

    thin 是「可用但须标注」,不放行会让「高源数低票数」的好日子被误杀。
    """
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)

    for verdict, label in [(OK, "ok"), (THIN, "thin")]:
        d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                         quorum=_rq(verdict))
        _check(f"book + quorum.{label} → ENTERED(放行)",
               d.verdict == Verdict.ENTERED, f"{label}: {d.verdict}")


def test_quorum_collapsed_blocks_book():
    """verdict=COLLAPSED → SKIPPED,reason 写出裁决与原因。

    这是核心:塌陷的「全票通过」不能用来定仓位(S-263)。
    """
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)
    quorum = _rq(COLLAPSED,
                 reason="信源数 1(基线中位数 3)—— 「全票通过」是减员产生的")
    d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                     quorum=quorum)
    _check("book + COLLAPSED → SKIPPED(不是 ENTERED)",
           d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 必带 reason", bool(d.reason), d.reason[:60])
    _check("reason 写出 verdict",
           "COLLAPSED" in d.reason, d.reason[:100])
    _check("reason 引用 quorum 自己写的 reason(可追到源头)",
           "信源" in d.reason and "减员" in d.reason, d.reason[:100])
    _check("SKIPPED 没有腿", not d.legs)

    # mutation:换成 ok → 应该放行(ENTERED)
    d2 = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                      quorum=_rq(OK))
    _check("mutation:quorum=COLLAPSED → ok → ENTERED(闸真起作用)",
           d2.verdict == Verdict.ENTERED,
           f"{d2.verdict} {d2.reason[:60]}")


def test_quorum_frozen_blocks_book():
    """verdict=frozen → SKIPPED(标签停太久,可能是判断也可能是输入死了)。"""
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)
    d = decide_gated(spec, panel, as_of=as_of, regime="TIGHTENING", n_open=0,
                     quorum=_rq(FROZEN, reason="TIGHTENING 已停留 40 天"))
    _check("book + frozen → SKIPPED", d.verdict == Verdict.SKIPPED, d.verdict)
    _check("reason 写 frozen",
           "frozen" in d.reason.lower(), d.reason[:80])

    # mutation:换成 ok → 放行
    d2 = decide_gated(spec, panel, as_of=as_of, regime="TIGHTENING", n_open=0,
                      quorum=_rq(OK))
    _check("mutation:frozen → ok → ENTERED", d2.verdict == Verdict.ENTERED,
           f"{d2.verdict} {d2.reason[:60]}")


def test_quorum_no_baseline_blocks_book():
    """verdict=no_baseline → SKIPPED(没量过 ≠ 健康, S-246)。"""
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)
    d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                     quorum=_rq(NO_BASELINE, reason="基线窗口只有 5 天"))
    _check("book + no_baseline → SKIPPED", d.verdict == Verdict.SKIPPED,
           d.verdict)
    _check("reason 写 no_baseline",
           "no_baseline" in d.reason, d.reason[:100])

    # mutation:换成 thin → 放行(thin 也是 usable)
    d2 = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                      quorum=_rq(THIN))
    _check("mutation:no_baseline → thin → ENTERED", d2.verdict == Verdict.ENTERED,
           f"{d2.verdict} {d2.reason[:60]}")


def test_quorum_no_data_blocks_book():
    """verdict=no_data → SKIPPED(没有行就什么都没有 —— 但不是「今天没机会」)。"""
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)
    d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                     quorum=_rq(NO_DATA, reason="daily_macro_regime 没有可用行"))
    _check("book + no_data → SKIPPED", d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED(不是 BLOCKED —— quorum 闸是 SKIPPED,不是数据缺失)",
           d.verdict == Verdict.SKIPPED, d.verdict)


def test_quorum_gate_routes_to_survivors_book():
    """闸也覆盖 book family —— 因为 decide() 内部已路由到 decide_survivors_book()。

    家族分派 + 闸分派 各自独立,合起来:non-book family 的闸也工作。
    """
    spec = _book_spec()
    panel = _panel()
    as_of = date(2026, 9, 1)

    # COLLAPSED 在 book family 上 SKIPPED
    d = decide_gated(spec, panel, as_of=as_of, regime="EASING", n_open=0,
                     quorum=_rq(COLLAPSED))
    _check("book + COLLAPSED → SKIPPED(且 reason 不含 M-93 任何特征)",
           d.verdict == Verdict.SKIPPED and "M-93" not in d.reason,
           d.reason[:80])
    # 没走到 decide_survivors_book,所以不会因为 universe 小 / BTC 缺 被拦


def test_quorum_gate_does_not_change_blocked_path():
    """闸不应该改变 BLOCKED 路径:数据算不了 ≠ 闸住。

    COLLAPSED quorum + 空面板 → SKIPPED(quorum 闸先),不是 BLOCKED(数据问题)。
    空面板 + ok quorum → BLOCKED(数据问题,quorum 不挡)。
    """
    spec = _book_spec()
    as_of = date(2026, 9, 1)

    blocked_panel = build_panel(
        [{"symbol": "BTC", "trade_date": "2026-09-01", "close": None,
          "source": "binance_hist"}],
        source="binance_hist",
    )
    d_collapsed = decide_gated(spec, blocked_panel, as_of=as_of,
                                regime="EASING", n_open=0,
                                quorum=_rq(COLLAPSED))
    _check("COLLAPSED + 空面板 → SKIPPED(闸先于 BLOCKED)",
           d_collapsed.verdict == Verdict.SKIPPED, d_collapsed.verdict)

    d_ok = decide_gated(spec, blocked_panel, as_of=as_of,
                        regime="EASING", n_open=0, quorum=_rq(OK))
    _check("ok + 空面板 → BLOCKED(数据算不了)",
           d_ok.verdict == Verdict.BLOCKED, d_ok.verdict)


if __name__ == "__main__":
    print("── paper-trade 多 sleeve book —— decide_gated regime_quorum 闸 (S-284 C) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ regime_quorum 闸守卫全绿")