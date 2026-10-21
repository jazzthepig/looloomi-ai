"""S-661 价值挖掘第一份:收入收益率 / 持币人收入收益率 / 收入动量 / 价值捕获比 —— 预注册见台账(2026-10-21 16:06 UTC)。

数据(缓存,不入库):`research/s661/_llama_rev.jsonl`(s661_fetch_llama.py)、`research/s661/_mcap_daily.json`(s661_fetch_mcap.py)。
两步,中间必须先把发现段结果写进台账:
    python3 docs/research/s661_value_mining.py discovery [--root …]
    python3 docs/research/s661_value_mining.py holdout --signals V3:3m,V4:1m [--root …]   # S-661,只跑一次
    python3 docs/research/s661_value_mining.py holdout --signals NV1:3m [--root …]        # S-662(−V1),只跑一次
"""
from __future__ import annotations

import bisect
import datetime as dt
import json
import math
import os
import random
import sys
from collections import defaultdict

ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv else "/Volumes/CometCloudAI/cometcloud-local"
DIR = os.path.join(ROOT, "research", "s661")
MIN_MCAP, MIN_HIST_DAYS, MIN_XS = 5e7, 120, 8
DISC = ("2021-01-31", "2023-12-31")
HOLD = ("2024-01-31", "2026-06-30")
HORIZONS = {"1m": 1, "3m": 3}
SIGNALS = ("V1", "V2", "V3", "V4", "V5")
SEED = 661


def month_ends(a: str, b: str) -> list[dt.date]:
    out, y, m = [], int(a[:4]), int(a[5:7])
    end = dt.date.fromisoformat(b)
    while True:
        nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
        d = nxt - dt.timedelta(days=1)
        if d > end:
            return out
        out.append(d)
        y, m = nxt.year, nxt.month


def add_months(d: dt.date, k: int) -> dt.date:
    y, m = d.year + (d.month - 1 + k) // 12, (d.month - 1 + k) % 12 + 1
    nxt = dt.date(y + (m == 12), m % 12 + 1, 1)
    return nxt - dt.timedelta(days=1)


# ── 数据 ─────────────────────────────────────────────────────────────────────────────────────────────────
def load():
    rev: dict[str, dict[dt.date, float]] = defaultdict(lambda: defaultdict(float))
    hrev: dict[str, dict[dt.date, float]] = defaultdict(lambda: defaultdict(float))
    start: dict[str, dt.date] = {}
    keep = set(json.load(open(os.path.join(DIR, "_slugs.json"))))
    for line in open(os.path.join(DIR, "_llama_rev.jsonl")):
        r = json.loads(line)
        g = r.get("gecko_id")
        if not g or r["slug"] not in keep:
            continue
        for key, store in (("dailyRevenue", rev), ("dailyHoldersRevenue", hrev)):
            for t, v in r.get(key) or []:
                d = dt.datetime.fromtimestamp(t, dt.timezone.utc).date()
                store[g][d] += v
                if key == "dailyRevenue":
                    start[g] = min(start.get(g, d), d)
    px: dict[str, list[tuple[dt.date, float, float]]] = defaultdict(list)
    for x in json.load(open(os.path.join(DIR, "_mcap_daily.json"))):
        if x.get("price"):
            px[x["coin_id"]].append((dt.date.fromisoformat(x["d"][:10]), float(x["price"]), float(x.get("mcap") or 0.0)))
    for g in px:
        px[g].sort()
    return rev, hrev, start, px


def at(series: list[tuple], d: dt.date, tol: int = 5):
    """最后一个 ≤ d 的观测(不超过 tol 天前);没有 ⇒ None。"""
    i = bisect.bisect_right(series, (d, float("inf"), float("inf"))) - 1
    if i < 0 or (d - series[i][0]).days > tol:
        return None
    return series[i]


def window_sum(s: dict[dt.date, float], end: dt.date, a: int, b: int) -> float:
    """Σ s[end − b … end − a](天,含两端)。"""
    return sum(s.get(end - dt.timedelta(days=k), 0.0) for k in range(a, b + 1))


def cross_section(t: dt.date, rev, hrev, start, px) -> list[dict]:
    rows = []
    for g, ser in px.items():
        if g not in rev or g not in start or (t - start[g]).days < MIN_HIST_DAYS:
            continue
        p0 = at(ser, t)
        if not p0 or p0[2] < MIN_MCAP:
            continue
        r30, r_prev = window_sum(rev[g], t, 0, 29), window_sum(rev[g], t, 30, 119)
        h30, h90, r90 = window_sum(hrev[g], t, 0, 29), window_sum(hrev[g], t, 0, 89), window_sum(rev[g], t, 0, 89)
        row = {"g": g, "mcap": p0[2], "p0": p0[1],
               "V1": r30 * 365 / 30 / p0[2], "NV1": -(r30 * 365 / 30 / p0[2]), "V2": h30 * 365 / 30 / p0[2],
               "V3": (r30 / (r_prev / 3) - 1.0) if r_prev > 0 else None,
               "V4": (h90 / r90) if r90 > 0 else None}
        for h, k in HORIZONS.items():
            p1 = at(ser, add_months(t, k))
            row["y" + h] = math.log(p1[1] / p0[1]) if p1 and p1[1] > 0 else None
        rows.append(row)
    # V5 = V1 与 V3 的截面秩相加(两者都有的)
    both = [r for r in rows if r["V3"] is not None]
    for key in ("V1", "V3"):
        for rank, r in enumerate(sorted(both, key=lambda r: r[key])):
            r["_rk" + key] = rank
    for r in rows:
        r["V5"] = (r["_rkV1"] + r["_rkV3"]) if r["V3"] is not None else None
    # 相对宇宙:减同截面等权均值
    for h in HORIZONS:
        ys = [r["y" + h] for r in rows if r["y" + h] is not None]
        mu = sum(ys) / len(ys) if ys else 0.0
        for r in rows:
            r["x" + h] = (r["y" + h] - mu) if r["y" + h] is not None else None
    return rows


def spearman(a: list[float], b: list[float]) -> float:
    def ranks(v):
        o = sorted(range(len(v)), key=lambda i: v[i])
        rk = [0.0] * len(v)
        i = 0
        while i < len(o):
            j = i
            while j + 1 < len(o) and v[o[j + 1]] == v[o[i]]:
                j += 1
            for k in range(i, j + 1):
                rk[o[k]] = (i + j) / 2.0
            i = j + 1
        return rk
    ra, rb = ranks(a), ranks(b)
    ma, mb = sum(ra) / len(ra), sum(rb) / len(rb)
    cov = sum((x - ma) * (y - mb) for x, y in zip(ra, rb))
    va = math.sqrt(sum((x - ma) ** 2 for x in ra))
    vb = math.sqrt(sum((y - mb) ** 2 for y in rb))
    return cov / (va * vb) if va and vb else 0.0


def month_stats(rows: list[dict], sig: str, h: str):
    pts = [(r[sig], r["x" + h]) for r in rows if r.get(sig) is not None and r.get("x" + h) is not None]
    if len(pts) < MIN_XS:
        return None
    ic = spearman([p[0] for p in pts], [p[1] for p in pts])
    pts.sort()
    k = len(pts) // 3
    spread = sum(p[1] for p in pts[-k:]) / k - sum(p[1] for p in pts[:k]) / k
    return ic, spread, len(pts)


def summarize(series: list[tuple]) -> dict:
    ics = [s[1] for s in series]
    n = len(ics)
    if n < 3:
        return {"months": n}
    mu = sum(ics) / n
    sd = math.sqrt(sum((x - mu) ** 2 for x in ics) / (n - 1))
    return {"months": n, "mean_ic": round(mu, 4), "t": round(mu / (sd / math.sqrt(n)), 2) if sd else None,
            "spread": round(sum(s[2] for s in series) / n, 4), "avg_n": round(sum(s[3] for s in series) / n, 1)}


def run(window: tuple[str, str], rev, hrev, start, px, sigs=SIGNALS, hz=tuple(HORIZONS)):
    res: dict = {}
    xs = {t: cross_section(t, rev, hrev, start, px) for t in month_ends(*window)}
    for sig in sigs:
        for h in hz:
            ser = []
            for t, rows in xs.items():
                st = month_stats(rows, sig, h)
                if st:
                    ser.append((t, st[0], st[1], st[2]))
            res[f"{sig}:{h}"] = {"all": summarize(ser), "series": [(t.isoformat(), round(i, 4)) for t, i, *_ in ser],
                                 "_raw": ser}
    return res, xs


def discovery():
    rev, hrev, start, px = load()
    res, xs = run(DISC, rev, hrev, start, px)
    out = {"coverage": {t.isoformat(): len(r) for t, r in xs.items()}}
    passed = []
    for key, v in res.items():
        ser = v.pop("_raw")
        h1 = summarize([s for s in ser if s[0] < dt.date(2023, 1, 1)])
        h2 = summarize([s for s in ser if s[0] >= dt.date(2023, 1, 1)])
        v["half_2021_22"], v["half_2023"] = h1, h2
        a = v["all"]
        ok = (a.get("mean_ic") or 0) > 0 and (a.get("t") or 0) >= 2.0 and (h1.get("mean_ic") or 0) > 0 \
            and (h2.get("mean_ic") or 0) > 0
        v["passes_discovery"] = ok
        if ok:
            passed.append((a["t"], key))
        out[key] = {k: v[k] for k in ("all", "half_2021_22", "half_2023", "passes_discovery")}
    out["passed"] = [k for _, k in sorted(passed, reverse=True)]
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s661_discovery.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


def holdout(spec: str):
    rev, hrev, start, px = load()
    keys = [s.strip() for s in spec.split(",") if s.strip()]
    k = len(keys)
    res, xs = run(HOLD, rev, hrev, start, px, sigs=tuple({s.split(":")[0] for s in keys}),
                  hz=tuple({s.split(":")[1] for s in keys}))
    out = {"k": k, "coverage": {t.isoformat(): len(r) for t, r in xs.items()}}
    rng = random.Random(SEED)
    for key in keys:
        ser = res[key]["_raw"]
        ics = [s[1] for s in ser]
        n = len(ics)
        blocks = [ics[i:i + 3] for i in range(0, n, 3)]
        boots = []
        for _ in range(2000):
            draw = [x for _b in range(len(blocks)) for x in rng.choice(blocks)]
            boots.append(sum(draw) / len(draw))
        p = sum(1 for b in boots if b <= 0) / len(boots)
        a = summarize(ser)
        ok = (a.get("mean_ic") or 0) > 0 and p < 0.05 / k and (a.get("spread") or 0) > 0
        out[key] = {"all": a, "p_block_boot": p, "threshold": round(0.05 / k, 4), "verdict": "过" if ok else "不过",
                    "series": res[key]["series"]}
    json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "s661_holdout.json"), "w"), indent=1)
    print(json.dumps(out, indent=1))


def onset_events():
    """只报:持币人收入「开闸」(此前 ≥ 180 天为 0、当月 > 0)之后 1 / 3 / 6 个月相对宇宙(本表所有币等权)的对数收益。"""
    rev, hrev, start, px = load()
    out = []
    for g, s in hrev.items():
        days = sorted(d for d, v in s.items() if v > 0)
        if not days or g not in px:
            continue
        first = days[0]
        if g in start and (first - start[g]).days < 180:
            continue
        p0 = at(px[g], first)
        if not p0:
            continue
        row = {"g": g, "onset": first.isoformat(), "mcap": round(p0[2] / 1e6)}
        for k in (1, 3, 6):
            p1 = at(px[g], first + dt.timedelta(days=30 * k))
            uni = []
            for h, ser in px.items():
                a0, a1 = at(ser, first), at(ser, first + dt.timedelta(days=30 * k))
                if a0 and a1 and a0[2] >= MIN_MCAP:
                    uni.append(math.log(a1[1] / a0[1]))
            if p1 and uni:
                row[f"rel_{k}m"] = round(math.log(p1[1] / p0[1]) - sum(uni) / len(uni), 3)
        out.append(row)
    print(json.dumps(sorted(out, key=lambda r: r["onset"]), indent=1))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "discovery"
    if cmd == "discovery":
        discovery()
    elif cmd == "holdout":
        holdout(sys.argv[sys.argv.index("--signals") + 1])
    elif cmd == "onset":
        onset_events()
