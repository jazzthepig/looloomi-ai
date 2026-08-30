"""CG Pro 回填:落库为可信源,且不碰旧数据 (S-258).

每条对着一个实测事实:

    ohlcv_daily 唯一键 = (symbol, trade_date, source)  → on_conflict 必须含 source,
                                                          否则新行覆盖 48,853 行旧数据
    coingecko_pro_ohlc 现有 0 行,coingecko 有 48,853 行 → 标签必须是 pro 那个
    /ohlc/range 单次上限 180 天(M-92 实测)              → 分块 ≤175 天
    /ohlc/range 不返回成交量                              → volume 留 NULL,不跨源拼
    binance_hist 343 天上限(M-91)、CG Pro 1811 天(M-92) → 这就是做这件事的理由
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.cg_pro_backfill import (                     # noqa: E402
    CHUNK_DAYS, LOCAL_DB, MAPPING_TOLERANCE_PCT, MIN_CANDLES_PER_SYMBOL,
    ON_CONFLICT, SOURCE_TAG, BackfillResult, SymbolResult, check_mapping,
    chunk_windows, to_rows, write_local)
from src.data.market.single_source import (                       # noqa: E402
    BARRED_RETURN_SOURCES, TRUSTED_RETURN_SOURCES)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _d(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).date().isoformat()


def test_on_conflict_includes_source_or_we_destroy_48853_rows():
    """**本文件最重要的一条。**

    实测 `ohlcv_daily` 的唯一约束是 `UNIQUE (symbol, trade_date, source)`。
    upsert 的 `on_conflict` **少写 `source`**,新的 `coingecko_pro_ohlc` 行就会
    按 `(symbol, trade_date)` 撞上现有的 48,853 行 `coingecko` 数据并覆盖它们。

    那是不可逆的:删掉旧行会让「我们用错端点四个月」这件事从数据里消失,
    而 the graveyard is the asset —— 那批行的存在本身就是 S-195 的证据。
    """
    _check("on_conflict 含 source", "source" in ON_CONFLICT.split(","), ON_CONFLICT)
    _check("on_conflict 三个字段都在",
           set(ON_CONFLICT.split(",")) == {"symbol", "trade_date", "source"}, ON_CONFLICT)


def test_source_tag_is_the_trusted_one_not_bare_coingecko():
    """标签按【端点】分,不按 vendor 分 (S-234)。

    `coingecko` 被 `BARRED_RETURN_SOURCES` 禁用于收益序列(market_chart 采样点
    塌缩,不是收盘);`coingecko_pro_ohlc` 在 `TRUSTED_RETURN_SOURCES` 里。
    **同一个 vendor 的两个端点是两种数据。** 标错就等于把被禁的数据洗成可信的。
    """
    _check(f"SOURCE_TAG = {SOURCE_TAG}", SOURCE_TAG == "coingecko_pro_ohlc", SOURCE_TAG)
    _check("它在 TRUSTED_RETURN_SOURCES 里", SOURCE_TAG in TRUSTED_RETURN_SOURCES,
           str(TRUSTED_RETURN_SOURCES))
    _check("裸 coingecko 仍在 BARRED 里(没被这次改动放行)",
           "coingecko" in BARRED_RETURN_SOURCES, str(sorted(BARRED_RETURN_SOURCES)))
    _check("两者不是同一个标签", SOURCE_TAG != "coingecko")


def test_chunks_respect_the_180d_cap_and_overlap_by_one_day():
    """Pro 单次上限 180 天(M-92 实测);相邻窗口重叠一天。

    重叠是有意的:candle 的边界归属取决于开盘时刻落在哪一侧,不重叠会在每个
    接缝丢一根 bar —— 而丢的那根**不会报错**,只会让某个 60 日窗口变成 59 根。
    唯一键吃掉重复,所以重叠的代价是零。
    """
    _check(f"CHUNK_DAYS={CHUNK_DAYS} ≤ 180(留余量)",
           CHUNK_DAYS <= 180, str(CHUNK_DAYS))
    _check("留了余量而不是贴着上限", CHUNK_DAYS < 180, str(CHUNK_DAYS))

    w = chunk_windows(date(2021, 9, 1), date(2026, 8, 27))
    _check(f"5 年切成 {len(w)} 块", len(w) > 5, str(len(w)))
    too_long = [(a, b) for a, b in w if (b - a) / 86400 > 180]
    _check("没有窗口超过 180 天", not too_long, str(len(too_long)))
    _check("首窗起点 = start", _d(w[0][0]) == "2021-09-01", _d(w[0][0]))
    _check("末窗终点 = end", _d(w[-1][1]) == "2026-08-27", _d(w[-1][1]))
    overlaps = [i for i in range(len(w) - 1) if _d(w[i][1]) == _d(w[i + 1][0])]
    _check(f"相邻窗口重叠一天({len(overlaps)}/{len(w) - 1} 个接缝)",
           len(overlaps) == len(w) - 1, str(len(overlaps)))
    _check("end < start → 空列表(不是抛异常也不是一个假窗口)",
           chunk_windows(date(2026, 8, 27), date(2021, 9, 1)) == [])


def test_rows_dedupe_and_never_fabricate_volume():
    """重叠产生的重复要去掉;`/ohlc/range` 不给量 → volume 必须是 NULL。

    从别的端点拼一个成交量进来就是跨源 (S-230),而拼进来的量看不出是拼的。
    **缺的量是 NULL,不是 0** —— 一个 0 成交量会让流动性维度读到"没人交易"。
    """
    c = [{"trade_date": "2026-08-26", "open": 1, "high": 2, "low": 0.5, "close": 1.5},
         {"trade_date": "2026-08-26", "open": 9, "high": 9, "low": 9, "close": 9},
         {"trade_date": "2026-08-27", "open": 1, "high": 2, "low": 0.5, "close": 1.8},
         {"trade_date": "2026-08-28", "open": 1, "high": 2, "low": 0.5, "close": None}]
    r = to_rows("BTC", c, asset_class="L1")
    _check("重复日期去重 + 无收盘丢弃 → 2 行", len(r) == 2, str(len(r)))
    _check("保留的是先到的那根(不是后到的覆盖)", r[0]["close"] == 1.5, str(r[0]["close"]))
    _check("volume 全部为 None(不是 0)",
           all(x["volume"] is None for x in r), str([x["volume"] for x in r]))
    _check("source 全部是 pro 标签", {x["source"] for x in r} == {SOURCE_TAG})
    _check("按日期升序", [x["trade_date"] for x in r] == sorted(x["trade_date"] for x in r))
    _check("空输入 → 空行(不是一行 NaN)", to_rows("BTC", []) == [])


def test_floor_refuses_sparse_writes():
    """bar 太少不写 —— 稀疏区间在下游与"这段时间没交易"不可分辨。"""
    _check(f"MIN_CANDLES_PER_SYMBOL = {MIN_CANDLES_PER_SYMBOL} 且 > 0",
           MIN_CANDLES_PER_SYMBOL > 0)
    skipped = SymbolResult("BTC", "bitcoin", False, 3,
                           reason=f"只取到 3 根 bar < {MIN_CANDLES_PER_SYMBOL}")
    p = skipped.as_payload()
    _check("跳过的标的在 payload 里带原因", "skipped_because" in p, str(p))
    ok = SymbolResult("BTC", "bitcoin", True, 500, "2021-09-01", "2026-08-27")
    _check("成功的不带 skipped_because", "skipped_because" not in ok.as_payload())
    _check("成功的带覆盖窗口", "coverage" in ok.as_payload(), str(ok.as_payload()))


def test_wrong_coin_id_is_caught_empirically():
    """**「不猜映射」从政策变成检查。**

    一个错的 `symbol → coin_id` 会把另一个币的整段价格历史写进这个标的,
    而**那条曲线看起来完全正常** —— 没有任何下游检查能发现 BTC 的历史里
    混进了 BCH 的价格。它不会让任何断言变红,只会让每个用到它的结论变错。

    库里没有 CG coin_id 映射表(`asset_aliases` 存的是 binance venue symbol),
    所以校验只能是**实证的**:同一天,拿 `/ohlc/range` 的收盘对既有的
    `coingecko`(market_chart)收盘。同 vendor 两端点必须接近。
    """
    ok = check_mapping("BTC", "bitcoin", pro_close=80268.4, existing_close=80100.0)
    _check("同 vendor 两端点小差 → 通过", ok.ok and ok.gap_pct < 1.0,
           str(ok.as_payload()))

    # coin_id 指向 BCH:实测 2026-08-29 BTC $80,268 vs BCH 量级几百
    bad = check_mapping("BTC", "bitcoin-cash", pro_close=640.0, existing_close=80100.0)
    _check("coin_id 指错币 → 不通过", not bad.ok, str(bad.as_payload()))
    _check("原因点明是映射问题",
           "coin_id" in bad.reason and "另一个币" in bad.reason, bad.reason[:70])

    # 没有对照行【不是通过】(S-163:not-checked ≠ pass)
    nc = check_mapping("XYZ", "xyz", pro_close=100.0, existing_close=None)
    _check("没有对照行 → 不通过(未校验 ≠ 通过)", not nc.ok, str(nc.as_payload()))
    _check("原因明说'未校验,不是通过'", "不是通过" in nc.reason, nc.reason[:60])

    none_pro = check_mapping("BTC", "bitcoin", pro_close=None, existing_close=80100.0)
    _check("Pro 没返回收盘 → 不通过", not none_pro.ok, none_pro.reason[:50])

    # 边界:容差本身要能挡住"刚好超一点",也要放行"刚好不到"
    just_in = check_mapping("BTC", "bitcoin", pro_close=100.0,
                            existing_close=100.0 / (1 + (MAPPING_TOLERANCE_PCT - 0.5) / 100))
    just_out = check_mapping("BTC", "bitcoin", pro_close=100.0,
                             existing_close=100.0 / (1 + (MAPPING_TOLERANCE_PCT + 2) / 100))
    _check(f"容差内({MAPPING_TOLERANCE_PCT}%)放行", just_in.ok, str(just_in.gap_pct))
    _check("容差外拦截", not just_out.ok, str(just_out.gap_pct))
    _check("容差不为 0(否则同 vendor 两端点永远过不了)", MAPPING_TOLERANCE_PCT > 0)


def test_local_is_the_default_destination():
    """**默认写本地,Supabase 是显式的一步** (S-261)。

    Jazz 2026-08-30:「supabase 我们是免费版的,能不增加用量就不增加。」

    实测当天:库 253 MB / 500 MB = **50.7%**。而这次回填按 ohlcv_daily 的密度
    (90.2MB / 533,989 行 ≈ 177 B/行)只有约 **3.2 MB**,占库 0.6% ——
    **担心的方向其实反了**:真正压额度的是 `ohlcv_hourly` **85.6 MB(全库 34%)**,
    而它被 DATA-EXPANSION-HOLD 明令禁用、`src/` 里无人读、陈旧 22 天。

    但「先本地」这条本身是对的,理由比省额度更硬:**研究面和系统记录是两种东西。**
    研究要反复重算、试错、丢弃;系统记录要稳定、可审计、被生产读。
    把研究中间产物写进 Supabase,等于让每次试错变成永久记录 ——
    而删掉它们又破坏「the graveyard is the asset」。两个都不要,所以分开放。
    """
    import inspect

    from src.data.market import cg_pro_backfill as B

    for fn in (B.backfill, B.backfill_symbol):
        sig = inspect.signature(fn)
        _check(f"{fn.__name__} 有 dest 参数", "dest" in sig.parameters, str(list(sig.parameters)))
        _check(f"{fn.__name__} 的 dest 默认是 local",
               sig.parameters["dest"].default == "local",
               str(sig.parameters["dest"].default))

    _check("结果里报出 dest(读者能判断动没动生产库)",
           BackfillResult(True, 1, (), "", dest="supabase").as_payload()["dest"] == "supabase")
    _check("复用既有的本地 sqlite,不建第三个 store",
           LOCAL_DB == "/tmp/cometcloud_data/ohlcv.db", LOCAL_DB)


def test_write_local_is_idempotent_and_keeps_volume_null():
    """本地写必须幂等(主键去重)且不伪造成交量。

    幂等很重要:研究面会被反复重跑,一个每次追加的写者会让同一天有 N 行,
    而下游按日期取值时拿到哪一行取决于查询顺序 —— 那正是 S-245 里
    「后到的源静默覆盖先到的」那个形状,只是换到了本地。
    """
    import os
    import sqlite3
    import tempfile

    db = tempfile.mktemp(suffix=".db")
    rows = to_rows("BTC", [{"trade_date": f"2026-01-{d:02d}", "open": 1, "high": 2,
                            "low": 0.5, "close": 100 + d} for d in range(1, 21)],
                   asset_class="L1")
    try:
        n1 = write_local(rows, db_path=db)
        n2 = write_local(rows, db_path=db)          # 再写一次
        c = sqlite3.connect(db)
        total = c.execute("select count(*) from ohlcv_daily").fetchone()[0]
        srcs = [r[0] for r in c.execute("select distinct source from ohlcv_daily")]
        nulls = c.execute("select count(*) from ohlcv_daily where volume is null").fetchone()[0]
        c.close()
        _check(f"两次各写 {n1}/{n2} 行,表里仍是 {total} 行(幂等)", total == 20, str(total))
        _check("源标签是 pro", srcs == [SOURCE_TAG], str(srcs))
        _check("volume 全 NULL(不伪造成交量)", nulls == total, f"{nulls}/{total}")
        _check("空输入写 0 行", write_local([], db_path=db) == 0)
    finally:
        if os.path.exists(db):
            os.unlink(db)


def test_no_pairs_refuses_instead_of_guessing_coin_ids():
    """不猜 symbol→coin_id。

    猜错一个映射会把另一个币的价格写进这个标的的历史,**而那条曲线看起来
    完全正常** —— 没有任何下游检查能发现 BTC 的历史里混进了 BCH 的价格。
    """
    import asyncio

    from src.data.market.cg_pro_backfill import backfill
    r = asyncio.new_event_loop().run_until_complete(
        backfill([], start=date(2026, 1, 1), end=date(2026, 8, 27)))
    _check("空映射 → 不 ok", not r.ok)
    _check("原因写明'不猜映射'", "不猜" in r.reason, r.reason)
    _check("degraded 而不是 ok", r.as_payload()["status"] == "degraded",
           r.as_payload()["status"])


if __name__ == "__main__":
    print("── CG Pro 回填:可信源 · 不覆盖旧数据 · 不伪造成交量 (S-258) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ CG Pro 回填守卫全绿")
