"""Sense 段的入口数,只减不增 (S-302)。

## 这个数是什么

**生产代码里各自发 HTTP 取价的文件数。** 2026-09-05 首测:**24**。

CLAUDE.md 规则 3b 写着「Ingestion is ONE lane (Seth), by function not by path」。
规则在,数是 24。**一条没有被任何东西检查的规则,和一条不存在的规则,
行为上是同一个东西** —— 这个文件把它变成后者的反面。

## 为什么已有的 lane 守卫不够

`tests/test_one_ingestion_lane.py` 守的是**写入者**:谁把价格写进 `ohlcv_daily`。
那个数是 3,而且被守住了。

这个文件守的是**取数者**:谁自己出去打外网拿价格。那个数是 24。

    写入者   3    受守卫 ✓
    取数者  24    在此之前无人看

**两者之差 21,就是「拿到价格用完就扔、从不落库也从不对账」的模块数。**
9 本纸面账各自在自己私有的价格上标 NAV —— 两本账可以在同一天对同一个资产
用不同的价格记账,而系统里没有任何东西会发现。

## 为什么是只减不增而不是一次修完

24 条不可能一次改完,而一个逼人做大重构的守卫会被绕过(本仓库已有先例)。
所以:**这个数只能降。** 每迁一本账到 `src/data/market/panel_read.py`,
预算跟着降一格,`scripts/loop_status.py` 的第一个数就是这件事的进度条。

**降不下来不算失败,涨上去才算。**
"""
from __future__ import annotations

import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.loop_status import sense_entrypoints            # noqa: E402

#: 2026-09-05 首测值。**只减不增。**
#: 降到新值时把这里改成新值,锁住成果 —— 与 NO_BEAT_BUDGET 同模式。
SENSE_ENTRYPOINT_BUDGET = 24

_OK, _FAIL = [], []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(label)


def t_sense_entrypoints_only_shrink() -> None:
    n = sense_entrypoints()
    _check(f"取数入口 {n} ≤ 预算 {SENSE_ENTRYPOINT_BUDGET}（只减不增）",
           n <= SENSE_ENTRYPOINT_BUDGET,
           f"新增了 {n - SENSE_ENTRYPOINT_BUDGET} 条自己打外网取价的路径。"
           f"账本要价格请走 src/data/market/panel_read.py —— "
           f"**再多一条私有取数路径,就多一处两本账对同一资产用不同价格的可能**")
    if n < SENSE_ENTRYPOINT_BUDGET:
        print(f"      ↓ 已降到 {n}，把 SENSE_ENTRYPOINT_BUDGET 改成 {n} 锁住成果")


def t_the_shared_reader_exists_and_is_composed_not_reinvented() -> None:
    """共享读取层必须是**组装**,不是第 25 条取数路径。

    如果 `panel_read.py` 自己 import httpx 去打外网,那它就不是解药,
    是又一条路径 —— 而且是带着「唯一入口」这个名字的那一条,最难被发现。
    """
    # ⚠️ 必须先剥注释与 docstring。第一版直接搜原文,命中的是**说明文字里**
    # 的 “能调的东西只有 httpx” 那一句 —— 守卫绊在自己的解释上,
    # 本 session 第六次同一个形状(见 tests/_source.py 的存在理由)。
    from tests._source import code_only
    src = code_only((ROOT / "src/data/market/panel_read.py").read_text(encoding="utf-8"))
    _check("panel_read 不自己发 HTTP", "httpx" not in src and "requests" not in src,
           "它必须组合已有的 fetch_panel / single_source / price_route，"
           "自己打外网就变成了第 25 条")
    for dep, why in (("fetch_panel", "读 ohlcv_daily 的单源实现"),
                     ("single_source", "NO CROSS-SOURCE RETURNS 的规则"),
                     ("price_route", "哪些标的禁入账本")):
        _check(f"组合了 {dep}（{why}）", dep in src)


def t_a_carried_price_is_distinguishable_from_a_quote() -> None:
    """S-287:前推的价格与真实报价在「非 NaN 且为正」上完全同形。"""
    from src.data.market.panel_read import Panel, apply_fill_mask
    vals, mask = apply_fill_mask([10.0, None, 12.0])
    _check("前推的格子被标记", mask == [False, True, False], str(mask))
    _check("前推仍然补值（研究侧需要连续序列）", vals == [10.0, 10.0, 12.0], str(vals))
    p = Panel(["A", "B"], ["d1"], [[1.0, 2.0]], [[False, True]],
              "coingecko_pro_ohlc", [])
    _check("n_usable_today 只数真实报价", p.n_usable_today == 1,
           f"得到 {p.n_usable_today}，前推的那个不该算进等权的分母")


def main() -> int:
    print("── Sense 入口只减不增 (S-302) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print()
    if _FAIL:
        print(f"🔴 {len(_FAIL)} FAILED: {_FAIL}")
        return 1
    print(f"✅ {len(_OK) or 'all'} 通过")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
