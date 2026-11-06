"""T-269 —— S-746 预注册:「政治不明朗 × 边际流动性变差」触发时买 30 天 90% 看跌,对冲本身赚不赚钱。

口径**一字不改**照 REFUTATION_LEDGER S-746(2026-11-06 14:44 UTC):

  触发(只用 d 当天已知的):
    G_d = `macro:gpr` 过去 30 天均值,在其**过去 730 天(严格更早)**里的分位
    L_d = `stable_supply_30d` < 0 **或** `macro:fed_net_liquidity` 60 天变化 < 0
    触发 = G_d ≥ 0.80 **且** L_d 成立
    票不重叠:触发后开一张,30 天到期后才可再开
  动作:持有 BTC + 买 30 天、行权价 = 90% 现货的看跌;定价 = Black-Scholes,σ = d 日 DVOL/100,r = 0
  进场 = d 收盘(perp_bv_daily symbol=BTC),到期 = d + 30 收盘
  对冲盈亏 = 看跌到期价值 − 权利金(占进场现货 %)
  样本 2021-03-24(DVOL 首日)→ 最后一个已到期日
  判据(全满足才 ✅):(a) 平均对冲盈亏 > 0;(b) 随机对照 1,000 次(种子 746)实际均值 ≥ 对照 95 分位;
    (c) 两段(2021-03→2023-12 / 2024-01→)平均对冲盈亏同号且 > 0;(d) 触发票数 ≥ 15

本脚本口径决定(台账未写死处,取最自然读法,报告里逐条列明):
  · 「过去 30 天均值」= 日历窗 [d−29, d] 内已有 gpr 值的均值(缺日按实有值)。
  · 「分位」= 中秩经验分位:严格小于的个数 + 0.5×相等的个数,除以参照样本量;参照样本 = 日期在
    (d−730, d) 的 30 天均值(严格更早,不含 d 当天)。
  · 「60 天变化」= macro:fed_net_liquidity 在 d 与 (d−60 日历天当天或之前最近一条)之差。
  · 「30 天到期后才可再开」= 下一张票的进场日 ≥ 前一张的 d + 31(到期日之后)。
  · 随机对照的合格日池 = 样本期内**定价可行日**(DVOL 与 perp 收盘都在,且 d+30 已到期);层 = 同一年(默认)。

只算、不改代码、不入库。
"""
from __future__ import annotations

import json
import math
import os
import sys
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from data.evaluation.apparatus import (  # noqa: E402
    NoOpNull,
    null_distribution,
    percentile_of,
    random_dates_like,
)

# ── 预注册常量(不改) ────────────────────────────────────────────────────────
G_THRESH = 0.80
G_THRESH_HI = 0.90
LOOKBACK_M = 30          # G_d 的均值窗(天)
LOOKBACK_PCT = 730       # G_d 的参照窗(天)
HOLD_DAYS = 30           # 看跌持有期(天)
STRIKE = 0.90            # 行权价 = 90% 现货
VOL_SKEW = 0.09          # 副项:σ + 9 个波动点
N_NULL = 1000
SEED = 746
SAMPLE_LO = "2021-03-24"   # DVOL 首日
SEG1 = ("2021-03-24", "2023-12-31")
SEG2 = ("2024-01-01", "2026-12-31")

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")
H = {"apikey": KEY, "Authorization": f"Bearer {KEY}", "Prefer": "count=exact"}

CACHE = Path("/Volumes/CometCloudAI/cometcloud-local/research/t269_cache")
OUT = Path(__file__).resolve().parent


# ── 数据层(分页 + 缓存) ────────────────────────────────────────────────────
def pull(table: str, query: str) -> list[dict]:
    rows: list[dict] = []
    off = 0
    while True:
        req = urllib.request.Request(
            f"{URL}/rest/v1/{table}?{query}&limit=1000&offset={off}", headers=H)
        with urllib.request.urlopen(req, timeout=300) as r:
            body = json.loads(r.read().decode())
            cr = r.headers.get("content-range", "")
        rows.extend(body)
        total = int(cr.split("/")[-1]) if "/" in cr else -1
        off += len(body)
        if not body or total < 0 or off >= total:
            break
    return rows


def load(name: str, table: str, query: str) -> list[dict]:
    p = CACHE / f"{name}.json"
    if p.exists():
        rows = json.loads(p.read_text())
        print(f"  cache {name}: {len(rows)} rows")
        return rows
    rows = pull(table, query)
    CACHE.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(rows))
    print(f"  pulled {name}: {len(rows)} rows")
    return rows


# ── Black-Scholes put(σ=DVOL/100, r=0, q=0,无偏斜无价差 —— 写死的估算口径) ──
def bs_put(s: float, k: float, sigma: float, t: float) -> float:
    if sigma <= 0 or t <= 0 or s <= 0 or k <= 0:
        return float("nan")
    sq = sigma * math.sqrt(t)
    d1 = (math.log(s / k) + 0.5 * sigma * sigma * t) / sq
    d2 = d1 - sq
    N = lambda x: 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))
    return k * N(-d2) - s * N(-d1)   # put = K·N(−d2) − S·N(−d1)


def Ncdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


# ── 工具 ────────────────────────────────────────────────────────────────────
def d2date(d: str) -> date:
    return datetime.strptime(d[:10], "%Y-%m-%d").date()


def to_np_dates(ds: list[str]) -> np.ndarray:
    return np.array([d[:10] for d in ds], dtype="datetime64[D]")


def rolling_mean_calendar(dates: np.ndarray, vals: np.ndarray, win: int) -> np.ndarray:
    """对每个 i,取日历窗 [d_i − (win−1), d_i] 内已有值的均值。"""
    out = np.full(len(dates), np.nan)
    for i in range(len(dates)):
        lo = int(np.searchsorted(dates, dates[i] - np.timedelta64(win - 1, "D"), side="left"))
        seg = vals[lo:i + 1]
        if seg.size:
            out[i] = float(seg.mean())
    return out


def pct_rank(value: float, window: np.ndarray) -> float | None:
    """中秩经验分位:严格小于 + 0.5×相等,除以样本量。"""
    w = window[np.isfinite(window)]
    if w.size == 0:
        return None
    return float(((w < value).sum() + 0.5 * (w == value).sum()) / w.size)


def clean(o):
    """把 NaN/inf 与 numpy 标量洗成严格 JSON 可写的类型。"""
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, (list, tuple)):
        return [clean(v) for v in o]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        f = float(o)
        return f if math.isfinite(f) else None
    if isinstance(o, (np.str_,)):
        return str(o)
    return o


def stats(vals: list[float]) -> dict:
    a = np.array(vals, dtype=float)
    if a.size == 0:
        return {"n": 0}
    return {"n": int(a.size), "mean": float(a.mean()), "median": float(np.median(a)),
            "p05": float(np.percentile(a, 5)), "p25": float(np.percentile(a, 25)),
            "p75": float(np.percentile(a, 75)), "p95": float(np.percentile(a, 95)),
            "win": float((a > 0).mean()), "min": float(a.min()), "max": float(a.max()),
            "sum": float(a.sum())}


# ── 主流程 ──────────────────────────────────────────────────────────────────
def main() -> None:
    print("== 拉数据 ==")
    gpr_rows = load("gpr", "macro_daily", "select=d,value&series=eq.gpr&order=d.asc")
    epu_rows = load("epu", "macro_daily", "select=d,value&series=eq.epu&order=d.asc")
    fnl_rows = load("fnl", "macro_daily", "select=d,value&series=eq.fed_net_liquidity&order=d.asc")
    ss_rows = load("ss30", "state_daily",
                   "select=d,value&entity=eq.panel&feature=eq.stable_supply_30d&order=d.asc")
    dv_rows = load("dvol", "deriv_vol_daily", "select=d,dvol_close&currency=eq.BTC&order=d.asc")
    perp_rows = load("perp", "perp_bv_daily", "select=d,c&symbol=eq.BTC&order=d.asc")

    def series(rows: list[dict]) -> tuple[list[str], np.ndarray]:
        rs = [r for r in rows if r.get("value") is not None]
        rs.sort(key=lambda r: r["d"])
        return [r["d"][:10] for r in rs], np.array([float(r["value"]) for r in rs])

    G_dates, G_vals = series(gpr_rows)
    E_dates, E_vals = series(epu_rows)
    F_dates, F_vals = series(fnl_rows)
    S_dates, S_vals = series(ss_rows)
    G_np, E_np, F_np = to_np_dates(G_dates), to_np_dates(E_dates), to_np_dates(F_dates)

    DVOL = {r["d"][:10]: float(r["dvol_close"]) for r in dv_rows if r.get("dvol_close") is not None}
    PERP = {r["d"][:10]: float(r["c"]) for r in perp_rows if r.get("c") is not None}
    S_map = dict(zip(S_dates, S_vals))
    F_map = dict(zip(F_dates, F_vals))
    print(f"  gpr {len(G_dates)} | epu {len(E_dates)} | fnl {len(F_dates)} | ss30 {len(S_dates)} "
          f"| dvol {len(DVOL)} | perp {len(PERP)}")
    assert len(perp_rows) == len(PERP), "perp 有重复日期"

    # GPR / EPU 的 30 天滚动均值
    print("== 滚动均值 ==")
    G_mean = rolling_mean_calendar(G_np, G_vals, LOOKBACK_M)
    E_mean = rolling_mean_calendar(E_np, E_vals, LOOKBACK_M)

    def pct_series(mean: np.ndarray, dates: np.ndarray, d: str,
                   include_self: bool = False) -> float | None:
        """d 当天的 30 天均值,在 (d−730, d) 严格更早的均值分布里的中秩分位。

        d 当天无值(缺日)时取 ≤ d 的最近一条已有均值 —— 仍是「d 当天已知」的量。
        include_self=True 只给稳健性变体用(参照窗含 d 当天)。"""
        idx = int(np.searchsorted(dates, np.datetime64(d, "D"), side="right")) - 1
        if idx < 0 or not np.isfinite(mean[idx]):
            return None
        lo = int(np.searchsorted(dates, np.datetime64(d, "D") - np.timedelta64(LOOKBACK_PCT, "D"),
                                 side="right"))
        hi = idx + 1 if include_self else idx
        return pct_rank(float(mean[idx]), mean[lo:hi])

    def fnl_chg60(d: str) -> float | None:
        """fnl 在 d 与 (d−60 日历天当天或之前最近一条)之差。"""
        i = int(np.searchsorted(F_np, np.datetime64(d, "D"), side="right"))
        j = int(np.searchsorted(F_np, np.datetime64(d, "D") - np.timedelta64(60, "D"), side="right"))
        if i == 0 or j == 0:
            return None
        return float(F_vals[i - 1] - F_vals[j - 1])

    # ── 样本域与每日特征 ────────────────────────────────────────────────────
    print("== 每日特征 ==")
    perp_dates = sorted(PERP)
    G_set = set(G_dates)
    daily: list[dict] = []
    for d in perp_dates:
        if d < SAMPLE_LO:
            continue
        d30 = (d2date(d) + timedelta(days=HOLD_DAYS)).isoformat()
        if d30 not in PERP or d not in DVOL or d not in G_set:
            continue
        g = pct_series(G_mean, G_np, d)
        if g is None:
            continue
        ss = S_map.get(d)
        chg = fnl_chg60(d)
        l_ss = (ss is not None) and (ss < 0)
        l_fnl = (chg is not None) and (chg < 0)
        L = l_ss or l_fnl
        daily.append({"d": d, "G": g, "G_epu": pct_series(E_mean, E_np, d),
                      "ss30": ss, "fnl_chg60": chg, "L": bool(L),
                      "L_ss": bool(l_ss), "L_fnl": bool(l_fnl),
                      "dvol": DVOL.get(d), "close": PERP.get(d), "close30": PERP.get(d30),
                      "d30": d30})
    print(f"  样本域 {len(daily)} 天 {daily[0]['d']}→{daily[-1]['d']}")
    for lab, key in (("GPR", "G"), ("EPU", "G_epu")):
        v = [x[key] for x in daily if x[key] is not None]
        print(f"  {lab} 分位: n={len(v)} 均值={np.mean(v):.3f} "
              f"≥0.8 天数={sum(1 for x in v if x >= 0.8)} ≥0.9 天数={sum(1 for x in v if x >= 0.9)}")

    # ── 触发日 & 票(不重叠) ─────────────────────────────────────────────────
    def make_tickets(gmap: dict[str, float], lset: set[str], gthresh: float) -> list[dict]:
        tickets: list[dict] = []
        next_free = None
        for row in daily:
            if next_free is not None and row["d"] < next_free:
                continue
            g = gmap.get(row["d"])
            if g is None or g < gthresh or row["d"] not in lset:
                continue
            tickets.append(dict(row))
            next_free = (d2date(row["d"]) + timedelta(days=HOLD_DAYS + 1)).isoformat()
        return tickets

    GMAP = {x["d"]: x["G"] for x in daily if x["G"] is not None}
    GMAP_EPU = {x["d"]: x["G_epu"] for x in daily if x["G_epu"] is not None}
    LSET = {x["d"] for x in daily if x["L"]}

    tickets = make_tickets(GMAP, LSET, G_THRESH)
    trig_days = [x["d"] for x in daily if x["G"] is not None and x["G"] >= G_THRESH and x["L"]]
    print(f"  触发日 {len(trig_days)} 个 | 票(不重叠) {len(tickets)} 张")

    # ── 定价(照写死口径) ────────────────────────────────────────────────────
    def price(tk: dict, vol_skew: float = 0.0, kk: float = STRIKE) -> dict:
        s = tk["close"]
        sig = tk["dvol"] / 100.0 + vol_skew
        t = HOLD_DAYS / 365.0
        k = kk * s
        prem = bs_put(s, k, sig, t)
        sx = tk["close30"]
        payoff = max(0.0, k - sx)
        return {"entry": s, "exit": sx, "K": k, "sigma": sig, "premium": prem,
                "premium_pct": 100.0 * prem / s, "payoff": payoff,
                "payoff_pct": 100.0 * payoff / s,
                "pnl_pct": 100.0 * (payoff - prem) / s,
                "btc_pnl_pct": 100.0 * (sx - s) / s,
                "moneyness_pct": 100.0 * sx / s}

    for tk in tickets:
        tk.update(price(tk))
        tk["pnl_30pct"] = 100.0 * (tk["close30"] - tk["close"]) / tk["close"]
        # 触发后 30 天最大回撤
        i0 = perp_dates.index(tk["d"])
        path = [PERP[x] for x in perp_dates[i0:i0 + HOLD_DAYS + 1] if x in PERP]
        tk["mdd30_pct"] = 100.0 * min((p / tk["entry"] - 1.0) for p in path) if path else float("nan")

    # ── (a)(c)(d) ───────────────────────────────────────────────────────────
    pnls = [tk["pnl_pct"] for tk in tickets]
    a_mean = float(np.mean(pnls)) if pnls else float("nan")
    seg1 = [tk["pnl_pct"] for tk in tickets if SEG1[0] <= tk["d"] <= SEG1[1]]
    seg2 = [tk["pnl_pct"] for tk in tickets if SEG2[0] <= tk["d"] <= SEG2[1]]
    print(f"  (a) 平均对冲盈亏 {a_mean:.4f}% | (c) 段1 {np.mean(seg1) if seg1 else float('nan'):.4f}% "
          f"(n={len(seg1)}) 段2 {np.mean(seg2) if seg2 else float('nan'):.4f}% (n={len(seg2)}) "
          f"| (d) 票数 {len(tickets)}")

    # ── (b) 随机对照(apparatus.random_dates_like) ───────────────────────────
    print("== (b) 随机对照 ==")
    eligible = [x["d"] for x in daily]          # 定价可行日

    def control_eval(tk_list: list[dict], actual: float) -> dict:
        """对照:每张票换一个同年份的随机进场日(同样不重叠),1,000 次,种子 746。"""
        eligible_by_key = {i: eligible for i in range(len(tk_list))}
        events = [(i, tk["d"]) for i, tk in enumerate(tk_list)]

        def rep(rng) -> float:
            pending = list(events)
            assigned: dict[int, str] = {}
            last: dict[int, str] = {}
            for _ in range(500):
                if not pending:
                    break
                draws = random_dates_like(pending, eligible_by_key, rng)
                still = []
                for (key, _td), (_k, cd) in zip(pending, draws):
                    if cd is None:
                        still.append((key, _td))
                        continue
                    last[key] = cd
                    clash = any(abs((d2date(cd) - d2date(c2)).days) <= HOLD_DAYS
                                for _k2, c2 in assigned.items())
                    if clash:
                        still.append((key, _td))
                    else:
                        assigned[key] = cd
                pending = still
                if not pending:
                    break
            for key, _td in pending:             # 500 次仍未解决:用最后一次抽到的
                if key in last:
                    assigned[key] = last[key]
            vals = []
            for i in range(len(tk_list)):
                cd = assigned.get(i)
                if cd is None:
                    continue
                d30 = (d2date(cd) + timedelta(days=HOLD_DAYS)).isoformat()
                vals.append(price({"close": PERP[cd], "close30": PERP.get(d30),
                                   "dvol": DVOL[cd]})["pnl_pct"])
            return float(np.mean(vals)) if vals else float("nan")

        try:
            null = null_distribution(rep, N_NULL, SEED, actual=actual)
        except NoOpNull as e:
            return {"n_null": N_NULL, "seed": SEED, "error": str(e), "pass": None}
        p95 = float(np.percentile(null, 95))
        return {"n_null": N_NULL, "seed": SEED,
                "null_p05": float(np.percentile(null, 5)), "null_p50": float(np.percentile(null, 50)),
                "null_p95": p95, "null_min": float(null.min()), "null_max": float(null.max()),
                "actual": actual, "actual_percentile": percentile_of(actual, null),
                "pass": bool(actual >= p95)}

    ctrl = control_eval(tickets, a_mean)
    null, p95, b_pct, b_pass = (ctrl.get("null_p05"), ctrl.get("null_p95"),
                                ctrl.get("actual_percentile"), ctrl.get("pass"))
    if ctrl.get("error"):
        print(f"  零分布失效: {ctrl['error']}")
    else:
        print(f"  对照均值: p05={ctrl['null_p05']:.4f} p50={ctrl['null_p50']:.4f} "
              f"p95={ctrl['null_p95']:.4f} | 实际 {a_mean:.4f} | 实际分位 {b_pct:.4f} "
              f"| (b) {'过' if b_pass else '不过'}")

    verdicts = {"a_mean_gt0": bool(a_mean > 0), "b_ge_p95": b_pass,
                "c_both_segments_pos": bool(seg1 and seg2 and np.mean(seg1) > 0 and np.mean(seg2) > 0),
                "d_n_ge15": bool(len(tickets) >= 15)}
    all_pass = all(verdicts.values())
    print(f"  判据 {verdicts} ⇒ {'✅ 通过' if all_pass else '❌ 未通过'}")

    # ── 副项(只报不判) ──────────────────────────────────────────────────────
    print("== 副项(只报不判) ==")
    sub: dict = {}

    # S1 EPU 代替 GPR
    epu_tickets = make_tickets(GMAP_EPU, LSET, G_THRESH)
    for tk in epu_tickets:
        tk.update(price(tk))
    epu_pnls = [tk["pnl_pct"] for tk in epu_tickets]
    sub["epu_instead_of_gpr"] = {
        "n_tickets": len(epu_tickets), "mean_pnl_pct": float(np.mean(epu_pnls)) if epu_pnls else None,
        "stats": stats(epu_pnls),
        "note": "epu 只从 2018-01-02 起,分位参照窗在 2021-03 之后已满 730 天"}

    # S2 G ≥ 0.9
    t90 = make_tickets(GMAP, LSET, G_THRESH_HI)
    for tk in t90:
        tk.update(price(tk))
    p90v = [tk["pnl_pct"] for tk in t90]
    sub["g_ge_0.9"] = {"n_tickets": len(t90), "mean_pnl_pct": float(np.mean(p90v)) if p90v else None,
                       "stats": stats(p90v)}

    # S3 看跌加 9 个波动点
    sk_pnls = []
    for tk in tickets:
        sk_pnls.append(price(tk, vol_skew=VOL_SKEW)["pnl_pct"])
    sub["put_vol_plus_9pts"] = {"n": len(sk_pnls), "mean_pnl_pct": float(np.mean(sk_pnls)) if sk_pnls else None,
                                "stats": stats(sk_pnls)}

    # S4 90/80 看跌价差(熊式 + 牛式,方向规格未写 → 两个都报)
    bear, bull = [], []
    for tk in tickets:
        s, sx, dv = tk["close"], tk["close30"], tk["dvol"]
        sig, t = dv / 100.0, HOLD_DAYS / 365.0
        p9 = bs_put(s, 0.9 * s, sig, t)
        p8 = bs_put(s, 0.8 * s, sig, t)
        y9 = max(0.0, 0.9 * s - sx)
        y8 = max(0.0, 0.8 * s - sx)
        bear.append(100.0 * ((y9 - y8) - (p9 - p8)) / s)
        bull.append(100.0 * ((p9 - p8) - (y9 - y8)) / s)
    sub["put_spread_90_80"] = {"bear": stats(bear), "bull": stats(bull),
                               "note": "熊式=买90卖80;牛式=卖90买80(方向规格未写,两个都报)"}

    # S5 触发日 vs 非触发日 之后 30 天 BTC 收益 / 最大回撤
    def fwd_profile(d: str) -> tuple[float, float] | None:
        i0 = perp_dates.index(d)
        path = [PERP[x] for x in perp_dates[i0:i0 + HOLD_DAYS + 1] if x in PERP]
        if len(path) < 2:
            return None
        e = path[0]
        return 100.0 * (path[-1] - e) / e, 100.0 * min(p / e - 1.0 for p in path)

    trig_set = set(trig_days)
    tr_prof = [fwd_profile(d) for d in trig_days]
    tr_prof = [x for x in tr_prof if x]
    nt_prof = [fwd_profile(x["d"]) for x in daily if x["d"] not in trig_set]
    nt_prof = [x for x in nt_prof if x]
    sub["btc_30d_after"] = {
        "trigger_days": {"n": len(tr_prof), "ret": stats([x[0] for x in tr_prof]),
                         "mdd": stats([x[1] for x in tr_prof])},
        "non_trigger_days": {"n": len(nt_prof), "ret": stats([x[0] for x in nt_prof]),
                             "mdd": stats([x[1] for x in nt_prof])},
        "note": "触发日 = 所有满足 G≥0.8 且 L 的日子(不含不重叠约束);非触发日 = 样本域其余日子"}

    # S6 「赚到目标就撤」:看跌价值 ≥ 2 × 权利金当天平仓
    tgt_pnls, tgt_hits, tgt_days = [], 0, []
    for tk in tickets:
        prem = tk["premium"]
        i0 = perp_dates.index(tk["d"])
        hit_i = None
        for j in range(i0, min(i0 + HOLD_DAYS, len(perp_dates))):
            dd = perp_dates[j]
            rem = (d2date(tk["d30"]) - d2date(dd)).days
            if rem <= 0:
                break
            v = bs_put(PERP[dd], tk["K"], DVOL[dd] / 100.0, rem / 365.0)
            if v >= 2.0 * prem:
                hit_i = j
                break
        if hit_i is None:
            continue
        dd = perp_dates[hit_i]
        rem = (d2date(tk["d30"]) - d2date(dd)).days
        v = bs_put(PERP[dd], tk["K"], DVOL[dd] / 100.0, max(rem, 1) / 365.0)
        tgt_pnls.append(100.0 * (v - prem) / tk["entry"])
        tgt_hits += 1
        tgt_days.append((d2date(dd) - d2date(tk["d"])).days)
    sub["take_profit_2x_premium"] = {
        "n_hit": tgt_hits, "n_tickets": len(tickets), "mean_pnl_pct": float(np.mean(tgt_pnls)) if tgt_pnls else None,
        "stats": stats(tgt_pnls), "days_to_hit": stats(tgt_days) if tgt_days else {"n": 0},
        "note": "逐日用当日 DVOL 与剩余期限重估;看跌价值 ≥ 2×权利金即按当日收盘平仓"}

    # ── 稳健性变体(只报不判;口径偏离主口径之处逐条标注) ────────────────────
    print("== 稳健性变体 ==")
    var: dict = {}

    # R1 进场挪一天:信号在 d,进场/到期都挪到 d+1 / d+31(S-665「只在当天成立的不算」的检查)
    r1 = []
    for tk in tickets:
        d1 = (d2date(tk["d"]) + timedelta(days=1)).isoformat()
        d31 = (d2date(tk["d"]) + timedelta(days=HOLD_DAYS + 1)).isoformat()
        if d1 not in PERP or d31 not in PERP or d1 not in DVOL:
            continue
        r1.append(price({"close": PERP[d1], "close30": PERP[d31], "dvol": DVOL[d1]})["pnl_pct"])
    var["entry_shifted_1d"] = {"n": len(r1), "mean_pnl_pct": float(np.mean(r1)) if r1 else None,
                               "stats": stats(r1),
                               "note": "进场=d+1 收盘,到期=d+31 收盘,σ 用 d+1 的 DVOL;主口径是 d 收盘"}

    # R2 G_d 参照窗含 d 当天(偏离「严格更早」)
    gmap_self = {x["d"]: pct_series(G_mean, G_np, x["d"], include_self=True) for x in daily}
    gmap_self = {k: v for k, v in gmap_self.items() if v is not None}
    t_r2 = make_tickets(gmap_self, LSET, G_THRESH)
    r2 = [price(tk)["pnl_pct"] for tk in t_r2]
    var["g_pct_window_includes_self"] = {
        "n_tickets": len(t_r2), "mean_pnl_pct": float(np.mean(r2)) if r2 else None, "stats": stats(r2),
        "note": "参照窗改成 (d−730, d],含 d 当天;主口径是严格更早"}

    # R3 fnl 的「60 天变化」按 60 个观测(而非 60 个日历天)
    def fnl_chg60_obs(d: str) -> float | None:
        i = int(np.searchsorted(F_np, np.datetime64(d, "D"), side="right")) - 1
        j = i - 60
        if i < 0 or j < 0:
            return None
        return float(F_vals[i] - F_vals[j])
    lset_r3 = set()
    for x in daily:
        ss = x["ss30"]
        chg = fnl_chg60_obs(x["d"])
        if (ss is not None and ss < 0) or (chg is not None and chg < 0):
            lset_r3.add(x["d"])
    t_r3 = make_tickets(GMAP, lset_r3, G_THRESH)
    r3 = [price(tk)["pnl_pct"] for tk in t_r3]
    var["fnl_60obs_instead_of_60cal"] = {
        "n_tickets": len(t_r3), "mean_pnl_pct": float(np.mean(r3)) if r3 else None, "stats": stats(r3),
        "note": "fnl 60 天变化改按 60 个观测回溯;主口径按 60 个日历天"}

    # 数据性质:GPR 序列是否阶梯(日频 vs 月频前推)
    yr = G_dates[-365:]
    yr_idx = [G_dates.index(x) for x in yr if x in set(G_dates)]
    diffs = np.abs(np.diff(G_vals[yr_idx])) if len(yr_idx) > 1 else np.array([0.0])
    var["gpr_series_nature"] = {
        "n_rows": len(G_dates), "rows_per_year_last": len(yr),
        "median_abs_day_change_last_year": float(np.median(diffs)),
        "frac_zero_change_last_year": float((diffs < 1e-12).mean()),
        "note": "若日间变动近乎为 0 → 是月频/周频前推,30 天均值近似常量 ⇒ 分位是阶梯状排序"}

    # L_d 两支各贡献多少「L 成立日」/ 多少触发日 / 多少票
    var["l_branch_split"] = {
        "L_days_ss_only": sum(1 for x in daily if x["L"] and x["L_ss"] and not x["L_fnl"]),
        "L_days_fnl_only": sum(1 for x in daily if x["L"] and x["L_fnl"] and not x["L_ss"]),
        "L_days_both": sum(1 for x in daily if x["L"] and x["L_ss"] and x["L_fnl"]),
        "L_days_total": sum(1 for x in daily if x["L"]),
        "sample_days_total": len(daily),
        "trigger_days_ss_only": sum(1 for x in daily if x["L"] and x["L_ss"] and not x["L_fnl"]
                                    and x["G"] is not None and x["G"] >= G_THRESH),
        "trigger_days_fnl_only": sum(1 for x in daily if x["L"] and x["L_fnl"] and not x["L_ss"]
                                     and x["G"] is not None and x["G"] >= G_THRESH),
        "trigger_days_both": sum(1 for x in daily if x["L"] and x["L_ss"] and x["L_fnl"]
                                 and x["G"] is not None and x["G"] >= G_THRESH),
        "tickets_ss_branch": sum(1 for tk in tickets if tk["L_ss"]),
        "tickets_fnl_branch": sum(1 for tk in tickets if tk["L_fnl"]),
    }

    # R4 「30 天到期后才可再开」的两种读法:下一张票 ≥ d+31(主口径)vs ≥ d+30(到期日当天就能开)
    def make_tickets_gap(gmap: dict[str, float], lset: set[str], gthresh: float, gap: int) -> list[dict]:
        out, next_free = [], None
        for row in daily:
            if next_free is not None and row["d"] < next_free:
                continue
            g = gmap.get(row["d"])
            if g is None or g < gthresh or row["d"] not in lset:
                continue
            out.append(dict(row))
            next_free = (d2date(row["d"]) + timedelta(days=gap)).isoformat()
        return out
    t_r4 = make_tickets_gap(GMAP, LSET, G_THRESH, HOLD_DAYS)
    r4 = [price(tk)["pnl_pct"] for tk in t_r4]
    r4_mean = float(np.mean(r4)) if r4 else float("nan")
    var["next_ticket_allowed_at_d_plus_30"] = {
        "n_tickets": len(t_r4), "mean_pnl_pct": r4_mean, "stats": stats(r4),
        "dates": [tk["d"] for tk in t_r4],
        "control": control_eval(t_r4, r4_mean),
        "note": "主口径是下一张 ≥ d+31(到期日之后);本变体允许到期日当天就开下一张"}
    sub["robustness_variants"] = var
    for k, v in var.items():
        print(f"  {k}: {v.get('n_tickets', v.get('n', ''))} → {v.get('mean_pnl_pct')}")

    # 末尾样本域的当前状态(供报告与情景文件用)
    cur = []
    for x in daily[-10:]:
        pr = price(x)
        cur.append({"d": x["d"], "G": x["G"], "G_epu": x["G_epu"], "ss30": x["ss30"],
                    "fnl_chg60": x["fnl_chg60"], "L_ss": x["L_ss"], "L_fnl": x["L_fnl"],
                    "L": x["L"], "is_trigger": bool(x["G"] is not None and x["G"] >= G_THRESH and x["L"]),
                    "dvol": x["dvol"], "close": x["close"], "prem90_pct": pr["premium_pct"]})
    print(f"  末 10 天当前状态: " + " | ".join(
        f"{c['d']} G={c['G']:.3f} L={'Y' if c['L'] else 'N'} prem={c['prem90_pct']:.2f}%"
        for c in cur))

    # ── 输出 ────────────────────────────────────────────────────────────────
    res = {
        "task": "T-269", "ledger": "S-746", "run_at": datetime.now().isoformat(timespec="seconds"),
        "sample": {"lo": daily[0]["d"], "hi": daily[-1]["d"], "n_days": len(daily),
                   "eligible_pool": len(eligible)},
        "data_rows": {"gpr": len(G_dates), "epu": len(E_dates), "fnl": len(F_dates),
                      "ss30": len(S_dates), "dvol": len(DVOL), "perp": len(PERP)},
        "trigger": {"g_thresh": G_THRESH, "n_trigger_days": len(trig_days), "n_tickets": len(tickets)},
        "tickets": [{k: (float(v) if isinstance(v, (int, float)) and not isinstance(v, bool)
                          else (v.isoformat() if isinstance(v, date) else v))
                      for k, v in tk.items()} for tk in tickets],
        "criteria": {
            "a": {"mean_pnl_pct": a_mean, "stats": stats(pnls), "pass": verdicts["a_mean_gt0"]},
            "b": {"n_null": N_NULL, "seed": SEED,
                  "null_p05": ctrl.get("null_p05"), "null_p50": ctrl.get("null_p50"),
                  "null_p95": ctrl.get("null_p95"), "null_min": ctrl.get("null_min"),
                  "null_max": ctrl.get("null_max"),
                  "actual": a_mean, "actual_percentile": b_pct, "pass": b_pass,
                  "error": ctrl.get("error")},
            "c": {"seg1": {"range": list(SEG1), "n": len(seg1), "mean_pnl_pct": float(np.mean(seg1)) if seg1 else None},
                  "seg2": {"range": list(SEG2), "n": len(seg2), "mean_pnl_pct": float(np.mean(seg2)) if seg2 else None},
                  "pass": verdicts["c_both_segments_pos"]},
            "d": {"n_tickets": len(tickets), "pass": verdicts["d_n_ge15"]},
            "all_pass": all_pass,
        },
        "sub_items": sub,
        "current_state": cur,
    }
    out_json = OUT / "t269_results.json"
    out_json.write_text(json.dumps(clean(res), ensure_ascii=False, indent=2, default=str))
    print(f"  → {out_json}")
    print(f"  结论: {'✅ 通过' if all_pass else '❌ 未通过'}")


if __name__ == "__main__":
    main()
