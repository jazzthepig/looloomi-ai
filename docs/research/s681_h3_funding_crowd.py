#!/usr/bin/env python3
"""T-195 / S-681 H3「资金费拥挤」—— lane-b 独立复算(Seth 那份不读,数字自己算)。

协议照台账 S-681 预注册(H3 一字不改):
  信号 = 该币 3 个 UTC 日(t−2..t)资金费日合计的平均 × 365 ≥ 0.50(年化 50%)
         且 30 日成交额 ≥ $5M 且 上市 ≥ 60 天;同币 10 天内只取第一次。
  执行 = 信号日 t 收盘定、t+1 开盘进空;硬止损 = 进场 × 1.30(s = 30%);N = 10 天(持有期间收资金费)。
  对照 = 同一天随机空一个资金费不拥挤(3 日年化 < 20%)的合格合约(null_same_day,1000 抽,种子 681)。
  判据(四条全过 ⇒「过」):
    ① 发现段(信号日 2020-01-01 → 2023-12-31)平均 R > 0 且月块自助(2000)p(均值 ≤ 0) < 0.05
    ② 发现段平均 R ≥ 对照零分布 95 分位
    ③ 留出段(2024-01-01 → 最后一个完整月)平均 R > 0
    ④ 发现段票数 ≥ 50
只报:资金费贡献 vs 价格贡献;按拥挤度分档;对冲版(空 + 等名义多 BTC);周末/工作日分开。

两段分开跑:发现段先算完写进结果 json,再打开留出段(脚本里两个函数,顺序有 UTC 时间戳为证)。
数据只读数据根 research/s681/(Binance Vision USDT 本位永续日线 + 资金费,含已下架)。
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys
from collections import defaultdict

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import short_lab_common as C  # noqa: E402  (S-681 唯一共用模拟器,不复制它的函数)

OUT_JSON = os.path.join(HERE, "s681_h3_funding_crowd_results.json")

# ── 协议参数(S-681 写死,不改)──────────────────────────────────────────────────────────────────
S_STOP = 0.30          # 硬止损 30%
N_HOLD = 10            # 持有 10 天
THR_CROWD = 0.50       # 信号:3 日平均资金费年化 ≥ 50%
THR_POOL = 0.20        # 对照池:3 日平均资金费年化 < 20%
MIN_ADV30 = 5e6        # 30 日成交额 ≥ $5M
MIN_LISTED_DAYS = 60   # 上市 ≥ 60 天
COOLDOWN_D = 10        # 同币 10 天内只取第一次
DISC = ("2020-01-01", "2023-12-31")
HOLD_FROM = "2024-01-01"
NULL_DRAWS = 1000
BOOT_DRAWS = 2000
SEED = C.SEED          # 681


def utcnow() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")


# ── 指标(只用信号日及以前)────────────────────────────────────────────────────────────────────
def build_metrics(um: dict, fund: dict) -> dict:
    """每个 symbol: ann0[i] = 3 日平均资金费年化(t−2..t);ann1[i] = 同上但窗口滞后一天(t−3..t−1);
    elig[i] = 通过成交额 / 上市天数的硬过滤。资金费缺日 ⇒ 该日 ann 为 NaN(不猜、不补 0)。"""
    met = {}
    for s, a in um.items():
        ds = a["d"]
        n = len(ds)
        fd = fund.get(s) or {}
        ann0 = np.full(n, np.nan)
        ann1 = np.full(n, np.nan)
        first = dt.date.fromisoformat(ds[0])
        adv = C.adv30(a)
        elig_avg = np.zeros(n, bool)
        elig_sum = np.zeros(n, bool)
        for i in range(n):
            t = dt.date.fromisoformat(ds[i])
            if (t - first).days < MIN_LISTED_DAYS:
                continue
            av = adv[i]
            if np.isfinite(av):
                elig_avg[i] = av >= MIN_ADV30          # 读法 A:30 日「日均」成交额 ≥ $5M
                elig_sum[i] = av * 30.0 >= MIN_ADV30   # 读法 B:30 日「合计」成交额 ≥ $5M
            for lag, arr in ((0, ann0), (1, ann1)):
                ks = (2, 1, 0) if lag == 0 else (3, 2, 1)
                vals, ok = [], True
                for k in ks:
                    v = fd.get((t - dt.timedelta(days=k)).isoformat())
                    if v is None:
                        ok = False
                        break
                    vals.append(v)
                if ok:
                    arr[i] = float(np.mean(vals)) * 365.0
        met[s] = {"ann0": ann0, "ann1": ann1, "elig_avg": elig_avg, "elig_sum": elig_sum}
    return met


def eligible_no_funding(met: dict) -> int:
    """通过硬过滤但 3 日资金费算不出来的 (symbol, day) 数 —— 覆盖率缺口。"""
    n = 0
    for s, m in met.items():
        n += int((m["elig_avg"] & ~np.isfinite(m["ann0"])).sum())
    return n


def build_pools(um: dict, met: dict, ann_key: str, elig_key: str) -> dict:
    """对照池:某天所有合格(成交额/上市)且 3 日资金费年化 < 20% 的 (symbol, 下标)。排序保证可复算。"""
    pools: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for s, a in um.items():
        ann, elig = met[s][ann_key], met[s][elig_key]
        for i in np.where(elig & np.isfinite(ann) & (ann < THR_POOL))[0]:
            pools[a["d"][int(i)]].append((s, int(i)))
    return {k: sorted(v) for k, v in pools.items()}


def build_signals(um: dict, met: dict, ann_key: str, elig_key: str) -> tuple[list, dict]:
    """信号候选 + 冷却(同币 10 天内只取第一次)。返回 (候选列表, 漏斗计数)。"""
    funnel = {"eligible_symbol_days": 0, "crowd_ge_threshold": 0, "after_cooldown": 0}
    cands = []
    for s, a in um.items():
        ann, elig = met[s][ann_key], met[s][elig_key]
        idx = np.where(elig & np.isfinite(ann) & (ann >= THR_CROWD))[0]
        funnel["eligible_symbol_days"] += int(elig.sum())
        funnel["crowd_ge_threshold"] += int(len(idx))
        last = None
        keep = []
        for i in idx:
            t = dt.date.fromisoformat(a["d"][int(i)])
            if last is None or (t - last).days >= COOLDOWN_D:
                keep.append(int(i))
                last = t
        funnel["after_cooldown"] += len(keep)
        cands.extend((s, i) for i in keep)
    return cands, funnel


def make_tickets(um: dict, fund: dict, cands: list, ann_key: str, met: dict) -> list:
    tk = []
    for s, i in cands:
        t = C.short_ticket(um[s], i, S_STOP, N_HOLD, fund.get(s), symbol=s)
        if t is None:
            continue
        t["ann"] = float(met[s][ann_key][i])
        t["weekend"] = dt.date.fromisoformat(t["signal_d"]).weekday() >= 5
        t["price_part"] = t["ret"] - t["funding"]          # gross − cost
        tk.append(t)
    return tk


def btc_legs(um: dict, tickets: list) -> None:
    """对冲版:空 + 等名义多 BTC(同一进出窗口,价格腿;不加 BTC 资金费)。就地写 hedged_* 字段。"""
    a = um.get("BTC")
    if a is None:
        for t in tickets:
            t["hedged_ret"] = None
            t["hedged_r"] = None
        return
    idx_by_d = {d: i for i, d in enumerate(a["d"])}
    ds = a["d"]
    o = a["o"]

    def px(d: str):
        i = idx_by_d.get(d)
        if i is None:
            i = int(np.searchsorted(ds, d, side="right")) - 1
            if i < 0:
                return None
        return float(o[i])

    for t in tickets:
        p0, p1 = px(t["entry_d"]), px(t["exit_d"])
        if not p0 or not p1:
            t["hedged_ret"] = None
            t["hedged_r"] = None
            continue
        br = p1 / p0 - 1.0
        t["btc_ret"] = br
        t["hedged_ret"] = t["ret"] + br
        t["hedged_r"] = t["hedged_ret"] / t["risk"]


def payoff(tickets: list) -> dict:
    if not tickets:
        return {"n": 0}
    r = np.array([t["r"] for t in tickets])
    w, l = r[r > 0], r[r <= 0]
    return {"n": int(len(r)), "win_pct": round(float((r > 0).mean()) * 100, 2),
            "avg_win_r": round(float(w.mean()), 4) if len(w) else None,
            "avg_loss_r": round(float(l.mean()), 4) if len(l) else None,
            "payoff_ratio": round(float(w.mean() / abs(l.mean())), 3) if len(w) and len(l) and l.mean() != 0 else None}


def bucket_of(x: float) -> str:
    if x < 1.00:
        return "50-100%"
    if x < 2.00:
        return "100-200%"
    return ">200%"


def bucket_stats(tickets: list) -> dict:
    out = {}
    for name in ("50-100%", "100-200%", ">200%"):
        sel = [t for t in tickets if bucket_of(t["ann"]) == name]
        st = C.summary(sel) if sel else {"n": 0}
        st["mean_ann"] = round(float(np.mean([t["ann"] for t in sel])), 4) if sel else None
        st["mean_price_part"] = round(float(np.mean([t["price_part"] for t in sel])), 6) if sel else None
        st["mean_funding"] = round(float(np.mean([t["funding"] for t in sel])), 6) if sel else None
        st["payoff"] = payoff(sel)
        out[name] = st
    return out


def wk_stats(tickets: list) -> dict:
    we = [t for t in tickets if t["weekend"]]
    wd = [t for t in tickets if not t["weekend"]]
    return {"weekend": C.summary(we) if we else {"n": 0}, "weekday": C.summary(wd) if wd else {"n": 0}}


def decompose(tickets: list) -> dict:
    if not tickets:
        return {"n": 0}
    ret = np.array([t["ret"] for t in tickets])
    fnd = np.array([t["funding"] for t in tickets])
    return {"n": len(tickets),
            "mean_ret": round(float(ret.mean()), 6),
            "mean_price_part": round(float((ret - fnd).mean()), 6),
            "mean_funding_part": round(float(fnd.mean()), 6),
            "total_ret": round(float(ret.sum()), 4),
            "total_funding": round(float(fnd.sum()), 4),
            "mean_gross": round(float(np.mean([t["ret"] - t["funding"] + 2 * C.COST_SIDE for t in tickets])), 6),
            "mean_cost": round(2 * C.COST_SIDE, 6)}


def seg_report(tickets: list) -> dict:
    if not tickets:
        return {"n": 0}
    reasons: dict[str, int] = defaultdict(int)
    for t in tickets:
        reasons[t["why"]] += 1
    stopped = [t for t in tickets if t["why"] in ("stop", "stop_gap")]
    tot = float(np.sum([t["r"] for t in tickets])) or 1.0
    return {"summary": C.summary(tickets), "payoff": payoff(tickets), "decompose": decompose(tickets),
            "buckets": bucket_stats(tickets), "weekday_split": wk_stats(tickets),
            "symbols": len({t["symbol"] for t in tickets}),
            "still_open_at_data_end": int(sum(t["still"] for t in tickets)),
            "gap_stops": int(sum(t["gap"] for t in tickets)),
            "exit_reasons": dict(reasons),
            "stopped_n": len(stopped), "stopped_share_of_total_r": round(float(sum(t["r"] for t in stopped) / tot), 4),
            "stopped_mean_r": round(float(np.mean([t["r"] for t in stopped])), 4) if stopped else None,
            "time_exit_mean_r": round(float(np.mean([t["r"] for t in tickets if t["why"] == "time"])), 4)
            if any(t["why"] == "time" for t in tickets) else None,
            "worst5": [{"symbol": t["symbol"], "signal_d": t["signal_d"], "r": round(t["r"], 4),
                        "ann": round(t["ann"], 4), "why": t["why"]}
                       for t in sorted(tickets, key=lambda x: x["r"])[:5]]}


def money_seg(tickets: list, bars: dict, d_to: str):
    if not tickets:
        return None
    st = C.money(tickets, bars, d_to, f=0.005, cap=10)
    if not st:
        return None
    return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in st.items()}


# ── 段 1:发现段(先算完写盘)────────────────────────────────────────────────────────────────
def run_discovery(um, fund, met, ann_key, bars, use_chain: bool = True,
                  elig_key: str = "elig_avg") -> dict:
    cands, funnel = build_signals(um, met, ann_key, elig_key)
    tk = make_tickets(um, fund, cands, ann_key, met)
    if use_chain:
        tk = C.chain(tk)
    btc_legs(um, tk)
    disc = [t for t in tk if DISC[0] <= t["signal_d"] <= DISC[1]]

    pools = build_pools(um, met, ann_key, elig_key)

    def make(s, i):
        return C.short_ticket(um[s], i, S_STOP, N_HOLD, fund.get(s), symbol=s)

    null = C.null_same_day(disc, pools, make, draws=NULL_DRAWS, seed=SEED)
    boot_p = C.boot_months(disc, draws=BOOT_DRAWS, seed=SEED)
    m = float(np.mean([t["r"] for t in disc])) if disc else float("nan")
    q95 = float(np.quantile(null, 0.95)) if len(null) else float("nan")

    return {
        "window": list(DISC),
        "funnel": funnel,
        "tickets_chained": len(tk),
        "tickets": len(disc),
        "null_draws": NULL_DRAWS,
        "null_median_r": round(float(np.median(null)), 6) if len(null) else None,
        "null_q95_r": round(q95, 6),
        "null_pct_below_mean_r": round(float((null < m).mean()), 4) if len(null) else None,
        "mean_r": round(m, 6),
        "boot_p_le0": round(boot_p, 6),
        "pool_size_by_date": {d: len(v) for d, v in sorted(pools.items()) if d in {t["signal_d"] for t in disc}},
        "report": seg_report(disc),
        "money": money_seg(disc, bars, DISC[1]),
        "_null": null.tolist(),
        "ticket_rows": disc,
    }


# ── 段 2:留出段(发现段已写盘才打开)────────────────────────────────────────────────────────
def run_holdout(um, fund, met, ann_key, bars, use_chain: bool = True,
                elig_key: str = "elig_avg") -> dict:
    cands, _ = build_signals(um, met, ann_key, elig_key)
    tk = make_tickets(um, fund, cands, ann_key, met)
    if use_chain:
        tk = C.chain(tk)
    btc_legs(um, tk)
    hold = [t for t in tk if t["signal_d"] >= HOLD_FROM]
    d_to = max(max(a["d"]) for a in um.values())
    return {
        "window_from": HOLD_FROM,
        "window_to": d_to,
        "tickets": len(hold),
        "report": seg_report(hold),
        "money": money_seg(hold, bars, d_to),
        "ticket_rows": hold,
    }


def hedged_summary(tickets: list) -> dict:
    hs = [t for t in tickets if t.get("hedged_r") is not None]
    if not hs:
        return {"n": 0}
    r = np.array([t["hedged_r"] for t in hs])
    hr = np.array([t["hedged_ret"] for t in hs])
    by_y: dict[str, list[float]] = {}
    for t in hs:
        by_y.setdefault(t["signal_d"][:4], []).append(t["hedged_r"])
    return {"n": len(hs), "mean_hedged_r": round(float(r.mean()), 6), "mean_hedged_ret": round(float(hr.mean()), 6),
            "win_pct": round(float((r > 0).mean()) * 100, 2),
            "by_year": {y: (len(v), round(float(np.mean(v)), 4)) for y, v in sorted(by_y.items())}}


def run_lag1(um, fund, met, bars) -> dict:
    """稳健性:资金费窗口滞后一天(判据用 t−3..t−1)。主判据不动。"""
    disc = run_discovery(um, fund, met, "ann1", bars, elig_key="elig_avg")
    hold = run_holdout(um, fund, met, "ann1", bars, elig_key="elig_avg")
    disc.pop("ticket_rows", None)
    disc.pop("_null", None)
    hold.pop("ticket_rows", None)
    return {"note": "资金费窗口滞后一天(t−3..t−1),其余协议不变",
            "disc_n": disc["tickets"], "disc_mean_r": disc["mean_r"], "disc_boot_p": disc["boot_p_le0"],
            "null_q95": disc["null_q95_r"], "hold_n": hold["tickets"],
            "hold_mean_r": hold["report"].get("summary", {}).get("mean_r"),
            "disc_buckets": disc["report"].get("buckets"),
            "hold_buckets": hold["report"].get("buckets"),
            "disc_weekend": disc["report"].get("weekday_split"),
            "hold_weekend": hold["report"].get("weekday_split")}


def main() -> None:
    t_all0 = utcnow()
    print(f"[T-195] load start {t_all0}")
    um = C.load_um()
    fund = C.daily_funding(C.load_funding())
    met = build_metrics(um, fund)
    bars = C.nav_bars(um)
    d_to = max(max(a["d"]) for a in um.values())
    print(f"[T-195] um symbols={len(um)} funding symbols={len(fund)} last_day={d_to} "
          f"eligible-but-no-funding(sym-days)={eligible_no_funding(met)}")

    # ── 段 1:发现段
    disc = run_discovery(um, fund, met, "ann0", bars)
    disc_written = utcnow()
    payload = {
        "task": "T-195", "ledger": "S-681", "hypothesis": "H3 资金费拥挤", "lane": "lane-b",
        "protocol": {"signal": "3 UTC 日(t−2..t)资金费日合计的平均 × 365 ≥ 0.50", "min_adv30_usd": MIN_ADV30,
                     "min_listed_days": MIN_LISTED_DAYS, "cooldown_days": COOLDOWN_D, "stop": S_STOP,
                     "n_hold": N_HOLD, "control": "同日随机空:合格且 3 日资金费年化 < 0.20",
                     "discovery": list(DISC), "holdout_from": HOLD_FROM,
                     "criteria": ["①发现段平均R>0 且月块p<0.05", "②发现段平均R ≥ 对照95分位",
                                  "③留出段平均R>0", "④发现段票数 ≥ 50"],
                     "data_root": C.S681},
        "data": {"um_symbols": len(um), "funding_symbols": len(fund), "last_day": d_to},
        "stage_order": {"discovery_written_at": disc_written, "holdout_started_at": None},
        "discovery": disc, "holdout": None, "judge": None, "verdict": None,
    }
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1, default=float)
    print(f"[T-195] stage 1 done: discovery tickets={disc['tickets']} mean_r={disc['mean_r']} "
          f"boot_p={disc['boot_p_le0']} null_q95={disc['null_q95_r']} json_written={disc_written}")

    # ── 段 2:留出段(现在才打开)
    hold_started = utcnow()
    hold = run_holdout(um, fund, met, "ann0", bars)
    hold_written = utcnow()
    payload["stage_order"]["holdout_started_at"] = hold_started
    payload["stage_order"]["holdout_written_at"] = hold_written
    payload["holdout"] = hold

    disc_rows = disc["ticket_rows"]
    hold_rows = hold["ticket_rows"]
    j = C.judge(disc_rows, np.array(disc["_null"]), hold_rows)
    payload["judge"] = j
    payload["verdict"] = j["verdict"]
    payload["hedged"] = {"discovery": hedged_summary(disc_rows), "holdout": hedged_summary(hold_rows)}
    payload["robustness_lag1"] = run_lag1(um, fund, met, bars)
    d_nc = run_discovery(um, fund, met, "ann0", bars, use_chain=False, elig_key="elig_avg")
    h_nc = run_holdout(um, fund, met, "ann0", bars, use_chain=False, elig_key="elig_avg")
    payload["robustness_nochain"] = {
        "note": "只留「同币 10 天内只取第一次」冷却,不再套用不叠票(chain)",
        "disc_n": d_nc["tickets"], "disc_mean_r": d_nc["mean_r"], "disc_boot_p": d_nc["boot_p_le0"],
        "null_q95": d_nc["null_q95_r"], "hold_n": h_nc["tickets"],
        "hold_mean_r": h_nc["report"].get("summary", {}).get("mean_r"),
        "disc_money": d_nc.get("money"), "hold_money": h_nc.get("money")}
    d_vs = run_discovery(um, fund, met, "ann0", bars, elig_key="elig_sum")
    h_vs = run_holdout(um, fund, met, "ann0", bars, elig_key="elig_sum")
    payload["robustness_volsum"] = {
        "note": "「30 日成交额 ≥ $5M」读作 30 日合计(而不是日均);其余协议不变",
        "disc_n": d_vs["tickets"], "disc_mean_r": d_vs["mean_r"], "disc_boot_p": d_vs["boot_p_le0"],
        "null_q95": d_vs["null_q95_r"], "hold_n": h_vs["tickets"],
        "hold_mean_r": h_vs["report"].get("summary", {}).get("mean_r"),
        "disc_money": d_vs.get("money"), "hold_money": h_vs.get("money")}
    d_vs.pop("ticket_rows", None)
    d_vs.pop("_null", None)
    h_vs.pop("ticket_rows", None)
    d_nc.pop("ticket_rows", None)
    d_nc.pop("_null", None)
    h_nc.pop("ticket_rows", None)
    payload["data"]["symbols_without_funding"] = sum(1 for s in um if s not in fund)
    payload["data"]["eligible_sym_days_without_funding"] = eligible_no_funding(met)
    payload["tickets"] = {"discovery": disc_rows, "holdout": hold_rows}
    disc.pop("ticket_rows", None)
    disc.pop("_null", None)
    hold.pop("ticket_rows", None)
    with open(OUT_JSON, "w") as f:
        json.dump(payload, f, indent=1, default=float)
    print(f"[T-195] stage 2 done: holdout tickets={hold['tickets']} "
          f"mean_r={hold['report'].get('summary', {}).get('mean_r')}")

    # ── 汇总行
    print("=" * 100)
    print(f"判据 ①发现段 mean_r={j['1_mean_r']:+.4f} boot_p={j['1_p_le0']:.4f} → {'✓' if j['1_ok'] else '✗'}")
    print(f"判据 ②对照 null_median={j['2_null_median']:+.4f} q95={j['2_null_q95']:+.4f} "
          f"pct={j['2_pct']:.4f} → {'✓' if j['2_ok'] else '✗'}")
    print(f"判据 ③留出段 n={j['3_holdout_n']} mean_r={j['3_holdout_mean_r']:+.4f} → {'✓' if j['3_ok'] else '✗'}")
    print(f"判据 ④发现段票数 n={j['4_n']} → {'✓' if j['4_ok'] else '✗'}")
    print(f"判决 = {j['verdict']}")
    for nm, seg in (("发现段", disc), ("留出段", hold)):
        s = seg["report"].get("summary", {})
        d = seg["report"].get("decompose", {})
        mny = seg.get("money") or {}
        print(f"--- {nm} n={seg['tickets']} mean_r={s.get('mean_r')} win={s.get('win')} "
              f"fund_cov={s.get('funding_coverage')} price_part={d.get('mean_price_part')} "
              f"funding_part={d.get('mean_funding_part')} gaps={s.get('gaps')}")
        print(f"    钱曲线 f0.5% cap10: end={mny.get('end')} ann={mny.get('annualised')} mdd={mny.get('mdd')} "
              f"taken={mny.get('taken')} skipped={mny.get('skipped')} d0={mny.get('d0')} d1={mny.get('d1')}")
        for b, v in (seg["report"].get("buckets") or {}).items():
            print(f"    拥挤度 {b}: n={v.get('n')} mean_r={v.get('mean_r')} win={v.get('win')} "
                  f"price_part={v.get('mean_price_part')} funding={v.get('mean_funding')}")
        w = seg["report"].get("weekday_split") or {}
        print(f"    周末 n={w.get('weekend', {}).get('n')} mean_r={w.get('weekend', {}).get('mean_r')} | "
              f"工作日 n={w.get('weekday', {}).get('n')} mean_r={w.get('weekday', {}).get('mean_r')}")
        print(f"    出场 {seg['report'].get('exit_reasons')} 止损票 n={seg['report'].get('stopped_n')} "
              f"mean_r={seg['report'].get('stopped_mean_r')} 占总R={seg['report'].get('stopped_share_of_total_r')} "
              f"到期平仓 mean_r={seg['report'].get('time_exit_mean_r')} 币种数={seg['report'].get('symbols')}")
        print(f"    按年 {seg['report'].get('summary', {}).get('by_year')} p01_r={seg['report'].get('summary', {}).get('p01_r')} "
              f"worst={seg['report'].get('summary', {}).get('worst_r')} best={seg['report'].get('summary', {}).get('best_r')}")
    print(f"对冲版(空+等名义多BTC) 发现 mean_hedged_r={payload['hedged']['discovery'].get('mean_hedged_r')} "
          f"留出 mean_hedged_r={payload['hedged']['holdout'].get('mean_hedged_r')}")
    l1 = payload["robustness_lag1"]
    print(f"稳健性(资金费窗口滞后一天 t−3..t−1) 发现 mean_r={l1.get('disc_mean_r')} n={l1.get('disc_n')} "
          f"留出 mean_r={l1.get('hold_mean_r')} n={l1.get('hold_n')} null_q95={l1.get('null_q95')}")
    nc = payload["robustness_nochain"]
    print(f"稳健性(不叠票,只留 10 天冷却) 发现 mean_r={nc.get('disc_mean_r')} n={nc.get('disc_n')} "
          f"boot_p={nc.get('disc_boot_p')} null_q95={nc.get('null_q95')} "
          f"留出 mean_r={nc.get('hold_mean_r')} n={nc.get('hold_n')}")
    print(f"漏斗(发现段口径): {disc.get('funnel')} chained={disc.get('tickets_chained')} "
          f"无资金费的币={payload['data'].get('symbols_without_funding')}")
    vs = payload["robustness_volsum"]
    print(f"稳健性(30 日成交额=合计口径) 发现 mean_r={vs.get('disc_mean_r')} n={vs.get('disc_n')} "
          f"boot_p={vs.get('disc_boot_p')} null_q95={vs.get('null_q95')} "
          f"留出 mean_r={vs.get('hold_mean_r')} n={vs.get('hold_n')}")
    print(f"结果 json: {OUT_JSON}")


if __name__ == "__main__":
    main()
