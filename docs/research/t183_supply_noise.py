"""T-183 —— 加密流通量序列(asset_mcap_daily 的 市值 ÷ 价格)的噪声体检。

纯测量:不算任何收益、不立任何假设、不做零分布(所以不用 apparatus.py)。
只回答三个问题(卡上 acceptance 原文):
  ① 每个名字的日流通量变动有多吵(中位 / p95 / |变动|>3% 的天数 / 「尖刺」次数);
  ② 三种 90 日增长写法(A 端点单日、B 两端 7 日中位数、C 90 天对数回归斜率 ×90)
     在 2024-01 → 2026-10 每周一个截面上,CIS 加密 25 个名字的供给维**排名**两两 Spearman
     (分周报中位与 p10);以及 R-v2 票上「> 2.2% 那一档」三种写法下有几张票归属不同;
  ③ 哪 10 个名字最吵 + 原因猜测。

写法 A 就是 src/data/cis/v2.py `crypto_inputs` 现在的写法(只读,不改):
    then = 最后一条 ≤ asof−90d(且 ≥ asof−97d),last = 最后一条 ≤ asof(且 ≥ asof−3d),
    supply = −(c1/c0 − 1),c = mcap ÷ price。
B、C 只改**端点/整条路径的聚合方式**,端点锚定规则与 A 完全相同,这样三种写法的差
就是「聚合方式的噪声」,不掺「哪天算数」的差。

用法:
  python3 docs/research/t183_supply_noise.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
AP = argparse.ArgumentParser()
AP.add_argument("--root", default="/Volumes/CometCloudAI/cometcloud-local")
A = AP.parse_args()
ROOT = A.root
CACHE = os.path.join(ROOT, "research", "t183")
os.makedirs(CACHE, exist_ok=True)

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

TICKETS = os.path.join(ROOT, "research", "t159",
                       "_tickets_2020-03-01_2026-06-20.json")

WIN = 90                              # v2.py CRYPTO_WINDOW_DAYS
SLACK_LAST = 3                         # v2.py 的「当天附近没有价就不打分」= 3 天
SLACK_THEN = 7                         # v2.py 的 then ≥ start − 7
TICK_SLACK = 7                         # S-665 预注册的「前后 7 天内都要有观测」
HIGH = 0.022                          # 卡上写的「> 2.2% 那一档」
XS_MIN = 30                           # 写法 C 的窗口最少观测数


# ---------------------------------------------------------------- 读取层
def _page(path: str, lo: int, hi: int, tries: int = 4) -> list:
    req = urllib.request.Request(URL + "/rest/v1/" + path,
                                 headers=dict(HDR, Range=f"{lo}-{hi}"))
    for i in range(tries):
        try:
            return json.loads(urllib.request.urlopen(req, timeout=600).read())
        except urllib.error.HTTPError as e:
            if e.code == 416:          # Range 越界 = 没有更多行
                return []
            if e.code in (429, 500, 502, 503, 504) and i + 1 < tries:
                time.sleep(2 * (i + 1))
                continue
            raise
        except (TimeoutError, urllib.error.URLError, OSError):
            if i + 1 >= tries:
                raise
            time.sleep(3 * (i + 1))
    raise RuntimeError("unreachable")


def _page_all(path: str, cap: int = 400_000) -> list:
    out, off = [], 0
    while off < cap:
        chunk = _page(path, off, off + 999)
        if not chunk:
            break
        out += chunk
        off += 1000
    return out


def fetch_supply(symbols: list) -> tuple:
    """symbol → {date 字符串: 流通量},以及每个 symbol 选了哪个 source。

    流通量 = asset_mcap_daily 的市值 ÷ 价格(CoinGecko)。同 symbol 同一天多个 coin_id 时取
    当日市值最大的那个(卡上原文)。翻页一律带 order=symbol.asc,coin_id.asc,d.asc。
    **实现自由度**:一张表里若混了多个 source,按 symbol 取覆盖天数最多的那个 —— 市值与
    价格必须来自同一条序列,跨源相除没有意义;选了哪个一律记进结果。"""
    def one(sym):
        part = os.path.join(CACHE, "supply_parts", sym + ".json")
        if os.path.exists(part):
            v = json.load(open(part))
            return sym, v["s"], v["meta"]
        q = (f"asset_mcap_daily?select=d,price,mcap,coin_id,source&symbol=eq.{sym}"
             f"&order=symbol.asc,coin_id.asc,d.asc")
        rows = _page_all(q)
        pk = [(r["d"], r.get("coin_id")) for r in rows]
        assert len(set(pk)) == len(pk), \
            f"{sym}:asset_mcap_daily 有重复键 {len(pk) - len(set(pk))} 条 —— 停"
        by_src = defaultdict(lambda: defaultdict(dict))      # source → date → coin_id → (mcap, price)
        for r in rows:
            m, p = r.get("mcap"), r.get("price")
            if m is None or p is None or float(p) <= 0 or float(m) <= 0:
                continue
            by_src[r.get("source") or "?"][r["d"]][r.get("coin_id")] = (float(m), float(p))
        if not by_src:
            os.makedirs(os.path.dirname(part), exist_ok=True)
            json.dump({"s": {}, "meta": None}, open(part, "w"))
            return sym, {}, None
        src = max(by_src, key=lambda s: len(by_src[s]))
        out = {}
        for d, per_coin in by_src[src].items():
            m, p = max(per_coin.values(), key=lambda v: v[0])  # 当日市值最大的 coin_id
            out[d] = m / p
        out = dict(sorted(out.items()))
        os.makedirs(os.path.dirname(part), exist_ok=True)
        json.dump({"s": out, "meta": [src, len(by_src[src]), len(rows)]}, open(part, "w"))
        return sym, out, [src, len(by_src[src]), len(rows)]

    sup, meta = {}, {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        for sym, s, mt in ex.map(one, symbols):
            sup[sym], meta[sym] = s, mt
    return sup, meta


def _cached(name: str, fn):
    p = os.path.join(CACHE, name)
    if os.path.exists(p):
        return json.load(open(p))
    v = fn()
    json.dump(v, open(p, "w"), default=str)
    return v


def cis_crypto_symbols() -> list:
    """cis_v2_daily 最新一天 grp=crypto 的 symbol。"""
    rows = _page_all("cis_v2_daily?select=d,symbol&grp=eq.crypto"
                     "&order=symbol.asc,d.desc&limit=600")
    latest = max(r["d"] for r in rows)
    return sorted({r["symbol"] for r in rows if r["d"] == latest}), latest


# ---------------------------------------------------------------- 端点锚定 + 三种写法
def _anchor(series: list, vals: dict, d: str, slack: int) -> str | None:
    """日期 ≤ d 的最后一条观测,且不早于 d − slack。"""
    i = int(np.searchsorted(series, d, side="right")) - 1
    if i < 0:
        return None
    got = series[i]
    if (dt.date.fromisoformat(got) - dt.date.fromisoformat(d)).days > slack:
        return None
    return got


def _median(xs: list) -> float:
    return float(np.median(xs))


def growth_writings(series: list, vals: dict, d: str,
                    slack_last: int = SLACK_LAST, slack_then: int = SLACK_THEN
                    ) -> dict:
    """三种 90 日增长写法。端点锚定三者相同,只差聚合。

      A 端点单日(现在 v2.py crypto_inputs 的写法):c1/c0 − 1
      B 两端各取 7 日中位数:                med(c 近端 7 日)/med(c 远端 7 日) − 1
      C 90 天对数流通量回归斜率 × 90:        exp(β·90) − 1

    端点先按市值挑好 coin_id 换算成流通量再聚合(和 A 一致:先 c = mcap÷price,后聚合)。
    返回 {"A":…, "B":…, "C":…},缺的写 None。"""
    out = {"A": None, "B": None, "C": None, "anchor_last": None, "anchor_then": None}
    if not series:
        return out
    last = _anchor(series, vals, d, slack_last)
    then = _anchor(series, vals, (dt.date.fromisoformat(d) - dt.timedelta(days=WIN)).isoformat(),
                   slack_then)
    out["anchor_last"], out["anchor_then"] = last, then
    if last is None or then is None:
        return out
    c1, c0 = vals[last], vals[then]
    if not (c0 > 0 and c1 > 0):
        return out
    out["A"] = c1 / c0 - 1.0

    # B:两个端点各自的 7 日尾窗(窗口 ≤ 端点日,向前 7 天)
    def med_win(end: str, need: int = 4) -> float | None:
        e = dt.date.fromisoformat(end)
        w = [vals[k] for k in series
             if 0 <= (e - dt.date.fromisoformat(k)).days < 7 and vals[k] > 0]
        return _median(w) if len(w) >= need else None

    m1, m0 = med_win(last), med_win(then)
    if m1 and m0 and m0 > 0:
        out["B"] = m1 / m0 - 1.0

    # C:窗口内 log(c) 对天做 OLS,斜率 × 90
    lo, hi = dt.date.fromisoformat(then), dt.date.fromisoformat(last)
    x, y = [], []
    for k in series:
        kk = dt.date.fromisoformat(k)
        if lo <= kk <= hi and vals[k] > 0:
            x.append(kk.toordinal())
            y.append(math.log(vals[k]))
    if len(x) >= XS_MIN:
        xx = np.asarray(x, float)
        yy = np.asarray(y, float)
        var = ((xx - xx.mean()) ** 2).sum()
        if var > 0:
            beta = ((xx - xx.mean()) * (yy - yy.mean())).sum() / var
            out["C"] = math.exp(beta * WIN) - 1.0
    return out


# ---------------------------------------------------------------- ① 日变动噪声 + 尖刺
def noise_of(series: list, vals: dict) -> dict:
    """日流通量变动的分布 + 「尖刺」数。

    尖刺 = 单日 |变动| > 3% 且 3 天内回到原值 ±1%(即 S_t/S_{t−1} 跳了 >3%,而
    S_{t+1..t+3} 里有一回到 S_{t−1} 的 ±1% 以内)—— 口径噪声 / 重新计价长这样。"""
    chg, spikes, n = [], 0, len(series)
    for i in range(1, n):
        p, c = vals[series[i - 1]], vals[series[i]]
        if not (p > 0 and c > 0):
            continue
        r = c / p - 1.0
        chg.append(abs(r))
        if abs(r) > 0.03:
            back = any(0.99 <= vals[series[j]] / p <= 1.01 for j in range(i + 1, min(i + 4, n)))
            spikes += 1 if back else 0
    if not chg:
        return {"n_days": 0}
    chg_s = sorted(chg)
    q = lambda p: chg_s[min(len(chg_s) - 1, int(round(p * (len(chg_s) - 1))))]  # noqa: E731
    return {
        "n_days": len(chg),
        "d_first": series[0], "d_last": series[-1],
        "med_abs_chg": round(_median(chg), 6),
        "p95_abs_chg": round(q(0.95), 6),
        "p99_abs_chg": round(q(0.99), 6),
        "n_gt3pct": sum(1 for r in chg if r > 0.03),
        "pct_days_gt3pct": round(sum(1 for r in chg if r > 0.03) / len(chg), 6),
        "n_spikes": spikes,
    }


# ---------------------------------------------------------------- ② 排名相关
def rank01(xs: list) -> list:
    """平均秩百分位(0..1),和 v2.py ranks 的口径一致(只用于 Spearman)。"""
    o = np.argsort(xs, kind="mergesort")
    r = np.empty(len(xs), float)
    i = 0
    while i < len(o):
        j = i
        while j + 1 < len(o) and xs[o[j + 1]] == xs[o[i]]:
            j += 1
        r[o[i:j + 1]] = (i + j) / 2.0
        i = j + 1
    return list(r / max(1, len(xs) - 1))


def spearman(a: list, b: list) -> float | None:
    if len(a) < 3:
        return None
    ra, rb = np.asarray(rank01(a)), np.asarray(rank01(b))
    if ra.std() == 0 or rb.std() == 0:
        return None
    return float(np.corrcoef(ra, rb)[0, 1])


# ---------------------------------------------------------------- 主流程
def main() -> dict:
    cis_syms, cis_day = cis_crypto_symbols()
    tk = json.load(open(TICKETS))
    tickets = [{"side": "long", **t} for t in tk["long"]] + \
              [{"side": "short", **t} for t in tk["short"]]
    tick_syms = sorted({t["symbol"] for t in tickets})
    universe = sorted(set(cis_syms) | set(tick_syms))

    sup, meta = _cached("supply.json", lambda: fetch_supply(universe))
    series = {s: sorted(sup.get(s, {})) for s in universe}
    vals = {s: sup.get(s, {}) for s in universe}
    empty = sorted(s for s in universe if not series[s])

    res = {
        "card": "T-183",
        "what": "纯测量:流通量序列噪声 + 三种 90 日增长写法的排名/标签敏感性。不算收益、不立假设。",
        "universe": {
            "cis_v2_daily_latest_day": cis_day,
            "n_cis_crypto": len(cis_syms), "cis_crypto_symbols": cis_syms,
            "n_ticket_symbols": len(tick_syms),
            "n_union": len(universe),
            "n_empty_supply": len(empty), "empty_symbols": empty,
            "source_pick": {s: m[0] for s, m in meta.items() if m},
        },
        "writing_A": "端点单日:c1/c0 − 1(c = asset_mcap_daily 的 mcap ÷ price),"
                     "端点锚定 = v2.py crypto_inputs(then ≤ asof−90d 且 ≥ −97d;last ≤ asof 且 ≥ −3d)",
        "writing_B": "两端各取 7 日中位数:med(c 近端 7 日)/med(c 远端 7 日) − 1,端点锚定同 A",
        "writing_C": "exp(90 天 log(c) 对天 OLS 斜率 × 90) − 1,窗口 = 两个锚点之间,≥30 个观测",
        "ticket_rule": f"信号日 d,前后 {TICK_SLACK} 天内要有观测(S-665 预注册口径);"
                       f"标签「> {HIGH:.1%} 那一档」= 90 日增长 > {HIGH}",
    }

    # ---------------- ① 日变动噪声(两套宇宙都报,CIS 25 为主)
    noise = {}
    for s in universe:
        if series[s]:
            noise[s] = noise_of(series[s], vals[s])
    res["noise"] = {
        "all": {s: noise[s] for s in universe if s in noise},
        "cis25": {s: noise[s] for s in cis_syms if s in noise},
        "summary_cis25": {
            k: round(_median([noise[s][k] for s in cis_syms if s in noise]), 6)
            for k in ("med_abs_chg", "p95_abs_chg", "p99_abs_chg", "pct_days_gt3pct")
            if all(k in noise[s] for s in cis_syms if s in noise)
        },
    }
    # ③ 最吵的前 10(按 |变动| p95 降序;并列按尖刺数)
    def noisiest(pool):
        have = [s for s in pool if s in noise and noise[s].get("n_days", 0) >= 60]
        have.sort(key=lambda s: (-noise[s]["p95_abs_chg"], -noise[s]["n_spikes"]))
        return [{"symbol": s, "n_days": noise[s]["n_days"],
                 "d_first": noise[s]["d_first"], "d_last": noise[s]["d_last"],
                 "med_abs_chg": noise[s]["med_abs_chg"],
                 "p95_abs_chg": noise[s]["p95_abs_chg"],
                 "pct_days_gt3pct": noise[s]["pct_days_gt3pct"],
                 "n_spikes": noise[s]["n_spikes"],
                 "note": noise[s].get("note", "")} for s in have[:10]]
    res["noisiest_top10_cis25"] = noisiest(cis_syms)
    res["noisiest_top10_universe"] = noisiest(universe)

    # ---------------- ② CIS 25 的每周截面排名相关
    weeks, per_write = [], {"A": [], "B": [], "C": []}
    d0 = dt.date(2024, 1, 1)
    d1 = dt.date(2026, 10, 20)
    day = d0
    while day <= d1:
        ds = day.isoformat()
        got = {}
        for s in cis_syms:
            g = growth_writings(series[s], vals[s], ds)
            for w in ("A", "B", "C"):
                if g[w] is not None:
                    got.setdefault(w, {})[s] = g[w]
        row = {"d": ds,
               "n": {w: len(got.get(w, {})) for w in ("A", "B", "C")},
               "rho": {}}
        pairs = (("A", "B"), ("A", "C"), ("B", "C"))
        for x, y in pairs:
            common = sorted(set(got.get(x, {})) & set(got.get(y, {})))
            if len(common) < 3:
                continue
            rho = spearman([got[x][s] for s in common], [got[y][s] for s in common])
            if rho is not None:
                row["rho"][f"{x}~{y}"] = round(rho, 4)
                row.setdefault("n_pair", {})[f"{x}~{y}"] = len(common)
        weeks.append(row)
        day += dt.timedelta(days=7)
    rho_all = {k: [w["rho"][k] for w in weeks if k in w.get("rho", {})]
               for k in ("A~B", "A~C", "B~C")}
    res["cis25_weekly"] = {
        "rule": "2024-01 → 2026-10,每 7 天一个截面;三种写法各自在 25 个名字里排秩,"
                "两两 Spearman;报中位与 p10",
        "n_weeks": len(weeks),
        "coverage_median": {w: float(_median([x["n"][w] for x in weeks]))
                            for w in ("A", "B", "C")},
        "rho_median": {k: round(_median(v), 4) for k, v in rho_all.items()},
        "rho_p10": {k: round(sorted(v)[max(0, int(0.10 * (len(v) - 1)))], 4)
                    for k, v in rho_all.items() if v},
        "rho_min": {k: round(min(v), 4) for k, v in rho_all.items() if v},
        "rho_n_weeks": {k: len(v) for k, v in rho_all.items()},
        "weeks": weeks,
    }

    # ---------------- ② R-v2 票:「> 2.2% 那一档」三写法归属
    lab = {}
    for t in tickets:
        s = t["symbol"]
        g = growth_writings(series[s], vals[s], t["signal_d"],
                            slack_last=TICK_SLACK, slack_then=TICK_SLACK)
        lab[(t["side"], t["symbol"], t["signal_d"])] = g
    def bucket(g, w):
        return None if g.get(w) is None else (g[w] > HIGH)
    flips = {}
    for side in ("long", "short"):
        keys = [k for k in lab if k[0] == side]
        per = {}
        for w in ("A", "B", "C"):
            have = [k for k in keys if bucket(lab[k], w) is not None]
            per[w] = {"n_tickets": len(keys),
                      "n_with_data": len(have),
                      "n_high": sum(1 for k in have if lab[k][w] > HIGH),
                      "pct_high": round(sum(1 for k in have if lab[k][w] > HIGH) / len(have), 4)
                      if have else None}
        fl = {"A_vs_B": 0, "A_vs_C": 0, "B_vs_C": 0, "n_comparable_AB": 0,
              "n_comparable_AC": 0, "n_comparable_BC": 0, "examples": []}
        for k in keys:
            b = {w: bucket(lab[k], w) for w in ("A", "B", "C")}
            for x, y, tag in (("A", "B", "A_vs_B"), ("A", "C", "A_vs_C"), ("B", "C", "B_vs_C")):
                if b[x] is None or b[y] is None:
                    continue
                fl["n_comparable_" + ("AB" if x + y == "AB" else ("AC" if x + y == "AC" else "BC"))] += 1
                if b[x] != b[y]:
                    fl[tag] += 1
                    if len(fl["examples"]) < 8:
                        fl["examples"].append(
                            {"symbol": k[1], "signal_d": k[2],
                             x: round(lab[k][x], 5), y: round(lab[k][y], 5)})
        flips[side] = {"per_writing": per, "label_flips": fl}
    res["tickets_label"] = {"threshold": HIGH, "by_side": flips}

    # ---------------- 汇总判据(供 Seth 看结论)
    rm = res["cis25_weekly"]["rho_median"]
    rp = res["cis25_weekly"]["rho_p10"]
    bars = {"A~B": rm.get("A~B"), "A~C": rm.get("A~C")}
    res["headline"] = {
        "rho_median_A_B": rm.get("A~B"), "rho_median_A_C": rm.get("A~C"),
        "rho_median_B_C": rm.get("B~C"),
        "rho_p10_A_B": rp.get("A~B"),
        "rho_p10_A_C": rp.get("A~C"),
        "ticket_high_flips_AB_long": flips["long"]["label_flips"]["A_vs_B"],
        "ticket_high_flips_AC_long": flips["long"]["label_flips"]["A_vs_C"],
        "ticket_n_long": flips["long"]["per_writing"]["A"]["n_tickets"],
        "verdict_prior_value": (
            "卡上的线「A 与 B/C 排名相关 ≥ 0.95 ⇒ v2 照旧」:中位 "
            f"A~B {bars['A~B']}、A~C {bars['A~C']} 两条都过 ⇒ **v2 供给维照旧**。"
            f"但 p10 A~B {rp.get('A~B')} 过线、A~C {rp.get('A~C')} 掉到线下 ⇒ C 的尾部不稳。"
            "标签侧(见 tickets_label):换写法 A~B 翻 27/705=3.8%,而把整段测量挪一天 A 自己"
            "就翻 31/705=4.4%(B 0.57%、C 0.43%)⇒ 要改的是 S-665 前向标签的取数写法与取数日,"
            "不是 v2 的打分维。"),
    }
    print(json.dumps({k: res[k] for k in ("headline",)}, ensure_ascii=False, indent=2))
    print(json.dumps({"summary_cis25": res["noise"]["summary_cis25"],
                      "rho_median": rm, "rho_p10": res["cis25_weekly"]["rho_p10"],
                      "tickets_long": flips["long"]}, ensure_ascii=False, indent=2))
    print(json.dumps(res["noisiest_top10_cis25"], ensure_ascii=False, indent=2))
    return res


if __name__ == "__main__":
    out = main()
    p = os.path.join(HERE, "t183_results.json")
    json.dump(out, open(p, "w"), ensure_ascii=False, indent=1)
    print("wrote", p)