"""T-428 探针:① fixture 上 `_s642_known_to` / `_s642_member` 的行为;② 生产窗口的算耗时(用 Mac 缓存的 bars)。"""
from __future__ import annotations

import json
import sys
import time

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai-lane-a")

from src.data.universe.state_book import _s642_known_to, _s642_member  # noqa: E402
from src.data.signals.short_paper import gate_closed_by_day  # noqa: E402

FIX = "/Users/sbb/Projects/looloomi-ai-lane-a/tests/fixtures/s642_fixture.json"
CACHE = "/Volumes/CometCloudAI/cometcloud-local/research/t428"


def counts(bars: dict[str, list[dict]]) -> dict[str, int]:
    c: dict[str, int] = {}
    for rows in bars.values():
        for r in rows:
            d = str(r["trade_date"])[:10]
            c[d] = c.get(d, 0) + 1
    return c


def main() -> None:
    fx = json.loads(open(FIX).read())
    keys = ("trade_date", "open", "high", "low", "close", "volume")
    bars = {s: [dict(zip(keys, r)) for r in rows] for s, rows in fx["bars"].items()}
    gate_rows = [{"d": d, "ret": r} for d, r in fx["gate"]]
    gate = gate_closed_by_day(gate_rows)
    c = counts(bars)
    print("[fixture] bar 天数", len(c), "首", min(c), "末", max(c))
    kt = _s642_known_to(bars, gate)
    print("[fixture] known_to =", kt, "(段末", fx["meta"]["segment"][1], ")")
    # 每天的覆盖数(2021-12 起)与规则断点
    print("[fixture] 2021-12-01 起每天覆盖数:", [(d, c[d]) for d in sorted(c) if d >= "2021-12-01" and d <= "2022-03-05"])

    # 逐日裁剪:找「裁到 X ⇒ known_to == X」的可行 X(测试用)
    good = []
    for x in sorted(c):
        if not ("2022-01-21" <= x <= "2022-03-05"):
            continue
        tb = {s: [r for r in rows if str(r["trade_date"])[:10] <= x] for s, rows in bars.items()}
        tb = {s: r for s, r in tb.items() if r}
        if _s642_known_to(tb, gate) == x:
            m = sb_member(tb, gate_rows, x)
            good.append((x, len(m["rets"]), m["known_to"]))
    print("[fixture] 裁剪后 known_to == 裁剪日 的日子(前 8 个):", good[:8])

    t0 = time.time()
    m = _s642_member(bars, gate_rows, fx["meta"]["signal_to"], d_from=fx["meta"]["signal_from"])
    print("[fixture] _s642_member 用时", round(time.time() - t0, 2), "s; known_to", m["known_to"], "reason", m["reason"])
    nav, exp = m["nav"], {d: v for d, v in fx["expected"]}
    common = sorted(set(nav) & set(exp))
    print("[fixture] 共同天数", len(common), "of", len(exp))

    # 生产窗口:用 Mac 缓存的 bars(上一轮读库缓存)量「算」的耗时
    p = f"{CACHE}/bars.jsonl"
    try:
        pb: dict[str, list[dict]] = {}
        for line in open(p):
            r = json.loads(line)
            pb.setdefault(r["symbol"], []).append(r)
        grows = json.loads(open(f"{CACHE}/gate.json").read())
        grows = grows["rows"] if isinstance(grows, dict) and "rows" in grows else grows
        t0 = time.time()
        m2 = _s642_member(pb, grows, "2026-11-22")
        print("[prod] 算用时", round(time.time() - t0, 2), "s;known_to", m2["known_to"], "reason", m2["reason"],
              ";nav 天数", len(m2["nav"]), "收益天数", len(m2["rets"]))
    except FileNotFoundError:
        print("[prod] 没有缓存", p)


def sb_member(bars, gate_rows, known_to):
    return _s642_member(bars, gate_rows, known_to, d_from="2020-03-01", known_to=known_to)


if __name__ == "__main__":
    main()
