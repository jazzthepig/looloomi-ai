"""T-145 / S-633 —— 鱼潮:全市场突破广度高的时候开的 R 臂票,是不是更常在鱼上、更赚钱。

照 S-633 原文(台账 2026-10-20 14:51 UTC 预注册,写于对广度与 R 票做任何匹配之前):

  票     R 臂 S-610 进场 + 2.5 × ATR14 止损 + 原出场,不加慢闸门,信号日 ≤ 2026-06-20。
         「在鱼上」按 S-618 原定义(entry 起 120 根内最高 high 或 close ≥ 3 × entry)。
  广度   B(d) = 宇宙(binance_hist、rn ≥ 220、30 日均成交额 ≥ 500 万美元)里
         收盘 > 之前 40 天最高收盘的名字占比。
  鱼潮   W(d) = 1 ⇔ B(d) ≥ 它自己过去 365 天(d − 365 … d − 1)的 80 分位(只用当时可知的数)。
  判 ①  W = 1 的票在鱼上的比例 > W = 0;每年内打乱 W 标签 2,000 次,单侧 p < 0.05。
  判 ②  W = 1 的票平均 R > W = 0;对票有放回自助 2,000 次,单侧 p < 0.05。
  只报  各组张数、捕到的鱼、每条鱼的票价、按年;与慢闸门的 2 × 2;「急跌见底」旗单独与交叉;
         按 W 加权(1.0 / 0.25)对恒定 0.5 的总 R 与最大回撤。

读库用 os.environ['SUPABASE_URL'] / os.environ['SUPABASE_KEY'],不读 .env、不打印 key。
零分布 / 自助都在本脚本内按预注册的写法实现(预注册指定了重排与自助本身,不是可替换的统计口径)。
"""
from __future__ import annotations

import json
import os
import random
import sys
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

SUPABASE_URL = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "")
if not SUPABASE_URL or not SUPABASE_KEY:
    sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")

DATA_PATH = "/private/tmp/binance_raw.json"  # 全量 binance_hist 快照(与 T-141 同一份)
EXCLUDED = {"USDC", "BTCDOM", "DEFI"}
SIGNAL_START = "2020-03-01"
SIGNAL_END = "2026-06-20"  # S-633 写死
MIN_RN = 220
MIN_ADV30 = 5e6
COST_PCT_OF_ENTRY = 0.004  # 与 s610_breakout_sim.sql 一致
K_STOP = 2.5  # S-620(a) / S-633
LOOKBACK_HIGH = 40  # 广度:之前 40 天
WINDOW = 365  # 广度:自己的过去 365 天
W_PCTL = 0.80
N_PERM = 2000
N_BOOT = 2000
FISH_BARS = 120  # S-618:120 根内收盘翻 3 倍
SEED = 20261020  # 预注册日的日期,固定种子


# ── 数据 ──────────────────────────────────────────────────────────────────────
def load_rows():
    with open(DATA_PATH) as f:
        rows = json.load(f)
    rows = [r for r in rows if r["symbol"] not in EXCLUDED]
    rows.sort(key=lambda r: (r["symbol"], r["trade_date"]))
    return rows


def build_per_symbol(rows):
    by_sym = defaultdict(list)
    for r in rows:
        by_sym[r["symbol"]].append(r)
    out = {}
    for sym, rs in by_sym.items():
        n = len(rs)
        o = [r["open"] for r in rs]
        h = [r["high"] for r in rs]
        l = [r["low"] for r in rs]
        c = [r["close"] for r in rs]
        d = [r["trade_date"] for r in rs]
        v = [r["volume"] for r in rs]
        dv = [c[i] * v[i] for i in range(n)]
        pc = [c[0]] + c[:-1]
        tr = [max(h[i] - l[i], abs(h[i] - pc[i]), abs(l[i] - pc[i])) for i in range(n)]
        sma20 = [0.0] * n
        sma200 = [0.0] * n
        atr14 = [0.0] * n
        adv30 = [0.0] * n
        adv40p = [0.0] * n
        for i in range(n):
            lo20 = max(0, i - 19)
            sma20[i] = sum(c[lo20 : i + 1]) / (i - lo20 + 1)
            lo200 = max(0, i - 199)
            sma200[i] = sum(c[lo200 : i + 1]) / (i - lo200 + 1)
            lo14 = max(0, i - 13)
            atr14[i] = sum(tr[lo14 : i + 1]) / (i - lo14 + 1)
            lo30 = max(0, i - 29)
            adv30[i] = sum(dv[lo30 : i + 1]) / (i - lo30 + 1)
            lo40p, hi40p = max(0, i - 40), i - 1
            if lo40p <= hi40p:
                adv40p[i] = sum(dv[lo40p : hi40p + 1]) / (hi40p - lo40p + 1)
        hh40 = [h[0]] + [max(h[max(0, i - 40) : i]) for i in range(1, n)]
        ll40 = [l[0]] + [min(l[max(0, i - 40) : i]) for i in range(1, n)]
        # 广度用:收盘 vs 之前 40 天最高收盘(不含当天)
        cch40 = [c[0]] + [max(c[max(0, i - 40) : i]) for i in range(1, n)]
        # S-610 的「不在深跌里接刀」:t-120…t 内 close / 前 365 根最高收盘 的最小值 <= 0.5
        max365 = [c[0]] + [max(c[max(0, i - 365) : i + 1]) for i in range(1, n)]
        dd = [c[i] / max365[i] for i in range(n)]
        mindd120 = [dd[0]] + [min(dd[max(0, i - 120) : i + 1]) for i in range(1, n)]
        out[sym] = dict(
            n=n, o=o, h=h, l=l, c=c, d=d, dv=dv,
            sma20=sma20, sma200=sma200, atr14=atr14, adv30=adv30,
            adv40p=adv40p, hh40=hh40, ll40=ll40, cch40=cch40,
            mindd120=mindd120,
        )
    return out


def find_signals(by):
    """S-610 R 臂进场(T-141 逐行复用)。"""
    sigs = []
    for sym, d in by.items():
        n = d["n"]
        for i in range(n):
            if i + 1 < MIN_RN:
                continue
            if d["adv30"][i] < MIN_ADV30:
                continue
            if not (SIGNAL_START <= d["d"][i] <= SIGNAL_END):
                continue
            if d["mindd120"][i] > 0.5:
                continue
            if (d["hh40"][i] - d["ll40"][i]) / d["hh40"][i] > 0.40:
                continue
            if not (d["c"][i] > d["hh40"][i] and d["c"][i] > d["sma200"][i]):
                continue
            if not (d["dv"][i] >= 2 * d["adv40p"][i]):
                continue
            sigs.append((sym, i))
    return sigs


def simulate(by, sigs, k=K_STOP):
    """进场 = 信号次日 open;止损 = max(信号日 low, 进场 − k×ATR14[信号日]);出场 S-610 原样。"""
    sym_sigs = defaultdict(list)
    for sym, idx in sigs:
        sym_sigs[sym].append(idx)
    evs_all = []
    for sym, idxs in sym_sigs.items():
        d = by[sym]
        n = d["n"]
        for ei in idxs:
            if ei + 1 >= n:
                continue
            entry_idx = ei + 1
            entry = d["o"][entry_idx]
            stop = max(d["l"][ei], entry - k * d["atr14"][ei])
            if entry <= stop:
                continue
            hi = min(ei + FISH_BARS, n - 1)
            k_idx = None
            for j in range(entry_idx, hi + 1):
                if d["l"][j] <= stop or d["c"][j] < d["sma20"][j]:
                    k_idx = j
                    break
            if k_idx is None:
                xi, xp = hi, d["c"][hi]
            elif d["l"][k_idx] <= stop:
                if k_idx > entry_idx and d["o"][k_idx] <= stop:
                    xi, xp = k_idx, d["o"][k_idx]
                else:
                    xi, xp = k_idx, stop
            else:
                xi = k_idx + 1
                xp = d["o"][xi] if xi < n else d["c"][k_idx]
            evs_all.append(dict(
                sym=sym, sig_idx=ei, entry_idx=entry_idx, exit_idx=xi,
                entry=entry, stop=stop, exit_price=xp,
                d_sig=d["d"][ei], d_entry=d["d"][entry_idx], d_exit=d["d"][xi],
            ))
    chain = defaultdict(list)
    for ev in sorted(evs_all, key=lambda e: (e["sym"], e["entry_idx"])):
        lst = chain[ev["sym"]]
        if lst and ev["entry_idx"] <= lst[-1]["exit_idx"]:
            continue
        lst.append(ev)
    flat = [e for lst in chain.values() for e in lst]
    flat.sort(key=lambda e: (e["d_entry"], e["sym"]))
    for ev in flat:
        ev["R"] = ((ev["exit_price"] - ev["entry"]) / (ev["entry"] - ev["stop"])
                   - COST_PCT_OF_ENTRY * ev["entry"] / (ev["entry"] - ev["stop"]))
        ev["year"] = ev["d_sig"][:4]
    return flat


# ── 广度与鱼潮 ────────────────────────────────────────────────────────────────
def build_breadth(by):
    """B(d) = 宇宙(rn ≥ 220、ADV30 ≥ 5M)里 收盘 > 之前 40 天最高收盘 的占比。"""
    num = defaultdict(int)
    den = defaultdict(int)
    for d in by.values():
        n = d["n"]
        for i in range(n):
            if i + 1 < MIN_RN or i < LOOKBACK_HIGH:
                continue
            if d["adv30"][i] < MIN_ADV30:
                continue
            day = d["d"][i]
            den[day] += 1
            if d["c"][i] > d["cch40"][i]:
                num[day] += 1
    days = sorted(den)
    B = {}
    for day in days:
        B[day] = num[day] / den[day] if den[day] else None
    return B, den


def panel_series(by):
    """面板等权收盘(同一宇宙),供「急跌见底」旗用。"""
    sums = defaultdict(float)
    cnt = defaultdict(int)
    for d in by.values():
        n = d["n"]
        for i in range(n):
            if i + 1 < MIN_RN or i < 90:
                continue
            if d["adv30"][i] < MIN_ADV30:
                continue
            sums[d["d"][i]] += d["c"][i]
            cnt[d["d"][i]] += 1
    days = sorted(cnt)
    px = {dd: sums[dd] / cnt[dd] for dd in days}
    idx = {dd: i for i, dd in enumerate(days)}
    dd90 = {}
    for dd in days:
        i = idx[dd]
        hi = max(px[days[j]] for j in range(max(0, i - 89), i + 1))
        dd90[dd] = px[dd] / hi - 1.0
    return px, dd90


def wave_flags(B, WINDOW_DAYS=WINDOW, PCTL=W_PCTL, min_obs=None):
    """W(d)=1 ⇔ B(d) ≥ 过去 WINDOW 天(d−WINDOW … d−1)的 PCTL 分位。只用当时可知的数。"""
    days = sorted(d for d in B if B[d] is not None)
    vals = [B[d] for d in days]
    idx = {d: i for i, d in enumerate(days)}
    W = {}
    hist_len = {}
    for d in days:
        i = idx[d]
        lo = 0
        j = i - 1
        while lo <= j:
            dd = days[j]
            if (date.fromisoformat(d) - date.fromisoformat(dd)).days > WINDOW_DAYS:
                break
            j -= 1
        past = vals[j + 1 : i]
        hist_len[d] = len(past)
        if min_obs is None:
            ok = len(past) == WINDOW_DAYS  # 只在过去 365 天的数齐全时才算
        else:
            ok = len(past) >= min_obs
        if not ok or not past:
            W[d] = None
            continue
        s = sorted(past)
        # 80 分位:线性插值,与 numpy.percentile 默认一致
        rank = PCTL * (len(s) - 1)
        lo_i = int(rank)
        frac = rank - lo_i
        thr = s[lo_i] + frac * (s[min(lo_i + 1, len(s) - 1)] - s[lo_i])
        W[d] = 1 if B[d] >= thr else 0
    return W, hist_len


def slow_gate(signal_dates=None):
    """S-627 慢状态闸门:majors(cap)指数按 ret 复原的水平 > 其 200 日均值。只读库。"""
    hdr = {"apikey": SUPABASE_KEY, "Authorization": f"Bearer {SUPABASE_KEY}"}
    raw = []
    page = 0
    while True:
        q = urllib.parse.urlencode({
            "select": "d,ret", "dimension": "eq.tier", "weighting": "eq.cap",
            "style": "eq.majors", "order": "d.asc", "limit": "1000",
            "offset": str(page * 1000),
        })
        url = f"{SUPABASE_URL}/rest/v1/style_index_pit_daily?{q}"
        req = urllib.request.Request(url, headers=hdr)
        with urllib.request.urlopen(req, timeout=120) as r:
            chunk = json.loads(r.read().decode())
        raw.extend(chunk)
        if len(chunk) < 1000:
            break
        page += 1
        if page > 20:
            break
    if not raw:
        return {}, None
    raw = [row for row in raw if row.get("ret") is not None]
    lvl, cur = {}, 100.0
    for row in raw:
        cur *= 1.0 + row["ret"]
        lvl[row["d"]] = cur
    days = sorted(lvl)
    ma200 = {}
    for i, d in enumerate(days):
        if i < 199:
            ma200[d] = None
        else:
            ma200[d] = sum(lvl[dd] for dd in days[i - 199 : i + 1]) / 200.0
    gate = {d: (1 if (ma200[d] is not None and lvl[d] > ma200[d]) else 0) for d in days}
    return gate, (days[0], days[-1], len(days))


# ── 分组统计 ──────────────────────────────────────────────────────────────────
def pearson(x, y):
    n = len(x)
    mx, my = sum(x) / n, sum(y) / n
    num = sum((a - mx) * (b - my) for a, b in zip(x, y))
    dx = sum((a - mx) ** 2 for a in x) ** 0.5
    dy = sum((b - my) ** 2 for b in y) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


def group_stats(trades, key_fn, label):
    g = defaultdict(list)
    for t in trades:
        g[key_fn(t)].append(t)
    out = {}
    for k, lst in sorted(g.items(), key=lambda kv: str(kv[0])):
        n = len(lst)
        on_fish = sum(1 for t in lst if t["on_fish"])
        fish = sum(1 for t in lst if t["fish_caught"])
        off = [t for t in lst if not t["on_fish"]]
        ticket_price = (sum(t["R"] for t in off) / fish) if fish else None
        out[k] = dict(
            n=n, on_fish=on_fish, on_fish_pct=on_fish / n if n else 0.0,
            fish_caught=fish, ticket_price=ticket_price,
            total_r=sum(t["R"] for t in lst),
            mean_r=sum(t["R"] for t in lst) / n if n else 0.0,
        )
    return out


def perm_test_fish(trades, n_perm=N_PERM, seed=SEED):
    """判 ①:每年内打乱 W 标签,单侧 p = #(diff ≥ 实测) / n_perm。"""
    by_year = defaultdict(list)
    for t in trades:
        by_year[t["year"]].append(t)
    for lst in by_year.values():
        lst.sort(key=lambda t: t["tid"])
    obs = (sum(1 for t in trades if t["W"] == 1 and t["on_fish"]) / max(1, sum(1 for t in trades if t["W"] == 1))
           - sum(1 for t in trades if t["W"] == 0 and t["on_fish"]) / max(1, sum(1 for t in trades if t["W"] == 0)))
    rng = random.Random(seed)
    ge = 0
    for _ in range(n_perm):
        hit1 = hit0 = tot1 = tot0 = 0
        for lst in by_year.values():
            labs = [t["W"] for t in lst]
            rng.shuffle(labs)
            for t, w in zip(lst, labs):
                if w == 1:
                    tot1 += 1
                    hit1 += 1 if t["on_fish"] else 0
                else:
                    tot0 += 1
                    hit0 += 1 if t["on_fish"] else 0
        d = hit1 / tot1 - hit0 / tot0 if tot1 and tot0 else 0.0
        if d >= obs - 1e-12:
            ge += 1
    return dict(obs_diff=obs, p_ge=(ge + 1) / (n_perm + 1), n_perm=n_perm, hits=ge)


def boot_test_mean_r(trades, n_boot=N_BOOT, seed=SEED + 1):
    """判 ②:对票有放回自助,单侧 p = #(diff ≥ 实测) / n_boot。"""
    rs = [t["R"] for t in trades]
    ws = [t["W"] for t in trades]
    n = len(rs)
    s1 = sum(r for r, w in zip(rs, ws) if w == 1) / max(1, sum(1 for w in ws if w == 1))
    s0 = sum(r for r, w in zip(rs, ws) if w == 0) / max(1, sum(1 for w in ws if w == 0))
    obs = s1 - s0
    rng = random.Random(seed)
    ge = 0
    for _ in range(n_boot):
        a = b = na = nb = 0.0
        for _ in range(n):
            i = rng.randrange(n)
            if ws[i] == 1:
                a += rs[i]
                na += 1
            else:
                b += rs[i]
                nb += 1
        d = (a / na - b / nb) if na and nb else 0.0
        if d >= obs - 1e-12:
            ge += 1
    return dict(obs_diff=obs, p_ge=(ge + 1) / (n_boot + 1), n_boot=n_boot, hits=ge)


def risk_profile(trades, weights, label):
    """按每票风险权重累计,报 R 单位的总 R / 最大回撤 / 谷底(与 S-620、S-627 的「总 R、回撤 R」同口径)。
    不用复利:这张票表的左尾是「很长一段小亏 + 少数几条 +77R」,任何 f 复利都会在 2023 之前
    把权益打到 1e-119,复利口径没有信息量(见 T-145 报告)。"""
    tr = sorted(trades, key=lambda t: (t["d_exit"], t["sym"], t["tid"]))
    cum, peak, mdd_r = 0.0, 0.0, 0.0
    trough, trough_at, mdd_at = 0.0, None, None
    for t in tr:
        cum += weights(t) * t["R"]
        peak = max(peak, cum)
        if cum - peak < mdd_r:
            mdd_r, mdd_at = cum - peak, t["d_exit"]
        if cum < trough:
            trough, trough_at = cum, t["d_exit"]
    return dict(label=label, total_r=cum, max_dd_r=mdd_r, max_dd_at=mdd_at,
                trough_r=trough, trough_at=trough_at)


def main():
    rows = load_rows()
    print(f"# rows: {len(rows)}")
    by = build_per_symbol(rows)
    sigs = find_signals(by)
    trades = simulate(by, sigs)
    n = len(trades)
    mean_r = sum(t["R"] for t in trades) / n if n else 0.0
    print(f"# tickets: {n}  mean_R: {mean_r:+.4f}  total_R: {mean_r * n:+.1f}"
          f"   [T-141 k=2.5 无上限参照: n=940 mean=+0.250]")

    # 在鱼上(S-618 原定义)与「捕到的鱼」(120 根内 3 倍,含当天最高)
    for i, t in enumerate(trades):
        d = by[t["sym"]]
        n_b = d["n"]
        lo_i = t["entry_idx"] + 1
        hi_i = min(t["entry_idx"] + FISH_BARS, n_b - 1)
        if hi_i < lo_i:
            fmh = fmc = t["entry"]
        else:
            fmh = max(d["h"][lo_i : hi_i + 1])
            fmc = max(d["c"][lo_i : hi_i + 1])
        t["mfe"] = max(fmh, fmc) / t["entry"] - 1.0
        t["on_fish"] = max(fmh, fmc) >= 3.0 * t["entry"]
        t["fish_caught"] = (fmh >= 3.0 * t["entry"]) or (fmc >= 3.0 * t["entry"])
        t["tid"] = i

    B, den = build_breadth(by)
    px, dd90 = panel_series(by)
    W_full, hist_len = wave_flags(B)
    W_min, _ = wave_flags(B, min_obs=120)

    gate, gate_meta = slow_gate(None)
    print(f"# slow gate rows: {gate_meta}")

    und = []
    for t in trades:
        w = W_full.get(t["d_sig"])
        if w is None:
            und.append(t)
        t["W"] = w
        t["W_min"] = W_min.get(t["d_sig"])
        t["B"] = B.get(t["d_sig"])
        t["gate"] = gate.get(t["d_sig"])
        sd = date.fromisoformat(t["d_sig"])
        flag = 0
        for k in range(1, 15):
            dd = (sd - timedelta(days=k)).isoformat()
            if dd in dd90 and dd90[dd] <= -0.30:
                flag = 1
                break
        t["crash_bottom"] = flag

    tested = [t for t in trades if t["W"] is not None]
    print(f"# W defined: {len(tested)} / {n}  (W 未定义 {len(und)};"
          f" 最早 {min((t['d_sig'] for t in tested), default='-')})")
    print(f"# W=1 张数: {sum(1 for t in tested if t['W'] == 1)}"
          f"  W=0 张数: {sum(1 for t in tested if t['W'] == 0)}"
          f"  闸门=1: {sum(1 for t in tested if t['gate'] == 1)}")

    res = dict(
        meta=dict(n_tickets=n, mean_r=mean_r, total_r=mean_r * n,
                  n_tested=len(tested), n_undefined=len(und),
                  breadth_days=len(B), breadth_first=min(B), breadth_last=max(B),
                  gate_meta=gate_meta, seed=SEED),
        by_W=group_stats(tested, lambda t: t["W"], "W"),
    )
    t1 = perm_test_fish(tested)
    t2 = boot_test_mean_r(tested)
    res["test_fish_pct"] = t1
    res["test_mean_r"] = t2
    print(f"\n# 判 ① 在鱼上比例差 W1-W0 = {t1['obs_diff']:+.4f}  单侧 p = {t1['p_ge']:.4f}")
    print(f"# 判 ② 平均 R 差 W1-W0 = {t2['obs_diff']:+.4f}  单侧 p = {t2['p_ge']:.4f}")

    # 只报:按年
    res["yearly"] = {}
    for y in sorted({t["year"] for t in tested}):
        lst = [t for t in tested if t["year"] == y]
        res["yearly"][y] = dict(
            all=group_stats(lst, lambda t: t["W"], "W"),
            breadth_mean=sum(t["B"] for t in lst if t["B"] is not None) / max(1, len(lst)),
        )

    # 只报:与慢闸门的 2 × 2
    res["cross_gate"] = group_stats([t for t in tested if t["gate"] is not None],
                                    lambda t: f"W{t['W']}_gate{t['gate']}", "WxG")

    # 只报:急跌见底旗,单独与交叉
    res["crash_bottom"] = group_stats(tested, lambda t: t["crash_bottom"], "CB")
    res["cross_cb"] = group_stats(tested, lambda t: f"W{t['W']}_cb{t['crash_bottom']}", "WxCB")

    # 只报:按 W 加权 vs 恒定 0.5(原文)与「同平均风险」的恒定
    w_wa = risk_profile(tested, lambda t: 1.0 if t["W"] == 1 else 0.25, "W:1.0/0.25")
    w_c5 = risk_profile(tested, lambda t: 0.5, "const 0.5")
    avg_risk = (sum(1.0 if t["W"] == 1 else 0.25 for t in tested) / len(tested))
    w_ca = risk_profile(tested, lambda t: avg_risk, f"const {avg_risk:.4f}(同平均风险)")
    w_25 = risk_profile(tested, lambda t: 0.25, "const 0.25")
    w_10 = risk_profile(tested, lambda t: 1.0, "const 1.0")
    res["risk"] = dict(avg_risk=avg_risk, weighted=w_wa, const05=w_c5,
                       const_avg=w_ca, const025=w_25, const10=w_10)
    res["breadth"] = dict(
        first=min(B), last=max(B), n_days=len(B),
        W1_share_tickets=sum(1 for t in tested if t["W"] == 1) / len(tested),
        W1_share_days=(sum(1 for d in B if W_full.get(d) == 1)
                       / max(1, sum(1 for d in B if W_full.get(d) is not None))),
    )
    rs = sorted(t["R"] for t in trades)
    res["r_dist"] = dict(
        min=rs[0], p01=rs[max(0, len(rs) // 100)], median=rs[len(rs) // 2],
        max=rs[-1], n_below_minus2=sum(1 for x in rs if x < -2.0),
        n_below_minus5=sum(1 for x in rs if x < -5.0),
        mean_ruin_group=None,
    )

    # 探索:120 天最小观察数的敏感度(不在判据内)
    tested_min = [t for t in trades if t["W_min"] is not None]
    res["explore_min120"] = dict(
        n=len(tested_min),
        by_W=group_stats(tested_min, lambda t: t["W_min"], "W"),
        test_fish=perm_test_fish(tested_min),
        test_mean_r=boot_test_mean_r(tested_min),
    )

    # 探索:连续的 B(d) 与「在鱼上」/ 平均 R(检验「阈值切出来的 W 没信息,连续值有?」)
    with_b = [t for t in tested if t["B"] is not None]
    with_b.sort(key=lambda t: t["B"])
    q = len(with_b) // 5
    dec = []
    for i in range(5):
        chunk = with_b[i * q : (i + 1) * q] if i < 4 else with_b[4 * q :]
        dec.append(dict(
            B_lo=chunk[0]["B"], B_hi=chunk[-1]["B"], n=len(chunk),
            on_fish_pct=sum(1 for t in chunk if t["on_fish"]) / len(chunk),
            mean_r=sum(t["R"] for t in chunk) / len(chunk),
        ))
    bs = [t["B"] for t in with_b]
    fs = [1.0 if t["on_fish"] else 0.0 for t in with_b]
    rs2 = [t["R"] for t in with_b]
    res["explore_breadth_quintile"] = dict(
        n=len(with_b),
        corr_b_onfish=pearson(bs, fs),
        corr_b_meanr=pearson(bs, rs2),
        quintiles=dec,
    )

    print("\n" + json.dumps(res, indent=2, default=str))
    out_path = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-145_results.json"
    with open(out_path, "w") as f:
        json.dump(res, f, indent=2, default=str)
    print(f"\n# wrote {out_path}")


if __name__ == "__main__":
    main()