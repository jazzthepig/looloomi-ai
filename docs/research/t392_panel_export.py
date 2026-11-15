"""T-392 —— S-869 面板补全(A 道):把「策略自己那份回测 / 账本」的逐日净值导出成 `s869_extra_panel_a.csv`。

S-869 的脚本 `s869_strategy_state.py` 会读同目录下所有 `s869_extra_panel*.csv`(family,d,nav,funded)。
本脚本只做一件事:把 A 道名下那几条策略**原样**导出来 —— 参数一个不改、不重新调、不下结论。
每一族都跟它自己已发布的数字对账(对不上就报错退出,不写盘)。

  族                     来源                                    funded  对账对象
  tom_pd13_btc/eth       S-596 `s596_tom_pyramid.py` PD13 臂      1      research/s596/s596_results.json
  s823_r6                S-823 `s823_three_state.py` R6 留出段     1      docs/research/s823_results.json
  s819_short_s015/s030   S-819 `s819_gate_short.py` 空头腿自己    0      docs/research/s819_results.json
  style_* × 7            T-160 `t160_bear_floor.py` 的 7 个风格指数 1      DB style_index_pit_daily(cap)
  carry_b_top_rc         T-359 返工后那条资金费套息(账本 NAV)     0      docs/research/t359_results.json

用法(仓库根目录):python3 docs/research/t392_panel_export.py
产物:docs/research/s869_extra_panel_a.csv + docs/research/s869_extra_panel_a.meta.json
"""
from __future__ import annotations

import csv
import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

MAC = Path("/Volumes/CometCloudAI/cometcloud-local")
OUT_CSV = HERE / "s869_extra_panel_a.csv"
OUT_META = HERE / "s869_extra_panel_a.meta.json"

# T-160 `t160_bear_floor.py` 的 STYLES(7 个,cap 加权,不含 majors —— majors 就是大盘)
STYLES = ("ai", "defi", "meme", "infra_tokenization", "app", "second_l1_l2", "top_l1")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Prefer": "count=exact"}

ROWS: list[dict] = []
META: list[dict] = []


def sb_get(table: str, params: dict):
    q = urllib.parse.urlencode(params)
    req = urllib.request.Request(f"{URL}/rest/v1/{table}?{q}", headers=HDR)
    with urllib.request.urlopen(req, timeout=180) as r:
        body = r.read().decode()
        rng = r.headers.get("Content-Range", "") or ""
    total = None
    if "/" in rng:
        tail = rng.split("/")[-1].strip()
        if tail.isdigit():
            total = int(tail)
    return (json.loads(body) if body else []), total


def sb_paged(table: str, params: dict, page: int = 1000, max_pages: int = 400):
    out, tot = [], None
    for i in range(max_pages):
        p = dict(params)
        p["limit"] = str(page)
        p["offset"] = str(i * page)
        rows, t = sb_get(table, p)
        if i == 0:
            tot = t
        out += rows
        if len(rows) < page:
            break
    return out, tot


def load_mod(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cumprod(r: pd.Series | np.ndarray) -> pd.Series:
    s = pd.Series(r)
    return (1.0 + s.fillna(0.0)).cumprod()


def emit(family: str, nav: pd.Series, funded: int, meta: dict) -> None:
    nav = nav.dropna()
    for d, v in nav.items():
        ROWS.append({"family": family, "d": str(pd.Timestamp(d).date()), "nav": repr(float(v)), "funded": str(int(funded))})
    meta = dict(meta)
    meta.update({"family": family, "funded": int(funded), "first": str(pd.Timestamp(nav.index[0]).date()),
                 "last": str(pd.Timestamp(nav.index[-1]).date()), "days": int(len(nav))})
    META.append(meta)
    print(f"  {family:26s} {meta['first']} → {meta['last']}  {len(nav):5d} 天  funded={funded}  nav末 {float(nav.iloc[-1]):.6f}")


def close(a: float, b: float, tol: float = 1e-9) -> bool:
    return abs(float(a) - float(b)) <= tol * max(1.0, abs(float(b)))


# ── ① tom_pd13(S-596)───────────────────────────────────────────────────────────
def fam_tom_pd13() -> None:
    s596 = load_mod("s596_tom_pyramid", HERE / "s596_tom_pyramid.py")
    close_path = MAC / "research/w50_daily/close.json"
    fund_path = MAC / "research/s596/funding_monthly.txt"
    pub = json.load(open(MAC / "research/s596/s596_results.json"))
    cap, defend = s596.ARMS["PD13"]
    for sym in ("BTC", "ETH"):
        dates, close_v, fund = s596.load(str(close_path), str(fund_path), sym)
        g, info = s596.gross_path(close_v, cap, defend)
        r = s596.daily_returns(close_v, g, fund)
        st = s596.stats(r)
        p = pub[sym]["arms"]["PD13"]
        for k in ("total_x", "cagr", "max_dd"):
            if not close(st[k], p[k], 1e-9):
                raise SystemExit(f"tom_pd13 {sym} 对账失败 {k}: 复算 {st[k]} vs 已发布 {p[k]}")
        nav = cumprod(pd.Series(r, index=pd.to_datetime(dates)))
        emit(f"tom_pd13_{sym.lower()}", nav, 1, {
            "what": f"S-596 Trader Tom 仓位管理 PD13 臂(cap={cap}, defend={defend})在 {sym} 上的账户净值",
            "ledger": "S-596",
            "source": "docs/research/s596_tom_pyramid.py::run_asset 的 gross_path+daily_returns(参数未改)",
            "data": [str(close_path), str(fund_path)],
            "params": {"arm": "PD13", "cap": cap, "defend": defend, "cost_bp": 10, "funding": "月均永续资金费(2020 前 10% 年化)"},
            "check": {"total_x": st["total_x"], "cagr": st["cagr"], "max_dd": st["max_dd"],
                      "published_total_x": p["total_x"], "published_cagr": p["cagr"], "published_max_dd": p["max_dd"]},
        })


# ── ② S-823 三态敞口 R6(留出段)────────────────────────────────────────────────
def fam_s823_r6() -> None:
    s823 = load_mod("s823_three_state", HERE / "s823_three_state.py")
    price = MAC / "research/t339/coinmetrics_price_usd.json"
    funding = MAC / "research/s681/_um_funding.jsonl"
    pub = json.load(open(HERE / "s823_results.json"))
    disc = json.load(open(HERE / "s823_discovery.json"))
    if disc["picked"] != "R6":
        raise SystemExit(f"S-823 发现段选的不是 R6(是 {disc['picked']})")
    p, f = s823.load(str(price), str(funding), s823.H1)
    st = s823.states(p)
    ret, pos, sl = s823.account(st["R6"], p, f, s823.H0, s823.H1)
    m = s823.metrics(ret, pos)
    q = pub["R6"]
    for k in ("cagr", "total", "mdd"):
        if not close(m[k], q[k], 1e-9):
            raise SystemExit(f"S-823 R6 对账失败 {k}: 复算 {m[k]} vs 已发布 {q[k]}")
    if not close(s823.comp(sl), q["short_leg_total"], 1e-9):
        raise SystemExit("S-823 R6 对账失败 short_leg_total")
    nav = cumprod(ret)
    emit("s823_r6", nav, 1, {
        "what": "S-823 三态敞口 R6(= R2 + V 形护栏)在留出段 2021-01-01 → 2026-10-30 的账户净值(e ∈ {−0.3,+0.3,+1.0})",
        "ledger": "S-823",
        "source": "docs/research/s823_three_state.py::states+account(参数未改,发现段已选定 R6)",
        "data": [str(price), str(funding)],
        "params": {"rule": "R6", "E_DOWN": s823.E_DOWN, "E_MID": s823.E_MID, "E_UP": s823.E_UP, "cost": s823.COST,
                   "window": [s823.H0, s823.H1]},
        "check": {"cagr": m["cagr"], "total": m["total"], "mdd": m["mdd"], "short_leg_total": s823.comp(sl),
                  "published_cagr": q["cagr"], "published_total": q["total"], "published_mdd": q["mdd"]},
    })


# ── ③ S-819 闸门关时空大盘(空头腿自己的曲线)────────────────────────────────────
def fam_s819_short() -> None:
    import t310_slots as T310
    T310.UM = str(MAC / "research/s681/_um_daily.jsonl")
    T310.STYLE = str(MAC / "research/t156/_style.json")
    pub = json.load(open(HERE / "s819_results.json"))
    d = pd.read_csv(HERE / "t342_daily.csv", parse_dates=["date"]).set_index("date")
    START = pd.Timestamp("2021-10-11")

    def daily(sym: str) -> pd.Series:
        rw = None
        for line in open(T310.UM):
            x = json.loads(line)
            if x["symbol"] == sym:
                rw = sorted({tuple(b) for b in x["bars"] if len(b) >= 6 and b[4] > 0})
                break
        c = pd.Series({pd.Timestamp(r[0]): float(r[4]) for r in rw}).sort_index()
        return c.pct_change().dropna()

    def fund(sym: str) -> pd.Series:
        for line in open(MAC / "research/s681/_um_funding.jsonl"):
            x = json.loads(line)
            if x["symbol"] == sym:
                s = pd.Series({pd.Timestamp(t).tz_convert(None) if pd.Timestamp(t).tzinfo else pd.Timestamp(t): float(v)
                               for t, v in x["rates"]})
                return s.groupby(s.index.normalize()).sum()
        raise SystemExit(f"funding 缺 {sym}")

    rb, re_, fb, fe = daily("BTC"), daily("ETH"), fund("BTC"), fund("ETH")
    cal = pd.date_range(START - pd.Timedelta(days=5), d.index[-1], freq="D")
    basket = ((rb + re_) / 2).reindex(cal)
    fnd = ((fb.reindex(cal).fillna(0) + fe.reindex(cal).fillna(0)) / 2)
    gate_d, _, _ = T310.load_gate()
    g = pd.Series({pd.Timestamp(k): bool(v) for k, v in gate_d.items()}).sort_index().reindex(cal).ffill()

    def short_ret(gs, s):
        closed = (~gs.astype(bool)).shift(1).fillna(False).astype(bool)
        flips = (closed != closed.shift(1).fillna(False)).astype(float)
        return (closed * (-s * basket.fillna(0) + s * fnd) - flips * 0.0005 * s), closed

    for s, key in ((0.15, "0.15"), (0.30, "0.3")):
        sr, closed = short_ret(g, s)
        w = sr[sr.index >= START]
        tot = float((1 + w).prod() - 1)
        p = pub[key]
        if not close(tot, p["short_total"], 1e-9):
            raise SystemExit(f"S-819 s={s} 对账失败 short_total: 复算 {tot} vs 已发布 {p['short_total']}")
        yr = {int(y): round(float((1 + x).prod() - 1) * 100, 2) for y, x in w.groupby(w.index.year)}
        if yr != {int(k): v for k, v in p["short_yearly"].items()}:
            raise SystemExit(f"S-819 s={s} 对账失败 short_yearly: 复算 {yr} vs 已发布 {p['short_yearly']}")
        nav = cumprod(w)
        emit(f"s819_short_s{int(s * 100):03d}", nav, 0, {
            "what": f"S-819 闸门关着时直接空大盘(BTC/ETH 永续 50/50),规模 s={s};**只有空头腿自己的盈亏曲线**(不含 C0 的叠加)",
            "ledger": "S-819",
            "source": "docs/research/s819_gate_short.py::short_ret(逐行照抄,参数未改)",
            "data": [str(MAC / 'research/s681/_um_daily.jsonl'), str(MAC / 'research/s681/_um_funding.jsonl'),
                     str(MAC / 'research/t156/_style.json'), "docs/research/t342_daily.csv"],
            "params": {"s": s, "START": str(START.date()), "flip_cost": 0.0005, "basket": "BTC/ETH 永续日收益等权"},
            "check": {"short_total": tot, "short_yearly_pct": yr, "published_short_total": p["short_total"],
                      "published_short_yearly": p["short_yearly"], "episodes": p["episodes"]},
        })


# ── ④ 七个风格指数(T-160 的 STYLES,cap 加权)────────────────────────────────────
def fam_styles() -> None:
    for sty in STYLES:
        rows, tot = sb_paged("style_index_pit_daily",
                             {"select": "d,ret", "style": f"eq.{sty}", "weighting": "eq.cap", "order": "d.asc"})
        if not rows:
            raise SystemExit(f"风格指数 {sty} 没有数据")
        s = pd.Series({str(r["d"])[:10]: float(r["ret"]) for r in rows if r.get("ret") is not None}).sort_index()
        if len(s) != tot:
            raise SystemExit(f"风格指数 {sty} 分页不全: 取到 {len(s)} / 共 {tot}")
        nav = cumprod(s)
        emit(f"style_{sty}", nav, 1, {
            "what": f"风格指数 {sty}(cap 加权)的逐日净值 —— T-160 `t160_bear_floor.py` 的 7 个 STYLES 之一",
            "ledger": "S-645③ / T-160",
            "source": "DB style_index_pit_daily(style,weighting=cap) 的 ret 列 → 累乘成净值(指数本身,不是回测)",
            "data": [f"style_index_pit_daily?style=eq.{sty}&weighting=eq.cap"],
            "params": {"weighting": "cap", "style": sty},
            "check": {"rows": int(tot), "first": str(s.index[0]), "last": str(s.index[-1]), "nav_last": float(nav.iloc[-1])},
        })


# ── ⑤ 资金费套息(T-359 返工后那条)─────────────────────────────────────────────
def fam_carry() -> None:
    from src.data.signals import carry_hl as CH
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE

    DATA_ROOT = MAC / "_data" / "hyperliquid_funding"
    CARRY_INCEPTION = dt.date(2023, 6, 12)
    d = pd.read_csv(HERE / "t342_daily.csv", parse_dates=["date"]).set_index("date")
    legs_px = {"crypto": d.crypto_leg_nav_x1v, "equity": d.equity_close_acwi, "gold": d.gold_close_xauusd}
    df = pd.concat(legs_px, axis=1).dropna().sort_index()
    ACCT_START = pd.Timestamp("2021-10-11")
    idx = [x for x in df.index if x >= ACCT_START]
    ACCT_END = idx[-1].date()

    names = tuple(sorted({n for n in DEFAULT_UNIVERSE if (DATA_ROOT / f"{n.lower()}_funding_1h.csv").exists()}))

    hourly = []
    for n in names:
        p = DATA_ROOT / f"{n.lower()}_funding_1h.csv"
        if not p.exists():
            continue
        buckets: dict[str, list[float]] = {}
        with open(p, newline="") as f:
            rd = csv.reader(f)
            next(rd)
            for row in rd:
                if not row or not row[0]:
                    continue
                dd = dt.datetime.fromtimestamp(int(row[0]) / 1000, dt.timezone.utc).date().isoformat()
                buckets.setdefault(dd, []).append(float(row[1]))
        for dd, vals in buckets.items():
            hourly.append({"coin": n, "d": dd, "rate_sum": sum(vals), "n_hours": len(vals)})

    sb_rows, sb_tot = sb_paged("hl_funding_daily",
                                {"select": "coin,d,rate_sum,n_hours",
                                 "coin": "in.(" + ",".join(names) + ")",
                                 "d": "gte.2023-05-12", "order": "coin.asc,d.asc"})
    keep = [{"coin": r["coin"], "d": str(r["d"])[:10], "rate_sum": float(r["rate_sum"]), "n_hours": int(r["n_hours"])}
            for r in sb_rows if str(r["d"])[:10] <= ACCT_END.isoformat()]
    merged = {(r["coin"], r["d"]): (r["rate_sum"], r["n_hours"]) for r in hourly}
    for r in keep:
        merged.setdefault((r["coin"], r["d"]), (r["rate_sum"], r["n_hours"]))
    rows_m = [{"coin": c, "d": dd, "rate_sum": v[0], "n_hours": v[1]} for (c, dd), v in merged.items()]
    d0 = dt.date(2023, 5, 12)
    days_c, F = CH.matrix(rows_m, names, d0, ACCT_END)
    path = CH.path(days_c, F, "carry_b_top_rc", inception=CARRY_INCEPTION, cost=CH.COST_REAL)
    nav = pd.Series({r["d"]: float(r["nav"]) for r in path}).sort_index()
    nav.index = pd.to_datetime(nav.index)
    nav = nav[nav.index <= pd.Timestamp(ACCT_END)]
    rets = pd.Series({r["d"]: float(r["ret"]) for r in path}).sort_index()
    rets.index = pd.to_datetime(rets.index)
    rets = rets[rets.index <= pd.Timestamp(ACCT_END)]
    emit("carry_b_top_rc", nav, 0, {
        "what": "资金费套息臂 carry_b_top_rc(每周一在费率前一半的名字上收资金费;生产核 `src/data/signals/carry_hl.py`,真实成本 15.5bp/次)",
        "ledger": "S-835 / T-359(返工后那条)",
        "source": "src/data/signals/carry_hl.py::matrix+path(参数未改) —— 用的是它自己记的 NAV",
        "data": [str(DATA_ROOT / "<coin>_funding_1h.csv"), "hl_funding_daily(Supabase 视图,补尾)"],
        "params": {"arm": "carry_b_top_rc", "inception": str(CARRY_INCEPTION), "cost": CH.COST_REAL,
                   "universe_n": len(names), "account_end": str(ACCT_END)},
        "check": {"nav_last": float(nav.iloc[-1]), "ret_total": float((1 + rets).prod() - 1),
                  "days": int(len(nav)), "n_on_last": int(path[-1].get("n_on", -1))},
    })


def main() -> None:
    print("[1/5] tom_pd13(S-596)"); fam_tom_pd13()
    print("[2/5] S-823 R6"); fam_s823_r6()
    print("[3/5] S-819 空头腿"); fam_s819_short()
    print("[4/5] 七个风格指数"); fam_styles()
    print("[5/5] 资金费套息(T-359)"); fam_carry()

    rows = sorted(ROWS, key=lambda r: (r["family"], r["d"]))
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["family", "d", "nav", "funded"])
        w.writeheader()
        w.writerows(rows)
    json.dump({"task": "T-392", "written": str(OUT_CSV), "n_rows": len(rows),
               "families": sorted({r["family"] for r in rows}), "entries": META},
              open(OUT_META, "w"), ensure_ascii=False, indent=1)
    print(f"WROTE {OUT_CSV}  rows={len(rows)}  families={len(META)}")
    print(f"WROTE {OUT_META}")


if __name__ == "__main__":
    main()
