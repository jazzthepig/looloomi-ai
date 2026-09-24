"""S-421 — 结论必须带着它的问题。

2026-09-24 我读到 STRATEGY_PLAYBOOK 里 Strategy 3/4 的「🔴 REFUTED」,就建议停掉那两本账。
Jazz 问:「证伪的条件问对问题了吗?有没有可能是错的风格周期,而不是错的策略?」—— 复核后问题确实问错了(S-420)。

**根子不在设计,在注意力:** 上下文压缩之后,留下来的只有标签,标签背后的推理没有留下来。
提醒自己「更小心」挡不住下一次压缩。能挡住的是让文件本身带着推理:
STRATEGY_PLAYBOOK 里每一个带 🔴/✅ 的结论标题,它的段落里必须写明三样东西 ——

    基准:   对照的是什么(是否「持有同一面板」)
    regime: 是否分了 regime,分了哪些
    判据:   判据原文

缺任何一样,结论就只是一个标签。现有的旧结论列在 `AWAITING_REASK`(待重问),**只减不增**;
补齐三样之后必须从名单里删掉(反向检查),否则名单会悄悄过期。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PLAYBOOK = ROOT / "STRATEGY_PLAYBOOK.md"

_VERDICT_HEADING = re.compile(r"^(#{2,4})\s+(.*(?:🔴|✅).*(?:REFUTED|SHIP|LIVE).*)$")
_MARKERS = {
    "基准": re.compile(r"(基准|benchmark)\s*[::]", re.I),
    "regime": re.compile(r"regime\s*[::]", re.I),
    "判据": re.compile(r"(判据|criterion|criteria)\s*[::]", re.I),
}

#: 2026-09-24 的存量:结论标题在,三样没写全。**只减不增。** 补齐后删掉对应行。
AWAITING_REASK = {
    "Strategy 2 — R89 Perp-Spot Basis Sleeve — 🔴 REFUTED (taker-fee illusion)",
    "Strategy 3 — Pod Aggregator (Millennium flavor) — 🔴 REFUTED on real data (2026-08-24)",
    "Strategy 4 — Cross-Asset Quality-Momentum-LowVol Tilt (AQR flavor) — 🔴 REFUTED on real data (2026-08-24)",
    "Strategy 3 — Pod Aggregator (🔴 REFUTED on real data 2026-08-24)",
    "Strategy 4 — Cross-Asset Factor Tilt (🔴 REFUTED on real data 2026-08-24)",
    "Strategy 2 — R76 Standalone Funding Residual L/S (2026-08-24) — ✅ SHIPPED",
}


def verdicts() -> dict[str, list[str]]:
    """{结论标题: 缺的标记}。段落 = 到下一个同级或更高级标题为止。"""
    lines = PLAYBOOK.read_text(encoding="utf-8").splitlines()
    out: dict[str, list[str]] = {}
    for i, line in enumerate(lines):
        m = _VERDICT_HEADING.match(line)
        if not m:
            continue
        level = len(m.group(1))
        body = []
        for nxt in lines[i + 1:]:
            h = re.match(r"^(#{1,6})\s", nxt)
            if h and len(h.group(1)) <= level:
                break
            body.append(nxt)
        text = "\n".join(body)
        out[m.group(2).strip()] = [k for k, rx in _MARKERS.items() if not rx.search(text)]
    return out


def test_new_verdicts_carry_their_question() -> None:
    v = verdicts()
    bad = {h: miss for h, miss in v.items() if miss and h not in AWAITING_REASK}
    assert not bad, (
        "这些结论只有标签,没有它的问题 —— 段落里补上「基准:」「regime:」「判据:」:\n  "
        + "\n  ".join(f"{h}  缺 {m}" for h, m in bad.items()))
    print(f"  ✓ {len(v)} 个结论标题:新结论都带着基准 / regime / 判据")


def test_the_reask_list_only_shrinks() -> None:
    v = verdicts()
    assert len(AWAITING_REASK) <= 6, "待重问名单只减不增(2026-09-24 基线 6)—— 新结论请直接写全三样"
    stale = [h for h in AWAITING_REASK if h in v and not v[h]]
    gone = [h for h in AWAITING_REASK if h not in v]
    assert not stale, f"这些已补齐三样,请从 AWAITING_REASK 删掉:{stale}"
    assert not gone, f"这些标题已不存在(改名或删除),请从 AWAITING_REASK 删掉:{gone}"
    print(f"  ✓ 待重问 {len(AWAITING_REASK)} 条,名单没有过期项")


if __name__ == "__main__":
    print("── S-421 结论必须带着它的问题 ──")
    test_new_verdicts_carry_their_question()
    test_the_reask_list_only_shrinks()
    print("\n✅ 2/2 passed")
