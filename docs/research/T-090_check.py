"""T-090 pre-registration check (run 2: n=5000 shuffles, + hit-rate diagnostic)."""
from __future__ import annotations
import os, datetime as dt, json, urllib.request, random, statistics
from collections import defaultdict

ROOT = "/Users/sbb/Projects/looloomi-ai-lane-b"
ENV_PATH = f"{ROOT}/.env"
if os.path.exists(ENV_PATH):
    for line in open(ENV_PATH):
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        os.environ.setdefault(k.strip(), v.strip())

BASE = os.environ["SUPABASE_URL"].rstrip("/")
KEY = os.environ["SUPABASE_KEY"]

def get(path: str) -> list[dict]:
    rows: list[dict] = []
    offset = 0
    while True:
        url = f"{BASE}/rest/v1/{path}&limit={1000}&offset={offset}" if "limit=" not in path else f"{BASE}/rest/v1/{path}"
        req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            chunk = json.loads(r.read().decode())
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        offset += 1000

print("[1/5] pulling cis_standard_outcomes (crypto) ...")
so = get("cis_standard_outcomes?select=symbol,d,alpha&grp=eq.crypto&alpha=not.is.null")
print(f"    got {len(so)} rows, d range: {min(r['d'] for r in so)} → {max(r['d'] for r in so)}")

print("[2/5] pulling cis_rebuild_daily v1.3 ...")
rb_rows = get("cis_rebuild_daily?select=symbol,d,pillar_f,score&code_ref=eq.cis-standard-v1.3")

print("[3/5] pulling state_daily mom_20, style_rel_majors_30d ...")
sd_mom = get("state_daily?select=d,value&entity=eq.panel&feature=eq.mom_20")
sd_sty = get("state_daily?select=d,value&entity=eq.panel&feature=eq.style_rel_majors_30d")

mom_by_d = {r["d"]: r["value"] for r in sd_mom}
sty_by_d = {r["d"]: r["value"] for r in sd_sty}
rb_by_sd = {(r["symbol"], r["d"]): r for r in rb_rows}

all_ds = sorted({r["d"] for r in so})
def mondays(lo: str, hi: str) -> list[str]:
    out, cur, end_d = [], dt.date.fromisoformat(lo), dt.date.fromisoformat(hi)
    while cur <= end_d:
        if cur.weekday() == 0:
            out.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    return out

monday_set = set(mondays("2023-01-02", all_ds[-1]))

joined = []
for r in so:
    d = r["d"]
    if d not in monday_set:
        continue
    rb = rb_by_sd.get((r["symbol"], d))
    if not rb or rb.get("pillar_f") is None:
        continue
    d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
    m, s = mom_by_d.get(d1), sty_by_d.get(d1)
    if m is None or s is None:
        continue
    is_a = (m > 0) and (s <= 0)
    joined.append({"symbol": r["symbol"], "d": d, "alpha": float(r["alpha"]),
                   "pillar_f": float(rb["pillar_f"]), "state": "A" if is_a else "B"})
print(f"[4/5] joined (week × symbol): {len(joined)}")

by_week = defaultdict(list)
for j in joined:
    by_week[j["d"]].append(j)

def tertile_spread(rows):
    if len(rows) < 6:
        return None
    rs = sorted(rows, key=lambda r: r["pillar_f"])
    n = len(rs)
    l_set = rs[: n // 3]
    h_set = rs[-2 * (n // 3):]
    if not h_set or not l_set:
        return None
    return sum(r["alpha"] for r in h_set) / len(h_set) - sum(r["alpha"] for r in l_set) / len(l_set)

def hit_rate(rows):
    if len(rows) < 6:
        return None
    rs = sorted(rows, key=lambda r: r["pillar_f"])
    n = len(rs)
    l_set = rs[: n // 3]
    h_set = rs[-2 * (n // 3):]
    top_mean = sum(r["alpha"] for r in h_set) / len(h_set)
    bot_mean = sum(r["alpha"] for r in l_set) / len(l_set)
    return float(top_mean > bot_mean)

h1_end = "2024-12-30"
h2_start = "2025-01-06"
weeks_full = sorted(by_week.keys())
weeks_h1 = [w for w in weeks_full if w <= h1_end]
weeks_h2 = [w for w in weeks_full if w >= h2_start]
print(f"    weeks H1={len(weeks_h1)}  H2={len(weeks_h2)}")

def make_series(weeks):
    out = {}
    for w in weeks:
        s = tertile_spread(by_week[w])
        if s is not None:
            out[w] = s
    return out

spread_h1 = make_series(weeks_h1)
spread_h2 = make_series(weeks_h2)
labels = {w: by_week[w][0]["state"] for w in weeks_full}

def mean_for_state(spreads, state):
    xs = [v for w, v in spreads.items() if labels.get(w) == state]
    if not xs:
        return float("nan")
    return sum(xs) / len(xs)

mu_A_h1 = mean_for_state(spread_h1, "A")
mu_B_h1 = mean_for_state(spread_h1, "B")
mu_A_h2 = mean_for_state(spread_h2, "A")
mu_B_h2 = mean_for_state(spread_h2, "B")

# Hit-rate per week (week-level fraction of weeks in A where top beats bottom)
def hit_rate_state(weeks, state):
    cnt = 0
    n2 = 0
    for w in weeks:
        if labels.get(w) != state:
            continue
        h = hit_rate(by_week[w])
        if h is None:
            continue
        cnt += int(h)
        n2 += 1
    return cnt / n2 if n2 else float("nan")

# Block-shuffle (8-week blocks), n=5000
random.seed(20261014)
def block_shuffle_pct(actual_mu, weeks, spreads, n=5000, block=8):
    seq_labels = [labels[w] for w in weeks if w in labels]
    weeks_with_label = [w for w in weeks if w in labels]
    spreads_aligned = [spreads.get(w) for w in weeks_with_label]
    if not seq_labels:
        return float("nan"), float("nan"), float("nan"), []
    cnt = 0
    shuf_mus = []
    for _ in range(n):
        sh = list(seq_labels)
        for bs in range(0, len(sh), block):
            be = min(bs + block, len(sh))
            sub = sh[bs:be]
            random.shuffle(sub)
            sh[bs:be] = sub
        xs = [s for s, lab in zip(spreads_aligned, sh) if lab == "A" and s is not None]
        mu = sum(xs) / len(xs) if xs else float("nan")
        if not math.isnan(mu) and mu <= actual_mu:
            cnt += 1
        shuf_mus.append(mu)
    pct = cnt / n
    shuf_clean = [x for x in shuf_mus if not math.isnan(x)]
    return pct, (min(shuf_clean) if shuf_clean else float("nan")), (max(shuf_clean) if shuf_clean else float("nan")), shuf_clean

import math
pct_h1, sh_lo_h1, sh_hi_h1, _ = block_shuffle_pct(mu_A_h1, weeks_h1, spread_h1, n=5000, block=8)
pct_h2, sh_lo_h2, sh_hi_h2, _ = block_shuffle_pct(mu_A_h2, weeks_h2, spread_h2, n=5000, block=8)

# Hit rates (week-level fraction where top-tertile mean alpha > bottom-tertile mean alpha)
hit_A_h1 = hit_rate_state(weeks_h1, "A")
hit_A_h2 = hit_rate_state(weeks_h2, "A")
hit_B_h1 = hit_rate_state(weeks_h1, "B")
hit_B_h2 = hit_rate_state(weeks_h2, "B")

n_A_h1 = sum(1 for w in weeks_h1 if labels.get(w) == "A")
n_B_h1 = sum(1 for w in weeks_h1 if labels.get(w) == "B")
n_A_h2 = sum(1 for w in weeks_h2 if labels.get(w) == "A")
n_B_h2 = sum(1 for w in weeks_h2 if labels.get(w) == "B")

verdict_h1 = "PASS" if (pct_h1 <= 0.05 and mu_A_h1 < 0) else "FAIL"
verdict_h2 = "PASS" if (pct_h2 <= 0.05 and mu_A_h2 < 0) else "FAIL"

results = {
    "panel": {
        "n_joined_rows": len(joined),
        "n_weeks_total": len(weeks_full),
        "weeks_H1_2023_2024": len(weeks_h1),
        "weeks_H2_2025_latest": len(weeks_h2),
    },
    "F_top_minus_bot_pp_by_state": {
        "H1": {
            "mu_A_pp": round(mu_A_h1 * 100, 2), "mu_B_pp": round(mu_B_h1 * 100, 2),
            "n_A_weeks": n_A_h1, "n_B_weeks": n_B_h1,
            "hit_rate_A_top_gt_bot": round(hit_A_h1, 3),
            "hit_rate_B_top_gt_bot": round(hit_B_h1, 3),
            "block_shuffle_pctile_A_pct": round(pct_h1 * 100, 1),
            "shuffle_lo_pp": round(sh_lo_h1 * 100, 2), "shuffle_hi_pp": round(sh_hi_h1 * 100, 2),
            "verdict": verdict_h1,
        },
        "H2": {
            "mu_A_pp": round(mu_A_h2 * 100, 2), "mu_B_pp": round(mu_B_h2 * 100, 2),
            "n_A_weeks": n_A_h2, "n_B_weeks": n_B_h2,
            "hit_rate_A_top_gt_bot": round(hit_A_h2, 3),
            "hit_rate_B_top_gt_bot": round(hit_B_h2, 3),
            "block_shuffle_pctile_A_pct": round(pct_h2 * 100, 1),
            "shuffle_lo_pp": round(sh_lo_h2 * 100, 2), "shuffle_hi_pp": round(sh_hi_h2 * 100, 2),
            "verdict": verdict_h2,
        },
    },
    "global_verdict": "PASS" if (verdict_h1 == "PASS" and verdict_h2 == "PASS") else "FAIL",
    "criteria_met": {
        "H1_pct_le_5pct": pct_h1 <= 0.05,
        "H1_mu_A_negative": mu_A_h1 < 0,
        "H2_pct_le_5pct": pct_h2 <= 0.05,
        "H2_mu_A_negative": mu_A_h2 < 0,
    },
}

print(json.dumps(results, indent=2, default=str))

with open(f"{ROOT}/docs/research/T-090_check_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"wrote {ROOT}/docs/research/T-090_check_results.json")