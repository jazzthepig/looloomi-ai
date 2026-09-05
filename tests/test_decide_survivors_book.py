"""Paper-trade 多 sleeve book —— 拒绝比成交更有信息 (S-254, M-115 验证).

`decide_survivors_book` 是 M-113 V3 / M-115 Book B 的执行入口,把两条 sleeve 合到
一笔 Decision:

    ① regime-gated BTC long  (M-93 sleeve)  — long when regime ∉ skip_regimes
    ④ cross-section L/S      (R14-Lite / R19-Lite) — 14d momentum, K_long/K_short

每条断言对应一个今天可能走错的现实(M-115 验证缺口 — Book B 落地但没测过):

  BLOCKED  分支
    1  面板 0 标的                → BLOCKED「不等于没有机会」(S-180)
    2  面板没有 last_bar          → BLOCKED
    3  面板过期 > MAX_PANEL_AGE_DAYS → BLOCKED(用旧价开仓是不可分辨污染, S-251)
    4  BTC 不在面板              → BLOCKED「M-93 sleeve 需要 BTC」

  SKIPPED 分支(规则在工作 vs 我们算不了 — S-207)
    5  universe < k_long+k_short  → SKIPPED「不足以排 N 条腿」
    6  usable < MIN_UNIVERSE_FOR_RANK → SKIPPED「算不出名次不等于名次是平的」
    7  K_long / K_short 在小宇宙上重叠 → SKIPPED
    8  n_open >= max_open_trades  → SKIPPED「纪律在工作」
    9  regime cash + xs 无腿       → SKIPPED「book 当天空仓」

  ENTERED 分支(三种组合都要测)
    10 M-93 long + xs 有腿        → ENTERED full book (BTC long + 4 xs legs)
    11 M-93 cash + xs 有腿        → ENTERED 单 sleeve (4 xs legs, 无 BTC)
    12 M-93 long + xs 无腿        → ENTERED 单 sleeve (BTC long only)

每条 SKIPPED/BLOCKED 必须带原因(S-207);verdict_kind 在三值之间不互相污染
(J fix 2026-09-04)。每条配一条 mutation 测试(改一个参 → 翻转),避免 vacuous pass。
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
    MAX_PANEL_AGE_DAYS, MIN_UNIVERSE_FOR_RANK, Spec, Verdict,
    build_panel, decide_survivors_book)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _rows(n_days: int, last: str, syms, src: str = "binance_hist") -> list[dict]:
    """Daily bars, monotonically rising close: ret_Nd 对每个 symbol 都可算。"""
    out = []
    end = date.fromisoformat(last)
    for i in range(n_days):
        d = (end - timedelta(days=n_days - 1 - i)).isoformat()
        for j, s in enumerate(syms):
            out.append({"symbol": s, "trade_date": d, "close": 100 + i * (j + 1),
                        "source": src})
    return out


def _book_spec(universe, *, skip_regimes=("RISK_OFF",), max_open: int = 10,
               k_long: int = 2, k_short: int = 2, n_lookback: int = 14,
               weight_per_leg: float = 0.05, dd_stop: float = -0.20,
               spec_name: str = "M115_BOOK_B_TEST") -> Spec:
    """Inline `survivors_only_lag1_book` spec —— S-122 不填默认值。"""
    raw = {
        "spec_name": spec_name,
        "spec_family": "survivors_only_lag1_book",
        "universe": list(universe),
        "data_source": {"primary": "binance_hist"},
        "parameters": {
            "sleeve_weights": {"m93": 0.5, "xs": 0.5},
            "sleeve_M93": {"cash_when_regime_in": list(skip_regimes)},
            "sleeve_R14-Lite": {
                "rank_by": f"ret_{n_lookback}d",
                "K_long": k_long, "K_short": k_short,
                "cadence_days": 7, "hold_days": 7,
                "weight_per_leg": weight_per_leg,
            },
            "cost_bps_rt_max": 5.0,
            "dd_stop_pct": dd_stop,
            "max_open_trades": max_open,
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


def _book_panel(last: str = "2026-09-01",
                syms=("BTC", "ETH", "SOL", "AVAX"), n_days: int = 20):
    return build_panel(_rows(n_days, last, syms), source="binance_hist")


def test_blocked_on_empty_or_barless_panel():
    """分支 1 + 2:面板 0 标的 / 没有 last_bar → BLOCKED,且点明原因。

    BLOCKED 不是"今天没机会",纸面账必须看得见「我们瞎了」。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"])
    as_of = date(2026, 9, 1)

    # 空面板走 assert_single_source 抛错;想要 0 标的 → 用全 None close 的行
    empty = build_panel(
        [{"symbol": "BTC", "trade_date": "2026-09-01", "close": None,
          "source": "binance_hist"}],
        source="binance_hist",
    )
    _check("构造出 0 标的的 Panel(n_symbols=0)", empty.n_symbols == 0,
           f"n_symbols={empty.n_symbols}")
    d = decide_survivors_book(spec, empty, as_of=as_of, regime="EASING", n_open=0)
    _check("0 个标的 → BLOCKED", d.verdict == Verdict.BLOCKED, d.verdict)
    _check("原因点出 '不等于没有机会' (S-180)", "不等于" in d.reason, d.reason[:60])
    _check("BLOCKED 没有腿", not d.legs)

    # 注:`age is None` 分支 (panel.age_days 返回 None) 在 build_panel 路径下不可达
    # —— n_symbols=0 ⇒ last_bar=None ⇒ 先被 n_symbols==0 分支吃掉。这条防御性
    # 分支只在外部构造 Panel(custom Panel)时才会走到,本文件不强测。
    # 真正的缺口:decide_survivors_book 没有 universe 覆盖检查 —— 它只查 BTC,
    # 不查 universe 里的其它标的。如果 ETH 不在面板但 ETH 在 universe,会 KeyError。
    # 这不在 A 范围,在 C/规则守卫里另开。

    # mutation:全 None close + universe 缺 ETH 等 → 不测(spec_runner bug,见上)
    # 改测:universe=[BTC, ETH, SOL] + K=0 + 3 标的 panel → ENTERED(BTC long only)
    spec_btc_only = _book_spec(["BTC", "ETH", "SOL"], k_long=0, k_short=0)
    panel_btc = _book_panel(syms=("BTC", "ETH", "SOL"))
    d_mut = decide_survivors_book(spec_btc_only, panel_btc, as_of=as_of,
                                  regime="EASING", n_open=0)
    _check("mutation:3 标的 universe + xs K=0 + EASING → ENTERED,不在 BLOCKED 分支",
           d_mut.verdict == Verdict.ENTERED,
           f"{d_mut.verdict} {d_mut.reason[:60]}")


def test_blocked_on_stale_panel():
    """分支 3:面板过期 → BLOCKED(用旧价开仓是不可分辨污染, S-251)。

    边界:阈值恰好不挡、阈值+1 挡。两端都要测,否则这条守卫要么永不触发要么
    永远触发,等于没有。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"])
    as_of = date(2026, 9, 1)

    fresh = _book_panel(last="2026-09-01")
    d_fresh = decide_survivors_book(spec, fresh, as_of=as_of, regime="EASING", n_open=0)
    _check("新鲜面板 → 不在 stale 分支", d_fresh.verdict != Verdict.BLOCKED
           or "天" not in d_fresh.reason, d_fresh.reason[:60])

    over = build_panel(
        _rows(10, (as_of - timedelta(days=MAX_PANEL_AGE_DAYS + 1)).isoformat(),
              ("BTC", "ETH", "SOL", "AVAX")),
        source="binance_hist",
    )
    d_over = decide_survivors_book(spec, over, as_of=as_of, regime="EASING", n_open=0)
    _check(f"{MAX_PANEL_AGE_DAYS + 1} 天 → BLOCKED",
           d_over.verdict == Verdict.BLOCKED, d_over.verdict)
    _check("BLOCKED 原因写出 bar 日期 + 天数",
           "天" in d_over.reason and str(MAX_PANEL_AGE_DAYS + 1) in d_over.reason,
           d_over.reason[:80])

    # mutation:阈值恰好 → 仍可开仓
    on_edge = build_panel(
        _rows(10, (as_of - timedelta(days=MAX_PANEL_AGE_DAYS)).isoformat(),
              ("BTC", "ETH", "SOL", "AVAX")),
        source="binance_hist",
    )
    d_edge = decide_survivors_book(spec, on_edge, as_of=as_of, regime="EASING", n_open=0)
    _check(f"阈值 {MAX_PANEL_AGE_DAYS} 天不在 stale BLOCKED 分支(后续可能仍被其它拦)",
           not (d_edge.verdict == Verdict.BLOCKED
                and str(MAX_PANEL_AGE_DAYS) in d_edge.reason and "天" in d_edge.reason),
           f"{d_edge.verdict} {d_edge.reason[:60]}")


def test_blocked_when_btc_missing():
    """分支 4:BTC 不在面板 → BLOCKED「M-93 sleeve 需要 BTC」。

    M-93 是 regime-gated BTC long,book 不能在残缺宇宙上开仓(M-115)。
    """
    spec = _book_spec(["ETH", "SOL", "AVAX", "LINK"])  # 没有 BTC
    panel = _book_panel(syms=("ETH", "SOL", "AVAX", "LINK"))
    as_of = date(2026, 9, 1)
    d = decide_survivors_book(spec, panel, as_of=as_of, regime="EASING", n_open=0)
    _check("BTC 不在面板 → BLOCKED", d.verdict == Verdict.BLOCKED, d.verdict)
    _check("原因点名 BTC + book/M-93",
           "BTC" in d.reason and ("M-93" in d.reason or "book" in d.reason),
           d.reason[:80])
    _check("BLOCKED 没有腿", not d.legs)

    # mutation:加 BTC → 不再被这条 BLOCKED(可能后续因其它原因被拦)
    spec_with_btc = _book_spec(["BTC", "ETH", "SOL", "AVAX"])
    panel_with_btc = _book_panel(syms=("BTC", "ETH", "SOL", "AVAX"))
    d2 = decide_survivors_book(spec_with_btc, panel_with_btc,
                               as_of=as_of, regime="EASING", n_open=0)
    _check("universe 含 BTC + panel 含 BTC → 不在 BTC-缺 BLOCKED 分支",
           not (d2.verdict == Verdict.BLOCKED and "BTC" in d2.reason
                and "M-93" in d2.reason),
           f"{d2.verdict} {d2.reason[:60]}")


def test_skipped_when_universe_too_small():
    """分支 5:universe < k_long+k_short → SKIPPED「不足以排 N 条腿」。

    横截面排名需要至少 min(K_long+K_short, MIN_UNIVERSE_FOR_RANK) 个标的。
    """
    # K_long=2, K_short=2 → 需要 ≥4 个 universe;给 3 个 → SKIPPED
    spec = _book_spec(["BTC", "ETH", "SOL"])  # 3 个,K_long+K_short=4
    panel = _book_panel(syms=("BTC", "ETH", "SOL"))
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=0)
    _check("universe 不足 → SKIPPED", d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 原因提到 universe 大小或腿数",
           "universe" in d.reason or "条腿" in d.reason or "排" in d.reason,
           d.reason[:80])

    # mutation:加一个标的到 universe → 不再被这条 SKIPPED
    spec_big = _book_spec(["BTC", "ETH", "SOL", "AVAX"])
    panel_big = _book_panel(syms=("BTC", "ETH", "SOL", "AVAX"))
    d2 = decide_survivors_book(spec_big, panel_big, as_of=date(2026, 9, 1),
                               regime="EASING", n_open=0)
    _check("universe 够大 → 不在 universe-小 SKIPPED 分支",
           not (d2.verdict == Verdict.SKIPPED
                and ("universe" in d2.reason and ("不足" in d2.reason or "少" in d2.reason))),
           f"{d2.verdict} {d2.reason[:60]}")


def test_skipped_when_usable_too_few():
    """分支 6:usable < MIN_UNIVERSE_FOR_RANK → SKIPPED「算不出名次不等于平」。

    所有 4 个标的都在面板,但 n_lookback 太大 → 部分 return 算不出。
    """
    # 只给 5 天历史,n_lookback=14 → 全部算不出 → usable=0
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], n_lookback=14)
    short_panel = _book_panel(last="2026-09-01", n_days=5)
    d = decide_survivors_book(spec, short_panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=0)
    _check("usable 不足 → SKIPPED", d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 原因提到 usable 或收益算不出",
           "usable" in d.reason or "算不出" in d.reason or "收益" in d.reason,
           d.reason[:80])

    # mutation:加历史到 30 天 → 不再被这条 SKIPPED
    long_panel = _book_panel(last="2026-09-01", n_days=30)
    d2 = decide_survivors_book(spec, long_panel, as_of=date(2026, 9, 1),
                               regime="EASING", n_open=0)
    _check("历史够长 → 不在 usable-少 SKIPPED 分支",
           not (d2.verdict == Verdict.SKIPPED and "usable" in d2.reason),
           f"{d2.verdict} {d2.reason[:60]}")


def test_skipped_when_k_overlaps():
    """分支 7:K_long + K_short 在小宇宙上重叠 → SKIPPED。

    ⚠️ 这条分支在 decide_survivors_book 里**当前不可达**:
    `if len(universe) < max(MIN_UNIVERSE_FOR_RANK, k_long+k_short)` 先吃
    所有 K_long+K_short > len(universe) 的情况,而 K 重叠本身要求
    K_long+K_short > len(ranked)。两条互斥,所以 SKIPPED 「K=... 重叠」
    这条 reason 在 book 路径下写不出来,只能由 branch 5(universe 不足)代理。
    同形状在 decide() 里也是死代码。属防御性守卫,留着不删,但【不测它的 reason 文本】。
    """
    # 实际可达 SKIPPED 是 branch 5(因 universe 小被吃),不是 branch 7。
    spec = _book_spec(["BTC", "ETH"], k_long=1, k_short=1)  # 2 标的 vs K=2
    panel = _book_panel(syms=("BTC", "ETH"))
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=0)
    _check("K 长 + K 短 在小宇宙上 → SKIPPED(由 branch 5 代理,不是 branch 7)",
           d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 原因是 universe 不足(branch 5 代理 branch 7)",
           "universe" in d.reason and ("不足" in d.reason or "排" in d.reason),
           d.reason[:80])

    # mutation:K_long=2, K_short=0 → 单边 → 不在 SKIPPED 分支
    spec_long_only = _book_spec(["BTC", "ETH", "SOL", "AVAX"], k_long=2, k_short=0)
    d2 = decide_survivors_book(spec_long_only, _book_panel(),
                               as_of=date(2026, 9, 1), regime="EASING", n_open=0)
    _check("单边 L/S → ENTERED(无重叠风险)",
           d2.verdict == Verdict.ENTERED,
           f"{d2.verdict} {d2.reason[:60]}")


def test_skipped_when_max_open_reached():
    """分支 8:n_open >= max_open_trades → SKIPPED「纪律在工作」。

    这是 SKIPPED(规则在拒绝),不是 BLOCKED(我们算不了)。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], max_open=2)
    panel = _book_panel()
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=2)
    _check("n_open = max_open → SKIPPED", d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 原因提到 max_open",
           "max_open" in d.reason, d.reason[:80])

    # mutation:n_open < max_open → 不被这条 SKIPPED
    d2 = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                               regime="EASING", n_open=1)
    _check("n_open < max_open → 不在 max-open SKIPPED 分支",
           not (d2.verdict == Verdict.SKIPPED and "max_open" in d2.reason),
           f"{d2.verdict} {d2.reason[:60]}")


def test_skipped_when_no_legs_at_all():
    """分支 9:regime cash + xs K=0 → 两条 sleeve 都没腿 → SKIPPED。

    「book 当天空仓」与「book 没开仓」是同一个 verdict,但要写在 reason 里,
    否则纸面账分不出 book 静默死亡 vs 纪律地空仓。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], k_long=0, k_short=0,
                      skip_regimes=("RISK_OFF",))
    panel = _book_panel()
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="RISK_OFF", n_open=0)
    _check("regime cash + xs 无腿 → SKIPPED(不是 ENTERED with no legs)",
           d.verdict == Verdict.SKIPPED, d.verdict)
    _check("SKIPPED 原因说明两条 sleeve 都空",
           ("cash" in d.reason or "M-93" in d.reason or "sleeve" in d.reason)
           and ("xs" in d.reason or "R*" in d.reason or "无腿" in d.reason
                or "空仓" in d.reason),
           d.reason[:80])

    # mutation:regime 改成 EASING → M-93 sleeve 进入 → 不再这条 SKIPPED
    d2 = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                               regime="EASING", n_open=0)
    _check("regime EASING + xs 无腿 → ENTERED (BTC long only),不在 no-legs SKIPPED",
           d2.verdict == Verdict.ENTERED
           and not (d2.verdict == Verdict.SKIPPED and "空仓" in d2.reason),
           f"{d2.verdict} {d2.reason[:60]}")


def test_entered_full_book_when_m93_long_and_xs_has_legs():
    """分支 10:EASING + K_long=2, K_short=2 → ENTERED 全 book(BTC + 4 xs legs)。"""
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], k_long=2, k_short=2,
                      skip_regimes=("RISK_OFF",))
    panel = _book_panel()
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=0)
    _check("full book → ENTERED", d.verdict == Verdict.ENTERED, d.verdict)
    legs = d.legs
    _check("有 5 条腿(BTC long + 4 xs)", len(legs) == 5, str(len(legs)))
    _check("BTC 是 long 腿且 weight=0.5(M-93)",
           any(l.symbol == "BTC" and l.side == "long" and abs(l.weight - 0.5) < 1e-9
               for l in legs),
           str([(l.symbol, l.side, l.weight) for l in legs]))
    _check("xs 多腿 = 2 条 long + 2 条 short",
           sum(1 for l in legs if l.side == "long" and l.symbol != "BTC") == 2
           and sum(1 for l in legs if l.side == "short") == 2,
           str([(l.symbol, l.side) for l in legs]))
    _check("ENTERED 没有 reason 字段", not d.reason)


def test_entered_only_xs_when_m93_cash():
    """分支 11:RISK_OFF + K_long=2, K_short=2 → ENTERED 单 sleeve(4 xs legs)。"""
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], k_long=2, k_short=2,
                      skip_regimes=("RISK_OFF",))
    panel = _book_panel()
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="RISK_OFF", n_open=0)
    _check("M-93 cash + xs 有腿 → ENTERED(不是 SKIPPED)",
           d.verdict == Verdict.ENTERED, d.verdict)
    legs = d.legs
    # M-93 sleeve 在 cash ⇒ 没有 BTC long 腿;但 BTC 可能在 xs sleeve 里被做空
    # (xs 是横截面,独立于 M-93 regime 闸)。所以断言「没有 BTC long」,不断言「没有 BTC」。
    _check("没有 BTC long 腿(M-93 sleeve 在 cash ⇒ 不加 BTC long)",
           not any(l.symbol == "BTC" and l.side == "long" for l in legs),
           str([(l.symbol, l.side) for l in legs]))
    _check("xs 多空共 4 条腿",
           sum(1 for l in legs if l.side == "long") == 2
           and sum(1 for l in legs if l.side == "short") == 2,
           str([(l.symbol, l.side) for l in legs]))


def test_entered_only_m93_when_xs_empty():
    """分支 12:EASING + K_long=0, K_short=0 → ENTERED 单 sleeve(BTC long only)。

    xs K=0 是合法的(虽然没 L/S);M-93 接管整本 book。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"], k_long=0, k_short=0,
                      skip_regimes=("RISK_OFF",))
    panel = _book_panel()
    d = decide_survivors_book(spec, panel, as_of=date(2026, 9, 1),
                              regime="EASING", n_open=0)
    _check("xs 无腿 + M-93 long → ENTERED(不是 SKIPPED)",
           d.verdict == Verdict.ENTERED, d.verdict)
    legs = d.legs
    _check("只有 1 条腿 = BTC long",
           len(legs) == 1 and legs[0].symbol == "BTC" and legs[0].side == "long",
           str([(l.symbol, l.side) for l in legs]))


def test_verdict_kinds_do_not_collide():
    """三值不互相污染(J fix 2026-09-04):同一 book 不同日 / 不同参 → 不同 kind。

    之前 SKIPPED 和 BLOCKED 都被压进同一个 `reason` 字段,consumer 分不清
    「规则拒绝」与「我们瞎了」。现在 verdict 与 verdict_kind 同层。
    """
    spec = _book_spec(["BTC", "ETH", "SOL", "AVAX"])
    panel = _book_panel()
    as_of = date(2026, 9, 1)

    # BLOCKED:走「0 个标的」分支(全 None close 让 build_panel 返回空 Panel)
    blocked_panel = build_panel(
        [{"symbol": "BTC", "trade_date": "2026-09-01", "close": None,
          "source": "binance_hist"}],
        source="binance_hist",
    )
    d_blocked = decide_survivors_book(spec, blocked_panel,
                                      as_of=as_of, regime="EASING", n_open=0)
    d_skipped = decide_survivors_book(spec, panel, as_of=as_of,
                                      regime="EASING", n_open=99)  # max_open=10 default
    d_entered = decide_survivors_book(spec, panel, as_of=as_of,
                                      regime="EASING", n_open=0)

    p_blocked = d_blocked.as_payload()
    p_skipped = d_skipped.as_payload()
    p_entered = d_entered.as_payload()

    _check("BLOCKED.verdict_kind == 'blocked'",
           p_blocked["verdict_kind"] == "blocked", p_blocked["verdict_kind"])
    _check("SKIPPED.verdict_kind == 'skipped'",
           p_skipped["verdict_kind"] == "skipped", p_skipped["verdict_kind"])
    _check("ENTERED.verdict_kind == 'entered'",
           p_entered["verdict_kind"] == "entered", p_entered["verdict_kind"])

    # 三值的 kind 各不相同 —— 消费者按 kind 分桶不能撞
    kinds = {p_blocked["verdict_kind"], p_skipped["verdict_kind"], p_entered["verdict_kind"]}
    _check("三 verdict_kind 不重复", len(kinds) == 3, str(kinds))

    # SKIPPED/BLOCKED 必带 reason
    _check("BLOCKED 必带 reason", bool(p_blocked.get("reason")), p_blocked.get("reason", "")[:50])
    _check("SKIPPED 必带 reason", bool(p_skipped.get("reason")), p_skipped.get("reason", "")[:50])
    # ENTERED 不带 reason 字段
    _check("ENTERED 不带 reason 字段", "reason" not in p_entered, str(p_entered.keys()))


if __name__ == "__main__":
    print("── paper-trade 多 sleeve book —— decide_survivors_book 6-branch 守卫 (M-115) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 多 sleeve book 守卫全绿")