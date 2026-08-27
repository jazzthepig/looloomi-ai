"""价源判活按覆盖率,不按最新日期 (S-251).

钉住的每一条都来自 2026-08-27 的实测,不是假想:

    binance_hist 08-09 起每天只写 1 个标的(BCH),连写 19 天
      → max(trade_date) 天天前进,而 260 个标的已经死了
    /internal/data-freshness 报 verdict="fresh", age_days=0.5
      → 因为它 `order=trade_date.desc limit 1`,全表一行,不分源不分标的
    crypto 三个源:binance_hist DEAD · hyperliquid DEAD · coingecko 在写但被 S-195 禁用
      → 加密侧【没有能用于收益的价源】,而任何全局判决都会说 ok(eodhd 活着)
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.source_freshness import (                    # noqa: E402
    COVERAGE_SQL, classify, from_rows, overall)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def test_one_surviving_writer_does_not_read_as_healthy():
    """**本条是整个模块存在的理由。**

    binance_hist 从 2026-08-09 起每天只写 BCH 一个标的,连续 19 天。
    `max(trade_date)` 因此天天前进,全表 max 看起来永远新鲜 ——
    而 260 个标的已经停了。日期新 ≠ 管道活。
    """
    h = classify("binance_hist", last_bar="2026-08-20", age_days=0,
                 symbols_recent=1, symbols_typical=212)
    _check("1/212 个标的 → COLLAPSED(不是 flowing)", h.verdict == "COLLAPSED", h.verdict)
    _check("COLLAPSED 不可用于收益", not h.usable_for_returns)
    _check("detail 点明了'少数写入者把 max 推着走'", "max(trade_date)" in h.detail, h.detail[:60])
    # 负控制:覆盖完好时必须 flowing,否则这条守卫等于把所有源永久判死
    ok = classify("binance_hist", last_bar="2026-08-27", age_days=0,
                  symbols_recent=210, symbols_typical=212)
    _check("负控制:覆盖完好 → flowing 且可用", ok.verdict == "flowing" and ok.usable_for_returns,
           ok.verdict)


def test_dead_is_decided_before_baseline_is_missing():
    """0 个标的就是死了,不需要基线。

    顺序反过来的话,一个没有历史常态的源(新接入/历史太短)在完全停写时会被报成
    `no_baseline` —— 那读起来像"还不知道",不像"死了"。yfinance 正是这个形状:
    实测 symbols_typical 为 None 而 symbols_recent 为 0。
    """
    h = classify("yfinance", last_bar="2026-06-18", age_days=70,
                 symbols_recent=0, symbols_typical=None)
    _check("无基线 + 零覆盖 → DEAD(不是 no_baseline)", h.verdict == "DEAD", h.verdict)
    nb = classify("newsrc", last_bar="2026-08-27", age_days=0,
                  symbols_recent=5, symbols_typical=None)
    _check("有覆盖但无基线 → no_baseline", nb.verdict == "no_baseline", nb.verdict)
    _check("no_baseline 明说'不是通过'", "不是" in nb.detail, nb.detail)


def test_verdict_is_per_asset_domain_not_global():
    """**一个全局的 ok 会掩盖一整个资产域的全灭。**

    我写这个模块时第一版就是全局的,拿实测数据跑出来是 `verdict: "ok"` ——
    因为 eodhd 活着。而 eodhd 只有 TradFi,加密侧三个源全部不可用。
    在修「一个 max 掩盖一个总体」的同时,把"某域有可用源"压成了"系统有可用源"。
    """
    live = from_rows([
        {"source": "coingecko", "last_bar": "2026-08-27", "age_days": 0,
         "symbols_recent": 25, "symbols_typical": 25},
        {"source": "eodhd", "last_bar": "2026-08-26", "age_days": 1,
         "symbols_recent": 33, "symbols_typical": 33},
        {"source": "hyperliquid", "last_bar": "2026-08-23", "age_days": 4,
         "symbols_recent": 0, "symbols_typical": 177},
        {"source": "binance_hist", "last_bar": "2026-08-20", "age_days": 7,
         "symbols_recent": 0, "symbols_typical": 212},
    ])
    o = overall(live)
    _check("整体不得是 ok(crypto 域没有可用价源)",
           o["verdict"] != "ok", o["verdict"])
    _check("点名是 crypto 域", o["domains_without_usable_source"] == ["crypto"],
           str(o["domains_without_usable_source"]))
    _check("tradfi 域仍判 ok(不能一竿子打死)",
           o["by_domain"]["tradfi"]["verdict"] == "ok", str(o["by_domain"]["tradfi"]))
    _check("coingecko 归'在写但被禁',既不算可用也不算死",
           o["by_domain"]["crypto"]["flowing_but_barred"] == ["coingecko"],
           str(o["by_domain"]["crypto"]))
    # 负控制:crypto 恢复后整体必须回到 ok
    fixed = from_rows([
        {"source": "binance_hist", "last_bar": "2026-08-27", "age_days": 0,
         "symbols_recent": 210, "symbols_typical": 212},
        {"source": "eodhd", "last_bar": "2026-08-26", "age_days": 1,
         "symbols_recent": 33, "symbols_typical": 33},
    ])
    _check("负控制:crypto 恢复 → 整体 ok", overall(fixed)["verdict"] == "ok",
           overall(fixed)["verdict"])


def test_tradfi_survives_a_long_weekend_without_crying_wolf():
    """**周末不得触发 DEAD。**

    `main.py` 的 `/internal/data-freshness` 里有一段写给未来的人的警告:
    「周末合法地掉到只剩加密(~25 个标的),因为 EODHD 是 TradFi 而市场关门 ——
    一个忽略这件事的标的数检查会每个周六都狼来了,而一个狼来了的检查会被静音,
    那正是这一整层存在要避免的失败。」

    我第一版全局 `RECENT_DAYS = 3`,周四实测没事,但**周二早上**
    (上周五收盘 + 周六 + 周日 + 周一假期)窗口里一根 eodhd bar 都没有 → DEAD。
    那就是那段警告描述的失败,一字不差。
    """
    from src.data.market.source_freshness import RECENT_DAYS_BY_DOMAIN, recent_days_for
    _check("TradFi 的窗口比加密宽(容长周末)",
           RECENT_DAYS_BY_DOMAIN["tradfi"] > RECENT_DAYS_BY_DOMAIN["crypto"],
           str(RECENT_DAYS_BY_DOMAIN))
    _check("TradFi 窗口 ≥ 6 天(周五收盘 + 周六日 + 周一假期 + 抖动)",
           recent_days_for("eodhd") >= 6, str(recent_days_for("eodhd")))
    _check("加密窗口保持 3 天(24/7,零覆盖无歧义)",
           recent_days_for("binance_hist") == 3, str(recent_days_for("binance_hist")))

    # 长周末场景:eodhd 最近 3 天零 bar,但 6 天窗口里有 33 个 → 必须 flowing
    long_weekend = from_rows([
        {"source": "eodhd", "last_bar": "2026-08-21", "age_days": 4,
         "symbols_recent_crypto_win": 0, "symbols_recent_tradfi_win": 33,
         "symbols_typical": 33},
        {"source": "coingecko", "last_bar": "2026-08-25", "age_days": 0,
         "symbols_recent_crypto_win": 25, "symbols_recent_tradfi_win": 25,
         "symbols_typical": 25},
    ])
    verdicts = {h.source: h.verdict for h in long_weekend}
    _check("长周末后 eodhd 仍是 flowing(不是 DEAD)",
           verdicts.get("eodhd") == "flowing", str(verdicts))
    _check("同一场景下加密源不受影响", verdicts.get("coingecko") == "flowing", str(verdicts))
    # 负控制:eodhd 真的死了(6 天窗口也是 0)必须报 DEAD,否则这条豁免变成永久失明
    really_dead = from_rows([{"source": "eodhd", "last_bar": "2026-07-01", "age_days": 57,
                              "symbols_recent_crypto_win": 0, "symbols_recent_tradfi_win": 0,
                              "symbols_typical": 33}])
    _check("负控制:6 天窗口也为零 → DEAD", really_dead[0].verdict == "DEAD",
           really_dead[0].verdict)


def test_flowing_but_barred_is_not_usable():
    """在写 ≠ 能用于收益。coingecko 每天都在更新,而 S-195 禁它做收益序列。"""
    cg = classify("coingecko", last_bar="2026-08-27", age_days=0,
                  symbols_recent=25, symbols_typical=25)
    _check("coingecko flowing", cg.verdict == "flowing")
    _check("但 usable_for_returns 为 False（S-195）", not cg.usable_for_returns)
    eo = classify("eodhd", last_bar="2026-08-26", age_days=1,
                  symbols_recent=33, symbols_typical=33)
    _check("eodhd flowing 且可用", eo.verdict == "flowing" and eo.usable_for_returns)


def test_baseline_window_excludes_the_ongoing_decay():
    """基线不能包含最近 15 天,否则正在衰减的源自己就是标尺。

    一个缓慢死亡的源,如果拿"最近 30 天平均"做常态,常态会跟着它一起下降,
    比值永远接近 1,**永远不告警**。SQL 里的窗口是 45→15 天前,把当前衰减排除在外。
    """
    # ⚠️ 第一版只断言 SQL 里【出现】了 %(base_lo)s / %(base_hi)s —— 变异测试打穿:
    # 把 45,15 改成 30,0 之后测试仍全绿,而那正是"基线含当前衰减"的形状。
    # 我验的是占位符在不在,要验的是**那两个数把最近窗口排除在外**。
    # 又一次匹配了模式而不是属性。
    from src.data.market.source_freshness import (
        BASELINE_HI_DAYS, BASELINE_LO_DAYS, RECENT_DAYS)
    _check(f"基线窗口的近端({BASELINE_HI_DAYS}d)必须晚于'最近'窗口({RECENT_DAYS}d)",
           BASELINE_HI_DAYS > RECENT_DAYS,
           f"base_hi={BASELINE_HI_DAYS} 不大于 recent={RECENT_DAYS} —— "
           f"基线与被比较的区间重叠,衰减会把标尺一起拉低")
    _check(f"基线窗口的近端({BASELINE_HI_DAYS}d)要留出足够缓冲",
           BASELINE_HI_DAYS >= 7,
           f"base_hi={BASELINE_HI_DAYS} < 7 天 —— 一次持续一周的衰减就会进基线")
    _check(f"基线窗口非空({BASELINE_LO_DAYS}d → {BASELINE_HI_DAYS}d)",
           BASELINE_LO_DAYS > BASELINE_HI_DAYS,
           f"{BASELINE_LO_DAYS} 不大于 {BASELINE_HI_DAYS}")
    _check("SQL 用 %(base_lo)s / %(base_hi)s 参数化这个窗口",
           "%(base_lo)s" in COVERAGE_SQL and "%(base_hi)s" in COVERAGE_SQL)
    _check("SQL 按 source 分组(不是全表一行)",
           COVERAGE_SQL.count("group by") >= 3 and "distinct symbol" in COVERAGE_SQL)
    _check("SQL 数的是 distinct symbol,不是 max(trade_date)",
           "count(distinct symbol)" in COVERAGE_SQL)


if __name__ == "__main__":
    print("── 价源判活:按覆盖率不按日期 · 按域不按全局 (S-251) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 价源判活守卫全绿")
