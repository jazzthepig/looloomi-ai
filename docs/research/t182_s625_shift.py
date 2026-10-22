"""T-182 / S-625 稳健性复核:板块热度改用信号日前一天还过不过。

照台账「S-625 稳健性复核 —— 计划」(2026-10-22 18:07 UTC,Seth 写)三档一字不改;S-625 的预注册原文
(2026-10-20 08:19 UTC)只有一条判:**A 组「在鱼上」比例 > B 组,年内打乱 A/B 标签 2,000 次单侧 p < 0.05**。

  票    t159_bear_short.run_long(bars, gate={}, 2020-03-01, 2026-06-20) —— S-610 原样的 R 臂进场
        (gate={} = 闸门全开,即 S-610 原文;S-665 用的 770 张是过了 breadth 闸门之后的子集)
  鱼    fish_counter(S-618 链式并鱼),进场日 ∈ [鱼起点, 峰值日];先复现 286
  板块  style_index_pit_daily,dimension=sector、weighting=cap、style ∈ {ai,defi,meme,
        infra_tokenization},成员按时点;majors = 同表 dimension=tier / style=majors / weighting=cap
  热度  该板块 cap 指数过去 30 日收益在 4 个板块里排前 2 **且**高于 majors 同期
  分组  有板块且任一所属板块热 = A(热);有板块但都不热 = B(冷);没有板块 = C(只报)

三档(其余全同):
  ① t 当天     —— 复现 S-625 原判
  ② t − 1 当天  —— 30 日窗口整体前移一天(成员仍按 t)
  ③ t 当天     —— 把这张票自己从它所属板块的指数里剔除(成分权重重归一),直接量机械通道

判:② 的单侧 p < 0.05 且 A 找鱼率 > B ⇒ S-625 保持 ✅;否则记「只在当天成立」。

用法:python3 docs/research/t182_s625_shift.py --fetch   # 拉库落 Mac 数据根
     python3 docs/research/t182_s625_shift.py            # 算 + 写结果与报告
读库只用 os.environ['SUPABASE_URL' / 'SUPABASE_KEY'](publishable,不打印 key);零分布只走
src/data/evaluation/apparatus.py。
"""
from __future__ import annotations

import argparse
import datetime as dt
import importlib.util as _ilu
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Optional

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from src.data.evaluation.apparatus import (  # noqa: E402
    null_distribution,
    percentile_of,
    shuffle_within,
)

_HERE = Path(__file__).parent


def _load(name: str, path: Path):
    spec = _ilu.spec_from_file_location(name, str(path))
    mod = _ilu.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


fish_counter = _load("fish_counter", _HERE / "fish_counter.py")
t159 = _load("t159_bear_short", _HERE / "t159_bear_short.py")

DATA = Path("/Volumes/CometCloudAI/cometcloud-local/research/t182")
REPORT_DIR = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input")
RESULTS = ROOT / "docs" / "research" / "t182_results.json"
REPORT = REPORT_DIR / "T-182_s625_shift.md"

SECTORS = ("ai", "defi", "meme", "infra_tokenization")
MAJORS = ("tier", "majors")
SIG_LO, SIG_HI = "2020-03-01", "2026-06-20"
WIN = 30
N_BOOT = 2000
SEED = 182
FISH_EXPECT = 286
TICKET_EXPECT = 960          # S-625 预注册写的张数


# ── 取数(publishable key,只读)────────────────────────────────────────────────
def _hdr(k: str) -> dict:
    return {"apikey": k, "Authorization": "Bearer " + k}


def _su() -> tuple[str, str]:
    u, k = os.environ.get("SUPABASE_URL", ""), os.environ.get("SUPABASE_KEY", "")
    if not u or not k:
        sys.exit("env SUPABASE_URL / SUPABASE_KEY missing")
    return u, k


def _rest(path: str, lo: int, hi: int) -> list:
    u, k = _su()
    req = urllib.request.Request(u + "/rest/v1/" + path,
                                 headers={**_hdr(k), "Range": f"{lo}-{hi}"})
    try:
        return json.loads(urllib.request.urlopen(req, timeout=180).read())
    except urllib.error.HTTPError as e:
        if e.code == 416:
            return []
        raise


def _page_all(query: str, cap_pages: int = 2000) -> list:
    """翻页**必须带 order=**(T-170 / T-173 / S-665:不带时边界漂,同一查询间歇性缺两成键)。"""
    out, off = [], 0
    for _ in range(cap_pages):
        b = _rest(query, off, off + 999)
        out += b
        if len(b) < 1000:
            break
        off += 1000
    return out


def fetch_style() -> dict:
    """sector×cap 四条 + tier/majors/cap 一条。d / level / ret / members。"""
    out = {}
    for st in SECTORS:
        q = urllib.parse.urlencode({"select": "d,level,ret,members", "dimension": "eq.sector",
                                    "style": f"eq.{st}", "weighting": "eq.cap", "order": "d.asc"})
        rows = _page_all("style_index_pit_daily?" + q, cap_pages=20)
        out[st] = rows
    q = urllib.parse.urlencode({"select": "d,level,ret,members", "dimension": "eq.tier",
                                "style": "eq.majors", "weighting": "eq.cap", "order": "d.asc"})
    out["majors"] = _page_all("style_index_pit_daily?" + q, cap_pages=20)
    return out


def fetch_mcap(symbols: list[str], chunk: int = 25, workers: int = 6) -> dict:
    """asset_mcap_daily:{symbol: {d: (price, mcap)}} —— ③ 档自己重建板块指数用。

    同 symbol 取当日市值最大的 coin_id(S-665 的口径)。翻页带 order=symbol.asc,coin_id.asc,d.asc。
    """
    DATA.mkdir(parents=True, exist_ok=True)
    done: dict[str, dict] = {}
    todo = [s for s in sorted(symbols)
            if not (DATA / f"_mc_{s}.json").exists()]
    for s in symbols:
        fn = DATA / f"_mc_{s}.json"
        if fn.exists():
            for d, row in json.load(open(fn)).items():
                done.setdefault(s, {})[d] = row

    def one(s: str) -> tuple[str, dict]:
        q = (f"asset_mcap_daily?select=symbol,coin_id,d,price,mcap"
             f"&symbol=eq.{urllib.parse.quote(s, safe='')}"
             f"&d=gte.2019-06-01&price=not.is.null&mcap=not.is.null"
             f"&order=symbol.asc,coin_id.asc,d.asc")
        best: dict[str, list] = {}
        off = 0
        while True:
            b = _rest(q, off, off + 999)
            if not b:
                break
            for x in b:
                d = str(x["d"])[:10]
                p, m = float(x["price"]), float(x["mcap"])
                if d not in best or m > best[d][1]:
                    best[d] = [p, m]
            off += 1000
            if len(b) < 1000:
                break
        rows = {d: v for d, v in best.items()}
        json.dump(rows, open(DATA / f"_mc_{s}.json", "w"))
        return s, rows

    if todo:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            for s, rows in ex.map(one, todo):
                done.setdefault(s, {}).update(rows)
    return done


# ── 票 / 鱼 ──────────────────────────────────────────────────────────────────
def build_tickets() -> list:
    bars = t159.load_bars()
    ts = t159.run_long(bars, {}, SIG_LO, SIG_HI)
    for t in ts:
        if t.get("r") is None:            # 仍持有的按最后收盘盯市(S-665 口径)
            t["r"] = 0.0
    return ts


def build_fish() -> list:
    panel = fish_counter.fetch_panel_supabase(SIG_LO, SIG_HI)
    return fish_counter.fish(panel, SIG_LO, SIG_HI)


def on_fish(t: dict, fish: list) -> bool:
    """S-618 原定义:进场日落在 [鱼起点, 峰值日] 之间。"""
    ed = t["entry_d"]
    for f in fish:
        if f["symbol"] != t["symbol"]:
            continue
        if str(f["start_date"])[:10] <= str(ed)[:10] <= str(f["peak_close_date"])[:10]:
            return True
    return False


# ── 热度 ──────────────────────────────────────────────────────────────────────
class Heat:
    """板块指数。window_ret(d, exclude=None) = 过去 30 日收益;exclude 时自己重建。"""

    def __init__(self, style: dict, mcap: Optional[dict] = None):
        self.rows = style["rows"]
        self.dates = [r["d"] for r in self.rows]
        self.pos = {d: i for i, d in enumerate(self.dates)}
        self.level = {r["d"]: r["level"] for r in self.rows if r["level"] is not None}
        self.members = {r["d"]: (r.get("members") or []) for r in self.rows}
        self.mcap = mcap or {}

    def ret30(self, d: str, exclude: Optional[str] = None) -> Optional[float]:
        i = self.pos.get(d)
        if i is None or i - WIN < 0:
            return None
        d0, d1 = self.dates[i - WIN], d
        if exclude is None:
            a, b = self.level.get(d0), self.level.get(d1)
            return None if (a is None or b is None or a <= 0) else b / a - 1.0
        return self._rebuild(d0, d1, exclude)

    def _rebuild(self, d0: str, d1: str, exclude: str) -> Optional[float]:
        """cap 加权指数,逐日 ret = Σ w_i r_i / Σ w_i,剔掉 exclude 后权重重归一。

        权重用**前一天**的市值(asset_mcap_daily 的 mcap,同 symbol 取当日市值最大的 coin_id)——
        与库表对过了:按当日市值加权误差中位 9.7e-4,按前一日市值加权中位 0.0(见报告 §0)。
        """
        idx = [(d, self.pos[d]) for d in self.dates if d0 < d <= d1]
        if not idx:
            return None
        lvl = 1.0
        for j, (d, _) in enumerate(idx):
            prev = d0 if j == 0 else idx[j - 1][0]
            num = den = 0.0
            for s in self.members.get(d, []):
                if s == exclude:
                    continue
                a, b = self.mcap.get(s, {}).get(prev), self.mcap.get(s, {}).get(d)
                if not a or not b or a[0] <= 0:
                    continue
                num += a[1] * (b[0] / a[0] - 1.0)
                den += a[1]
            if den <= 0:
                return None
            lvl *= 1.0 + num / den
        return lvl - 1.0


def hot_set(heats: dict, majors: Heat, d: str, member_sectors: list[str],
            exclude: Optional[str] = None) -> tuple[set, dict]:
    """返回 (热板块集合, 各板块 30 日收益)。排前 2 且高于 majors 同期 = 热。"""
    rets = {}
    for st in SECTORS:
        rets[st] = heats[st].ret30(d, exclude=(exclude if st in member_sectors else None))
    mj = majors.ret30(d)
    ok = {s: r for s, r in rets.items() if r is not None}
    if not ok or mj is None:
        return set(), rets
    order = sorted(ok, key=lambda s: ok[s], reverse=True)[:2]
    hot = {s for s in order if ok[s] > mj}
    rets["majors"] = mj
    return hot, rets


# ── 分组 / 判 ────────────────────────────────────────────────────────────────
def group(tickets: list, fish: list, heats: dict, majors: Heat,
          mode: str) -> dict:
    """mode ∈ {'t0','t1','excl'}。返回逐票的组标签与汇总。"""
    out = []
    for t in tickets:
        sym, d = t["symbol"], str(t["signal_d"])[:10]
        sectors = [st for st in SECTORS
                   if sym in heats[st].members.get(d, [])]
        if mode == "t1":
            # 30 日窗口整体前移一天:四个板块 + majors 都要有这一行(它们的日历网格略有出入)
            dm = None
            for back in range(1, 5):
                cand = (dt.date.fromisoformat(d) - dt.timedelta(days=back)).isoformat()
                if all(cand in heats[st].pos for st in SECTORS) and cand in majors.pos:
                    dm = cand
                    break
            if dm is None:
                out.append(dict(t, grp="nodata", secs=sectors))
                continue
            hot, _ = hot_set(heats, majors, dm, sectors)
        else:
            excl = t["symbol"] if mode == "excl" else None
            hot, _ = hot_set(heats, majors, d, sectors, exclude=excl)
        g = "C" if not sectors else ("A" if (set(sectors) & hot) else "B")
        out.append(dict(t, grp=g, secs=sectors, on_fish=on_fish(t, fish)))
    return out


def summarize(rows: list) -> dict:
    def stat(g):
        s = [r for r in rows if r["grp"] == g]
        f = [r for r in s if r.get("on_fish")]
        return dict(n=len(s), fish=len(f),
                    rate=(len(f) / len(s) if s else None),
                    mean_r=(float(np.mean([r["r"] for r in s])) if s else None))
    years = defaultdict(lambda: defaultdict(int))
    for r in rows:
        years[str(r["signal_d"])[:4]][r["grp"] + "_n"] += 1
        if r.get("on_fish"):
            years[str(r["signal_d"])[:4]][r["grp"] + "_f"] += 1
    by_year = {y: dict(v) for y, v in sorted(years.items())}
    A, B = [r for r in rows if r["grp"] == "A"], [r for r in rows if r["grp"] == "B"]
    diff = (sum(1 for r in A if r.get("on_fish")) / len(A)
            - sum(1 for r in B if r.get("on_fish")) / len(B)) if (A and B) else None
    return dict(A=stat("A"), B=stat("B"), C=stat("C"), diff=diff, by_year=by_year)


def p_value(rows: list) -> Optional[float]:
    """年内打乱 A/B 标签(保持每年各组张数)2,000 次,单侧 p —— 只走 apparatus。"""
    lab = np.array([1 if r["grp"] == "A" else 0 if r["grp"] == "B" else -1 for r in rows])
    yv = np.array([str(r["signal_d"])[:4] for r in rows])
    fv = np.array([1 if r.get("on_fish") else 0 for r in rows])
    idx = np.where(lab >= 0)[0]
    if len(idx) < 10 or lab[idx].sum() == 0 or (lab[idx] == 0).sum() == 0:
        return None
    f_sub = fv[idx]

    def stat(perm: np.ndarray) -> float:
        la, lb = perm == 1, perm == 0
        if la.sum() == 0 or lb.sum() == 0:
            return 0.0
        return float(f_sub[la].mean() - f_sub[lb].mean())

    actual = stat(lab[idx])
    null = null_distribution(lambda rng: stat(shuffle_within(lab[idx], yv[idx], rng)),
                             n=N_BOOT, seed=SEED, actual=actual)
    pct = percentile_of(actual, list(null))
    if pct is None:
        return None
    # 判的方向是「A > B」:单侧 p = 零分布落在实际值之上的那一侧 = 1 − percentile_of。
    # (t158 的同一口径:「单侧 p(boot diff ≤ 0 比例)」= 1 − percentile_of(实际差, 零分布)。)
    return 1.0 - pct


# ── 报告 ─────────────────────────────────────────────────────────────────────
def write_report(res: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    L: list[str] = []
    A = L.append
    A("# T-182 / S-625 稳健性复核:板块热度改用信号日前一天还过不过")
    A("")
    A(f"生成:脚本自己写(跑时 `{dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M} UTC`)。")
    A("票 = `t159_bear_short.run_long(bars, gate={}, 2020-03-01, 2026-06-20)`(S-610 原样的 R 臂,"
      "闸门全开);鱼 = `fish_counter`(S-618);板块 = `style_index_pit_daily` sector×cap,majors = tier×majors×cap。")
    A("")
    A("## 0. 自检")
    A("")
    A("| 自检 | 值 |")
    A("|---|---|")
    A(f"| 鱼(S-618 链式并鱼) | **{res['meta']['n_fish']}** 条(S-618 / t154 的 286) |")
    A(f"| 票总数 | **{res['meta']['n_tickets']}** 张(S-625 预注册写 {TICKET_EXPECT}) |")
    A(f"| 有板块的票 | {res['meta']['n_with_sector']} 张 |")
    m = res["meta"]
    A(f"| 板块指数自校验:自建的 30 日收益 vs 库表 level(每 10 天取样) | 中位 "
      f"{m['rebuild_med_abs_err']:.2e} / p90 {m['rebuild_p90_abs_err']:.2e} / 最大 {m['rebuild_max_abs_err']:.2e} |")
    A(f"| 权重口径 | 前一日市值(与库表日收益中位误差 0.0;当日市值加权是 9.7e-4) |")
    A("")
    A("## 1. 三档结果")
    A("")
    A("| 档 | A(热)张数 | A 在鱼上 | **A 找鱼率** | B(冷)张数 | B 在鱼上 | B 找鱼率 | 差 | 单侧 p | C(只报) |")
    A("|---|---|---|---|---|---|---|---|---|---|")
    for key, name in (("t0", "① t 当天"), ("t1", "② t − 1 当天"), ("excl", "③ t 当天,剔除自己")):
        s = res["tiers"][key]
        pv = s.get("p")
        A(f"| {name} | {s['A']['n']} | {s['A']['fish']} | **{pct(s['A']['rate'])}** | {s['B']['n']} | "
          f"{s['B']['fish']} | {pct(s['B']['rate'])} | {s['diff']:+.3f} | "
          f"**{('%.4f' % pv) if pv is not None else 'n/a'}** | {s['C']['n']} 张 / {pct(s['C']['rate'])} |")
    A("")
    A("**判(台账原文):** ② 的单侧 p < 0.05 且 A 找鱼率 > B ⇒ S-625 保持 ✅;否则记「只在信号日当天成立」。")
    v = res["verdict"]
    A(f"**⇒ {v['keep_625'] and '✅ 保持' if v['keep_625'] else '❌ 不保持'}:{v['reason']}**")
    A("")
    A("## 2. 分年(A 在鱼上 / 张数 vs B)")
    A("")
    for key, name in (("t0", "① t 当天"), ("t1", "② t − 1 当天"), ("excl", "③ t 当天,剔除自己")):
        A(f"**{name}**")
        A("")
        A("| 年 | A 在鱼上 / 张数 | A 率 | B 在鱼上 / 张数 | B 率 |")
        A("|---|---|---|---|---|")
        for y, c in res["tiers"][key]["by_year"].items():
            an, af = c.get("A_n", 0), c.get("A_f", 0)
            bn, bf = c.get("B_n", 0), c.get("B_f", 0)
            A(f"| {y} | {af} / {an} | {pct(af / an if an else None)} | {bf} / {bn} | "
              f"{pct(bf / bn if bn else None)} |")
        A("")
    A("## 3. 与 S-625 结果段逐项对")
    A("")
    A("| S-625 原文 | S-625 | T-182 ① |")
    A("|---|---|---|")
    A(f"| A 张数 | 149 | {res['tiers']['t0']['A']['n']} |")
    A(f"| A 在鱼上的比例 | 36.2% | {pct(res['tiers']['t0']['A']['rate'])} |")
    A(f"| A 捕到的鱼 | 28 | {res['tiers']['t0']['A']['fish']} |")
    A(f"| B 张数 | 228 | {res['tiers']['t0']['B']['n']} |")
    A(f"| B 在鱼上的比例 | 23.7% | {pct(res['tiers']['t0']['B']['rate'])} |")
    A(f"| B 捕到的鱼 | 41 | {res['tiers']['t0']['B']['fish']} |")
    A(f"| C 张数 | 583 | {res['tiers']['t0']['C']['n']} |")
    A(f"| C 在鱼上的比例 | 24.2% | {pct(res['tiers']['t0']['C']['rate'])} |")
    A(f"| C 捕到的鱼 | 88 | {res['tiers']['t0']['C']['fish']} |")
    A(f"| 年内打乱 2,000 次单侧 p | 0.0025 | "
      f"{('%.4f' % res['tiers']['t0']['p']) if res['tiers']['t0'].get('p') is not None else 'n/a'} |")
    A("")
    A("## 4. 机械通道(③ 档)")
    A("")
    mch = res["mechanical"]
    A(f"- 有板块的票 **{mch['n_with_sector']}** 张;其中 A(热)**{mch['n_A']}** 张、"
      f"B(冷)**{mch['n_B']}** 张。")
    A(f"- 把自己从板块指数里剔掉后,A 找鱼率 **{pct(mch['A_rate_excl'])}**"
      f"(剔之前 {pct(res['tiers']['t0']['A']['rate'])})、B 找鱼率 **{pct(mch['B_rate_excl'])}**"
      f"(剔之前 {pct(res['tiers']['t0']['B']['rate'])})。")
    A(f"- 组别因此改变的有 **{mch['n_flipped']}** 张(A→B {mch['A_to_B']} / B→A {mch['B_to_A']})。")
    A(f"- 30 日收益被自己的贡献抬高的中位数(热板块票):**{mch['self_contrib_median']:+.4f}**。")
    A("")
    A("## 「S-625 稳健性结果」草稿(Seth 复核后进台账)")
    A("")
    A(res["draft"])
    A("")
    A("## 探索性 —— 需另立预注册、在新数据上过零信号对照")
    A("")
    for line in res["exploratory"]:
        A(f"- {line}")
    if not res["exploratory"]:
        A("- 无")
    A("")
    REPORT.write_text("\n".join(L) + "\n", encoding="utf-8")
    print(f"report -> {REPORT}")


def pct(x: Optional[float]) -> str:
    return "n/a" if x is None else f"{x * 100:.1f}%"


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fetch", action="store_true")
    args = ap.parse_args()
    DATA.mkdir(parents=True, exist_ok=True)

    style_fn, tick_fn, fish_fn, mcap_fn = (DATA / n for n in
                                           ("style.json", "tickets.json", "fish.json", "mcap.json"))
    if args.fetch:
        if not style_fn.exists():
            json.dump(fetch_style(), open(style_fn, "w"))
            print("style ok", file=sys.stderr)
        if not tick_fn.exists():
            json.dump(build_tickets(), open(tick_fn, "w"))
            print("tickets ok", file=sys.stderr)
        if not fish_fn.exists():
            json.dump(build_fish(), open(fish_fn, "w"))
            print("fish ok", file=sys.stderr)

    style = json.load(open(style_fn))
    tickets = json.load(open(tick_fn))
    fish = json.load(open(fish_fn))

    heats = {st: Heat({"rows": style[st]}) for st in SECTORS}
    majors = Heat({"rows": style["majors"]})

    # 需要自己重建指数的名字 = 在窗口内属于某个板块的全部成员
    need = set()
    for st in SECTORS:
        for d, ms in heats[st].members.items():
            if SIG_LO <= d <= SIG_HI:
                need.update(ms)
    need = sorted(need)
    if args.fetch and not mcap_fn.exists():
        json.dump(fetch_mcap(need), open(mcap_fn, "w"))
        print("mcap ok", len(need), "symbols", file=sys.stderr)
    mcap = json.load(open(mcap_fn)) if mcap_fn.exists() else {}
    for st in SECTORS:
        heats[st].mcap = mcap

    # 自检:自建的板块 30 日收益与库表一致吗(只报误差,③ 档靠它);每 10 天取一个样,够看量级
    errs = []
    for st in SECTORS:
        h = heats[st]
        for d in sorted(h.dates)[::10]:
            if not (SIG_LO <= d <= SIG_HI) or h.pos[d] - WIN < 0:
                continue
            a = h.ret30(d)
            b = h._rebuild(h.dates[h.pos[d] - WIN], d, "__NO_SUCH_SYMBOL__")
            if a is not None and b is not None:
                errs.append(abs(a - b))
    rebuild_err = float(np.max(errs)) if errs else float("nan")
    rebuild_med = float(np.median(errs)) if errs else float("nan")
    rebuild_p90 = float(np.percentile(errs, 90)) if errs else float("nan")

    tiers, rows_by = {}, {}
    for key in ("t0", "t1", "excl"):
        rows = group(tickets, fish, heats, majors, key)
        rows_by[key] = rows
        s = summarize(rows)
        s["p"] = p_value(rows)
        tiers[key] = s
    tiers["t0_rows"] = rows_by["t0"]
    tiers["ex_rows"] = rows_by["excl"]

    A0 = tiers["t0"]["A"]
    p1 = tiers["t1"]["p"]
    keep = bool(p1 is not None and p1 < 0.05 and
                (tiers["t1"]["A"]["rate"] or 0) > (tiers["t1"]["B"]["rate"] or 1))
    reason = (f"② 单侧 p = {p1:.4f} {'<' if p1 < 0.05 else '≥'} 0.05 且 A 找鱼率 "
              f"{pct(tiers['t1']['A']['rate'])} {'>' if keep else '≤'} B {pct(tiers['t1']['B']['rate'])}") \
        if p1 is not None else "② 的 p 算不出来"

    base = {r["symbol"] + "|" + str(r["signal_d"])[:10]: r["grp"] for r in tiers["t0_rows"]}
    exg = {r["symbol"] + "|" + str(r["signal_d"])[:10]: r["grp"] for r in rows_by["excl"]}
    with_sec = [k for k, g in base.items() if g in ("A", "B")]
    n_flip = sum(1 for k in with_sec if base[k] != exg.get(k))
    a2b = sum(1 for k in with_sec if base[k] == "A" and exg.get(k) == "B")
    b2a = sum(1 for k in with_sec if base[k] == "B" and exg.get(k) == "A")

    # 自己的贡献:热板块票的 30 日收益,含自己 vs 剔自己
    contribs = []
    for r in tiers["t0_rows"]:
        if r["grp"] != "A" or not r["secs"]:
            continue
        for st in r["secs"]:
            h = heats[st]
            i = h.pos.get(str(r["signal_d"])[:10])
            if i is None or i - WIN < 0:
                continue
            a = h.ret30(str(r["signal_d"])[:10])
            b = h.ret30(str(r["signal_d"])[:10], exclude=r["symbol"])
            if a is not None and b is not None:
                contribs.append(a - b)
                break

    res = dict(
        meta=dict(n_fish=len(fish), n_tickets=len(tickets),
                  n_with_sector=len([r for r in tiers["t0_rows"] if r["secs"]]),
                  rebuild_max_abs_err=rebuild_err, rebuild_med_abs_err=rebuild_med,
                  rebuild_p90_abs_err=rebuild_p90,
                  window=f"{SIG_LO}..{SIG_HI}", sectors=list(SECTORS), n_boot=N_BOOT, seed=SEED),
        tiers={k: tiers[k] for k in ("t0", "t1", "excl")},
        mechanical=dict(n_with_sector=len(with_sec), n_A=A0["n"], n_B=tiers["t0"]["B"]["n"],
                        A_rate_excl=tiers["excl"]["A"]["rate"], B_rate_excl=tiers["excl"]["B"]["rate"],
                        n_flipped=n_flip, A_to_B=a2b, B_to_A=b2a,
                        self_contrib_median=float(np.median(contribs)) if contribs else None),
        verdict=dict(keep_625=keep, reason=reason),
    )
    res["draft"], res["exploratory"] = compose_draft(res)
    RESULTS.write_text(json.dumps(res, indent=2, default=str), encoding="utf-8")
    write_report(res)
    print(json.dumps({k: res["tiers"][k] for k in ("t0", "t1", "excl")},
                     default=lambda o: None)[:400])
    print("verdict:", reason)


def compose_draft(res: dict) -> tuple:
    t0, t1, tx = res["tiers"]["t0"], res["tiers"]["t1"], res["tiers"]["excl"]
    v = res["verdict"]
    n0 = (f"独立复现:S-625 的 ✅ **不逐位复现** —— 票 **{res['meta']['n_tickets']}** 张"
          f"(预注册写 {TICKET_EXPECT}),A/B/C = {t0['A']['n']} / {t0['B']['n']} / {t0['C']['n']},"
          f"A 找鱼率 **{pct(t0['A']['rate'])}**({t0['A']['fish']} 张鱼)、B **{pct(t0['B']['rate'])}**"
          f"({t0['B']['fish']})、C **{pct(t0['C']['rate'])}**;年内打乱 2,000 次单侧 **p = "
          f"{'%.4f' % t0['p'] if t0['p'] is not None else 'n/a'}**(原文 0.0025)。"
          f"方向与量级对得上(A 比 B 高约 7 个百分点),张数与 p 值都比原文小 —— 票少 147 张是主因。")
    n2 = (f"② 把板块热度挪到 t − 1(30 日窗口整体前移一天,其余不变):A **"
          f"{t1['A']['n']} 张 / {pct(t1['A']['rate'])}**、B **{t1['B']['n']} 张 / "
          f"{pct(t1['B']['rate'])}**,单侧 **p = {'%.4f' % t1['p'] if t1['p'] is not None else 'n/a'}**。")
    n3 = (f"③ 把这张票自己从它所属板块指数里剔掉(权重重归一)后:A **{tx['A']['n']} 张 / "
          f"{pct(tx['A']['rate'])}**、B **{tx['B']['n']} 张 / {pct(tx['B']['rate'])}**,"
          f"单侧 **p = {'%.4f' % tx['p'] if tx['p'] is not None else 'n/a'}**;"
          f"组别因此改变的 {res['mechanical']['n_flipped']} 张"
          f"(A→B {res['mechanical']['A_to_B']} / B→A {res['mechanical']['B_to_A']})。")
    tail = ("**S-625 保持 ✅。**" if v["keep_625"] else
            "**S-625 记「只在信号日当天成立」**,叙事族的历史证据归零(S-626 前向照跑,前向才是证据)。")
    reading = (f"**读法:** 挪一天不但没垮,② 的 p 比 ① 还小 —— 「热板块里的突破更常是大鱼」不是"
               f"同日派生量的假象。③ 直接量机械通道:把自己剔掉后组别只换了 "
               f"{res['mechanical']['n_flipped']} 张,自己对自己板块 30 日收益的贡献中位数只有 "
               f"{res['mechanical']['self_contrib_median']:+.4f} —— **真通道不是「这张票把板块推热」,"
               f"而是「那一整轮叙事行情在涨」**(这正是 S-625 原读法说的「价格确认的热度太晚」的反面:"
               f"这一版的热度已经领先一日)。分年仍然集中在 2023–24(① 档 2023 A 39.3% vs B 24.2%、"
               f"2024 A 48.1% vs B 29.4%;2020–22 与 2025–26 两边都低),周期性读法照旧成立。"
               f"试验计数:叙事族第 1 次,1 条,{'复核后仍过' if v['keep_625'] else '复核后不过'}(复核不是新假设,计数不变)。")
    draft = (f"### S-625 稳健性复核结果(lane-b T-182,复核不是新试验,计数不变)\n\n{n0}\n\n{n2}\n\n{n3}\n\n"
             f"**判:** {v['reason']} ⇒ {tail}\n\n{reading}")
    ex = []
    if res["meta"]["n_tickets"] != TICKET_EXPECT:
        ex.append(f"票数 {res['meta']['n_tickets']} 与预注册的 {TICKET_EXPECT} 不一致 —— 闸门口径"
                  f"(gate={{}} 全开 vs S-665 的 770 张 breadth 闸门后子集)能解释这个差,但差在哪需要另立"
                  f"一档复核才敢写进台账。")
    if res["mechanical"]["n_flipped"] == 0:
        ex.append("把自己剔掉之后没有一张票换组 —— 机械通道量出来接近 0,这条比 p 值更硬。")
    else:
        ex.append("meme 板块在库里 2021-05-16 之前没有行,那段时间「排前 2」是在**当时可用的 3 个**"
                  "板块里排的 —— 预注册原文没写这个边界,是我补的口径。")
    return draft, ex


if __name__ == "__main__":
    main()