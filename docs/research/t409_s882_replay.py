"""T-409 ④:把 S-882 那张「周末大跌之后两边都被扫」的表原样重出一遍。

台账(SETUP_REGISTRY.md 形态 #5 / S-882)记的数:
  - 「之后 ±2.5 – 3% 以上的偏移」:条件组 60 – 70%,普通周末 26 – 45%
  - 「反弹高点被碰到」:65% 对 77%(条件组 / 不带条件的全部周末)
  - 「周末低点被碰到」:43 – 50% 对 53 – 59%
  - 方向无

口径(本脚本写死;台账那份是 Seth 直接用 SQL 量的,口径没入库,所以这里把口径也一并写出来):
  样本 = 一个周末。周五 22:00 UTC(价 p_fri22)→ 周日 06:00 UTC(价 p0 = 观察点)。
  条件组 = 周五 22:00 起跌幅 ≥ 阈值(BTC 3% / ETH 4%)。
  观察窗 = 周日 06:00 → 下周一 13:00 UTC(31 小时;与结算器 `high:/low:` 的窗口同一个定义)。
  对照组(§每张基率表必须自带的对照 S-882):全部周末 + 两个「只满足一半」的组
    - 波动大但没跌到阈值(区间宽,方向不是跌)
    - 整周跌但周五 22:00 之后没跌(跌在周末之前)
  结局:上冲 / 下探 / 任一边(用 apparatus.max_excursions);
        反弹高点被碰到 / 周末低点被碰到 / 两边都被碰到(用 apparatus.touched_before)。

用法(仓库根目录):
    nohup python3 docs/research/t409_s882_replay.py > docs/research/t409_s882_run.txt 2>&1 &
写 docs/research/t409_s882_replay.json
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))


def _load(name, path):
    sp = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


apparatus = _load("apparatus", os.path.join(ROOT, "src", "data", "evaluation", "apparatus.py"))

URL = os.environ.get("SUPABASE_URL")
KEY = os.environ.get("SUPABASE_KEY")
if not URL or not KEY:
    sys.exit("需要 SUPABASE_URL / SUPABASE_KEY")

# 阈值:条件(状态)与偏移(读数)分开 —— SETUP 形态 #5 写的是 BTC ≥ 3% / ETH ≥ 4%
COND_THR = {"BTC": 0.03, "ETH": 0.04}
OFF_THR = {"BTC": 0.025, "ETH": 0.03}
OFF_ALT = 0.03          # 台账写「±2.5 – 3%」,可能是两个币各一个阈值,也可能是同一族两个候选
PRE_LOW_FRAC = None     # 周末低点 = 观察点之前那一段的最低价(绝对价位)

WINDOW_END_HOUR = 13    # 周一 13:00 UTC


def _get(path, count=False):
    h = {"apikey": KEY, "Authorization": "Bearer " + KEY}
    if count:
        h["Prefer"] = "count=exact"
    r = urllib.request.Request(URL + "/rest/v1/" + path, headers=h)
    resp = urllib.request.urlopen(r)
    return json.load(resp), resp.headers.get("Content-Range")


def load_hourly(sym: str):
    """整表拉下来:每页 1000 行 + order=ts.asc(offset 分页);核总行数。"""
    rows, cr = _get(
        f"ohlcv_hourly?select=ts,open,high,low,close&symbol=eq.{sym}"
        f"&source=eq.binance_hist&order=ts.asc&limit=1000",
        count=True,
    )
    total = None
    if cr and "/" in cr:
        tail = cr.rsplit("/", 1)[-1]
        if tail.isdigit():
            total = int(tail)
    out = list(rows)
    while len(rows) == 1000:
        off = len(out)
        rows, _ = _get(
            f"ohlcv_hourly?select=ts,open,high,low,close&symbol=eq.{sym}"
            f"&source=eq.binance_hist&order=ts.asc&limit=1000&offset={off}"
        )
        if not rows:
            break
        out.extend(rows)
    if total is not None and len(out) != total:
        raise SystemExit(f"{sym}: 抓到 {len(out)} 行,与库里 {total} 行不符 —— 不算数")
    bars = []
    for r in out:
        t = dt.datetime.fromisoformat(str(r["ts"]).replace("Z", "+00:00")).astimezone(dt.timezone.utc)
        f = lambda x: (float(x) if x is not None else None)
        o, h, l, c = f(r.get("open")), f(r.get("high")), f(r.get("low")), f(r.get("close"))
        if None in (o, h, l, c):
            continue
        bars.append((t, o, h, l, c))
    return bars, total


def build_samples(bars):
    """一个周末 = 一个样本。缺 bar 的周末直接丢掉(判不了的不算分母)。"""
    by_ts = {b[0]: b for b in bars}
    days = sorted({b[0].date() for b in bars})
    out = []
    for mon in days:
        if mon.weekday() != 0:                       # 只看周一,凑一周
            continue
        fri22 = dt.datetime.combine(mon - dt.timedelta(days=1), dt.time(22, 0), dt.timezone.utc)
        sun06 = dt.datetime.combine(mon + dt.timedelta(days=6), dt.time(6, 0), dt.timezone.utc)
        next_mon13 = dt.datetime.combine(mon + dt.timedelta(days=7), dt.time(WINDOW_END_HOUR, 0), dt.timezone.utc)
        mon00 = dt.datetime.combine(mon, dt.time(0, 0), dt.timezone.utc)
        need = [fri22, sun06, mon00]
        if any(t not in by_ts for t in need):
            continue
        pre = [b for b in bars if fri22 <= b[0] < sun06]
        win = [b for b in bars if sun06 <= b[0] < next_mon13]
        if len(pre) < 24 or len(win) < 24:
            continue
        p_fri22 = by_ts[fri22][4]
        p0 = by_ts[sun06][4]
        p_mon00 = by_ts[mon00][4]
        if min(p_fri22, p0, p_mon00) <= 0:
            continue
        pre_high = max(b[2] for b in pre)
        pre_low = min(b[3] for b in pre)
        out.append({
            "mon": mon.isoformat(),
            "p_fri22": p_fri22,
            "p0": p0,
            "p_mon00": p_mon00,
            "pre_high": pre_high,
            "pre_low": pre_low,
            "pre_width": (pre_high - pre_low) / p_fri22,
            "dd_fri22": p0 / p_fri22 - 1.0,
            "dd_week": p0 / p_mon00 - 1.0,
            "win": win,
        })
    return out


def make_outcomes(sym):
    thr = OFF_THR[sym]
    alt = OFF_ALT

    def _exc(s, key):
        up, dn = apparatus.max_excursions(s["win"], s["p0"])
        return up, dn

    def up_t(thr):
        return lambda s: (_exc(s, 0)[0] is not None and _exc(s, 0)[0] >= thr)

    def dn_t(thr):
        return lambda s: (_exc(s, 0)[1] is not None and _exc(s, 0)[1] <= -thr)

    def either(thr):
        def f(s):
            up, dn = _exc(s, 0)
            return (up is not None and up >= thr) or (dn is not None and dn <= -thr)
        return f

    def rebound_high(s):
        return apparatus.touched_before(s["win"], s["pre_high"], "up")

    def weekend_low(s):
        return apparatus.touched_before(s["win"], s["pre_low"], "down")

    def both(s):
        return rebound_high(s) and weekend_low(s)

    def first_side(s):
        return apparatus.first_touch(s["win"], s["pre_high"], s["pre_low"]) == "up"

    return {
        f"up>={thr*100:.1f}%": up_t(thr),
        f"down>={thr*100:.1f}%": dn_t(thr),
        f"either>={thr*100:.1f}%": either(thr),
        f"up>={alt*100:.1f}%": up_t(alt),
        f"down>={alt*100:.1f}%": dn_t(alt),
        f"either>={alt*100:.1f}%": either(alt),
        "rebound_high_touched": rebound_high,
        "weekend_low_touched": weekend_low,
        "both_touched": both,
        "first_side_up": first_side,
    }


def make_groups(sym):
    thr = COND_THR[sym]

    def condition(s):
        return s["dd_fri22"] <= -thr

    def wide_but_not_down(s):
        return s["pre_width"] >= thr and s["dd_fri22"] > -thr

    def week_down_not_fri22(s):
        return s["dd_week"] <= -thr and s["dd_fri22"] > -thr

    return condition, {"波动大但没跌到阈值": wide_but_not_down,
                       "整周跌但周五22:00后没跌": week_down_not_fri22}


def pct(rec, key):
    r = rec.get(key) or {}
    return r.get("rate")


def main():
    result = {
        "card": "T-409",
        "what": "S-882(形态 #5)那张基率表的重出:用 apparatus 的走法原子函数 + 强制带对照组的 base_rate_table",
        "definitions": {
            "sample": "一个周末(ISO 周)",
            "p_fri22": "周五 22:00 UTC 那根小时线的 close",
            "p0": "周日 06:00 UTC 那根小时线的 close(= 观察点)",
            "window": "周日 06:00 → 下周一 13:00 UTC(含起点、不含终点;与结算器 high:/low: 的窗口定义一致)",
            "pre_high": "周五 22:00 → 周日 06:00 之间的最高价(反弹高点)",
            "pre_low": "同一段的最低价(周末低点)",
            "condition": "周五 22:00 起跌幅 ≤ -阈值(BTC 3% / ETH 4%)",
            "controls": "全部周末(自动)+ 波动大但没跌到阈值 + 整周跌但周五 22:00 后没跌",
            "offset_threshold": "BTC 2.5% / ETH 3%(另有 3.0% 的候选一起报)",
        },
        "ledger_reference": {
            "note": "台账 S-882 / SETUP_REGISTRY.md 形态 #5 记的数(Seth 用 SQL 量的,SQL 未入库)",
            "offset_up_or_down": {"condition": "60-70%", "all": "26-45%"},
            "rebound_high_touched": {"condition": "65%", "all": "77%"},
            "weekend_low_touched": {"condition": "43-50%", "all": "53-59%"},
            "direction": "无",
        },
        "symbols": {},
    }

    for sym in ("BTC", "ETH"):
        bars, total = load_hourly(sym)
        samples = build_samples(bars)
        outcomes = make_outcomes(sym)
        condition, controls = make_groups(sym)
        table = apparatus.base_rate_table(samples, outcomes, condition, controls)
        seg = {}
        for name, lo, hi in (("发现段≤2022", "0000-01-01", "2022-12-31"),
                             ("留出段2023+", "2023-01-01", "9999-12-31")):
            sub = [s for s in samples if lo <= s["mon"] <= hi]
            seg[name] = apparatus.base_rate_table(sub, outcomes, condition, controls)
        result["symbols"][sym] = {
            "hourly_rows": total,
            "bars_usable": len(bars),
            "weeks_sampled": len(samples),
            "first_week": samples[0]["mon"] if samples else None,
            "last_week": samples[-1]["mon"] if samples else None,
            "table": table,
            "segments": seg,
        }
        print(f"[{sym}] rows={total} samples={len(samples)} "
              f"cond_n={table['condition']['n']} all_n={table['all']['n']}", flush=True)
        for g, rec in table.items():
            print("   ", g, {k: pct(rec, k) for k in
                             list(outcomes)[:3] + ["rebound_high_touched", "weekend_low_touched", "both_touched"]}, flush=True)

    with open(os.path.join(HERE, "t409_s882_replay.json"), "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)
    print("written", os.path.join(HERE, "t409_s882_replay.json"))


if __name__ == "__main__":
    main()
