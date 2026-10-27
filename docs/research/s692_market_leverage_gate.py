"""S-692(台账,预注册 2026-10-27 04:33 UTC):全市场杠杆偏高时 ① 降到 0.5。Seth 版;C 道 T-207 独立复算。

输入 docs/research/s692_series.txt(Supabase 上算出:BTC 日收益 ×1e5、每天的降仓标记 —— 标记 = 前一天 z > 1;
'-' = z 窗口不足 300 个值,当作不降仓)。L_d = 当天市值前 30(有 Binance OI 且过映射校验的名字)Σ OI / Σ 市值,
z_d = (L_d − 过去 365 天均值) / 标准差(d 当天不进窗口)。
"""
import json
import math
import random
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent


def load(p: Path):
    kv = dict(line.split("=", 1) for line in p.read_text().strip().splitlines())
    d0, n = date.fromisoformat(kv["d0"]), int(kv["n"])
    ret = [int(x) / 1e5 for x in kv["btc_1e5"].split(",")]
    flag = kv["flag"]
    assert len(ret) == n == len(flag), (len(ret), n, len(flag))
    days = [d0 + timedelta(days=i) for i in range(n)]
    expo = [0.5 if f == "1" else 1.0 for f in flag]
    return days, ret, expo


def stats(ret, expo, days):
    nav, peak, mdd = 1.0, 1.0, 0.0
    for r, e in zip(ret, expo):
        nav *= 1 + e * r
        peak = max(peak, nav)
        mdd = max(mdd, 1 - nav / peak)
    yrs = (days[-1] - days[0]).days / 365.25
    cagr = nav ** (1 / yrs) - 1
    return {"total": round(nav - 1, 4), "cagr": round(cagr, 4), "mdd": round(mdd, 4), "calmar": round(cagr / mdd, 4) if mdd else None}


def run(p: Path) -> dict:
    days, ret, expo = load(p)
    hold = [1.0] * len(ret)
    g, h = stats(ret, expo, days), stats(ret, hold, days)
    rng = random.Random(692)
    n = len(expo)
    null = []
    for _ in range(2000):
        k = rng.randrange(1, n)
        sh = expo[k:] + expo[:k]
        null.append(stats(ret, sh, days)["calmar"])
    null.sort()
    p95 = null[int(0.95 * (len(null) - 1))]
    cut = days.index(date(2024, 11, 1))
    halves = {}
    for name, sl in (("2023-01_2024-10", slice(0, cut)), ("2024-11_2026-09", slice(cut, n))):
        halves[name] = {"gated": stats(ret[sl], expo[sl], days[sl]), "hold": stats(ret[sl], hold[sl], days[sl])}
    c1 = g["mdd"] <= 0.85 * h["mdd"]
    c2 = g["calmar"] > p95
    c3 = all(v["gated"]["calmar"] >= v["hold"]["calmar"] for v in halves.values())
    return {"ledger": "S-692", "asset": "BTC", "n_days": n, "derisked_days": sum(1 for e in expo if e < 1),
            "gated": g, "hold": h, "null_calmar_p95": p95, "null_calmar_median": null[len(null) // 2],
            "gated_calmar_pct_in_null": round(sum(1 for x in null if x < g["calmar"]) / len(null), 4),
            "halves": halves,
            "verdict": {"c1_mdd_15pct_shallower": c1, "c2_calmar_above_null_p95": c2, "c3_both_halves_calmar_ge_hold": c3,
                        "pass": c1 and c2 and c3}}


if __name__ == "__main__":
    out = run(Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "s692_series.txt")
    json.dump(out, open(HERE / "s692_results.json", "w"), ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
