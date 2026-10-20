"""T-154 自检 —— fish_counter.py 与台账 S-618 原文对表。

台账 S-618 原文 2020-03-01 → 2026-06-20 在 binance_hist 上数出 286 条鱼(±2;原记 287)。

这次必须复现:数对就过,数不对就 sys.exit(非 0)。
并把第一行命中样本打印出来给人工 spot-check。

读库只用 os.environ['SUPABASE_URL' / 'SUPABASE_KEY'],publishable,不打印 key。
零分布 / 分位 / A/B 仍走 src/data/evaluation/apparatus.py(不动)。
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request


REPO = "/Users/sbb/Projects/looloomi-ai"  # apparatus.py 在主仓库,只读
sys.path.insert(0, REPO)


from docs import research as _research_pkg  # noqa: E402,F401
import importlib.util as _ilu  # noqa: E402
_FC_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fish_counter.py")
_spec = _ilu.spec_from_file_location("fish_counter", _FC_PATH)
fish_counter = _ilu.module_from_spec(_spec)  # type: ignore
_spec.loader.exec_module(fish_counter)  # type: ignore

URL = os.environ.get("SUPABASE_URL", "")
KEY = os.environ.get("SUPABASE_KEY", "")
if not URL or not KEY:
    sys.exit("缺 SUPABASE_URL / SUPABASE_KEY")


WINDOW_START = "2020-03-01"
WINDOW_END = "2026-06-20"
EXPECTED = 286
TOL = 2  # ±2
ROW_CHECK_LIMIT = 1000  # 拉多少行做点抽检测;不再造事


def _sb_count(source: str) -> int:
    """Head-only 数 ohlcv_daily 在 source 上的总行数(用 Prefer count=exact)。"""
    q = urllib.parse.urlencode({"select": "symbol", "source": "eq." + source, "limit": "1"})
    req = urllib.request.Request(
        f"{URL}/rest/v1/ohlcv_daily?{q}",
        headers={"apikey": KEY, "Authorization": f"Bearer {KEY}",
                 "Prefer": "count=exact", "Range-Unit": "items",
                 "Range": "0-0"},
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        cr = r.headers.get("Content-Range") or ""
    # 例:0-0/354580
    return int(cr.split("/")[-1]) if "/" in cr else -1


def main() -> None:
    t0 = time.time()
    n_total = _sb_count("binance_hist")
    print(f"[t154] binance_hist total rows: {n_total}")

    panel = fish_counter.fetch_panel_supabase(WINDOW_START, WINDOW_END)
    panel_rows = sum(len(v) for v in panel.values())
    n_sym = len(panel)
    print(f"[t154] panel rows: {panel_rows}   symbols: {n_sym}   (elapsed pull: {time.time()-t0:.1f}s)")

    fish = fish_counter.fish(panel, WINDOW_START, WINDOW_END)
    n_fish = len(fish)
    n_fish_sym = len({f["symbol"] for f in fish})
    print(f"[t154] fish: {n_fish}   distinct symbols: {n_fish_sym}")
    print(f"[t154] first 5 fish (sorted by start_date asc):")
    for f in fish[:5]:
        print(f"        {f['symbol']:14s}  start={f['start_date']}  hits={f['n_hits']}"
              f"  peak_close={f['peak_close']:.4g}  ({f['peak_multiple']:.2f}×)  "
              f"peak_date={f['peak_close_date']}")

    # 判据
    delta = n_fish - EXPECTED
    ok = abs(delta) <= TOL
    print(f"[t154] expected={EXPECTED} ±{TOL}  observed={n_fish}  delta={delta:+d}  → {'PASS' if ok else 'ABORT'}")
    if not ok:
        sys.exit(1)

    # 把面板第一行(任何 symbol)的字段写出来给人工看,确认 schema 与 t145_fish_wave.py 一致
    sample_sym = sorted(panel.keys())[0]
    print(f"[t154] sample symbol={sample_sym}  rows={len(panel[sample_sym])}")
    print(f"[t154] sample head: {json.dumps(panel[sample_sym][0], default=str)}")
    print(f"[t154] sample tail: {json.dumps(panel[sample_sym][-1], default=str)}")

    out_path = "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-154_fish_count_check.json"
    payload = {
        "window": [WINDOW_START, WINDOW_END],
        "expected": EXPECTED,
        "tolerance": TOL,
        "observed_fish": n_fish,
        "observed_symbols": n_fish_sym,
        "delta": delta,
        "pass": ok,
        "panel_rows": panel_rows,
        "panel_symbols": n_sym,
        "binance_hist_total_rows": n_total,
        "first_5_fish": fish[:5],
        "elapsed_s": round(time.time() - t0, 1),
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(payload, f, indent=2, default=str)
    print(f"[t154] wrote {out_path}")


if __name__ == "__main__":
    main()
