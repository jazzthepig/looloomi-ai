#!/usr/bin/env python3
"""T-361 —— S-835 准入表:坟场里有曲线的族统一过一遍(S-681 H2 / H4、S-808、S-810、S-642、S-736、World50 回放)。

口径(全部照台账 S-835 的登记,账户照 S-834 的体检):
  账户 = RB(加密 / 股 / 金,flex_alloc.rb_weights)+ 现金 + R-v2(t352_engine.simulate(fix=True),
          每票 0.75% / 上限 0.80 / 名额 10)—— 与 docs/research/s834_diversification_audit.py 逐字同一套;
          动手前先对上「年化 +35.7%、R-v2 风险占比 0.742」。
  族   = T-348 的装配(t348_r3.py)产出的独立袖套净值(t348_r3_families.csv);
          World50 = docs/research/t099_world50_replay.py 的 EWxMom 臂(月频 → 按日历日铺到共同日)。
  尺寸 = 二分,调到该族自己的边际风险贡献 = 账户月度方差的 10%(w=1 时 rc→1,单调;二分即可)。
  窗口 = A:max(族的首个进场日, 2021-10-11);B:2021-10-11 起(T-348 同口径;A=B 时第 (iv) 条退化,表里注明)。
  零分布 = apparatus.circular_shift(族的日收益序列, block 1, 500 次)—— 拆开族与账户的对齐;
          统计量 = 族进账户后账户年化的变化(实际对齐 vs 500 种错位对齐)。

用法(仓库根):python3 docs/research/t361_admission_table.py
产物:docs/research/t361_results.json(全部数) + docs/research/T-361_admission_table.md(表)
只读:不写库、不改任何既有文件。
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import warnings

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")
HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, REPO)
R = "/Volumes/CometCloudAI/cometcloud-local/research/"

import t310_slots as T310                                     # noqa: E402
from src.data.evaluation import apparatus as ap              # noqa: E402
from src.data.universe import flex_alloc as fa               # noqa: E402

T310.UM = R + "s681/_um_daily.jsonl"
T310.STYLE = R + "t156/_style.json"
OUT_JSON = os.path.join(HERE, "t361_results.json")
OUT_MD = os.path.join(HERE, "T-361_admission_table.md")

START = pd.Timestamp("2021-10-11")
F_, CAP_, N_ = 0.0075, 0.80, 10          # S-831 真钱现配置:每票 0.75% / 上限 0.80 / 名额 10
SRC = ["crypto", "equity", "gold", "rv2", "cash"]
TARGET_RC = 0.10                         # S-835:族自己的风险贡献占账户 10%
N_NULL = 500                             # S-835:circular_shift 500 次
SEED = 361
FEB = ("2023-02-08", "2023-03-08")        # 卡里点名的那段
FAM_ORDER = ["S681_H2", "S681_H4", "S808", "S810", "S642", "S736_fixed", "S736_published", "World50_EWxMom"]
FAM_LABEL = {
    "S681_H2": "S-681 H2(pump fade)",
    "S681_H4": "S-681 H4(熊市反弹失败)",
    "S808": "S-808(被挤之后 · T-332)",
    "S810": "S-810(被挤之后 · T-334)",
    "S642": "S-642(空头臂 · T-159)",
    "S736_fixed": "S-736(战术空单 · 记账修正版)",
    "S736_published": "S-736(战术空单 · 原始记账)",
    "World50_EWxMom": "World50 回放(EW×Mom)",
}


def _mod(name: str, path: str):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


E1 = _mod("t352_engine", os.path.join(HERE, "t352_engine.py"))
S823 = _mod("s823", os.path.join(HERE, "s823_three_state.py"))


def log(msg: str) -> None:
    print(msg, flush=True)


# ── 月份网格(向量化:零分布要跑 500 次 × 每族 × 每窗)────────────────────────
class MonthGrid:
    def __init__(self, idx: pd.DatetimeIndex):
        per = idx.to_period("M").to_numpy()
        change = np.where(per[1:] != per[:-1])[0] + 1
        self.bounds = np.concatenate([[0], change, [len(per)]])
        self.labels = [str(p) for p in pd.PeriodIndex(per, freq="M").unique()]

    def comp(self, r: np.ndarray) -> np.ndarray:
        """月内复利 → 月收益。"""
        return np.expm1(np.add.reduceat(np.log1p(r), self.bounds[:-1]))

    def summ(self, r: np.ndarray) -> np.ndarray:
        """月内加总(贡献口径,同 S-834 的 C[k].resample('M').sum())。"""
        return np.add.reduceat(r, self.bounds[:-1])


def cagr_from_monthly(m: np.ndarray, years: float) -> float:
    if years <= 0 or not len(m):
        return float("nan")
    return float(np.prod(1.0 + m) ** (1.0 / years) - 1.0)


def cagr_from_daily(r: pd.Series) -> float:
    yrs = (r.index[-1] - r.index[0]).days / 365.25
    if yrs <= 0:
        return float("nan")
    return float((1.0 + r).prod() ** (1.0 / yrs) - 1.0)


# ── 账户(照 s834_diversification_audit.py 的做法)────────────────────────────
def build_account() -> dict:
    d = pd.read_csv(os.path.join(HERE, "t342_daily.csv"), parse_dates=["date"]).set_index("date")
    legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
    cal = pd.date_range(d.index[0], d.index[-1], freq="D")
    cash_rate = d.cash_daily_rate.reindex(cal).ffill().fillna(0.0)
    raw, _ = T310.load_tickets()
    bars = T310.load_bars({t["symbol"] for t in raw})
    exits, _ = T310.classify_exits(raw, bars)
    TK = T310.to_engine_tickets(raw, exits)
    gate_d, _, _ = T310.load_gate()
    res = E1.simulate(TK, bars, gate_d, CAP_, equity0=630.0, risk_frac=F_, cap_n=N_, fix=True)
    rv2 = pd.Series({pd.Timestamp(r[0]): float(r[1]) for r in res["curve"]}).sort_index().pct_change().dropna()
    df = pd.concat(legs_px, axis=1).dropna().sort_index()
    rets = df.pct_change()
    idx = [x for x in df.index if x >= START]
    tgt = pd.Series(fa.rb_weights(rets.loc[:idx[0]].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
    hold = tgt.copy()
    rows, nav = [], 1.0
    between = fa._between
    for i, day in enumerate(idx[1:], start=1):
        row = rets.loc[day, list(fa.LEGS)]
        prev = idx[i - 1]
        c = {k: float(hold[k] * row[k]) for k in fa.LEGS}
        c["cash"] = (1.0 - float(hold.sum())) * between(cash_rate, prev, day)
        c["rv2"] = between(rv2, prev, day)
        g = sum(c.values())
        nav *= 1 + g
        hold = hold * (1 + row) / (1 + g)
        if i % 21 == 0:
            new = pd.Series(fa.rb_weights(rets.loc[:day].iloc[1:])).reindex(list(fa.LEGS)).fillna(0.0)
            cost = float((hold - new).abs().sum()) * 20 / 1e4
            nav *= 1 - cost
            c["cost"] = -cost
            hold = new.copy()
        rows.append({"d": day, **c, "acct": g + c.get("cost", 0.0), "nav": nav})
    C = pd.DataFrame(rows).set_index("d").fillna(0.0)
    core = d.core_nav_1_cap_pit24.reindex(C.index).pct_change().fillna(0.0)
    return {"C": C, "idx": idx, "core": core, "rv2": rv2, "cal": cal, "core_daily": d}


def account_stats(C: pd.DataFrame) -> dict:
    SRC5 = list(SRC)
    Cm = pd.DataFrame({k: C[k].resample("M").sum() for k in SRC5})
    Am = (1 + C["acct"]).resample("M").prod() - 1
    rc = {k: float(np.cov(Cm[k], Am)[0, 1] / Am.var()) for k in SRC5}
    return {
        "cagr": cagr_from_daily(C["acct"]),
        "months": int(len(Am)),
        "risk_contribution": rc,
        "rv2_risk_share": rc["rv2"],
        "eff_sources": float(np.exp(-sum(x * np.log(x) for x in
                                          (np.clip(list(rc.values()), 1e-9, None) / max(sum(rc.values()), 1e-12))))),
        "worst_month": [str(Am.idxmin().date()), float(Am.min())],
        "Cm": Cm, "Am": Am,
    }


# ── 族曲线 → 账户共同日上的日收益 ───────────────────────────────────────────
def nav_to_account_ret(nav: pd.Series, acct_idx: list) -> pd.Series:
    """族的独立袖套净值 → 账户共同日上的日收益(两共同日之间按 flex_alloc._between 复利)。"""
    cal = pd.date_range(nav.index[0], nav.index[-1], freq="D")
    r = nav.reindex(cal).ffill().pct_change().fillna(0.0)
    out = [fa._between(r, acct_idx[i - 1], acct_idx[i]) for i in range(1, len(acct_idx))]
    return pd.Series(out, index=acct_idx[1:])


def monthly_to_account_ret(monthly: dict, acct_idx: list) -> pd.Series:
    """月频族的月度收益 → 日频:每月按日历日均摊 ((1+r_m)^(1/该月日历天数) − 1),
    再按 flex_alloc._between 落到账户共同日(账户只吃到跨进该月的那几天)。"""
    cal = pd.date_range(acct_idx[0] - pd.Timedelta(days=40), acct_idx[-1], freq="D")
    per = cal.to_period("M")
    days_in = per.map(lambda p: p.days_in_month).to_numpy()
    r_cal = np.zeros(len(cal))
    for i, p in enumerate(per):
        key = str(p)
        rm = monthly.get(key)
        if rm is None:
            continue
        r_cal[i] = (1.0 + float(rm)) ** (1.0 / days_in[i]) - 1.0
    r = pd.Series(r_cal, index=cal)
    out = [fa._between(r, acct_idx[i - 1], acct_idx[i]) for i in range(1, len(acct_idx))]
    return pd.Series(out, index=acct_idx[1:])


def load_families(acct_idx: list) -> dict:
    df = pd.read_csv(os.path.join(HERE, "t348_r3_families.csv"), parse_dates=["d"])
    meta = json.load(open(os.path.join(HERE, "t348_r3_families_meta.json")))
    out: dict = {}
    for k, m in meta.items():
        nav = df[df["family"] == k].set_index("d")["nav"].astype(float).sort_index()
        nav.index = pd.to_datetime(nav.index)
        out[k] = {"ret": nav_to_account_ret(nav, acct_idx), "meta": m, "nav": nav}
    return out


def load_world50(rep_path: str, acct_idx: list) -> dict:
    rep = json.load(open(rep_path))
    w50_m = monthly_ret_from_replay(rep, "EWxMom")
    return {"ret": monthly_to_account_ret(w50_m, acct_idx),
            "meta": {"first_entry": str(min(w50_m)) if w50_m else str(START.date()),
                     "note": "本机 w50_daily 重建面板 · 价格收益(不含股息);S-581 私有面板为总收益,EW 17.4%/EW×Mom 18.0%"},
            "nav": None}


# ── 核心:一族一窗的准入四条的数 ─────────────────────────────────────────────
def window_metrics(acct: dict, fam_r: pd.Series, w: float, a, b, stress_flags: dict, active_start) -> dict:
    C = acct["C"]
    idx = C.index
    m = (idx >= a) & (idx <= b)
    rb = C["acct"][m]
    rf = fam_r.reindex(idx)[m]
    if len(rb) < 60:
        return {"ok": False, "n_days": int(len(rb))}
    g = MonthGrid(rb.index)
    rb_a, rf_a = rb.to_numpy(), rf.to_numpy()
    ra = (1 - w) * rb_a + w * rf_a
    A = g.comp(ra)                       # 叠加后的账户月收益
    Fw = g.summ(w * rf_a)                # 族对账户的月贡献(加总口径)
    Cm_base = {k: g.summ((1 - w) * C[k][m].to_numpy()) for k in SRC}
    Rv2m = Cm_base["rv2"]
    labels = g.labels
    st = np.array([bool(stress_flags.get(l, False)) for l in labels])

    def corr(x, y, sel=None):
        if sel is not None:
            x, y = x[sel], y[sel]
        if len(x) < 4 or np.std(x) == 0 or np.std(y) == 0:
            return float("nan")
        return float(np.corrcoef(x, y)[0, 1])

    # 风险贡献(叠加后的账户为分母)
    contrib = dict(Cm_base)
    contrib["fam"] = Fw
    rc = {k: float(np.cov(v, A)[0, 1] / A.var()) for k, v in contrib.items()}
    tot = sum(rc.values())
    eff = float(np.exp(-sum((x / tot) * np.log(x / tot) for x in rc.values() if x > 0)))
    # 基线:不加族时的有效来源数(同一窗口)
    A_base = g.comp(rb_a)
    rc_base = {k: float(np.cov(g.summ(C[k][m].to_numpy()), A_base)[0, 1] / A_base.var()) for k in SRC}
    tb = sum(rc_base.values())
    eff_base = float(np.exp(-sum((x / tb) * np.log(x / tb) for x in rc_base.values() if x > 0)))

    # 最差 20 日
    def worst20(x):
        s = pd.Series(x, index=rb.index)
        return float(((1 + s).rolling(20).apply(np.prod) - 1).min())

    w20_base, w20_aug = worst20(rb_a), worst20(ra)

    # (ii) 零分布:把族的日收益整体错位,账户年化会怎样
    i0 = int(np.searchsorted(rb.index.to_numpy(), np.datetime64(active_start), side="left")) if active_start is not None else 0
    i0 = max(0, min(i0, len(rf_a) - 2))
    seg = rf_a[i0:]
    years = (rb.index[-1] - rb.index[0]).days / 365.25
    base_cagr = cagr_from_monthly(A_base, years)
    rng = np.random.default_rng(SEED)
    nulls = []
    for _ in range(N_NULL):
        sh = ap.circular_shift(seg, rng, block=1)
        rs = rf_a.copy()
        rs[i0:] = sh
        nulls.append(cagr_from_monthly(g.comp((1 - w) * rb_a + w * rs), years))
    actual = cagr_from_monthly(A, years)
    p_up = ap.p_upper(actual - base_cagr, [x - base_cagr for x in nulls])

    return {
        "ok": True,
        "n_days": int(len(rb)),
        "start": str(rb.index[0].date()),
        "end": str(rb.index[-1].date()),
        "months": int(len(A)),
        "stress_months": int(st.sum()),
        "w": float(w),
        "cagr_base": float(base_cagr),
        "cagr_aug": float(actual),
        "dcagr_pp": float(100 * (actual - base_cagr)),
        "p_upper": float(p_up) if p_up is not None else None,
        "null_mean": float(np.mean(nulls)),
        "null_sd": float(np.std(nulls)),
        "corr_fam_acct_full": corr(Fw, A),
        "corr_fam_acct_stress": corr(Fw, A, st),
        "corr_fam_rv2_full": corr(Fw, Rv2m),
        "corr_fam_rv2_stress": corr(Fw, Rv2m, st),
        "mean_monthly_contrib_pct": float(Fw.mean() * 100),
        "total_contrib_pct": float(Fw.sum() * 100),
        "rc": {k: round(v, 4) for k, v in rc.items()},
        "rc_fam": float(rc["fam"]),
        "eff_sources": eff,
        "eff_sources_base": eff_base,
        "worst20_base": w20_base,
        "worst20_aug": w20_aug,
        "worst20_delta_pp": float(100 * (w20_aug - w20_base)),
        "fam_vol_ann": float(np.std(rf_a) * np.sqrt(365)),
        "fam_cagr": cagr_from_daily(pd.Series(rf_a, index=rb.index)),
    }


def size_family(acct: dict, fam_r: pd.Series) -> dict:
    """二分:调到族自己的边际风险贡献 = 账户月度方差的 10%。"""
    C = acct["C"]
    rb = C["acct"]
    rf = fam_r.reindex(C.index).fillna(0.0)
    g = MonthGrid(rb.index)

    def rc_at(w):
        ra = (1 - w) * rb.to_numpy() + w * rf.to_numpy()
        A = g.comp(ra)
        Fw = g.summ(w * rf.to_numpy())
        if A.var() == 0:
            return float("nan")
        return float(np.cov(Fw, A)[0, 1] / A.var())

    grid = np.linspace(0.0, 1.0, 201)
    vals = [rc_at(x) for x in grid]
    ok = [(x, v) for x, v in zip(grid, vals) if not np.isnan(v)]
    mono = all(ok[i][1] <= ok[i + 1][1] + 1e-9 for i in range(len(ok) - 1))
    cross = None
    for i in range(len(ok) - 1):
        if ok[i][1] <= TARGET_RC <= ok[i + 1][1]:
            cross = (ok[i][0], ok[i + 1][0])
            break
    if cross is None:
        return {"w": None, "rc_max": ok[-1][1], "monotone": bool(mono), "reachable": False}
    lo, hi = cross
    for _ in range(60):
        mid = (lo + hi) / 2
        if rc_at(mid) < TARGET_RC:
            lo = mid
        else:
            hi = mid
    w = (lo + hi) / 2
    return {"w": float(w), "rc_at_w": rc_at(w), "rc_max": ok[-1][1], "monotone": bool(mono), "reachable": True}


def judge(m: dict) -> dict:
    """S-835 的 (i)–(iv) 逐条判定。"""
    c1 = [m["corr_fam_acct_full"], m["corr_fam_acct_stress"], m["corr_fam_rv2_full"], m["corr_fam_rv2_stress"]]
    c1_ok = all((v is not None) and (not np.isnan(v)) and abs(v) < 0.30 for v in c1)
    c2_ok = bool(m["mean_monthly_contrib_pct"] > 0) and (m["p_upper"] is not None) and (m["p_upper"] < 0.10)
    c3a = bool(m["worst20_aug"] >= m["worst20_base"] - 1e-12)
    c3b = bool(m["eff_sources"] > m["eff_sources_base"])
    c3_ok = c3a and c3b
    return {
        "i_corr_lt_030": bool(c1_ok),
        "ii_positive_and_p_lt_010": bool(c2_ok),
        "iii_worst20_not_worse": bool(c3a),
        "iii_eff_sources_up": bool(c3b),
        "iii_ok": bool(c3_ok),
        "pattern": [bool(c1_ok), bool(c2_ok), bool(c3_ok)],
    }


def main() -> None:
    log("=== 账户(S-834 口径)===")
    acct = build_account()
    C = acct["C"]
    st = account_stats(C)
    log(f"  账户 {C.index[0].date()} → {C.index[-1].date()} · {st['months']} 个月 · "
        f"年化 {st['cagr']:+.2%} · R-v2 风险占比 {st['rv2_risk_share']:.3f} · 有效来源 {st['eff_sources']:.2f}")
    chk = {"cagr_pct": round(st["cagr"] * 100, 2), "rv2_risk_share": round(st["rv2_risk_share"], 3),
           "expect_cagr_pct": 35.7, "expect_rv2": 0.742,
           "cagr_ok": bool(abs(st["cagr"] - 0.357) < 0.005), "rv2_ok": bool(abs(st["rv2_risk_share"] - 0.742) < 0.005)}
    log(f"  对账:年化 {chk['cagr_pct']}% (期望 35.7%) · R-v2 {chk['rv2_risk_share']} (期望 0.742) · "
        f"{'对上' if chk['cagr_ok'] and chk['rv2_ok'] else '对不上!'}")
    if not (chk["cagr_ok"] and chk["rv2_ok"]):
        raise SystemExit("账户对不上 S-834 的 +35.7% / 0.742,停。")

    # 压力月:core(账户主腿)月度收益的 20 分位以下
    core_m = (1 + acct["core_daily"]["core_nav_1_cap_pit24"].reindex(C.index).pct_change().fillna(0.0)).resample("M").prod() - 1
    stress_flags = {str(k.to_period("M")): bool(v) for k, v in (core_m <= core_m.quantile(0.2)).items()}

    acct_idx = acct["idx"]
    log("=== 族曲线(T-348 的装配)===")
    fams = load_families(acct_idx)

    # World50:本机重建的面板(价格收益)跑 t099_world50_replay → EWxMom 月收益
    fams["World50_EWxMom"] = load_world50(R + "w50_daily/world50_replay_t361.json", acct_idx)

    results = {"account": {k: v for k, v in st.items() if k not in ("Cm", "Am")}, "reconcile": chk,
               "families": {}, "config": {"f": F_, "cap": CAP_, "n": N_, "target_rc": TARGET_RC,
                                          "n_null": N_NULL, "seed": SEED, "start": str(START.date())}}

    for key in FAM_ORDER:
        if key not in fams:
            continue
        fam = fams[key]
        fr = fam["ret"].reindex(C.index).fillna(0.0)
        fe = pd.Timestamp(fam["meta"].get("first_entry", str(C.index[0].date())))
        sz = size_family(acct, fr)
        w = sz.get("w")
        log(f"=== {key}({FAM_LABEL.get(key, key)}) 首个进场 {fe.date()} · 尺寸 w="
            f"{'不可达' if w is None else f'{w:.4f}'} (rc_max={sz.get('rc_max')})")
        wins = {"A_earliest": max(fe, START), "B_2021-10-11": START}
        rec = {"label": FAM_LABEL.get(key, key), "first_entry": str(fe.date()),
               "meta": {k: v for k, v in fam["meta"].items() if k in ("n_tickets", "note", "last_exit", "risk_frac")},
               "sizing": sz, "windows": {}}
        if w is not None:
            for wn, ws in wins.items():
                m = window_metrics(acct, fr, w, ws, C.index[-1], stress_flags, fe)
                if not m.get("ok"):
                    continue
                j = judge(m)
                m["judge"] = j
                rec["windows"][wn] = m
                log(f"  [{wn}] {m['start']}→{m['end']}:年化 {m['cagr_base']:+.2%}→{m['cagr_aug']:+.2%} "
                    f"| corr(acct) {m['corr_fam_acct_full']:+.2f}/{m['corr_fam_acct_stress']:+.2f} "
                    f"corr(rv2) {m['corr_fam_rv2_full']:+.2f}/{m['corr_fam_rv2_stress']:+.2f} "
                    f"| 贡献 {m['mean_monthly_contrib_pct']:+.3f}%/月 p={m['p_upper']:.3f} "
                    f"| 20日 {m['worst20_base']:+.1%}→{m['worst20_aug']:+.1%} "
                    f"| 有效来源 {m['eff_sources_base']:.2f}→{m['eff_sources']:.2f} | (i){'✓' if j['i_corr_lt_030'] else '✗'}"
                    f"(ii){'✓' if j['ii_positive_and_p_lt_010'] else '✗'}(iii){'✓' if j['iii_ok'] else '✗'}")
            a = rec["windows"].get("A_earliest", {}).get("judge", {}).get("pattern")
            b = rec["windows"].get("B_2021-10-11", {}).get("judge", {}).get("pattern")
            if a is not None and b is not None:
                rec["iv_same_direction"] = bool(a == b)
                rec["iv_window_dependent"] = bool(a != b)
                rec["iv_note"] = "A=B(同窗口,退化)" if wins["A_earliest"] == wins["B_2021-10-11"] else ""
                log(f"  (iv) 两窗口同向:{rec['iv_same_direction']} {rec['iv_note']}")
        # 2023-02-08 → 03-08
        seg = fr.loc[FEB[0]:FEB[1]]
        fam_feb = float((1 + seg).prod() - 1) if len(seg) else float("nan")
        rec["feb_window"] = {"start": FEB[0], "end": FEB[1], "fam_total_pct": round(100 * fam_feb, 2),
                             "n_days": int(len(seg))}
        # 族自身全历史
        if fam.get("nav") is not None:
            nav = fam["nav"]
            yrs = (nav.index[-1] - nav.index[0]).days / 365.25
            rec["standalone"] = {"start": str(nav.index[0].date()), "end": str(nav.index[-1].date()),
                                 "total_pct": round(100 * float(nav.iloc[-1] - 1), 1),
                                 "cagr_pct": round(100 * float(nav.iloc[-1] ** (1 / yrs) - 1), 2)}
        results["families"][key] = rec

    json.dump(results, open(OUT_JSON, "w"), indent=1, default=str)
    write_md(results)
    log(f"=== 写完 {OUT_JSON} · {OUT_MD}")


def monthly_ret_from_replay(rep: dict, arm: str) -> dict:
    """从回放报告里取逐月收益(arms[arm] 的 ret 与 months 对齐;缺就按窗口顺序兜底)。"""
    a = rep["arms"][arm]
    ms = a.get("months")
    rs = a.get("ret")
    if ms is None or rs is None:
        return {}
    return {m: float(r) for m, r in zip(ms, rs) if r is not None}


def write_md(res: dict) -> None:
    L = []
    A = res["account"]
    L.append("# T-361 —— S-835 准入表:坟场里有曲线的族统一过一遍\n")
    L.append(f"- 账户(照 S-834 口径):年化 **{A['cagr']*100:.1f}%**(期望 35.7%)· R-v2 风险占比 **{A['rv2_risk_share']:.3f}**(期望 0.742)"
             f"· 有效来源 {A['eff_sources']:.2f}· {A['months']} 个月\n")
    L.append("- 尺寸:族自己的边际风险贡献 = 账户月度方差的 10%(二分,满仓 w=1 时 rc→1)\n")
    L.append("- 零分布:`apparatus.circular_shift`(族的日收益序列,block 1,500 次,种子 361)—— 拆开族与账户的对齐;"
             "统计量 = 叠加后账户年化 − 原账户年化\n")
    L.append("- (i) 月度相关(族贡献 vs 账户 / vs R-v2),全样本与压力月,|ρ| < 0.30;"
             "(ii) 族自己的月贡献为正 且 p_upper < 0.10;(iii) 最差 20 日不变差、有效来源数上升;"
             "(iv) 两窗口同向\n")
    L.append("| 族 | 尺寸 w | (i) 相关(账户 全/压力) | (i) 相关(R-v2 全/压力) | (ii) 月贡献 | (ii) p_upper | (iii) 最差20日(基→加族) | (iii) 有效来源(基→加族) | (iv) 两窗口同向 | 2023-02-08→03-08 |")
    L.append("|---|---|---|---|---|---|---|---|---|---|")
    base_eff = res["account"]["eff_sources"]
    for k, r in res["families"].items():
        w = r["sizing"].get("w")
        b = r["windows"].get("B_2021-10-11", {})
        a = r["windows"].get("A_earliest", {})
        m = b or a
        if not m:
            L.append(f"| {r['label']} | 尺寸不可达 | — | — | — | — | — | — | — | {r['feb_window']['fam_total_pct']:+.1f}% |")
            continue
        j = m["judge"]
        iv = r.get("iv_same_direction")
        ivs = "退化(A=B)" if r.get("iv_note") else ("同向 ✓" if iv else "窗口依赖 ✗")
        L.append(f"| {r['label']} | {w:.3f} | {m['corr_fam_acct_full']:+.2f} / {m['corr_fam_acct_stress']:+.2f} "
                 f"{'✓' if j['i_corr_lt_030'] else '✗'} | {m['corr_fam_rv2_full']:+.2f} / {m['corr_fam_rv2_stress']:+.2f} "
                 f"| {m['mean_monthly_contrib_pct']:+.3f}% {'✓' if m['mean_monthly_contrib_pct']>0 else '✗'} "
                 f"| {('%.3f' % m['p_upper']) if m['p_upper'] is not None else 'n/a'} {'✓' if j['ii_positive_and_p_lt_010'] else '✗'} "
                 f"| {m['worst20_base']:+.1%} → {m['worst20_aug']:+.1%} {'✓' if j['iii_worst20_not_worse'] else '✗'} "
                 f"| {m['eff_sources_base']:.2f} → {m['eff_sources']:.2f} {'✓' if j['iii_eff_sources_up'] else '✗'} "
                 f"| {ivs} | {r['feb_window']['fam_total_pct']:+.1f}% |")
    L.append("")
    open(OUT_MD, "w").write("\n".join(L))


if __name__ == "__main__":
    main()
