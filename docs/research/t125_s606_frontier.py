"""T-125 / S-606 —— 灵活组合的回撤—收益地图(预注册见 REFUTATION_LEDGER §S-606)。

S-604 → S-606 的两处变化:
  1. 股票腿:ACWI → World50 EW×Mom 月收益(在 research/w50_daily 上重跑,t099_world50_replay.run_arm('EWxMom'))
  2. 黄金网格:{0, 0.10, 0.20} → {0.00, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30, 0.35, 0.40}

其余(crypto 腿 H / X1V / X1V_fric、grid 范围、cost、rebalance、bootstrap 块长、days、seed)照 s604_frontier 一字不改。

用法:python3 docs/research/t125_s606_frontier.py <research 目录> <输出 json>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.data.evaluation.apparatus import stationary_bootstrap_index  # noqa: E402
from src.data.universe.world50 import momentum_scores, select_members, tilt_weights  # noqa: E402
import s602_simulate as s602  # noqa: E402
import t099_world50_replay as t099  # noqa: E402

# ── 照搬 s604 的常量(一个字不改) ─────────────────────────────────────────────
START, END, REB, COST, N_PATHS, DAYS, BLOCK, SEED = "2016-01-04", "2026-10-15", 21, 10 / 1e4, 1000, 1512, 60, 604

# ── 黄金网格放宽到 0–40%(本卡唯一的 grid 改动) ────────────────────────────────
GOLD_STEP = 0.05


def gold_grid() -> list[float]:
    out = []
    g = 0.0
    while g <= 0.40 + 1e-9:
        out.append(round(g, 4))
        g += GOLD_STEP
    return out


def grid():
    """crypto 1..7 / equity 1..8 / gold 0..0.40 步长 5%;c+e+g ∈ [3, 10];其余现金。"""
    out = []
    for c in range(1, 8):
        for e in range(1, 9):
            for g in gold_grid():
                gw = round(g, 2)
                if c / 10 + e / 10 + gw <= 1.0 + 1e-9 and c / 10 + e / 10 + gw >= 0.30 - 1e-9:
                    out.append((c / 10, e / 10, gw))
    return out


# ── 复用 s604 的 portfolio / stats ────────────────────────────────────────────

def portfolio(R: np.ndarray, w: tuple) -> np.ndarray:
    """R: (paths, days, 3);恒定配比,每 REB 天再平衡;返回 (paths, days) 日收益。"""
    tgt = np.array(w)
    P, D, _ = R.shape
    hold = np.tile(tgt, (P, 1))
    out = np.zeros((P, D))
    for t in range(D):
        if t % REB == 0 and t > 0:
            tv = np.abs(hold - tgt).sum(axis=1)
            hold = np.tile(tgt, (P, 1))
            cost = tv * COST
        else:
            cost = 0.0
        r = (hold * R[:, t, :]).sum(axis=1)
        out[:, t] = r - cost
        grown = hold * (1 + R[:, t, :])
        tot = grown.sum(axis=1) + (1 - hold.sum(axis=1))
        hold = grown / tot[:, None]
    return out


def stats(r: np.ndarray, per_year: float = 252.0):
    nav = np.cumprod(1 + r, axis=1)
    yrs = r.shape[1] / per_year
    cagr = nav[:, -1] ** (1 / yrs) - 1
    dd = (nav / np.maximum.accumulate(nav, axis=1) - 1).min(axis=1)
    return cagr, dd


# ── 把 w50_daily 聚成 t099 期望的 panel 格式 ─────────────────────────────────

def build_panel_from_w50(daily_dir: Path) -> dict:
    """读 w50_daily/close.json + mcap.json,产出 t099 的 panel 格式:
       {months: ['YYYY-MM', ...], ret: {key: [月收益 或 null]}, mcap: {'YYYY-MM': {key: mcap}}, cls: {key: 'equity'|'metal'|'crypto'|'benchmark'}}
    """
    close = json.loads((daily_dir / "close.json").read_text())
    mcap = json.loads((daily_dir / "mcap.json").read_text())
    dates = close["dates"]
    cls = close["cls"]

    # 月份骨架(2015-01 到 2026-10)
    months = []
    for y in range(2015, 2027):
        for m in range(1, 13):
            if y == 2026 and m > 10:
                break
            months.append(f"{y:04d}-{m:02d}")

    # 月末价格 = 该月最后一条非空 close
    last_in_month: dict[str, dict[str, float]] = {m: {} for m in months}
    for k in close["close"]:
        c = close["close"][k]
        for i, d in enumerate(dates):
            v = c[i]
            if v is not None and v > 0:
                ym = d[:7]
                if ym in last_in_month:
                    last_in_month[ym][k] = float(v)

    # 月收益 = 当月最后价 / 上月最后价 − 1(上一个月缺价则 None)
    syms = sorted(close["close"].keys())
    ret: dict[str, list[Optional[float]]] = {}
    for k in syms:
        seq = []
        prev = None
        for m in months:
            p = last_in_month[m].get(k)
            if prev is None or p is None:
                seq.append(None)
            else:
                seq.append(p / prev - 1.0)
            if p is not None:
                prev = p
        ret[k] = seq

    # mcap:每个季末(03 / 06 / 09 / 12)取 mcap.json 里当时点最近一条
    mcap_q: dict[str, dict[str, float]] = {}
    for k, pts in mcap.items():
        for d, v in pts:
            ym = d[:7]
            if ym not in mcap_q:
                mcap_q[ym] = {}
            if v and v > 0:
                # 同一个 ym 内可能有多个,取最后一条
                mcap_q[ym][k] = float(v)

    return {"months": months, "ret": ret, "mcap": mcap_q, "cls": cls}


def expand_monthly_to_daily(months: list[str], monthly_ret: list[Optional[float]],
                          daily_dates: list[str], start: str, end: str) -> tuple[list[str], list[float]]:
    """把月收益按月内工作日等比拆分:每个工作日 return = (1+r_m)^(1/ndays) − 1。
       返回 (common_dates, daily_nav_series) —— NAV 自 1 起算,月内每天累计。
    """
    # 找出每月包含的 daily_dates 子集
    month_to_dates: dict[str, list[str]] = {m: [] for m in months}
    for d in daily_dates:
        if start <= d <= end:
            ym = d[:7]
            if ym in month_to_dates:
                month_to_dates[ym].append(d)

    nav_dates: list[str] = []
    nav_vals: list[float] = []
    nav = 1.0
    for m in months:
        r = monthly_ret[months.index(m)]
        ds = month_to_dates[m]
        if not ds:
            continue
        if r is None or not np.isfinite(r) or r <= -1.0:
            # 当月收益不可算:NAV 不变,跳过该日
            for d in ds:
                nav_dates.append(d)
                nav_vals.append(nav)
            continue
        n = len(ds)
        # (1+r)^(1/n) - 1
        daily_r = (1.0 + r) ** (1.0 / n) - 1.0
        for d in ds:
            nav = nav * (1.0 + daily_r)
            nav_dates.append(d)
            nav_vals.append(nav)
    return nav_dates, nav_vals


# ── 替换 s604 的 legs():股票腿从 ACWI 换成 World50 EW×Mom ─────────────────────

def legs(research: str):
    daily = json.loads((Path(research) / "w50_daily/close.json").read_text())
    dates = daily["dates"]

    # 1. World50 EW×Mom 月收益(t099.run_arm)—— 在 w50_daily 上重跑
    panel = build_panel_from_w50(Path(research) / "w50_daily")
    months = panel["months"]
    rets = {k: [None if v is None else float(v) for v in vs] for k, vs in panel["ret"].items()}
    mcap_q = {m: {k: float(v) for k, v in snap.items() if v} for m, snap in panel["mcap"].items()}
    closes = {k: t099.closes_from_returns(v) for k, v in rets.items()}
    w50_arm = t099.run_arm("EWxMom", months, rets, mcap_q, panel["cls"], closes)
    w50_months = w50_arm["months"]
    w50_monthly = w50_arm["ret"]
    print(f"[legs] World50 EW×Mom 月收益: {len(w50_months)} 月 "
          f"CAGR={((1 + np.array(w50_monthly)).prod() ** (12 / len(w50_monthly)) - 1):.2%}", flush=True)

    # 2. 把月收益展开成日 NAV
    nav_dates, nav_vals = expand_monthly_to_daily(w50_months, w50_monthly, dates, START, END)

    # 3. Crypto leg(s604 一样)—— H / X1V / X1V_fric
    btc = np.array([x if x else np.nan for x in daily["close"]["BTC"]], dtype=float)
    ok = np.isfinite(btc)
    bd = [d for d, o in zip(dates, ok) if o]
    bc = btc[ok]
    ex = s602.exposures(bc)
    nav_crypto = {"H": np.cumprod(1 + s602.rets(bc, ex["H"])),
                  "X1V": np.cumprod(1 + s602.rets(bc, ex["X1V"])),
                  "X1V_fric": np.cumprod(1 + s602.rets(bc, ex["X1V"], True))}
    crypto_nav = {k: dict(zip(bd, v)) for k, v in nav_crypto.items()}

    # 4. Gold 腿 —— 仍用 XAUUSD 日收盘价
    xau = daily["close"]["XAUUSD"]

    # 5. 对齐 common 日期(全部腿都有数据且落在 [START, END])
    eq_by_date = dict(zip(nav_dates, nav_vals))
    common = [d for d in nav_dates if START <= d <= END and xau[dates.index(d)] and d in crypto_nav["H"]]
    if not common:
        raise RuntimeError("没有公共交易日")

    # 6. 组装 (paths, days, 3) 收益矩阵
    out = {}
    for k in nav_crypto:
        c = np.array([crypto_nav[k][d] for d in common])
        eq = np.array([eq_by_date[d] for d in common])
        gd = np.array([xau[dates.index(d)] for d in common])
        R = np.column_stack([c[1:] / c[:-1] - 1,
                             eq[1:] / eq[:-1] - 1,
                             gd[1:] / gd[:-1] - 1])
        out[k] = R
    return common, out, {"window": (w50_months[0], w50_months[-1]), "w50_stats": w50_arm}


# ── 复用 s604 的 main 结构,但输出 grid 大小 / w50 元信息 ──────────────────────

def main(research: str, out_path: str):
    common, legs_R, w50_info = legs(research)
    rng = np.random.default_rng(SEED)
    n = len(next(iter(legs_R.values())))
    idx = stationary_bootstrap_index(n, BLOCK, N_PATHS, rng)[:, :DAYS]
    gs = grid()
    print(f"[grid] 共 {len(gs)} 个配比(crypto×equity×gold),黄金网格 0–40% 步长 {GOLD_STEP}", flush=True)
    res = {
        "days": [common[0], common[-1], len(common)],
        "gold_grid_step": GOLD_STEP,
        "grid_size": len(gs),
        "w50_meta": w50_info,
        "variants": {},
    }
    for k, R in legs_R.items():
        Rp = R[idx]
        rows = []
        for w in gs:
            cg, dd = stats(portfolio(Rp, w))
            hc, hd = stats(portfolio(R[None, :, :], w))
            rows.append({"crypto": w[0], "equity": w[1], "gold": w[2], "cash": round(1 - sum(w), 2),
                         "cagr_median": float(np.median(cg)), "cagr_p05": float(np.percentile(cg, 5)),
                         "dd_median": float(np.median(dd)), "dd_p05_worst": float(np.percentile(dd, 5)),
                         "hist_cagr": float(hc[0]), "hist_dd": float(hd[0])})
        front = {}
        for cap in (-0.25, -0.35, -0.45):
            ok = [r for r in rows if r["dd_p05_worst"] >= cap]
            front[str(cap)] = max(ok, key=lambda r: r["cagr_median"]) if ok else None
        res["variants"][k] = {"rows": rows, "frontier": front}
        print(k, "done", flush=True)
    Path(out_path).write_text(json.dumps(res, ensure_ascii=False, indent=1))
    return res


if __name__ == "__main__":
    from typing import Optional
    r = main(sys.argv[1], sys.argv[2])
    print("days", r["days"], "grid_size", r["grid_size"])
    for k, v in r["variants"].items():
        print("==", k)
        for cap, f in v["frontier"].items():
            if f:
                print(f"  worst5%DD ≥ {cap}: crypto {f['crypto']:.0%} eq {f['equity']:.0%} gold {f['gold']:.0%} cash {f['cash']:.0%} | "
                      f"cagr med {f['cagr_median']*100:.1f}% p05 {f['cagr_p05']*100:.1f}% | dd med {f['dd_median']*100:.1f}% worst5 {f['dd_p05_worst']*100:.1f}% | hist {f['hist_cagr']*100:.1f}% / {f['hist_dd']*100:.1f}%")