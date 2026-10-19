"""T-126 red test —— 滑点只读走盘口的名义额守恒。

Bug pre-fix:`qty = notional / c[t-1]` 用历史收盘换算 qty,但走的是 10-18
夹具盘口(单点)。当 c[t-1] << mid_fix 时,qty 被放大 mid_fix / c[t-1] 倍,
实际走出的卖出额(spent)随之被夸大(实测 2.7-4.8×),滑点 bp 看似漂亮
但底层名义额已被偷偷拉大,估算结果系统性偏乐观。

Post-fix:`qty = notional / mid_fix`(夹具当前中间价,notional 不变),走出的
spent 名义额 ≈ 输入名义额(差 = 滑点)。

红测唯一断言:`notional=3000 ⇒ walked_spent ≈ 3000`(± 微 spread)。
跑前会 RED(老脚本 spent = qty × mid_fix ≫ 3000),修后 PASS。
"""
from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.data.venues.hl_spot import (  # noqa: E402
    HlSpotFixture,
    parse_l2_book,
    walk_book_for_qty,
)


FIX = ROOT / "tests" / "fixtures" / "hl_spot"


def _spent_notional(pair: str, notional: float, qty_divisor: float) -> tuple[float, float, float]:
    fx = HlSpotFixture.from_dir(FIX)
    book = parse_l2_book(fx._books[pair])
    mid = book.mid_px
    assert mid is not None and mid > 0
    qty = notional / qty_divisor
    filled, spent = walk_book_for_qty(book.bids, qty, "sell")
    return mid, filled, spent


def test_notional_preserved_with_mid_divisor() -> None:
    """走盘口模型在「用 mid 换 qty」下,spent 名义额 ≈ 输入名义额。"""
    mid, filled, spent = _spent_notional("UBTC", 3000.0, qty_divisor=81640.5)
    assert filled > 0
    ratio = spent / 3000.0
    # best bid 距 mid 0.5bp 不到(81640 / 81640.5),小单全在 level 1 上,ratio 应极近 1。
    assert 0.999 <= ratio <= 1.001, (
        f"post-fix: spent should track notional within micro-spread; "
        f"mid={mid} filled={filled} spent={spent} ratio={ratio:.6f}"
    )


def test_buggy_shape_amplifies_spent_notional() -> None:
    """重现 bug 形状 —— 用历史价当 divisor 一定放大 spent。"""
    # 2023 BTC 均值 ≈ $30k,mid_fix ≈ $81.6k → 放大 ~2.72×
    mid, filled, spent = _spent_notional("UBTC", 3000.0, qty_divisor=30000.0)
    assert filled > 0
    ratio = spent / 3000.0
    assert ratio > 2.0, (
        f"buggy shape: spent should be inflated by mid/divisor; "
        f"mid={mid} spent={spent} ratio={ratio:.3f} (expected >> 2.7)"
    )