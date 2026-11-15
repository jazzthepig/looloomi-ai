"""T-406 夹具导出:把「研究输入 + T-392 已发布的逐日净值」落成 `tests/fixtures/state_arms_fixture.json`。

做三件事(全只读):
1. 用**生产内核**(`src/data/signals/state_arms.py`)在研究输入上重算 R6 / GATE_S15 / GATE_S30 的逐日净值,
   与 T-392 导出的 `s869_extra_panel_a.csv` **整段逐日**对账(≤ 1e-9)—— 对不上就报错退出,不写盘。
2. 证明**生产闸门 == 研究闸门**:生产 = `style_index_pit_daily`(eq.majors / eq.cap)按同一算式,
   研究 = `t310_slots.load_gate`(`t156/_style.json`);另核 `multiplier._majors_gate()`(③ 在用的那条)同样逐日相同。
3. 写夹具:一段 ≥120 天的研究输入 + 期望净值(归一化到片段首日的前一日)+ 闸门逐日对照(位串)。

用法:python3 docs/research/t406_fixture_export.py
产物:tests/fixtures/state_arms_fixture.json
"""
from __future__ import annotations

import asyncio
import csv
import json
import os
import sys
import urllib.parse
import urllib.request
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from src.data.signals.state_arms import (gate_short_returns, majors_gate_from_ret,  # noqa: E402
                                         r6_exposure, r6_returns)

MAC = Path("/Volumes/CometCloudAI/cometcloud-local")
OUT = ROOT / "tests/fixtures/state_arms_fixture.json"

SEG0, SEG1 = "2026-06-01", "2026-10-30"        # 片段(152 天 ≥ 120)
R6_WARM = "2025-09-01"                          # R6 需要 230 天历史(200 日均线 + 30 日斜率)
GATE_WARM0, GATE_WARM1 = "2026-05-18", "2026-05-30"   # 闸门片段前的热身(翻转要前一天的闸门)
S819_START = pd.Timestamp("2021-10-11")
S823_H0, S823_H1 = pd.Timestamp("2021-01-01"), pd.Timestamp("2026-10-30")

URL = os.environ["SUPABASE_URL"]
KEY = os.environ["SUPABASE_KEY"]
HDR = {"apikey": KEY, "Authorization": "Bearer " + KEY, "Prefer": "count=exact"}


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
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def cumprod(r) -> pd.Series:
    s = pd.Series(r)
    return (1.0 + s.fillna(0.0)).cumprod()


def read_export() -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    with open(HERE / "s869_extra_panel_a.csv") as f:
        for row in csv.DictReader(f):
            out.setdefault(row["family"], {})[row["d"]] = float(row["nav"])
    return out


def series_to_map(s: pd.Series) -> dict[str, float]:
    return {str(pd.Timestamp(d).date()): float(v) for d, v in s.items() if pd.notna(v)}


def bits(gate: dict[str, bool], dates: list[str]) -> str:
    return "".join("1" if gate.get(d) else "0" for d in dates)


def main() -> None:
    export = read_export()
    s823 = load_mod("s823_three_state", HERE / "s823_three_state.py")
    import t310_slots as T310

    # ── ① 研究输入 ────────────────────────────────────────────────────────────
    price_path = MAC / "research/t339/coinmetrics_price_usd.json"
    funding_path = MAC / "research/s681/_um_funding.jsonl"
    p, f_btc = s823.load(str(price_path), str(funding_path), s823.H1)     # p: BTC 收盘;f_btc: BTC 日资金费

    T310.UM = str(MAC / "research/s681/_um_daily.jsonl")
    T310.STYLE = str(MAC / "research/t156/_style.json")
    res_gate, _, _ = T310.load_gate()

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

    rb, re_ = daily("BTC"), daily("ETH")
    fb, fe = fund("BTC"), fund("ETH")
    cal = pd.date_range(S819_START - pd.Timedelta(days=5), pd.Timestamp(SEG1), freq="D")
    basket = ((rb + re_) / 2).reindex(cal)
    fnd = ((fb.reindex(cal).fillna(0) + fe.reindex(cal).fillna(0)) / 2)
    g_res = pd.Series({pd.Timestamp(k): bool(v) for k, v in res_gate.items()}).sort_index().reindex(cal).ffill()

    # ── ② 生产内核重算,整段与 T-392 导出逐日对账 ─────────────────────────────
    e = r6_exposure(p)
    ret_r6, pos_r6, sl_r6 = r6_returns(p, e, f_btc, start=str(S823_H0.date()), end=str(S823_H1.date()))
    nav_r6 = cumprod(ret_r6)
    exp_r6 = export["s823_r6"]
    common_r6 = sorted(set(exp_r6) & set(series_to_map(nav_r6)))
    diff_r6 = max(abs(nav_r6[pd.Timestamp(d)] - exp_r6[d]) for d in common_r6)
    print(f"[R6] 生产内核重算 vs T-392 导出:共同 {len(common_r6)} 天,最大差 {diff_r6:.3e}")
    if diff_r6 > 1e-9:
        raise SystemExit("R6 对账失败 —— 不写盘")

    navs_g = {}
    for s, fam in ((0.15, "s819_short_s015"), (0.30, "s819_short_s030")):
        sr, closed = gate_short_returns(basket, fnd, g_res, s)
        w = sr[sr.index >= S819_START]
        nav = cumprod(w)
        navs_g[s] = nav
        exp = export[fam]
        cm = sorted(set(exp) & set(series_to_map(nav)))
        df = max(abs(nav[pd.Timestamp(d)] - exp[d]) for d in cm)
        print(f"[GATE s={s}] 生产内核重算 vs T-392 导出:共同 {len(cm)} 天,最大差 {df:.3e}")
        if df > 1e-9:
            raise SystemExit(f"GATE s={s} 对账失败 —— 不写盘")

    # ── ③ 闸门:研究 vs 生产,逐日 ────────────────────────────────────────────
    rows, tot = sb_paged("style_index_pit_daily",
                         {"select": "d,ret", "style": "eq.majors", "weighting": "eq.cap", "order": "d.asc"})
    prod_ret = pd.Series({pd.Timestamp(x["d"]): float(x["ret"]) for x in rows
                          if x.get("ret") is not None and float(x["ret"]) > -0.95}, dtype=float).sort_index()
    prod_gate = majors_gate_from_ret(prod_ret)
    prod_gate_d = {str(pd.Timestamp(d).date()): bool(v) for d, v in prod_gate.items()}
    res_gate_d = {str(pd.Timestamp(k).date()): bool(v) for k, v in res_gate.items()}
    dates = sorted(set(prod_gate_d) & set(res_gate_d))
    mism = [d for d in dates if prod_gate_d[d] != res_gate_d[d]]
    print(f"[gate] 生产 vs 研究:重叠 {len(dates)} 天({dates[0]} → {dates[-1]}),不一致 {len(mism)} 天")
    if mism:
        raise SystemExit(f"闸门对不上(前 5 天 {mism[:5]})—— 不写盘")

    # ③ 在用的那条(multiplier._majors_gate)也要逐日相同
    from src.data.signals.multiplier import _majors_gate
    mj = asyncio.run(_majors_gate())
    mj_d = {str(pd.Timestamp(d).date()): bool(v) for d, v in mj.items()}
    mj_dates = sorted(set(mj_d) & set(res_gate_d))
    mj_mism = [d for d in mj_dates if mj_d[d] != res_gate_d[d]]
    print(f"[gate] multiplier._majors_gate vs 研究:重叠 {len(mj_dates)} 天,不一致 {len(mj_mism)} 天")
    if mj_mism:
        raise SystemExit(f"_majors_gate 与研究闸门对不上(前 5 天 {mj_mism[:5]})—— 不写盘")

    # ── ④ 片段与夹具 ──────────────────────────────────────────────────────────
    seg0, seg1 = pd.Timestamp(SEG0), pd.Timestamp(SEG1)
    base_d = str((seg0 - pd.Timedelta(days=1)).date())

    r6_slice_p = p[(p.index >= pd.Timestamp(R6_WARM)) & (p.index <= seg1)]
    r6_slice_f = f_btc[(f_btc.index >= pd.Timestamp(R6_WARM)) & (f_btc.index <= seg1)]
    nav_r6_seg = nav_r6[(nav_r6.index >= seg0) & (nav_r6.index <= seg1)]
    exp_r6_seg = {d: exp_r6[d] for d in sorted(exp_r6) if seg0 <= pd.Timestamp(d) <= seg1}
    base_r6 = exp_r6[base_d]

    g_slice = slice(pd.Timestamp(GATE_WARM0), seg1)
    basket_seg = basket[g_slice]
    fnd_seg = fnd[g_slice]
    gseg = g_res[g_slice]

    def nav_norm(exp: dict[str, float]) -> tuple[dict[str, float], float]:
        seg = {d: exp[d] for d in sorted(exp) if seg0 <= pd.Timestamp(d) <= seg1}
        b = exp[base_d]
        return {d: v / b for d, v in seg.items()}, b

    nav15, base15 = nav_norm(export["s819_short_s015"])
    nav30, base30 = nav_norm(export["s819_short_s030"])

    fixture = {
        "what": "T-406 夹具:R6(S-823 三态敞口)与 GATE_S15 / GATE_S30(S-819 闸门关时空大盘)的前向内核。",
        "how_to_read": [
            "输入 = 研究侧的原始输入(研究脚本用的那一份),期望净值 = T-392 导出的 s869_extra_panel_a.csv 同族同一段。",
            "expected_nav 是**归一化**值(以片段首日的前一日为基点);expected_nav_abs 是导出的原值;"
            "base_nav 是片段首日前一日的导出净值 —— 三者相乘/相除可复原原值。",
            "gate_equality 是研究闸门(t156/_style.json)与生产闸门(style_index_pit_daily eq.majors/eq.cap)"
            "在重叠历史上的逐日对照:位串 1 = 闸门开,0 = 闸门关;导出时逐日核对过,不一致 0 天。",
        ],
        "generated_by": "docs/research/t406_fixture_export.py",
        "segment": [SEG0, SEG1],
        "r6": {
            "arm": "R6",
            "source": "docs/research/s823_three_state.py::states/account(参数未改)",
            "input_range": [R6_WARM, SEG1],
            "close": series_to_map(r6_slice_p),
            "funding": series_to_map(r6_slice_f),
            "expected_nav": {d: v / base_r6 for d, v in exp_r6_seg.items()},
            "expected_nav_abs": exp_r6_seg,
            "base_d": base_d,
            "base_nav": base_r6,
        },
        "gate": {
            "arms": {"GATE_S15": 0.15, "GATE_S30": 0.30},
            "source": "docs/research/s819_gate_short.py::short_ret(逐行照抄)",
            "input_range": [GATE_WARM0, SEG1],
            "basket_ret": series_to_map(basket_seg),
            "funding": series_to_map(fnd_seg),
            "gate_open": {str(pd.Timestamp(d).date()): bool(v) for d, v in gseg.items()},
            "expected_nav": {"GATE_S15": nav15, "GATE_S30": nav30},
            "expected_nav_abs": {
                "GATE_S15": {d: export["s819_short_s015"][d] for d in sorted(export["s819_short_s015"])
                             if seg0 <= pd.Timestamp(d) <= seg1},
                "GATE_S30": {d: export["s819_short_s030"][d] for d in sorted(export["s869_short_s030"] if False else export["s819_short_s030"])
                             if seg0 <= pd.Timestamp(d) <= seg1},
            },
            "base_d": base_d,
            "base_nav": {"GATE_S15": base15, "GATE_S30": base30},
        },
        "gate_equality": {
            "dates": dates,
            "research": bits(res_gate_d, dates),
            "production": bits(prod_gate_d, dates),
            "overlap_days": len(dates),
            "mismatches": len(mism),
            "research_source": str(MAC / "research/t156/_style.json"),
            "production_source": "style_index_pit_daily style=eq.majors weighting=eq.cap",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(fixture, ensure_ascii=False, indent=1))
    print(f"[fixture] wrote {OUT} ({OUT.stat().st_size} bytes)")
    print(f"[fixture] R6 片段 {len(exp_r6_seg)} 天 · GATE 片段 {len(nav15)} 天 · 闸门对照 {len(dates)} 天")


if __name__ == "__main__":
    main()
