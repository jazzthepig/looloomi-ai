"""RWA 面板守卫 (S-266)。

最重要的两条,都不是聚合算得对不对:

  · **`market_cap: null` 不得塌成 0。** 实测 2026-09-01,`/rwas/markets` 的市场
    数据嵌在 `tokenized_market_data` 里,顶层没有 `market_cap`。取错层会拿到
    250 个 null,而 `sum(null→0)` 会给出一个「$0 全市场持仓量」**并且不报错**。
    一个静默的 0 比一个异常危险得多 —— 它会一路流进图表。

  · **标量必须带着裁决一起走。** 公开来源在几周内给过 $2.3B / $2.4B / $2.6B /
    「突破 $3B」四个说法。一个不带成色的「持仓量」是在假装这个分歧不存在。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.rwa.panel import (                      # noqa: E402
    AGREE, DISPERSED, EQUITY_LIKE, NO_DATA, SINGLE,
    by_axis, herfindahl, parse_rows, snapshot, total_equity_like,
)

_FAIL: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _api(rid, name, atype, mcap, vol=None, chg=None, symbol="x"):
    """CG 的真实响应形状 —— 市场数据在 tokenized_market_data 里。"""
    return {"id": rid, "name": name, "symbol": symbol, "asset_type": atype,
            "tokenized_market_data": {
                "market_cap": mcap, "total_volume": vol,
                "market_cap_change_24h": chg,
                "market_cap_change_percentage_24h": None,
                "price_change_percentage_30d_in_currency": None,
                "last_updated": "2026-09-01T04:00:00Z"}}


#: 按 2026-09-01 网检的真实结构造:Ondo 一家约占 41%。
REAL_SHAPED = [
    _api("nvidia", "Nvidia", "stock", 620e6, 2.4e9, 12e6, "nvda"),
    _api("tesla", "Tesla", "stock", 410e6, 1.8e9, -5e6, "tsla"),
    _api("spdr-sp500", "SPDR S&P 500 ETF Trust", "etf", 297e6, 900e6, 3e6, "spy"),
    _api("spacex", "SpaceX", "stock", 180e6, 260e6, 9e6, "spacex"),
    _api("circle", "Circle Internet Group", "stock", 150e6, 340e6, 1e6, "crcl"),
    _api("gold", "Gold", "commodity", 5.47e9, 352e6, -26e6, "xau"),
    _api("silver", "Silver", "commodity", 700e6, 40e6, 2e6, "xag"),
]


def t_null_market_cap_never_collapses_to_zero():
    """**本文件的第一理由。** 取错层 = 250 个 null;null 当 0 求和 = 静默的 $0。"""
    # 顶层有 market_cap、但 tokenized_market_data 里没有 —— 正是我 09-01 那次
    # jq 犯的错的数据形状。
    wrong_layer = [{"id": "nvidia", "name": "Nvidia", "symbol": "nvda",
                    "asset_type": "stock", "market_cap": 620e6,
                    "tokenized_market_data": {}}]
    rows = parse_rows(wrong_layer)
    _check("顶层的 market_cap 不被采信(它不是代币化市值)",
           rows[0].market_cap is None, str(rows[0].market_cap))
    # ⚠️ 初版写的是 `rows[0].market_cap is not 0` —— 对字面量做身份比较,
    # **恒真,永远不会红**。一条不会失败的断言比没有断言更糟:它占着位置,
    # 让人以为这个性质被守着。判据要问的是「它和 0 可区分吗」。
    _check("未测 = None,与 0 可区分",
           rows[0].market_cap is None and 0 is not None)

    est = total_equity_like(rows)
    _check("全是未测 → NO_DATA,不是 $0", est.verdict == NO_DATA,
           f"{est.verdict}: {est.value}")
    _check("value 是 None 而不是 0.0", est.value is None, str(est.value))
    _check("原因点明「取错层」这个最可能的成因", "tokenized_market_data" in est.reason,
           est.reason)

    # 判别性:同一批数据放对层就应该测得出来。
    ok_rows = parse_rows([_api("nvidia", "Nvidia", "stock", 620e6)])
    _check("放对层 → 测得出", ok_rows[0].market_cap == 620e6, str(ok_rows[0].market_cap))


def t_unmeasured_rows_are_counted_not_dropped():
    """I1:未测要被**数出来**,不是悄悄跳过。"""
    rows = parse_rows(REAL_SHAPED + [_api("mystery", "Mystery Co", "stock", None)])
    est = total_equity_like(rows)
    _check("未测计数 = 1", est.n_unmeasured == 1, str(est.n_unmeasured))
    _check("已测计数 = 5(股票 4 + ETF 1,不含商品)", est.n_measured == 5,
           str(est.n_measured))
    _check("原因里带出未测条数", "未测" in est.reason, est.reason)


def t_equity_like_scope_excludes_commodities():
    """口径边界集中在一处 —— 分歧来源①。"""
    _check("EQUITY_LIKE = {stock, etf}", EQUITY_LIKE == {"stock", "etf"},
           str(EQUITY_LIKE))
    est = total_equity_like(parse_rows(REAL_SHAPED))
    gold_silver = 5.47e9 + 700e6
    _check("黄金白银($6.17B)不进股票/ETF 口径",
           est.value is not None and est.value < gold_silver,
           f"{est.value} —— 商品被算进去了")
    _check("合计 = 620+410+297+180+150 = $1.657B",
           est.value is not None and abs(est.value - 1.657e9) < 1e6, str(est.value))


def t_a_single_estimate_is_labelled_as_such():
    """只有一个估计时,裁决必须说出来,而不是伪装成一致。"""
    est = total_equity_like(parse_rows(REAL_SHAPED))
    _check("单一来源 → SINGLE", est.verdict == SINGLE, f"{est.verdict}: {est.reason}")
    _check("SINGLE 仍算可用(但须标注)", est.usable is True)
    _check("原因指出该接哪个端点才有交叉", "issuers" in est.reason, est.reason)


def t_dispersion_is_reported_not_averaged_away():
    """三个估计分歧 13%(= 公开来源之间真实的分歧幅度)→ DISPERSED。"""
    rows = parse_rows(REAL_SHAPED)
    est = total_equity_like(rows, issuer_total=1.657e9 * 1.14, category_total=1.657e9)
    _check("离散超限 → DISPERSED", est.verdict == DISPERSED,
           f"{est.verdict}: {est.reason}")
    _check("DISPERSED 不可用", est.usable is False)
    _check("值仍然给出(中位数),不是抹成 None", est.value is not None)
    _check("离散度是个数,可被下游读", est.dispersion is not None and est.dispersion > 0.10,
           str(est.dispersion))
    _check("原因列出了三个估计各自的值", "panel_sum" in est.reason, est.reason)
    _check("原因给出了常见成因(重复计暴露 / 口径 / 背书模型)",
           "重复计暴露" in est.reason, est.reason)

    # 判别性:估计接近时必须判 AGREE,否则这个判据只是永远说不。
    ok = total_equity_like(rows, issuer_total=1.657e9 * 1.03)
    _check("估计接近 → AGREE", ok.verdict == AGREE, f"{ok.verdict}: {ok.reason}")
    _check("AGREE 可用", ok.usable is True)


def t_external_anchor_informs_but_never_computes():
    """外部锚只入说明。掺进计算 = 让数字依赖一个 CI 里复现不了的东西。"""
    rows = parse_rows(REAL_SHAPED)
    a = total_equity_like(rows, external_anchor=2.33e9)
    b = total_equity_like(rows, external_anchor=None)
    _check("锚不改变数值", a.value == b.value, f"{a.value} vs {b.value}")
    _check("锚改变说明", a.reason != b.reason)
    _check("偏离显著时说明里写明", "差距显著" in a.reason, a.reason)

    close = total_equity_like(rows, external_anchor=1.7e9)
    _check("偏离在容差内 → 说明为一致", "与外部锚一致" in close.reason, close.reason)


def t_axes_survive_before_the_scalar_does():
    """先有轴再有标量 —— §4「每层写明保什么」。"""
    rows = parse_rows(REAL_SHAPED)
    by_t = by_axis(rows, "asset_type")
    _check("asset_type 轴保住三类", set(by_t) == {"stock", "etf", "commodity"},
           str(set(by_t)))
    _check("每个桶都带未测计数", all("n_unmeasured" in v for v in by_t.values()))
    _check("换手率被算出(流的强度,不是存量大小)",
           by_t["stock"]["turnover"] is not None and by_t["stock"]["turnover"] > 1,
           str(by_t["stock"]["turnover"]))
    _check("净 24h 市值变化被保留(那是流本身)",
           by_t["stock"]["net_mcap_change_24h"] is not None)

    # 集中度:总量对结构完全沉默,而 ⓪ 层读的是结构。
    _check("单一主体 → HHI = 1.0", herfindahl([100]) == 1.0, str(herfindahl([100])))
    _check("四家均分 → HHI = 0.25", abs(herfindahl([1, 1, 1, 1]) - 0.25) < 1e-9)
    _check("全未测 → HHI = None(不是 0)", herfindahl([None, None]) is None)

    hhi = by_t["stock"]["hhi"]
    _check(f"股票桶 HHI = {hhi:.3f}(结构信息,标量丢掉的那部分)",
           hhi is not None and 0.2 < hhi < 0.5, str(hhi))


def t_unknown_issuer_is_a_bucket_not_a_silent_drop():
    """没有发行方映射的行,归 unknown 并可见 —— 不是从分母里消失。"""
    rows = parse_rows(REAL_SHAPED, issuer_of={"nvidia": "ondo", "tesla": "ondo"})
    by_i = by_axis(rows, "issuer")
    _check("已映射的归到发行方", by_i.get("ondo", {}).get("n") == 2, str(by_i.get("ondo")))
    _check("未映射的进 unknown 桶,不是被丢掉",
           by_i.get("unknown", {}).get("n") == 5, str(by_i.get("unknown")))
    _check("两个桶加起来等于全部行",
           sum(v["n"] for v in by_i.values()) == len(rows))


def t_snapshot_carries_the_verdict_with_the_number():
    """标量单独落库 = 下一个读它的人无从判断成色。"""
    s = snapshot(parse_rows(REAL_SHAPED))
    for k in ("equity_like_total", "equity_like_verdict", "equity_like_reason",
              "by_asset_type", "by_issuer", "equity_like_n_unmeasured"):
        _check(f"快照含 {k}", k in s, str(sorted(s)))
    _check("裁决是封闭取值之一",
           s["equity_like_verdict"] in (AGREE, DISPERSED, SINGLE, NO_DATA),
           s["equity_like_verdict"])


def t_pagination_stops_on_short_page_not_on_a_page_count():
    """`per_page=250` 是**单页上限,不是总数**。

    2026-09-01 实测第 1 页返回恰好 250 条 —— 一个正好等于上限的返回值,
    是「还有更多」最典型的形状。按固定页数拉会静默截断,而截断后求和仍是
    一个像样的美元数,没有任何东西会报错。
    """
    from src.data.rwa import collect as C
    src = (ROOT / "src/data/rwa/collect.py").read_text()
    code = "\n".join(l for l in src.split("\n") if not l.lstrip().startswith("#"))
    _check("停止条件是「本页不满」", "len(batch) < PER_PAGE" in code, "找不到短页判据")
    _check("翻到硬上限仍满页 → 抛异常,不静默截断",
           "raise RuntimeError" in code and "不静默截断" in src)
    _check("MAX_PAGES 是防翻页逻辑坏掉的护栏,不是面板的预期大小",
           C.MAX_PAGES * C.PER_PAGE >= 5000, f"{C.MAX_PAGES}x{C.PER_PAGE}")


def t_two_denominators_are_never_reported_unlabelled():
    """`n_rows`(全面板)与股票/ETF 口径的计数并排 ⇒ 必须各自带前缀。

    实测 2026-09-01 首跑:`n_rows=646` / `n_measured=644` / `n_unmeasured=0`。
    读的人会算 646−644=2 并以为有 2 条未测 —— 实际 644 是股票+ETF 全部已测,
    那 2 条是商品,**根本不在这个口径里**。
    **两个不同的分母并排报告而不标注,就是让人算出一个错的差。**
    """
    s = snapshot(parse_rows(REAL_SHAPED))
    _check("全面板计数叫 n_rows", s.get("n_rows") == 7, str(s.get("n_rows")))
    _check("口径内计数带 equity_like_ 前缀",
           "equity_like_n_measured" in s and "equity_like_n_unmeasured" in s,
           str(sorted(k for k in s if "measur" in k)))
    _check("没有裸的 n_measured / n_unmeasured 与 n_rows 混在一起",
           "n_measured" not in s and "n_unmeasured" not in s,
           str(sorted(s)))
    # 判别性:两个分母确实不同,所以标注是必需的而不是装饰。
    _check("两个分母确实不同(7 vs 5)—— 不标注就会被相减",
           s["n_rows"] != s["equity_like_n_measured"],
           f'{s["n_rows"]} vs {s["equity_like_n_measured"]}')


def t_missing_issuer_map_is_empty_not_invented():
    """拿不到发行方映射 → 全落 unknown 桶(可见),而不是猜一个(不可见)。"""
    src = (ROOT / "src/data/rwa/collect.py").read_text()
    _check("issuer 拉取失败返回空 dict", "return {}" in src)
    # 真实形状核过了:/rwas/issuers/list 只给 [{id, name}],没有资产清单。
    # 正确路径是拿 id 去 /rwas/markets?issuer= 反查。
    _check("按发行方反查,而不是从清单里读资产",
           '"issuer": iid' in src, "还在假设 issuers/list 自带资产清单")
    _check("一资产多发行方 → 记冲突,不后写覆盖",
           "__conflict__" in src, "覆盖会把集中度悄悄归到最后遍历到的那家")
    _check("落库 schema 注明 market_cap NULL ≠ 0",
           "NULL = 未测" in src, "I1 没有写进表定义")
    _check("裁决与数值同表同行", "equity_like_verdict  TEXT NOT NULL" in src,
           "裁决可空 ⇒ 又会出现一个没有成色的数字")


def t_garbage_input_does_not_produce_a_confident_number():
    """空/畸形输入不得产出一个看起来正常的数。"""
    _check("空输入 → NO_DATA", total_equity_like([]).verdict == NO_DATA)
    _check("空输入 value = None", total_equity_like([]).value is None)
    _check("非 dict 元素被跳过而不抛", parse_rows([None, 1, "x"]) == [])
    _check("缺 id 的行被跳过", parse_rows([_api("", "n", "stock", 1)]) == [])
    bad = parse_rows([_api("a", "A", "stock", "not-a-number")])
    _check("非数值市值 → None(不是崩,也不是 0)", bad[0].market_cap is None)


if __name__ == "__main__":
    print("── RWA 面板守卫 (S-266) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ RWA 面板守卫全绿")
