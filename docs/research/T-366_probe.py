"""T-366 对账探针(第二轮):把「补 OI / 补 funding 后达 10 维的币数」在两种 funding 口径下对齐。

**为什么需要这个探针**:Seth 2026-11-13 的 CHANGES ① 说「补 OI 后达 10 维的是 100 币不是 172」,
per_symbol 分组是「缺 [12] 仅 100、缺 [11][12] 72、缺 [6][10][12] 26、缺 [6][10][11][12] 43」(合计 241);
而本脚本 `T-366_coverage.py` 实测是「补 OI ⇒ 170、补 funding ⇒ 170」。两者不一致,必须说明差在哪。

**假设**:Seth 的分组要求 funding **新鲜**(≤7 天),而脚本的 [11] 只要「funding_history 里有过任意时刻的行」就算实测
(`funding_history` 覆盖 239/241 个币,但最新的一批是 16 天前的)。⇒ 把 funding 口径改成「≤7 天(或有 Hyperliquid 行)」
应当复现 Seth 的 100 / 172。

**用法**:`python3 docs/research/T-366_probe.py` → 读 `T-366_traded_universe_coverage.json` 的
`minimal_plan.per_symbol`,打印各口径下的分组与计数(只读,不联网)。
"""
from __future__ import annotations

import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
JSON_PATH = os.path.join(HERE, "T-366_traded_universe_coverage.json")
TARGET = [6, 7, 8, 9, 10, 11, 12, 13, 16, 17]
FLOOR = 10


def main() -> None:
    res = json.load(open(JSON_PATH))
    ps = res["minimal_plan"]["per_symbol"]

    ages = collections.Counter(
        (v["funding_age_days"] if v["funding_age_days"] is not None else "None")
        for v in ps.values()
    )
    print("funding_age_days 分布:", ages.most_common(12))
    print("有 Hyperliquid 行的币:",
          sum(1 for v in ps.values() if v.get("funding_src_hyperliquid")))
    print("有 Hyperliquid 末根日期的币:",
          sum(1 for v in ps.values() if v.get("funding_hl_last_d")))

    def fresh_funding(v):
        a = v.get("funding_age_days")
        if a is not None and a <= 7:
            return True
        return bool(v.get("funding_hl_last_d"))

    variants = {
        "A 脚本口径(funding 任意时刻都算实测)": None,
        "B funding 必须 ≤7 天": "fresh",
        "C funding ≤7 天 或 有 Hyperliquid 行": "fresh_or_hl",
    }
    for name, mode in variants.items():
        n_oi = 0
        n_oi_fund = 0
        groups = collections.Counter()
        for v in ps.values():
            base = set(v["dims_plus_oi"])
            nofund = base - {11}
            if mode is None:
                has = 11 in base
            else:
                has = fresh_funding(v)
            dims_oi = nofund | ({11} if has else set())
            if len(dims_oi) >= FLOOR:
                n_oi += 1
            if len(nofund | {11}) >= FLOOR:
                n_oi_fund += 1
            miss = sorted(set(TARGET) - dims_oi)
            groups[",".join(str(x) for x in miss) or "none"] += 1
        print("\n== %s ==" % name)
        print("  补 OI ⇒ 达 %d 维的币: %d" % (FLOOR, n_oi))
        print("  补 OI + funding ⇒ 达 %d 维的币: %d" % (FLOOR, n_oi_fund))
        print("  补 OI 后仍缺的维(分组):", groups.most_common())


if __name__ == "__main__":
    main()
