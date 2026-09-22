"""S-406 — 日期一律 UTC。裸的本地时间是机器时区,跨机器不一致。棘轮:只许降。

## 为什么不是「统一成日本时间」

2026-09-22 Jazz:「先解决 src 时间不统一的问题,我们是日本时间,
但刚才 preflight 失败就是因为成了东 8 时间。」

**实测之后,「统一到日本时间」会让它更糟:**

    DB TimeZone                UTC
    recorded_at                timestamptz —— 存 UTC,**自带时区,不会错**
    mark_date / trade_date / d **date(裸日期,没有时区)** ← 歧义全落在这里
    全仓提到 Asia/Tokyo 的地方  **1 处** —— JST 从来不是代码里的约定

裸 `date` 列吃的是**写入方算出来的那个日期**。
**Mac 在 JST,而每天 15:00 UTC 之后 JST 已经是第二天** ——
那之后的任何一次写入都会给行打上**明天**的日期。

而 ① 的起跑时刻正在逐日后漂(实测 01:38 → 03:12 → 04:29 → **05:43**)。
**漂过 15:00 UTC 就会发生,而且是静默的:一条日期错一天的 NAV 行,
和一条正确的行长得一模一样。**

**已经付过两次学费:**
- **S-195** coingecko 用写入日给 K 线打标签 → 08-19 BTC 记 +0.30%,**实际 +7.15%**
- **S-368** 沙箱 +09 跨 UTC 午夜 → `gap` 算出 22 而期望 23,三条断言测的不是构造的那个洞

**所以规则是:计算与存储一律 UTC,JST 只出现在显示层。**
加密行情本身就是 UTC 计日的;把人类时区带进计算,等于给每一行数据加一个
「它在哪台机器上算出来的」隐藏维度。

## 为什么不新建一个 `clock.py`

仓库里**已有 151 处**在用 `datetime.now(timezone.utc)`。
再包一层 helper 就是**第五种写法** —— 而这一周的每一个缺陷都源于同一个能力有多条活路。
**统一到既有的那一种,不发明新的。**

## 棘轮,不是一次性重写 122 处

裸本地时间总共 **194 处**,其中**被当成日期用**(落库或比较)的 **111 处**(抹掉注释后的真实数)。
后者才危险:一个 `datetime.now()` 用来算耗时是无害的。
基线冻结在当前值,**只许降**;并且 `PROTECTED` 里的文件必须**恒为 0**。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# ⚠️ 用 `tests/_source.py` 把注释和 docstring 抹掉再扫。
# 第一版直接扫原文,于是**我写来解释这个 bug 的那行注释,触发了抓这个 bug 的守卫**。
# 台账里记过一模一样的:「解释 bug 的注释废掉了抓这个 bug 的测试」——
# 当时就是为此抽出了 `_source.code_only()`。**已有解药还自己重踩,是第二次犯。**
sys.path.insert(0, str(Path(__file__).resolve().parent))
from _source import code_only  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCAN = ("src", "scripts", "paper_trading")

#: 被当成**日期**用的裸本地时间 —— 这些会落进裸 `date` 列或和日期比较。
#: `datetime.now()` 单独用来算耗时不在此列(无害,也无从判定)。
_NAIVE_DATE = re.compile(
    r"""(?x)
    \b date \. today \( \)
  | datetime \. now \( \) \. date \( \)
  | \. today \( \) \. isoformat
  | datetime \. now \( \) \. strftime \( ["']%Y-%m-%d
    """
)

#: 冻结基线。**只许降。** 降了就把这个数改小 —— 它是棘轮的棘齿。
BASELINE = 111

#: 这些文件必须**恒为 0**:它们写裸 `date` 列,错一天就是一行假数据。
#: `beta_core_paper.py` 是 ①,**我们唯一在产出的前向记录**(S-406 已清)。
PROTECTED = ("src/data/signals/beta_core_paper.py",)


def _fail(m: str) -> None:
    print(f"  ✗ {m}")
    sys.exit(1)


def _ok(m: str) -> None:
    print(f"  ✓ {m}")


def _hits() -> dict[str, int]:
    out: dict[str, int] = {}
    for top in SCAN:
        for p in sorted((ROOT / top).rglob("*.py")):
            sp = str(p.relative_to(ROOT))
            if ".venv" in sp or "__pycache__" in sp or "/tests/" in sp:
                continue
            if Path(sp).name.startswith("test_"):
                continue
            src = code_only(p.read_text(encoding="utf-8", errors="replace"))
            n = len(_NAIVE_DATE.findall(src))
            if n:
                out[sp] = n
    return out


def test_naive_local_dates_only_shrink() -> None:
    """总数只许降。升了 ⇒ RED。"""
    hits = _hits()
    total = sum(hits.values())
    if total > BASELINE:
        worst = sorted(hits.items(), key=lambda kv: -kv[1])[:6]
        _fail(
            f"裸本地日期 {total} 处 > 基线 {BASELINE} —— **新增了**。\n"
            "    裸 `date.today()` 吃机器时区;DB 的 mark_date/trade_date 是**无时区的 date**,\n"
            "    **Mac 在 JST,每天 15:00 UTC 之后写入就会打上明天的日期**,而且静默。\n"
            "    改成仓库既有的写法:`datetime.now(timezone.utc).date()`(已有 151 处在用)。\n"
            f"    最多的几个:{worst}"
        )
    if total < BASELINE:
        _fail(
            f"裸本地日期降到 {total}(基线 {BASELINE})—— **好事,但请把 BASELINE 改成 {total}**。\n"
            "    棘轮不自动下调:否则它会悄悄跟着退化回去。"
        )
    _ok(f"裸本地日期 {total} 处 = 基线(只许降)")


def test_protected_files_have_zero() -> None:
    """写裸 date 列的关键文件必须恒为 0。"""
    hits = _hits()
    bad = {f: hits[f] for f in PROTECTED if hits.get(f)}
    if bad:
        _fail(
            f"受保护文件里出现裸本地日期:{bad}\n"
            "    这些文件写 `mark_date` 这类**无时区** date 列 —— 错一天就是一行假数据,\n"
            "    而它和正确的行在库里长得一模一样。"
        )
    _ok(f"受保护文件({len(PROTECTED)} 个)零裸本地日期")


def test_the_dangerous_window_is_documented_not_assumed() -> None:
    """守住那条推理本身:JST 比 UTC 早 9 小时 ⇒ 15:00 UTC 之后就跨天。

    这条不测代码,测**算术** —— 因为整条规则都架在它上面,
    而一条没人验过的前提,是下一个人推翻规则的入口。
    """
    import datetime as dt
    probe = dt.datetime(2026, 9, 22, 15, 0, tzinfo=dt.timezone.utc)
    jst = probe.astimezone(dt.timezone(dt.timedelta(hours=9)))
    if jst.date() <= probe.date():
        _fail(f"前提不成立:15:00 UTC 时 JST 日期 {jst.date()} 未超过 UTC {probe.date()}")
    early = dt.datetime(2026, 9, 22, 14, 59, tzinfo=dt.timezone.utc)
    if early.astimezone(dt.timezone(dt.timedelta(hours=9))).date() != early.date():
        _fail("前提不成立:14:59 UTC 时两者本应同日")
    _ok("前提已验:15:00 UTC 是 JST 跨天的临界点,之前同日、之后早一天")


if __name__ == "__main__":
    print("── S-406 日期一律 UTC(棘轮) ──")
    test_the_dangerous_window_is_documented_not_assumed()
    test_protected_files_have_zero()
    test_naive_local_dates_only_shrink()
    print("\n✅ 3/3 passed")
