"""S-666:主机复核规则 V 的两种错误率 —— 真票被挡多少、伪造票能过多少(台账 S-666 预注册,2026-10-22 01:16 UTC)。

    python3 docs/research/s666_host_verify.py [--root /Volumes/CometCloudAI/cometcloud-local/research]

真票 = 770 张 R-v2 回放票(t159);ref_close = 币安信号日收盘;stop_frac = (进场 − 止损) ÷ 信号日收盘(= 2.5 × ATR14 ÷ 收盘)。
币名按主机的 `tickets.resolve_coin`(与线上一致);HL 日线取自 s657 缓存。
伪造 = 每张真票的信号日,固定种子从当天没有 R-v2 票、HL 有那根日线的币里抽 1 个,ref_close / stop_frac 用 HL 自己的(攻击者最优)。
规则只来自 `src.exec_host.verify.rv2_check` —— 主机上跑的就是这一个函数。

结果(台账 S-666,2026-10-22 01:3x UTC):① ✗ 真票(≥ 2023)78.0% · ② ✓ 伪造 6.1% · ③ ✓ < 2023 85.2% ⇒ 主机默认 report。
注意:S-666 跑的时候 `resolve_coin` 还不认币安的 1000 前缀(1000SHIB → kSHIB 是之后补的),现在重跑「认得出的票」会多几张。
"""
from __future__ import annotations

import argparse
import collections
import json
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.exec_host.tickets import resolve_coin  # noqa: E402
from src.exec_host.verify import ATR_N, STOP_ATR, rv2_check  # noqa: E402

SEED = 666
SPLIT = "2023-01-01"


def load(root: Path):
    tk = json.loads((root / "t159" / "_tickets_2020-03-01_2026-06-20.json").read_text())["long"]
    closes: dict[tuple[str, str], float] = {}
    for f in (root / "t156" / "_bars_early.jsonl", root / "t156" / "_bars.jsonl", root / "t159" / "_bars.jsonl"):
        for line in f.read_text().splitlines():
            for b in json.loads(line):
                closes[(b["symbol"], b["trade_date"][:10])] = float(b["close"])
    hl: dict[str, list[dict]] = {}
    for line in (root / "s657" / "_hl_daily.jsonl").read_text().splitlines():
        r = json.loads(line)
        hl[r["coin"]] = sorted(r["bars"], key=lambda b: b["d"])
    return tk, closes, hl


def hl_stop_frac(bars: list[dict], d: str) -> tuple[float, float] | None:
    upto = [b for b in bars if b["d"] <= d]
    if len(upto) < ATR_N + 1 or upto[-1]["d"] != d:
        return None
    trs = [max(upto[i]["h"] - upto[i]["l"], abs(upto[i]["h"] - upto[i - 1]["c"]), abs(upto[i]["l"] - upto[i - 1]["c"]))
           for i in range(len(upto) - ATR_N, len(upto))]
    c = upto[-1]["c"]
    return c, STOP_ATR * (sum(trs) / ATR_N) / c


def rate(rows):
    n = len(rows)
    k = sum(1 for r in rows if r["ok"])
    return {"n": n, "passed": k, "rate": round(k / n, 4) if n else None}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local/research")
    ap.add_argument("--out", default=str(Path(__file__).with_name("s666_results.json")))
    a = ap.parse_args()
    tk, closes, hl = load(Path(a.root))
    names = set(hl)
    assert len(tk) == 770, len(tk)
    total_r = sum(t["r"] or 0.0 for t in tk)
    print(f"票 {len(tk)} 张,总 R {total_r:.3f}(台账 369.008 = 扣成本后;未平的票 r 为空)")

    legit, unresolved, no_close = [], [], 0
    for t in tk:
        coin = resolve_coin(t["symbol"], names)
        if coin is None:
            unresolved.append(t["symbol"])
            continue
        c = closes.get((t["symbol"], t["signal_d"]))
        if not c:
            no_close += 1
            continue
        sf = (t["entry_px"] - t["stop_px"]) / c
        v = rv2_check(hl[coin], t["signal_d"], c, sf)
        legit.append({"ticket": f"{t['symbol']}:{t['signal_d']}", "coin": coin, "d": t["signal_d"], "r": t["r"] or 0.0,
                      "ok": v["ok"], "fails": v["fails"], "has_bar": not any(f.startswith("V1") for f in v["fails"])})

    covered = [r for r in legit if r["has_bar"]]
    by_day = collections.defaultdict(set)
    for r in legit:
        by_day[r["d"]].add(r["coin"])
    rng = random.Random(SEED)
    fakes = []
    coins_sorted = sorted(names)
    for r in covered:
        d = r["d"]
        pool = [k for k in coins_sorted if k not in by_day[d] and hl_stop_frac(hl[k], d)]
        if not pool:
            continue
        k = rng.choice(pool)
        c, sf = hl_stop_frac(hl[k], d)
        v = rv2_check(hl[k], d, c, sf)
        fakes.append({"coin": k, "d": d, "ok": v["ok"], "fails": v["fails"]})

    post = [r for r in covered if r["d"] >= SPLIT]
    pre = [r for r in covered if r["d"] < SPLIT]
    fake_post = [r for r in fakes if r["d"] >= SPLIT]
    res = {
        "tickets": len(tk), "unresolved_on_hl": len(unresolved), "unresolved_symbols": sorted(set(unresolved)),
        "no_binance_close": no_close, "resolved": len(legit), "hl_has_signal_bar": len(covered),
        "legit_ge_2023": rate(post), "legit_lt_2023": rate(pre), "legit_all": rate(covered),
        "fake_all": rate(fakes), "fake_ge_2023": rate(fake_post),
        "verdict": {
            "1_legit_ge_2023_ge_90pct": bool(post) and rate(post)["rate"] >= 0.90,
            "2_fake_le_15pct": bool(fakes) and rate(fakes)["rate"] <= 0.15,
            "3_legit_lt_2023_ge_80pct": bool(pre) and rate(pre)["rate"] >= 0.80,
        },
        "report_only": {
            "legit_fail_reasons": collections.Counter(f.split(" ")[0] for r in covered if not r["ok"] for f in r["fails"]),
            "fake_fail_reasons": collections.Counter(f.split(" ")[0] for r in fakes if not r["ok"] for f in r["fails"]),
            "legit_passed_mean_r": round(sum(r["r"] for r in covered if r["ok"]) / max(1, sum(r["ok"] for r in covered)), 4),
            "legit_rejected_mean_r": round(sum(r["r"] for r in covered if not r["ok"]) /
                                           max(1, sum(not r["ok"] for r in covered)), 4),
            "legit_rejected_sum_r": round(sum(r["r"] for r in covered if not r["ok"]), 3),
            "legit_rejected_examples": [{k: r[k] for k in ("ticket", "coin", "r", "fails")}
                                        for r in covered if not r["ok"]][:12],
        },
    }
    Path(a.out).write_text(json.dumps(res, ensure_ascii=False, indent=1, default=dict))
    print(json.dumps({k: v for k, v in res.items() if k not in ("unresolved_symbols",)}, ensure_ascii=False,
                     indent=1, default=dict)[:5000])


if __name__ == "__main__":
    main()
