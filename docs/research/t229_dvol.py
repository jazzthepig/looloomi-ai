"""T-229 / S-710 —— DVOL(BTC 隐含波动率指数)一年分位 ≥ 0.80 时把敞口降到 0.5 的回放。

预注册:REFUTATION_LEDGER.md 的 S-710(Seth,2026-11-03 15:55 UTC)。规则与三条判据逐字照抄,
只算一次,不扫参数。

输入
  BTC 现货日线:Supabase `ohlcv_daily`(symbol=BTC, source=binance_hist),close。
  DVOL:Deribit 公开 API `public/get_volatility_index_data`(resolution=1D)的 close;
        仓库里 `deriv_vol_daily` 表在本次开工时对该只读 key 返回 0 行(见报告「输入偏离声明」),
        故直接从同一个上游(Deribit)取原始日线,口径与表里的 `dvol_close` 一致。

输出
  docs/research/t229_results.json(与脚本同目录),并打印摘要。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
_spec = importlib.util.spec_from_file_location("apparatus", ROOT / "src/data/evaluation/apparatus.py")
ap = importlib.util.module_from_spec(spec=_spec)
_spec.loader.exec_module(ap)

MAC = Path("/Volumes/CometCloudAI/cometcloud-local")
CACHE = MAC / "_cache" / "t229"
OUT = Path(__file__).resolve().parent / "t229_results.json"

# ── 预注册参数(写死,不扫) ─────────────────────────────────────────────────────
START = date(2022, 3, 1)          # 收益区间起
END = date(2026, 10, 31)          # 收益区间止
CUT = date(2024, 7, 1)            # (c) 两半切点:第一半 ≤ 2024-06-30
WIN = 365                         # 分位窗口:过去 365 日(不含当日)
COST = 0.001                      # 10bp × |Δ敞口|
TRIG, REL = 0.80, 0.60            # 主规则:≥ 0.80 降到 0.5,< 0.60 恢复 1.0
HALF = 0.5
N_NULL = 1000
SEED = 710

DERIBIT_API = "https://www.deribit.com/api/v2/public/get_volatility_index_data"


# ── 取数 ─────────────────────────────────────────────────────────────────────
def _http_json(url, headers=None, timeout=120):
    req = urllib.request.Request(url, headers=headers or {"User-Agent": "cometcloud-research/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _ms(d: date, end_of_day=False):
    dt = datetime(d.year, d.month, d.day, 23, 59) if end_of_day else datetime(d.year, d.month, d.day)
    return int(dt.replace(tzinfo=timezone.utc).timestamp() * 1000)


def fetch_dvol(currency: str, start: date, end: date) -> dict:
    """Deribit DVOL 日线 close:{date: value}。按 365 天分块(端点单次上限 1000 行)。"""
    path = CACHE / ("deribit_dvol_" + currency.lower() + "_daily.json")
    if path.exists():
        return json.loads(path.read_text())
    out: dict[str, float] = {}
    a = start
    while a <= end:
        b = min(a + timedelta(days=364), end)
        url = (DERIBIT_API + "?currency=" + currency + "&resolution=1D"
               + "&start_timestamp=" + str(_ms(a)) + "&end_timestamp=" + str(_ms(b, True)))
        res = (_http_json(url).get("result") or {})
        for row in (res.get("data") or []):
            if not isinstance(row, (list, tuple)) or len(row) < 5:
                continue
            day = datetime.fromtimestamp(int(row[0]) / 1000, tz=timezone.utc).date().isoformat()
            out[day] = float(row[4])
        a = b + timedelta(days=1)
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


def fetch_ohlcv(symbol: str, source: str = "binance_hist") -> dict:
    """ohlcv_daily 的 close:{date: value}。只读 SELECT,翻页带 order。"""
    path = CACHE / ("ohlcv_" + symbol.lower() + "_" + source + ".json")
    if path.exists():
        return json.loads(path.read_text())
    url_env = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_KEY")
    if not url_env or not key:
        raise SystemExit("缺 SUPABASE_URL / SUPABASE_KEY")
    hdr = {"apikey": key, "Authorization": "Bearer " + key}
    out: dict[str, float] = {}
    page = 0
    while True:
        params = {"select": "trade_date,close", "symbol": "eq." + symbol, "source": "eq." + source,
                  "order": "trade_date.asc", "limit": "1000", "offset": str(page * 1000)}
        url = url_env + "/rest/v1/ohlcv_daily?" + urllib.parse.urlencode(params)
        rows = _http_json(url, headers=hdr)
        if not rows:
            break
        for r in rows:
            if r.get("close") is not None:
                out[str(r["trade_date"])[:10]] = float(r["close"])
        if len(rows) < 1000:
            break
        page += 1
    CACHE.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out))
    return out


# ── 分位与规则 ───────────────────────────────────────────────────────────────
def pct_series(dvol: dict, days: list[str]) -> dict:
    """分位 = 过去 365 日(不含当日)里 ≤ 当日值的比例(分母 = 窗口内实际观测数)。"""
    all_days = sorted(dvol)
    vals = np.array([dvol[d] for d in all_days], dtype=float)
    idx = {d: i for i, d in enumerate(all_days)}
    out = {}
    for d in days:
        i = idx.get(d)
        if i is None:
            continue
        lo = (date.fromisoformat(d) - timedelta(days=WIN)).isoformat()
        j = np.searchsorted(all_days, lo, side="left")
        w = vals[j:i]
        if w.size == 0:
            continue
        out[d] = float(np.sum(w <= vals[i]) / w.size)
    return out


def state_series(pcts: dict, days: list[str], trig: float, rel: float) -> dict:
    """滞回状态机:s[d] = d 日收盘后生效(用于 d+1)的敞口。"""
    s, state = {}, HALF * 0 + 1.0
    for d in days:
        q = pcts.get(d)
        if q is None:
            continue
        if state == 1.0 and q >= trig:
            state = HALF
        elif state == HALF and q < rel:
            state = 1.0
        s[d] = state
    return s


def state_series_sym(pcts: dict, days: list[str], lo_q: float = 0.20) -> dict:
    """对称臂:分位 ≤ 0.20 ⇒ 1.0,其余 0.5(无滞回,照卡)。"""
    s = {}
    for d in days:
        q = pcts.get(d)
        if q is None:
            continue
        s[d] = 1.0 if q <= lo_q else HALF
    return s


def daily_returns(days: list[str], px: dict) -> np.ndarray:
    """日收益;区间首日用区间前一日的收盘(区间外的前一根)。"""
    r = np.zeros(len(days))
    prior = [d for d in sorted(px) if d < days[0]]
    prev = px[prior[-1]] if prior else None
    for i, d in enumerate(days):
        p1 = px.get(d)
        if prev is not None and p1 is not None and prev > 0:
            r[i] = p1 / prev - 1.0
        prev = p1 if p1 is not None else prev
    return r


def strategy(dates: list[str], px: dict, s: dict) -> tuple[np.ndarray, np.ndarray]:
    """策略 / 持有 日收益。s[d] 是 d 收盘后生效的敞口,用于 d 的下一根;换仓成本记在换仓当日。"""
    r_btc_all = daily_returns(dates, px)
    prev_s = 1.0
    r_strat, r_hold = [], []
    for i, d in enumerate(dates):
        r_btc = float(r_btc_all[i])
        s_cur = s.get(d, prev_s)
        r_strat.append(prev_s * r_btc - COST * abs(s_cur - prev_s))
        r_hold.append(r_btc)
        prev_s = s_cur
    return np.array(r_strat), np.array(r_hold)


def metrics(rets) -> dict:
    r = np.asarray(rets, dtype=float)
    if r.size == 0:
        return {"n": 0}
    nav = np.cumprod(1.0 + r)
    total = float(nav[-1] - 1.0)
    years = r.size / 365.0
    ann = float((1.0 + total) ** (1.0 / years) - 1.0) if total > -1 else float("nan")
    peak = np.maximum.accumulate(nav)
    dd = nav / peak - 1.0
    mdd = float(dd.min())
    calmar = float(ann / abs(mdd)) if mdd < 0 else float("inf")
    return {"n": int(r.size), "total": total, "ann": ann, "mdd": mdd, "calmar": calmar}


def segments(s: dict, days: list[str]) -> list[tuple[float, int, str, str]]:
    """连续同敞口段 → [(敞口, 段长, 起日, 止日)]。"""
    out = []
    cur, ln, start, prev_day = None, 0, None, None
    for d in days:
        v = s.get(d)
        if v is None:
            continue
        if v == cur:
            ln += 1
        else:
            if cur is not None:
                out.append((cur, ln, start, prev_day))
            cur, ln, start = v, 1, d
        prev_day = d
    if cur is not None:
        out.append((cur, ln, start, prev_day))
    return out


# ── 主流程 ───────────────────────────────────────────────────────────────────
def run_arm(name, px: dict, dvol: dict, trig: float, rel: float, sym: bool = False):
    days = [d for d in sorted(px) if START <= date.fromisoformat(d) <= END]
    # 状态机需要区间起点之前就存在:把 DVOL 全部日期跑一遍状态机,再取区间内的敞口
    all_days = sorted(dvol)
    full_pcts = pct_series(dvol, all_days)
    full_s = state_series_sym(full_pcts, all_days) if sym else state_series(full_pcts, all_days, trig, rel)
    s = {d: full_s[d] for d in days if d in full_s}
    pcts = {d: full_pcts[d] for d in days if d in full_pcts}
    r_strat, r_hold = strategy(days, px, s)
    m_s = metrics(r_strat)
    m_h = metrics(r_hold)
    half_days = sum(1 for d in days if s.get(d) == HALF)
    segs = segments(s, days)
    return {"name": name, "days": days, "s": s, "pcts": pcts, "strat": r_strat, "hold": r_hold,
            "m_strat": m_s, "m_hold": m_h, "half_days": half_days, "segs": segs}


def random_control(px: dict, days: list[str], segs: list[tuple[float, int]], seed: int = SEED,
                    n: int = N_NULL):
    """随机对照:同样 0.5 总天数、同样段长分布、随机放时间轴,1,000 次,种子 710(走 apparatus.py)。"""
    # 用真实价格重算每条随机臂的收益(段决定敞口,价格决定收益,成本照算)
    rets_all = []
    r_btc = daily_returns(days, px)

    def one(rng):
        order = rng.permutation(len(segs))
        s = np.concatenate([np.full(segs[int(i)][1], segs[int(i)][0]) for i in order])
        if s.size != len(days):
            return float("nan")
        prev = 1.0
        r = np.empty(len(days))
        for t in range(len(days)):
            r[t] = prev * r_btc[t] - COST * abs(s[t] - prev)
            prev = s[t]
        return metrics(r)["calmar"]

    try:
        null = ap.null_distribution(one, n, seed)
        return {"null": null, "ok": True}
    except ap.NoOpNull as e:
        return {"null": None, "ok": False, "why": str(e)}


def main():
    CACHE.mkdir(parents=True, exist_ok=True)
    dvol_btc = fetch_dvol("BTC", date(2021, 3, 1), END)
    dvol_eth = fetch_dvol("ETH", date(2021, 3, 1), END)
    px_btc = fetch_ohlcv("BTC")
    px_eth = fetch_ohlcv("ETH")

    rep = {"meta": {"start": START.isoformat(), "end": END.isoformat(), "cut": CUT.isoformat(),
                    "cost_bp": 10, "seed": SEED, "n_null": N_NULL,
                    "dvol_btc_rows": len(dvol_btc), "dvol_eth_rows": len(dvol_eth),
                    "px_btc_rows": len(px_btc), "px_eth_rows": len(px_eth),
                    "dvol_btc_first": min(dvol_btc), "dvol_btc_last": max(dvol_btc)}}

    main_arm = run_arm("main BTC trig0.80 rel0.60", px_btc, dvol_btc, TRIG, REL)
    segs = main_arm["segs"]
    pcts_all = main_arm["pcts"]
    rep["main"] = {"days": len(main_arm["days"]), "half_days": main_arm["half_days"],
                   "strat": main_arm["m_strat"], "hold": main_arm["m_hold"],
                   "n_segments": len(segs),
                   "seg_lengths": [l for _, l, _, _ in segs],
                   "seg_exposures": [e for e, _, _, _ in segs],
                   "half_segments": [{"start": a, "end": b, "len": l,
                                      "pct_at_start": pcts_all.get(a), "pct_at_end": pcts_all.get(b),
                                      "dvol_at_start": dvol_btc.get(a), "dvol_at_end": dvol_btc.get(b)}
                                     for e, l, a, b in segs if e == HALF],
                   "pct_stats": {"min": min(pcts_all.values()), "max": max(pcts_all.values()),
                                 "mean": sum(pcts_all.values()) / len(pcts_all),
                                 "n": len(pcts_all)},
                   "cost_total_bp": 10000 * COST * sum(abs(segs[i + 1][0] - segs[i][0])
                                                      for i in range(len(segs) - 1))}

    # (b) 随机对照
    rc = random_control(px_btc, main_arm["days"], main_arm["segs"])
    calmar_r = main_arm["m_strat"]["calmar"]
    if rc["ok"]:
        pct = ap.percentile_of(calmar_r, rc["null"])
        rep["random_control"] = {"ok": True, "calmar_actual": calmar_r,
                                 "percentile_of_actual": pct,
                                 "null_p95": float(np.quantile(rc["null"], 0.95)),
                                 "null_median": float(np.median(rc["null"])),
                                 "null_min": float(np.min(rc["null"])), "null_max": float(np.max(rc["null"])),
                                 "passes_95": bool(pct is not None and pct > 0.95)}
    else:
        rep["random_control"] = {"ok": False, "why": rc["why"]}

    # (c) 两半
    halves = {}
    for label, mask in ap.windows(main_arm["days"], [START.isoformat(), CUT.isoformat()]):
        halves[label] = {"strat": metrics(main_arm["strat"][mask]), "hold": metrics(main_arm["hold"][mask])}
    rep["halves"] = halves

    # 判据
    mdd_s = main_arm["m_strat"]["mdd"]
    mdd_h = main_arm["m_hold"]["mdd"]
    # 「浅」= 回撤更小(数值更接近 0)⇒ mdd_s ≥ 0.85 × mdd_h(两者皆负)
    a_pass = bool(mdd_h < 0 and mdd_s >= 0.85 * mdd_h)
    b_pass = bool(rep["random_control"].get("passes_95"))
    c_pass = True
    for label, h in halves.items():
        if not (h["strat"]["calmar"] >= h["hold"]["calmar"]):
            c_pass = False
    rep["verdict"] = {"a_mdd_shallower_15pct": a_pass, "a_detail": {"mdd_rule": mdd_s, "mdd_hold": mdd_h,
                     "relative_depth": (abs(mdd_s) / abs(mdd_h)) if mdd_h else None},
                     "b_calmar_above_p95": b_pass, "c_both_halves_calmar_ge_hold": c_pass,
                     "all_pass": bool(a_pass and b_pass and c_pass)}

    # 副列(只报不判)
    side = {}
    for thr in (0.70, 0.90):
        arm = run_arm("BTC trig%.2f" % thr, px_btc, dvol_btc, thr, thr - 0.20)
        side["btc_trig_%.2f" % thr] = {"strat": arm["m_strat"], "hold": arm["m_hold"],
                                       "half_days": arm["half_days"]}
    if px_eth and dvol_eth:
        arm_eth = run_arm("ETH trig0.80", px_eth, dvol_eth, TRIG, REL)
        side["eth_trig_0.80"] = {"strat": arm_eth["m_strat"], "hold": arm_eth["m_hold"],
                                 "half_days": arm_eth["half_days"]}
    else:
        side["eth_trig_0.80"] = {"error": "ETH 价格或 DVOL 不可用"}
    arm_sym = run_arm("BTC symmetric <=0.20", px_btc, dvol_btc, 0.0, 0.0, sym=True)
    side["btc_symmetric_le_0.20"] = {"strat": arm_sym["m_strat"], "hold": arm_sym["m_hold"],
                                     "half_days": arm_sym["half_days"]}
    rep["side_columns"] = side

    # 探索性(不作判据):减仓日在跌之后还是之前;触发后 30 日 BTC 的走向
    days = main_arm["days"]
    px = px_btc
    r_all = daily_returns(days, px)
    half_mask = np.array([main_arm["s"].get(d) == HALF for d in days])
    fwd = {}
    for h in (1, 7, 30):
        vals_h, vals_f = [], []
        for i in range(len(days) - h):
            p0, p1 = px[days[i]], px[days[i + h]]
            if not p0:
                continue
            r = p1 / p0 - 1.0
            (vals_h if half_mask[i] else vals_f).append(r)
        fwd["d+%d" % h] = {"half_days_mean": float(np.mean(vals_h)) if vals_h else None,
                           "full_days_mean": float(np.mean(vals_f)) if vals_f else None,
                           "n_half": len(vals_h), "n_full": len(vals_f)}
    trig_days = [d for d in days if main_arm["s"].get(d) == HALF
                 and main_arm["s"].get(days[days.index(d) - 1] if days.index(d) > 0 else d) != HALF]
    rep["exploratory"] = {"forward_returns_by_exposure": fwd,
                          "n_trigger_entries": len(trig_days),
                          "trigger_days": trig_days}

    # 逐年(探索性)
    yearly = {}
    for y in range(START.year, END.year + 1):
        days = [d for d in main_arm["days"] if d.startswith(str(y))]
        if not days:
            continue
        idx = [main_arm["days"].index(d) for d in days]
        yearly[str(y)] = {"strat": metrics(main_arm["strat"][idx]), "hold": metrics(main_arm["hold"][idx]),
                          "half_days": sum(1 for d in days if main_arm["s"].get(d) == HALF)}
    rep["yearly"] = yearly

    OUT.write_text(json.dumps(rep, indent=2, ensure_ascii=False, default=float))
    print(json.dumps({"meta": rep["meta"], "main": rep["main"], "random_control": rep["random_control"],
                      "halves": rep["halves"], "verdict": rep["verdict"], "side": rep["side_columns"],
                      "yearly": yearly}, indent=2, ensure_ascii=False, default=float))


if __name__ == "__main__":
    main()
