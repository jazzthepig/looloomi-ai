"""战绩面板:一次只用一种度量,拒绝比数字更有信息 (S-248).

每条断言钉住一个**实测发生过**的缺陷,不是假想:

    标题写 α,曲线复利 return_pct        → 度量必须自报家门
    曲线用 8 天退出,胜率用 30 天窗口     → 两种度量不得混算
    83/95 行用被禁价源                   → 按 outcome_source 分层
    12 个可信样本给出一个 Sharpe          → 样本不足时给原因,不给数
    EASING / Easing 两行                 → 分组前必须 canonicalise
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.signals.track_record import (                       # noqa: E402
    BARRED_SOURCE_PREFIXES, MEASURE_ALPHA30, MEASURE_EXIT, MIN_MEASURABLE,
    by_regime, canonical_regime, classify_source, measure)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def test_source_classifier_has_four_states_not_two():
    """trusted / barred / cross_source / unsourced —— 后两类是**不同的失败**。

    负控制里最要紧的一条:`cross_source:signal_entry_price->coingecko`
    **含有 "coingecko" 字样**。用子串判会把它误分进 barred,而跨源(S-241)
    和"用了一个坏源"是两回事 —— 前者是入口出口不同源,后者是源本身不可用。
    判据必须是前缀,不是子串。
    """
    cases = {
        "ohlcv_daily:vs_BTC": "trusted",
        "coingecko:vs_BTC": "barred",
        "yfinance:vs_SPY": "barred",
        "cross_source:signal_entry_price->coingecko": "cross_source",
        "cross_source:signal_entry_price->yfinance": "cross_source",
        None: "unsourced",
        "": "unsourced",
        "hyperliquid:vs_BTC": "unknown",
    }
    bad = {k: classify_source(k)[0] for k, v in cases.items() if classify_source(k)[0] != v}
    _check("价源分四类,且跨源不被误判成 barred", not bad, str(bad))
    _check("被禁的源都带原因(拒绝的信息量 > 布尔值)",
           all(why.strip() for why in BARRED_SOURCE_PREFIXES.values()),
           str(BARRED_SOURCE_PREFIXES))
    _check("unsourced 的原因说的是'没记录',不是'为零'",
           "没有记录" in classify_source(None)[1], classify_source(None)[1])


def test_two_measures_are_never_mixed():
    """`return_pct`(8 天退出)与 `alpha_30d`(固定 30 天)不得混算。

    实测:23 个 WIN 行里 **12 个** `return_pct<0` 而 `return_pct_30d>0` ——
    曲线用前者、胜率用后者,同一块面板上两个数说着相反的话。
    """
    rows = [{"outcome_source": "ohlcv_daily:x", "return_pct": -2.46, "alpha_30d": 6.01}] * 40
    m_exit = measure(rows, which=MEASURE_EXIT)
    m_a30 = measure(rows, which=MEASURE_ALPHA30)
    _check("每个结果自报用的是哪种度量",
           m_exit.as_payload()["measure"] == MEASURE_EXIT
           and m_a30.as_payload()["measure"] == MEASURE_ALPHA30)
    _check("同一批行、两种度量给出不同的数(证明没有串用)",
           m_exit.mean_pct != m_a30.mean_pct,
           f"exit={m_exit.mean_pct} alpha={m_a30.mean_pct}")
    try:
        measure(rows, which="whatever")
        _check("未知度量必须抛异常", False, "没有抛")
    except ValueError:
        _check("未知度量必须抛异常", True)


def test_insufficient_sample_returns_a_reason_not_a_number():
    """12 个可信样本上的均值不是结论 —— 给原因,不给数。

    这是本条最重要的行为:页面现在展示的 −26.19% 既不是坏消息也不是好消息,
    **它是一个不可测量的量被渲染成了可信的数**。
    """
    rows = ([{"outcome_source": "coingecko:vs_BTC", "alpha_30d": -4.78}] * 83
            + [{"outcome_source": "ohlcv_daily:vs_BTC", "alpha_30d": -2.97}] * 12)
    m = measure(rows, which=MEASURE_ALPHA30, trusted_only=True)
    p = m.as_payload()
    _check("可信样本不足 → verdict=insufficient", p["verdict"] == "insufficient", p["verdict"])
    _check("不足时【不给】均值", p["mean_pct"] is None, str(p["mean_pct"]))
    _check("不足时【不给】胜率", p["win_rate_pct"] is None, str(p["win_rate_pct"]))
    _check("原因里点明了样本数与门槛",
           "12" in p["reason"] and str(MIN_MEASURABLE) in p["reason"], p.get("reason", ""))
    _check("原因明确说了'也不能得出我们不行'",
           "不行" in p["reason"], p.get("reason", ""))
    _check("source_mix 把混入了什么写在脸上",
           p["source_mix"].get("barred") == 83 and p["source_mix"].get("trusted") == 12,
           str(p["source_mix"]))
    # 负控制:样本够了就必须给数,否则这条守卫等于把面板永久关掉
    enough = [{"outcome_source": "ohlcv_daily:x", "alpha_30d": 1.0}] * (MIN_MEASURABLE + 1)
    _check("负控制:样本足够时 verdict=measured 且给出数",
           measure(enough, which=MEASURE_ALPHA30).as_payload()["mean_pct"] == 1.0)

    # ⚠️ 上面那几条【测不出】payload 有没有真的在抑制数字 —— 变异测试打穿过一次:
    # 把 `out["mean_pct"] = None` 改成 `= self.mean_pct` 之后测试仍然全绿,
    # 因为 insufficient 分支里 `self.mean_pct` 本来就是 None,那个变异是空操作。
    # 我验的是"结果里没有数",而要验的是"**即使算出了数,payload 也不放它出去**"。
    # 这两件事今天在别处已经分开过:值存在 ≠ 值被发布。
    #
    # 所以直接构造一个"算出了数但判定不足"的结果 —— 那正是未来某次重构会
    # 制造出来的形状(先算均值,再判样本量)。
    from src.data.signals.track_record import MeasureResult
    leaky = MeasureResult(MEASURE_ALPHA30, "insufficient", 12, 95,
                          mean_pct=-3.31, win_rate_pct=25.0,
                          by_source={"trusted": 12}, reason="样本不足")
    lp = leaky.as_payload()
    _check("即使内部算出了数,insufficient 的 payload 也不得放出均值",
           lp["mean_pct"] is None, str(lp["mean_pct"]))
    _check("即使内部算出了数,insufficient 的 payload 也不得放出胜率",
           lp["win_rate_pct"] is None, str(lp["win_rate_pct"]))
    _check("而 measured 的 payload 必须放出来(否则是把面板关死)",
           MeasureResult(MEASURE_ALPHA30, "measured", 40, 40, -3.31, 25.0,
                         {"trusted": 40}).as_payload()["mean_pct"] == -3.31)


def test_unmeasurable_is_not_zero():
    """一行都没有 ≠ 收益为零。S-180 在这一层的样子。"""
    m = measure([{"outcome_source": "yfinance:x", "alpha_30d": -2.0}] * 5,
                which=MEASURE_ALPHA30, trusted_only=True)
    _check("零个可信行 → unmeasurable 而非 0.0", m.verdict == "unmeasurable", m.verdict)
    _check("unmeasurable 也不给数", m.as_payload()["mean_pct"] is None)
    _check("原因说明'不等于收益为零'", "不等于" in m.reason, m.reason)


def test_regime_is_canonicalised_before_grouping():
    """`EASING` 与 `Easing` 必须合成一行,且合并这件事要可见。

    实测:两者 α 差 4.00pp;`RISK_ON` 与 `Risk-On` 差 12.01pp **且符号相反**。
    拼写在 2025-06-17 切换,所以它们是两段相邻时间窗,不是两个 regime ——
    不合并的话,那张「按 regime 归因」的表有一部分在测时代。
    """
    _check("拼写全部收敛到 UPPER_SNAKE",
           len({canonical_regime(x) for x in
                ["EASING", "Easing", "easing", " Easing "]}) == 1)
    _check("Risk-On 与 RISK_ON 同一个键",
           canonical_regime("Risk-On") == canonical_regime("RISK_ON") == "RISK_ON")
    _check("空与 None 都映射到 None(不是 'UNKNOWN' 字符串)",
           canonical_regime("") is None and canonical_regime(None) is None)
    # 无法识别的标签必须归 None,不能凭空造出一个新 regime 桶。
    # 我的第一版只做 .upper().replace(),`garbage_label` 会变成
    # `GARBAGE_LABEL` 并作为一个合法分组出现在归因表里。
    _check("无法识别的标签 → None(不发明新 regime)",
           canonical_regime("garbage_label") is None
           and canonical_regime("Bull Market") is None,
           f"{canonical_regime('garbage_label')!r} / {canonical_regime('Bull Market')!r}")


def test_there_is_only_one_regime_canonicaliser_reachable_from_here():
    """本模块**不实现** regime 规范化,只转发到唯一权威实现。

    ⚠️ 我的第一版自己写了一遍 —— 而仓库里已经有三个
    (`cis_provider.canonical_regime` / `canonical_regime_strict` /
    `r70_rule.canonical_regime`),我把它变成了第四个。

    今天早些时候我刚在路由展平上做对过同一件事:`test_no_route_is_shadowed`
    已经有 `_flatten()`,我复用而没有重写,理由写得很清楚 ——
    **两个展平器会各自漂移,而漂移的那一个会静默地少看几十条。**
    半天之后我在 regime 上原样犯了一遍,是 `test_regime_write_path` 抓住的,
    不是我自己发现的。

    这条断言按 AST 查:本模块里不得出现 `canonical_regime` 的**函数体实现**,
    只能有转发。判据是"函数体里有没有字符串变换",不是"有没有这个名字"。
    """
    import ast
    import inspect

    import src.data.signals.track_record as tr

    tree = ast.parse(inspect.getsource(tr))
    fn = next((n for n in tree.body
               if isinstance(n, ast.FunctionDef) and n.name == "canonical_regime"), None)
    _check("本模块确实定义了 canonical_regime(作为转发)", fn is not None)
    if fn:
        # ⚠️ 必须先剥 docstring。第一版直接 `ast.unparse(fn)`,而这个函数的
        # docstring 里**引用了** `.upper().replace("-","_")` 作为反面例子 ——
        # 于是守卫被自己的说明文字触发,红在一个正确的实现上。
        #
        # `tests/_source.py` 记的就是这个失败:**一条解释"此处禁止 X"的注释
        # 本身含有 X**。今天在 `test_no_investor_facing_internals` 里刚处理过
        # 一次(先剥注释再匹配),这里又踩了一遍 —— 因为那次剥的是 `//` 注释,
        # 这次是 Python docstring,**同一课的两种拼写**。
        body = [n for n in fn.body
                if not (isinstance(n, ast.Expr) and isinstance(n.value, ast.Constant)
                        and isinstance(n.value.value, str))]
        body_src = "\n".join(ast.unparse(n) for n in body)
        smells = [s for s in (".upper(", ".replace(", ".lower(") if s in body_src]
        _check("函数体里没有自己做字符串变换(说明是转发不是重实现)",
               not smells, f"出现了 {smells} —— 这是第四个实现,不是转发")
        _check("转发到 cis_provider 的 strict 版",
               "canonical_regime_strict" in body_src, body_src[-160:])

    rows = ([{"macro_regime": "EASING", "alpha_30d": -1.43}] * 1475
            + [{"macro_regime": "Easing", "alpha_30d": -5.43}] * 1185)
    out = by_regime(rows, which=MEASURE_ALPHA30)
    _check("两种拼写合成一行", list(out) == ["EASING"], str(list(out)))
    _check("合并后的 n 是两者之和", out["EASING"]["n"] == 2660, str(out["EASING"]["n"]))
    _check("合并这件事被写进 payload(可审计)",
           out["EASING"].get("merged_spellings") == ["EASING", "Easing"],
           str(out["EASING"].get("merged_spellings")))
    # 负控制:没有合并发生时不应出现 merged_spellings,否则这个字段变成噪声
    solo = by_regime([{"macro_regime": "RISK_OFF", "alpha_30d": 1.0}], which=MEASURE_ALPHA30)
    _check("负控制:未发生合并时不带 merged_spellings",
           "merged_spellings" not in solo["RISK_OFF"], str(solo))


if __name__ == "__main__":
    print("── 战绩面板:一种度量 · 分层价源 · 拒绝优于数字 (S-248) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 战绩度量守卫全绿")
