"""display_score 的 dp 常量守住 (S-284 / O fix).

模块级 `DISPLAY_SCORE_DP` 必须与 `display_score` 的默认值一致 —— 否则一处改了
另一处没改,这个值就被静默地分成了两半。`display_score(74.97)` 与
`display_score(74.97, DISPLAY_SCORE_DP)` 必须给出同一结果。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.cis.cis_provider import (                        # noqa: E402
    DISPLAY_SCORE_DP, display_score)

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def test_default_dp_matches_constant():
    """模块级 `DISPLAY_SCORE_DP` 与 `display_score` 的默认值必须一致。

    这是 O fix 留下的契约 —— 常量是文档/可测试的形式,默认值是签名。
    """
    # 调用方不传 dp → 用签名默认值。DISPLAY_SCORE_DP 必须与之相同。
    a = display_score(74.97)
    b = display_score(74.97, DISPLAY_SCORE_DP)
    _check("display_score 默认值 == DISPLAY_SCORE_DP", a == b, f"{a} vs {b}")
    # 常量是 int,且与 grade-floor 用的 dp 量级匹配 (1 位小数)
    _check("DISPLAY_SCORE_DP == 1", DISPLAY_SCORE_DP == 1, str(DISPLAY_SCORE_DP))
    # 负控制:这个常量独立可被 import(不会因为 display_score 改名而失效)
    _check("DISPLAY_SCORE_DP 暴露为模块级符号",
           isinstance(DISPLAY_SCORE_DP, int))


def test_display_score_does_not_cross_grade_band():
    """S-252 的核心契约:显示值永不越过自己评级带的天花板。

    74.97 在 B+(>=65),不应显示成 75.0 让自己看起来像 A 档 —— display_score
    必须向下让到本带内的最大 1 位小数。
    """
    out = display_score(74.97)
    _check("74.97 → 74.9 (不跨过 A 档的下界 75)",
           out == 74.9, str(out))
    # 75.21 在 A 档,不受影响
    _check("75.21 → 75.2 (在 A 档内,不强制下取)",
           display_score(75.21) == 75.2, str(display_score(75.21)))


if __name__ == "__main__":
    print("── display_score dp 常量守卫 (S-284 / O fix) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ display_score 守卫全绿")