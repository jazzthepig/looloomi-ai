"""主导率轨迹守卫 (S-268)。

最重要的一条不是算术:

    **两条序列按日期内连接,损耗必须被报出来。**

分子(BTC 市值)和分母(全局市值)来自两个端点,采样时刻不保证对齐。
静默的外连接会产生一条**形状对、数值错**的曲线 —— 每隔几天用错一次分母,
而主导率仍然落在 50–60% 这个看起来正常的区间里。**肉眼查不出来。**

这是「两个东西合并成一个表示」的时间维版本:两条不同节奏的序列被当成一条。
"""
from __future__ import annotations

import datetime as dt
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.market.global_history import (           # noqa: E402
    MAX_ALIGN_LOSS, MIN_ALIGNED_DAYS, MISALIGNED, NO_DATA, OK, THIN,
    build, trend,
)

_FAIL: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _ms(day_offset: int, hour: int = 0) -> int:
    base = dt.datetime(2026, 1, 1, hour, tzinfo=dt.timezone.utc)
    return int((base + dt.timedelta(days=day_offset)).timestamp() * 1000)


def _series(n, val, *, hour=0, start=0):
    return [[_ms(i, hour), val(i)] for i in range(start, start + n)]


def t_aligned_series_reads_ok():
    """两条同节奏的序列 → ok,且主导率算得对。"""
    s = build(_series(120, lambda i: 1.0e12 + i * 1e9),
              _series(120, lambda i: 2.0e12 + i * 1e9))
    _check("对齐良好 → ok", s.verdict == OK, f"{s.verdict}: {s.reason}")
    _check("120 天全部对上", s.n_aligned == 120, str(s.n_aligned))
    _check("主导率 = btc/total", abs(s.points[0].dominance - 0.5) < 1e-9,
           str(s.points[0].dominance))
    _check("损耗为 0", s.align_loss == 0, str(s.align_loss))
    _check("ok 可用", s.usable is True)


def t_misalignment_is_reported_not_silently_outer_joined():
    """**本文件的理由。** 隔天错配 → 曲线形状仍然正常,数值全错。"""
    # 分子每天都有;分母只有偶数天 —— 外连接会用前一天的分母填,得到一条
    # 平滑好看的曲线;内连接只剩一半天数,而那个「一半」必须被说出来。
    btc = _series(100, lambda i: 1.0e12)
    tot = [[_ms(i), 2.0e12] for i in range(0, 100, 2)]
    s = build(btc, tot)
    _check("只对上偶数天", s.n_aligned == 50, str(s.n_aligned))
    _check(f"损耗 {s.align_loss:.0%} 未超限(分母本来就只有 50 天)",
           s.verdict == OK, f"{s.verdict}: {s.reason}")

    # 真正的错配:分子 100 天、分母 100 天,但分母整体偏移了半天进到次日
    tot_drift = _series(100, lambda i: 2.0e12, hour=23, start=0)
    s2 = build(btc, tot_drift)
    _check("同一天两条都在 → 仍对得上(小时不影响日期)",
           s2.n_aligned == 100, str(s2.n_aligned))

    # 分母整体后移一天 ⇒ 只有重叠部分对得上
    tot_shift = _series(100, lambda i: 2.0e12, start=60)
    s3 = build(btc, tot_shift)
    _check("整体位移 → 损耗超限判 MISALIGNED", s3.verdict == MISALIGNED,
           f"{s3.verdict} 对上 {s3.n_aligned} 天: {s3.reason}")
    _check("MISALIGNED 不可用", s3.usable is False)
    _check("原因点明「形状对、数值错、肉眼查不出来」",
           "形状对" in s3.reason and "肉眼" in s3.reason, s3.reason)
    _check("点仍然给出(不可用 ≠ 抹掉)", len(s3.points) > 0)


def t_a_short_series_is_not_a_trajectory():
    """⓪ 层要的是轨迹;5 个点不是轨迹。"""
    s = build(_series(10, lambda i: 1e12), _series(10, lambda i: 2e12))
    _check(f"不足 {MIN_ALIGNED_DAYS} 天 → THIN", s.verdict == THIN, s.verdict)
    _check("THIN 不可用", s.usable is False)
    _check("原因说明拐点是轨迹的性质", "拐点" in s.reason, s.reason)
    _check("阈值不是 0(否则这条判据形同虚设)", MIN_ALIGNED_DAYS >= 20)


def t_nulls_never_become_zero():
    """I1:`null` 的市值不是 0 市值。"""
    btc = [[_ms(i), (None if i % 3 == 0 else 1e12)] for i in range(90)]
    s = build(btc, _series(90, lambda i: 2e12))
    _check("null 的天被跳过而不是当 0", s.n_btc_days == 60, str(s.n_btc_days))
    _check("没有任何一点的主导率是 0",
           all(p.dominance > 0 for p in s.points))
    # 判别性:若 null 被当 0,主导率会出现 0.0 —— 一个完全合法的浮点数。
    _check("分母为 0 的天不产生点(不是 ZeroDivision,也不是 inf)",
           all(p.total_mcap > 0 for p in s.points))
    z = build(_series(90, lambda i: 1e12), _series(90, lambda i: 0.0))
    _check("分母全 0 → 没有可用点", len(z.points) == 0, str(len(z.points)))


def t_empty_input_is_no_data_not_a_flat_line():
    _check("空输入 → NO_DATA", build([], []).verdict == NO_DATA)
    _check("单边空 → NO_DATA", build(_series(90, lambda i: 1e12), []).verdict == NO_DATA)
    _check("畸形元素被跳过而不抛",
           build([None, 1, "x", [1]], _series(90, lambda i: 2e12)).verdict == NO_DATA)


def t_trend_refuses_an_unusable_series():
    """不可用的序列不给方向 —— 一个方向词比一个数字更容易被当真。"""
    short = build(_series(10, lambda i: 1e12), _series(10, lambda i: 2e12))
    _check("THIN 序列 → trend 返回 None", trend(short) is None)

    # 主导率从 50% 升到约 55% ⇒ toward_btc
    up = build(_series(120, lambda i: 1.0e12 + i * 4e9),
               _series(120, lambda i: 2.0e12 + i * 4e9))
    t = trend(up, window=30)
    _check("可用序列给出方向", t is not None and t["direction"] == "toward_btc",
           str(t))
    _check("方向带出起止日期与变动幅度",
           t is not None and {"from", "to", "delta_pp"} <= set(t), str(t))

    # 反向:山寨与基础设施跑赢 ⇒ 主导率降
    down = build(_series(120, lambda i: 1.0e12),
                 _series(120, lambda i: 2.0e12 + i * 8e9))
    t2 = trend(down, window=30)
    _check("反向给出 toward_alt_and_infra",
           t2 is not None and t2["direction"] == "toward_alt_and_infra", str(t2))

    # 判别性:几乎不动时必须是 flat,否则这个字段只是在放大噪声
    flat = build(_series(120, lambda i: 1.0e12), _series(120, lambda i: 2.0e12))
    t3 = trend(flat, window=30)
    _check("几乎不动 → flat(不放大噪声)",
           t3 is not None and t3["direction"] == "flat", str(t3))


def t_thresholds_are_not_decorative():
    """两个阈值都要能被跨过 —— 一个永不触发的判据不是判据。"""
    _check(f"MAX_ALIGN_LOSS = {MAX_ALIGN_LOSS} 在 (0,1) 内", 0 < MAX_ALIGN_LOSS < 1)
    _check(f"MIN_ALIGNED_DAYS = {MIN_ALIGNED_DAYS} 大于典型窗口 30 的一半",
           MIN_ALIGNED_DAYS >= 15)


if __name__ == "__main__":
    print("── 主导率轨迹守卫 (S-268) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 主导率轨迹守卫全绿")
