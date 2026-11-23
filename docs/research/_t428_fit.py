"""T-428:找出 fixture 里那条逐日净值是怎么算出来的(起点 / d_to / 复利口径)。"""
from __future__ import annotations

import json
import sys

sys.path.insert(0, "/Users/sbb/Projects/looloomi-ai-lane-a")

from src.data.signals.s642_short import nav, run_short
from src.data.signals.short_paper import gate_closed_by_day

fx = json.load(open("/Users/sbb/Projects/looloomi-ai-lane-a/tests/fixtures/s642_fixture.json"))
m = fx["meta"]
bars = {s: [{"trade_date": r[0], "open": r[1], "high": r[2], "low": r[3], "close": r[4], "volume": r[5]}
            for r in rows] for s, rows in fx["bars"].items()}
gate_rows = [{"d": d, "ret": r} for d, r in fx["gate"]]
gate = gate_closed_by_day(gate_rows)
exp = {d: v for d, v in fx["expected"]}
seg = m["segment"]
print("meta:", {k: m[k] for k in ("bars_from", "signal_from", "signal_to", "segment", "n_days", "n_tickets")})

for d_from in (m["bars_from"], m["signal_from"], seg[0], "2022-01-20"):
    for d_to in (m["signal_to"], seg[1]):
        tk = run_short(bars, gate, d_from=d_from, d_to=d_to)
        curve = nav(tk, bars, d_to=d_to)
        if not curve:
            print(f"d_from={d_from} d_to={d_to}: 空")
            continue
        eq = {r["d"]: r["equity"] for r in curve}
        # 只看段内:用段前一天重基
        base_d = seg[0]
        idx = sorted(eq)
        i0 = idx.index(base_d) if base_d in idx else None
        if i0 is None:
            print(f"d_from={d_from} d_to={d_to}: 段起点不在净值里(首 {idx[0]} 末 {idx[-1]}) n_tk={len(tk)}")
            continue
        base = eq[idx[i0 - 1]] if i0 > 0 else 1.0
        got = {d: eq[d] / base for d in idx if base_d <= d <= seg[1]}
        keys = sorted(set(got) & set(exp))
        err = max(abs(got[d] - exp[d]) for d in keys) if keys else None
        print(f"d_from={d_from} d_to={d_to}: n_tk={len(tk)} 段内 {len(got)} 天,最大差 {err}")
