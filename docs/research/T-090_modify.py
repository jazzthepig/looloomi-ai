"""T-090 modify v3 — fixed data dedupe, proper drift, working random shuffle."""
from __future__ import annotations
import os, datetime as dt, json, urllib.request, math, random, statistics
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

def get_all(path):
    rows = []
    offset = 0
    while True:
        url = f"{BASE}/rest/v1/{path}&limit={1000}&offset={offset}" if "limit" in path else f"{BASE}/rest/v1/{path}&offset={offset}"
        req = urllib.request.Request(url, headers={"apikey": KEY, "Authorization": f"Bearer {KEY}"})
        with urllib.request.urlopen(req, timeout=120) as r:
            chunk = json.loads(r.read().decode())
        rows.extend(chunk)
        if len(chunk) < 1000:
            return rows
        offset += 1000

print("[1/7] pulling cis_a1_u_replay daily rows ...")
tilt = get_all("cis_tilt_daily?select=d,ret,weights,turnover&arm=eq.cis_a1_u_replay&order=d.asc")
print(f"    {len(tilt)} rows; first {tilt[0]['d']} last {tilt[-1]['d']}")

print("[2/7] pulling cis_rebuild_daily v1.3 with explicit order + dedupe ...")
rb = get_all("cis_rebuild_daily?select=symbol,d,pillar_f,pillar_m,pillar_o,pillar_s,pillar_a&code_ref=eq.cis-standard-v1.3&order=symbol.asc,d.asc")
seen = set()
pillar_by_sd = {}
for r in rb:
    k = (r["symbol"], r["d"])
    if k in seen: continue
    seen.add(k)
    pillar_by_sd[k] = r
print(f"    {len(pillar_by_sd)} unique (sym, d)")

print("[3/7] pulling state_daily mom_20 + style_rel_majors_30d ...")
sd_mom = get_all("state_daily?select=d,value&entity=eq.panel&feature=eq.mom_20")
sd_sty = get_all("state_daily?select=d,value&entity=eq.panel&feature=eq.style_rel_majors_30d")
mom_by_d = {r["d"]: r["value"] for r in sd_mom}
sty_by_d = {r["d"]: r["value"] for r in sd_sty}

print("[4/7] pulling core_u_replay daily returns ...")
core = get_all("multiplier_daily?select=d,ret&arm=eq.core_u_replay&order=d.asc")

print("[5/7] pulling panel prices from asset_mcap_daily ...")
panel_syms = sorted(tilt[0]["weights"].keys())
sym_list = ",".join(panel_syms)
price_rows = get_all(f"asset_mcap_daily?select=symbol,d,price&symbol=in.({sym_list})&source=eq.coingecko_pro_market_chart&order=symbol.asc,d.asc")
px_by_sd = {}
for r in price_rows:
    if r.get("price") is None: continue
    px_by_sd.setdefault(r["symbol"], {})[r["d"]] = float(r["price"])

# ---------- helpers ----------
W_F = 0.25; W_M = 0.20; W_O = 0.20; W_S = 0.15; W_A = 0.20
W_4 = W_M + W_O + W_S + W_A
W4_M, W4_O, W4_S, W4_A = W_M/W_4, W_O/W_4, W_S/W_4, W_A/W_4
K = 0.5

def composite_5p(p): return W_F*p["pillar_f"] + W_M*p["pillar_m"] + W_O*p["pillar_o"] + W_S*p["pillar_s"] + W_A*p["pillar_a"]
def composite_4p(p): return W4_M*p["pillar_m"] + W4_O*p["pillar_o"] + W4_S*p["pillar_s"] + W4_A*p["pillar_a"]

def cis_z(scores, names):
    have = {s: float(v) for s, v in scores.items() if s in names and v is not None and math.isfinite(v)}
    if len(have) < 2:
        return {s: 0.0 for s in names}, len(have)
    mu = sum(have.values()) / len(have)
    sd = math.sqrt(sum((v-mu)**2 for v in have.values()) / (len(have)-1))
    if not sd > 0:
        return {s: 0.0 for s in names}, len(have)
    return {s: ((have[s]-mu)/sd if s in have else 0.0) for s in names}, len(have)

# build rebalance days + z
dates = [r["d"] for r in tilt]
def is_rebalance(d):
    return d == dates[0] or dt.date.fromisoformat(d).weekday() == 0
rebal_days = sorted({d for d in dates if is_rebalance(d)})

def is_a_state(d):
    d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
    m, s = mom_by_d.get(d1), sty_by_d.get(d1)
    return (m is not None and s is not None and m > 0 and s <= 0)

print(f"[6/6] computing z for {len(rebal_days)} rebalance days ...")
z_full = {}
z_no_f = {}
n_full_per_day = []
n_no_f_per_day = []
for d in rebal_days:
    d1 = (dt.date.fromisoformat(d) - dt.timedelta(days=1)).isoformat()
    full, no_f = {}, {}
    for sym in panel_syms:
        p = pillar_by_sd.get((sym, d1))
        if p is None: continue
        if all(p.get(k) is not None for k in ("pillar_f","pillar_m","pillar_o","pillar_s","pillar_a")):
            full[sym] = composite_5p(p)
            no_f[sym] = composite_4p(p)
    z_full[d], n_f = cis_z(full, panel_syms)
    z_no_f[d], n_nf = cis_z(no_f, panel_syms)
    n_full_per_day.append(n_f)
    n_no_f_per_day.append(n_nf)
print(f"    z_full: min={min(n_full_per_day)}  median={statistics.median(n_full_per_day)}  max={max(n_full_per_day)}")
print(f"    z_no_f: min={min(n_no_f_per_day)}  median={statistics.median(n_no_f_per_day)}  max={max(n_no_f_per_day)}")
print(f"    A-state rebal days: {sum(1 for d in rebal_days if is_a_state(d))}")

weights_at_d = {r["d"]: r["weights"] for r in tilt}

# helper: price-at-or-prev
def price_at_or_prev(sym, d):
    mp = px_by_sd.get(sym, {})
    if d in mp: return mp[d]
    latest = None
    for k in sorted(mp.keys()):
        if k <= d: latest = mp[k]
        else: break
    return latest

# ---------- build modified weights via delta-z ----------
def build_modified_weights(z_choice: dict[str, dict]) -> dict[str, dict]:
    out = {}
    for d in rebal_days:
        w_orig = weights_at_d[d]
        z_orig = z_full[d]
        z_new = z_choice[d]
        raw = {s: float(w_orig.get(s, 0)) * math.exp(K * (z_new.get(s, 0) - z_orig.get(s, 0))) for s in w_orig}
        s_total = sum(v for v in raw.values() if v > 0)
        if s_total > 0:
            out[d] = {k: v/s_total for k, v in raw.items()}
        else:
            out[d] = w_orig
    return out

# z_choice for "modified" (A-state replaced by no_f)
z_choice_modified = {d: (z_no_f[d] if is_a_state(d) else z_full[d]) for d in rebal_days}
modified_weights = build_modified_weights(z_choice_modified)

# ---------- simulate NAV with proper drift ----------
def run_nav(rebal_weights: dict[str, dict]) -> dict[str, float]:
    rebal_set = set(rebal_days)
    nav_by_d = {}
    cur_w = None
    last_rebal = None
    pv = 1.0
    nav_cum = 1.0
    for r in tilt:
        d = r["d"]
        if d in rebal_set:
            cur_w = rebal_weights[d]
            last_rebal = d
            pv = 1.0
            nav_by_d[d] = nav_cum
            continue
        if cur_w is None or last_rebal is None:
            nav_by_d[d] = nav_cum
            continue
        pv_today = 0.0
        for sym, w in cur_w.items():
            if w <= 0: continue
            p_rebal = price_at_or_prev(sym, last_rebal)
            p_today = price_at_or_prev(sym, d)
            if p_rebal is None or p_today is None or p_rebal <= 0:
                continue
            pv_today += w * (p_today / p_rebal)
        ret = pv_today / pv - 1
        nav_cum *= (1 + ret)
        pv = pv_today
        nav_by_d[d] = nav_cum
    return nav_by_d

print("[7/7] running modified NAV + 200 random permutations ...")
nav_mod = run_nav(modified_weights)
nav_orig = {}
nav_cum = 1.0
for r in tilt:
    nav_cum *= (1 + float(r["ret"]))
    nav_orig[r["d"]] = nav_cum
nav_core = {}
nav_cum = 1.0
for r in core:
    nav_cum *= (1 + float(r["ret"]))
    nav_core[r["d"]] = nav_cum

print(f"    modified final NAV: {nav_mod[list(nav_mod.keys())[-1]]:.4f}")
print(f"    original final NAV: {nav_orig[list(nav_orig.keys())[-1]]:.4f}")
print(f"    core_u final NAV:   {nav_core[list(nav_core.keys())[-1]]:.4f}")

# ---------- random tilt null (200 draws) ----------
# BUG FIX: shuffle VALUES independently then zip with syms.
# random.shuffle(list of (sym, z) tuples) only reorders the list; the (sym, z) pair stays together,
# so dict(items) always yields the same key→value mapping. Correct: shuffle z values, pair with syms.
random.seed(20261014)
random_excess_totals = []
for k in range(200):
    z_choice_random = {}
    for d in rebal_days:
        if is_a_state(d):
            syms_d = list(z_no_f[d].keys())
            vals_d = [z_no_f[d][s] for s in syms_d]
            random.shuffle(vals_d)
            z_choice_random[d] = dict(zip(syms_d, vals_d))
        else:
            z_choice_random[d] = z_full[d]
    rw = build_modified_weights(z_choice_random)
    rnav = run_nav(rw)
    rfinal = rnav[list(rnav.keys())[-1]]
    core_final = nav_core[list(nav_core.keys())[-1]]
    random_excess_totals.append(rfinal / core_final - 1)
    if (k+1) % 50 == 0:
        print(f"      {k+1} done; last excess={rfinal/core_final - 1:.4f}")

# ---------- split by halves ----------
def half_cum_return(nav, h1_end, h2_start):
    h1_nav, h2_nav = 1.0, 1.0
    h1_prev, h2_prev = 1.0, 1.0
    h1_started, h2_started = False, False
    for d in sorted(nav.keys()):
        if d <= h1_end:
            if not h1_started:
                h1_started = True
                h1_prev = nav[d]
                continue
            if h1_prev > 0:
                h1_nav *= (nav[d] / h1_prev)
            h1_prev = nav[d]
        elif d >= h2_start:
            if not h2_started:
                h2_started = True
                h2_prev = nav[d]
                continue
            if h2_prev > 0:
                h2_nav *= (nav[d] / h2_prev)
            h2_prev = nav[d]
    return h1_nav - 1, h2_nav - 1

h1_end = "2024-12-30"
h2_start = "2025-01-06"

orig_h1, orig_h2 = half_cum_return(nav_orig, h1_end, h2_start)
mod_h1, mod_h2 = half_cum_return(nav_mod, h1_end, h2_start)
core_h1, core_h2 = half_cum_return(nav_core, h1_end, h2_start)

# Per-half random null percentiles
def half_random_pct(random_excess_halves, mod_excess_h1, mod_excess_h2):
    h1_pct = sum(1 for x in random_excess_halves["h1"] if x <= mod_excess_h1) / len(random_excess_halves["h1"])
    h2_pct = sum(1 for x in random_excess_halves["h2"] if x <= mod_excess_h2) / len(random_excess_halves["h2"])
    return h1_pct, h2_pct

# Recompute per-half random null
mod_excess_full = nav_mod[list(nav_mod.keys())[-1]] / nav_core[list(nav_core.keys())[-1]] - 1

# Rebuild random halve
random_excess_h1 = []
random_excess_h2 = []
random.seed(20261014)
for k in range(200):
    z_choice_random = {}
    for d in rebal_days:
        if is_a_state(d):
            syms_d = list(z_no_f[d].keys())
            vals_d = [z_no_f[d][s] for s in syms_d]
            random.shuffle(vals_d)
            z_choice_random[d] = dict(zip(syms_d, vals_d))
        else:
            z_choice_random[d] = z_full[d]
    rw = build_modified_weights(z_choice_random)
    rnav = run_nav(rw)
    rh1, rh2 = half_cum_return(rnav, h1_end, h2_start)
    random_excess_h1.append(rh1 - core_h1)
    random_excess_h2.append(rh2 - core_h2)
    if (k+1) % 50 == 0:
        print(f"      halve {k+1} done")

results = {
    "panel": {
        "n_rebalance_days": len(rebal_days),
        "panel_size": len(panel_syms),
        "renormalized_weights_4P": {"M": round(W4_M, 4), "O": round(W4_O, 4), "S": round(W4_S, 4), "A": round(W4_A, 4)},
        "K": K,
        "A_state_rebal_days": sum(1 for d in rebal_days if is_a_state(d)),
        "z_full_min_scored_per_day": min(n_full_per_day),
        "z_full_median_scored_per_day": round(statistics.median(n_full_per_day), 1),
    },
    "halves": {"H1_end_date": h1_end, "H2_start_date": h2_start},
    "before_after_excess_vs_core_u": {
        "H1": {
            "before_cis_a1_u_replay_cumret": round(orig_h1 * 100, 2),
            "after_modified_cumret": round(mod_h1 * 100, 2),
            "core_u_cumret": round(core_h1 * 100, 2),
            "before_excess_pp": round((orig_h1 - core_h1) * 100, 2),
            "after_excess_pp": round((mod_h1 - core_h1) * 100, 2),
        },
        "H2": {
            "before_cis_a1_u_replay_cumret": round(orig_h2 * 100, 2),
            "after_modified_cumret": round(mod_h2 * 100, 2),
            "core_u_cumret": round(core_h2 * 100, 2),
            "before_excess_pp": round((orig_h2 - core_h2) * 100, 2),
            "after_excess_pp": round((mod_h2 - core_h2) * 100, 2),
        },
    },
    "global": {
        "core_u_final": round(nav_core[list(nav_core.keys())[-1]], 4),
        "cis_a1_u_replay_final": round(nav_orig[list(nav_orig.keys())[-1]], 4),
        "modified_final": round(nav_mod[list(nav_mod.keys())[-1]], 4),
        "before_excess_pp": round((nav_orig[list(nav_orig.keys())[-1]]/nav_core[list(nav_core.keys())[-1]] - 1) * 100, 2),
        "after_excess_pp": round((nav_mod[list(nav_mod.keys())[-1]]/nav_core[list(nav_core.keys())[-1]] - 1) * 100, 2),
        "random_n": len(random_excess_totals),
        "random_mean_pp": round(statistics.mean(random_excess_totals) * 100, 2),
        "random_stdev_pp": round(statistics.stdev(random_excess_totals) * 100, 2),
        "random_p50_pp": round(statistics.median(random_excess_totals) * 100, 2),
        "random_p5_pp": round(statistics.quantiles(random_excess_totals, n=20)[0] * 100, 2),
        "random_p95_pp": round(statistics.quantiles(random_excess_totals, n=20)[-1] * 100, 2),
        "actual_excess_pp": round(mod_excess_full * 100, 2),
        "random_pctile_actual": round(half_random_pct({"h1": random_excess_h1, "h2": random_excess_h2}, mod_excess_full, mod_excess_full)[0] * 100, 1),
    },
    "halves_random": {
        "H1": {
            "random_n": len(random_excess_h1),
            "random_mean_pp": round(statistics.mean(random_excess_h1) * 100, 2),
            "random_stdev_pp": round(statistics.stdev(random_excess_h1) * 100, 2),
            "random_p5_pp": round(statistics.quantiles(random_excess_h1, n=20)[0] * 100, 2),
            "random_p95_pp": round(statistics.quantiles(random_excess_h1, n=20)[-1] * 100, 2),
            "actual_excess_pp": round((mod_h1 - core_h1) * 100, 2),
            "random_pctile_actual": round(sum(1 for x in random_excess_h1 if x <= (mod_h1 - core_h1)) / len(random_excess_h1) * 100, 1),
        },
        "H2": {
            "random_n": len(random_excess_h2),
            "random_mean_pp": round(statistics.mean(random_excess_h2) * 100, 2),
            "random_stdev_pp": round(statistics.stdev(random_excess_h2) * 100, 2),
            "random_p5_pp": round(statistics.quantiles(random_excess_h2, n=20)[0] * 100, 2),
            "random_p95_pp": round(statistics.quantiles(random_excess_h2, n=20)[-1] * 100, 2),
            "actual_excess_pp": round((mod_h2 - core_h2) * 100, 2),
            "random_pctile_actual": round(sum(1 for x in random_excess_h2 if x <= (mod_h2 - core_h2)) / len(random_excess_h2) * 100, 1),
        },
    },
}

print(json.dumps(results, indent=2, default=str))
with open(f"{ROOT}/docs/research/T-090_modify_results.json", "w") as f:
    json.dump(results, f, indent=2, default=str)
print(f"wrote {ROOT}/docs/research/T-090_modify_results.json")