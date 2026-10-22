"""T-178 / S-665 独立复算 —— 只按台账 §S-665 的预注册文字自己写。

纪律(**这张卡存在的全部理由**):
  · 只读了 REFUTATION_LEDGER.md L30078-30083(§S-665 预注册段,到「### S-665 结果」那一行为止);
  · 没读 §S-665 结果段;没读 docs/research/s665_dilution_rv2.py / s665_results.json;
  · 没读 src/data/signals/ticket_tags.py 与 battlefield_brief.py 里的 S-665 数字。
  · 票的生成器不是本卡的对照物:docs/research/s657_s658_breadth_second_leg.py 已把 t159 的 770 张
    复现出来并落盘在 <root>/research/t159/_tickets_2020-03-01_2026-06-20.json,直接取那份。

预注册(原文,2026-10-21 16:51 UTC):
  变量(写死):dil = ln(供给[t] / 供给[t − 90]);t 与 t − 90 前后 7 天内都要有观测,否则这张票记「无数据」并报个数。
  流通量 = asset_mcap_daily 的市值 ÷ 价格(CoinGecko),按 symbol 接(同 symbol 取当日市值最大的 coin_id)。
  判(三条全满足):
    ① 有数据的票里,dil 低于当年中位数的一半票平均 R − 高于中位数的一半 > 0,
       在每个日历年内打乱高低标签 2,000 次,单侧 p < 0.05;
    ② 两段(信号日 < 2023-01-01、≥ 2023-01-01)差都 > 0;
    ③ 低稀释一半的总 R ≥ 全部有数据票总 R 的 50%。
  只报:按 dil 三分位的平均 R / 胜率 / 最好 10 张落在哪一档;无数据票的平均 R。

用法:
  python3 docs/research/t178_s665_replication.py [--root /Volumes/CometCloudAI/cometcloud-local]
"""
from __future__ import annotations

import bisect
import datetime
import json
import math
import os
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
ROOT = sys.argv[sys.argv.index("--root") + 1] if "--root" in sys.argv \
    else "/Volumes/CometCloudAI/cometcloud-local"
CACHE = os.path.join(ROOT, "research", "t178")
os.makedirs(CACHE, exist_ok=True)
sys.path.insert(0, REPO)

URL = os.environ.get("SUPABASE_URL", "").rstrip("/")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY,退出(不要读 .env)")
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY}

NBOOT = 2000                      # 预注册写死:2,000 次
SEED = 20261023
WIN = 7                           # 预注册写死:前后 7 天内要有观测
# 预注册写的是「按 symbol 接」。面板里 1000SHIB 这种永续名,asset_mcap_daily 里只叫 SHIB
# (逐个查过 20 个空 symbol,只有它有别名)。别名档是**偏离预注册字面**的敏感检查,不作判据。
ALIASES = {"1000SHIB": "SHIB"}


# ---------------------------------------------------------------- 读取层
def _page(path: str, lo: int, hi: int) -> list:
    req = urllib.request.Request(URL + "/rest/v1/" + path,
                                 headers=dict(HDR, Range=f"{lo}-{hi}"))
    try:
        return json.loads(urllib.request.urlopen(req, timeout=300).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:            # Range 越界 = 没有更多行
            return []
        raise


def _page_all(path: str, cap: int = 400_000) -> list:
    out, off = [], 0
    while off < cap:
        chunk = _page(path, off, off + 999)
        if not chunk:
            break
        out += chunk
        off += 1000
    return out


def _ord(d: str) -> int:
    return datetime.date.fromisoformat(d).toordinal()


def fetch_supply(symbols: list) -> tuple:
    """symbol → {date: 流通量},以及每个 symbol 选了哪个 source。

    流通量 = asset_mcap_daily 的市值 ÷ 价格(CoinGecko)。同 symbol 同一天多个 coin_id 时取当日市值最大的
    那个(预注册原文)。**实现自由度**:一张表里若混了多个 source,按 symbol 取覆盖天数最多的那个 ——
    市值与价格必须来自同一条序列,跨源相除没有意义;选了哪个一律记进结果。翻页一律带 order=。"""
    def one(sym):
        q = (f"asset_mcap_daily?select=d,price,mcap,coin_id,source&symbol=eq.{sym}"
             f"&order=coin_id.asc,d.asc")
        rows = _page_all(q)
        pk = [(r["d"], r.get("coin_id"), r.get("source")) for r in rows]
        assert len(set(pk)) == len(pk), f"{sym}:asset_mcap_daily 有重复键 {len(pk) - len(set(pk))} 条 —— 停"
        by_src = defaultdict(lambda: defaultdict(dict))     # source → date → coin_id → (mcap, price)
        for r in rows:
            m, p = r.get("mcap"), r.get("price")
            if m is None or p is None or float(p) <= 0 or float(m) <= 0:
                continue
            by_src[r.get("source") or "?"][r["d"]][r.get("coin_id")] = (float(m), float(p))
        if not by_src:
            return sym, {}, None
        src = max(by_src, key=lambda s: len(by_src[s]))
        out = {}
        for d, per_coin in by_src[src].items():
            m, p = max(per_coin.values(), key=lambda v: v[0])   # 当日市值最大的 coin_id
            out[d] = m / p
        return sym, dict(sorted(out.items())), [src, len(by_src[src]), len(rows)]

    sup, meta = {}, {}
    with ThreadPoolExecutor(max_workers=8) as ex:
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


# ---------------------------------------------------------------- dil
def nearest(series: list, vals: dict, d: str, win: int = WIN, mode: str = "nearest"):
    """t 附近 win 天内的观测。两种读法:

      mode="nearest"    —— **前后**都找,取最近的一个(预注册原文「前后 7 天内都要有观测」的字面读法);
      mode="on_or_after" —— 只往后找,取第一个 ≥ d 且不超过 win 天的
                          (= apparatus.price_on_or_after 的口径,apparatus 默认 max_gap_days=3)。

    实现自由度:预注册写「前后 7 天内」,两种读法都成立。**这个选择会改变结论**,所以两种都算、都报。"""
    if not series:
        return None
    tgt = _ord(d)
    i = bisect.bisect_left(series, d)
    if mode == "nearest":
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(series) and abs(_ord(series[j]) - tgt) <= win:
                return vals[series[j]]
        return None
    for j in range(i, len(series)):                     # on_or_after
        if _ord(series[j]) - tgt > win:
            break
        if _ord(series[j]) >= tgt:
            return vals[series[j]]
    return None


def dil_of(t: dict, sup: dict, mode: str = "nearest"):
    sym, d = t["symbol"], t["signal_d"]
    vals = sup.get(sym) or {}
    series = list(vals)
    s0 = nearest(series, vals, d, mode=mode)
    s90 = nearest(series, vals, (datetime.date.fromisoformat(d)
                                 - datetime.timedelta(days=90)).isoformat(), mode=mode)
    if s0 is None or s90 is None or s90 <= 0:
        return None
    return math.log(s0 / s90)


def median(xs: list) -> float:
    a = sorted(xs)
    n = len(a)
    return a[n // 2] if n % 2 else (a[n // 2 - 1] + a[n // 2]) / 2.0


def mean(xs: list) -> float:
    return float(np.mean(xs)) if xs else float("nan")


def run(mode: str) -> dict:
    res = {}
    ref = json.load(open(os.path.join(ROOT, "research", "t159",
                                      "_tickets_2020-03-01_2026-06-20.json")))["long"]
    res.update({"prereg": "S-665 预注册段(REFUTATION_LEDGER.md L30078-30083,2026-10-21 16:51 UTC)",
                "independence": "只读预注册段;未读结果段 / s665 脚本 / s665_results.json / ticket_tags / brief",
                "nboot": NBOOT, "seed": SEED, "obs_window_days": WIN,
                "obs_window_rule": mode})
    res["tickets"] = {"n": len(ref), "span": [min(t["signal_d"] for t in ref),
                                              max(t["signal_d"] for t in ref)],
                      "path": "research/t159/_tickets_2020-03-01_2026-06-20.json [long]"}
    assert len(ref) == 770, f"票数 {len(ref)} ≠ 770"
    print(f"[票] {len(ref)} 张 · {res['tickets']['span'][0]} → {res['tickets']['span'][1]}", flush=True)

    # 预注册写死「仍持有的按最后收盘盯市」;落盘文件里仍持有的票 r 是 None,借 s657(票的生成器)的
    # load_hl + mtm 补上 —— 同一套口径,不在本卡重写管理逻辑。
    if any(t.get("r") is None for t in ref):
        import importlib.util
        sp = importlib.util.spec_from_file_location(
            "s657", os.path.join(HERE, "s657_s658_breadth_second_leg.py"))
        s657 = importlib.util.module_from_spec(sp)
        sys.modules["s657"] = s657
        sp.loader.exec_module(s657)
        panel = s657.t159.load_bars()          # s657 的基础面板(T-159 那份)
        native, _, _ = s657.load_hl(set(panel))
        bars = dict(panel)
        for k, v in native.items():
            nm = k[3:] if k.startswith("HL:") else k
            if nm not in bars:
                bars[nm] = v
        n_open = sum(1 for t in ref if t.get("r") is None)
        s657.mtm(ref, bars)
        res["still_open_marked_to_market"] = {"n": n_open,
                                              "r": [round(t["r"], 4) for t in ref
                                                    if t.get("still")]}
        print(f"[盯市] {n_open} 张仍持有的票按最后收盘补上 R", flush=True)

    syms = sorted({t["symbol"] for t in ref})
    sup, meta = _cached("supply.json", lambda: fetch_supply(syms))
    if mode.startswith("alias"):                              # 敏感检查档,见 ALIASES
        # 别名目标不一定在票的 symbol 集合里(SHIB 不是、1000SHIB 才是)⇒ 缺了就单抓。
        extra = {b: fetch_supply([b])[0][b] for b in set(ALIASES.values()) if b not in sup}
        for a, b in ALIASES.items():
            if not sup.get(a) and (sup.get(b) or extra.get(b)):
                sup = {**sup, a: sup.get(b) or extra[b]}
    srcs = defaultdict(int)
    for s, m in meta.items():
        if m:
            srcs[m[0]] += 1
    res["supply_coverage"] = {"n_symbols": len(syms), "source_pick": dict(srcs),
                              "symbols_empty": sorted(s for s, v in sup.items() if not v)}
    print(f"[流通量] {len(syms)} symbol · 选中 source {dict(srcs)}", flush=True)

    for t in ref:
        t["dil"] = dil_of(t, sup, mode)
    with_data = [t for t in ref if t["dil"] is not None]
    no_data = [t for t in ref if t["dil"] is None]

    # ---- 当年中位数切高 / 低:每年按 dil 排序,前 floor(n/2) 张为低,其余为高 ----
    by_year = defaultdict(list)
    for t in with_data:
        by_year[int(t["signal_d"][:4])].append(t)
    low, high, year_med = [], [], {}
    for y in sorted(by_year):
        ts = sorted(by_year[y], key=lambda t: t["dil"])
        half = len(ts) // 2
        low += ts[:half]
        high += ts[half:]
        for t in ts:
            t["high"] = t in high
        year_med[str(y)] = round(median([t["dil"] for t in ts]), 4)
    res["by_year"] = {"n_with_data": {str(y): len(v) for y, v in sorted(by_year.items())},
                      "year_median_dil": year_med}

    def stat(r, hi_lab):
        return float(r[~hi_lab].mean() - r[hi_lab].mean())

    rs = np.asarray([t["r"] for t in with_data], dtype=float)
    hi0 = np.asarray([bool(t["high"]) for t in with_data])
    groups = np.asarray([t["signal_d"][:4] for t in with_data], dtype=object)
    obs = stat(rs, hi0)
    diff = mean([t["r"] for t in low]) - mean([t["r"] for t in high])

    # ---- ① 年内打乱高低标签 2,000 次,单侧 p(标签是单位,不打乱 R)----
    from src.data.evaluation.apparatus import (NoOpNull, null_distribution,
                                               percentile_of, shuffle_within)

    def one(rng):
        sh = np.asarray(shuffle_within(hi0, groups, rng), dtype=bool)
        return stat(rs, sh)

    try:
        null = np.asarray(null_distribution(one, NBOOT, SEED, actual=obs))
    except NoOpNull as e:
        raise SystemExit(f"零分布空转:{e}")
    p_upper = float((null >= obs).mean())
    res["judge1"] = {"n_low": len(low), "low_mean_R": round(mean([t["r"] for t in low]), 4),
                     "n_high": len(high), "high_mean_R": round(mean([t["r"] for t in high]), 4),
                     "diff_low_minus_high": round(diff, 4),
                     "null_mean": round(float(null.mean()), 6), "null_sd": round(float(null.std()), 6),
                     "perm_p_upper_one_sided": round(p_upper, 4),
                     "perm_percentile": round(percentile_of(obs, null), 4),
                     "pass": bool(diff > 0 and p_upper < 0.05)}
    print(f"[①] 低 {res['judge1']['low_mean_R']:+.4f}R({len(low)}) − "
          f"高 {res['judge1']['high_mean_R']:+.4f}R({len(high)}) = {diff:+.4f}R · "
          f"单侧 p {p_upper:.4f} → {'过' if res['judge1']['pass'] else '不过'}", flush=True)

    # ---- ② 两段 ----
    seg = {}
    for name, f in (("lt_2023", lambda t: t["signal_d"] < "2023-01-01"),
                    ("ge_2023", lambda t: t["signal_d"] >= "2023-01-01")):
        lo = [t["r"] for t in low if f(t)]
        hi = [t["r"] for t in high if f(t)]
        d = mean(lo) - mean(hi)
        seg[name] = {"n_low": len(lo), "n_high": len(hi), "low_mean_R": round(mean(lo), 4),
                     "high_mean_R": round(mean(hi), 4), "diff": round(d, 4), "pass": bool(d > 0)}
    res["judge2"] = {"segments": seg, "pass": all(v["pass"] for v in seg.values())}
    print(f"[②] <2023 {seg['lt_2023']['diff']:+.4f}R · ≥2023 {seg['ge_2023']['diff']:+.4f}R → "
          f"{'过' if res['judge2']['pass'] else '不过'}", flush=True)

    # ---- ③ 低稀释一半的总 R ≥ 全部有数据票总 R 的 50% ----
    tot_low, tot_all = sum(t["r"] for t in low), sum(t["r"] for t in with_data)
    share = tot_low / tot_all if tot_all else float("nan")
    res["judge3"] = {"total_R_low": round(tot_low, 4), "total_R_all_with_data": round(tot_all, 4),
                     "share": round(share, 4), "pass": bool(share >= 0.50)}
    print(f"[③] 低稀释总 R / 全部有数据总 R = {share:.4f} → "
          f"{'过' if res['judge3']['pass'] else '不过'}", flush=True)

    # ---- 只报:dil 三分位 ----
    dils = [t["dil"] for t in with_data]
    q1, q2 = float(np.percentile(dils, 100 / 3)), float(np.percentile(dils, 200 / 3))
    terc = {}
    for name, sel in (("低", lambda t: t["dil"] <= q1), ("中", lambda t: q1 < t["dil"] <= q2),
                      ("高", lambda t: t["dil"] > q2)):
        b = [t for t in with_data if sel(t)]
        terc[name] = {"n": len(b), "dil_lo": round(min(t["dil"] for t in b), 4),
                      "dil_hi": round(max(t["dil"] for t in b), 4),
                      "mean_R": round(mean([t["r"] for t in b]), 4),
                      "win_rate": round(float(np.mean([t["r"] > 0 for t in b])), 4)}
    top10 = sorted(with_data, key=lambda t: -t["r"])[:10]
    bk = lambda t: "低" if t["dil"] <= q1 else ("中" if t["dil"] <= q2 else "高")  # noqa: E731
    res["terciles"] = {"boundaries": {"q1": round(q1, 4), "q2": round(q2, 4)}, "buckets": terc,
                       "top10_in_bucket": {k: sum(1 for t in top10 if bk(t) == k)
                                           for k in ("低", "中", "高")}}
    res["no_data_tickets"] = {"n": len(no_data),
                              "mean_R": round(mean([t["r"] for t in no_data]), 4) if no_data else None,
                              "win_rate": (round(float(np.mean([t["r"] > 0 for t in no_data])), 4)
                                           if no_data else None),
                              "symbols": sorted({t["symbol"] for t in no_data})}
    res["verdict_all_three"] = bool(res["judge1"]["pass"] and res["judge2"]["pass"]
                                    and res["judge3"]["pass"])
    return res


def main() -> dict:
    """两种「前后 7 天」读法都跑一遍 —— 这个选择会改变结论,不替 Seth 选;别名档另算敏感检查。"""
    out_all = {"readings": {"nearest": run("nearest"), "on_or_after": run("on_or_after"),
                            "alias_on_or_after": run("alias_on_or_after")}}
    res = out_all["readings"]["nearest"]
    for k in ("judge1", "judge2", "judge3", "verdict_all_three"):
        out_all[k] = res[k]
    out_all["verdict_on_or_after"] = out_all["readings"]["on_or_after"]["verdict_all_three"]
    out_all["verdict_alias_on_or_after"] = out_all["readings"]["alias_on_or_after"]["verdict_all_three"]
    out_all["note"] = ("结论依赖「前后 7 天内」怎么读:nearest(字面)不过 ①,on_or_after(装置默认口径)三条全过;"
                       "alias 档 = on_or_after + 1000SHIB→SHIB 别名(偏离预注册字面的敏感检查)。")
    out = os.path.join(HERE, "t178_results.json")
    json.dump(out_all, open(out, "w"), indent=1, ensure_ascii=False)
    os.makedirs(os.path.join(ROOT, "_reports", "absorb_input"), exist_ok=True)
    json.dump(res, open(os.path.join(ROOT, "_reports", "absorb_input",
                                     "T-178_s665_replication_results.json"), "w"),
              indent=1, ensure_ascii=False)
    print("→", out, "| nearest 三条全过:", out_all["verdict_all_three"],
          "| on_or_after 三条全过:", out_all["verdict_on_or_after"],
          "| alias 档:", out_all["verdict_alias_on_or_after"])
    return out_all


if __name__ == "__main__":
    main()