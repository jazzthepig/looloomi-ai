"""T-095 补 3:把 sym_ret_30d/btc_ret_30d 对所有事件回填(原 outcomes 只对 pump 算),
重算 z30_bucket / mliq_magnitude / alt_vs_majors_bucket / y_beat_btc_30d(dumps 重算) /
experience_layer(扩张窗口),写回 sup3 文件。

跑:python3 research/t095/recompute_outcomes_sup3.py
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

DB = "/Volumes/CometCloudAI/cometcloud-local/data/ohlcv_11yr.db"
OUT = Path("/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-095_outcomes_sup3_2026-10-14.json")


def z30_bucket(z: float) -> str:
    """与 T-095 触发桶对齐:pump=z>=3, dump=z<=-2, 中性=z[-2,3)。
    触发桶交界点(z==-2, z==3)归入触发桶(>= 优先)。
    """
    if z >= 5.0:
        return "z>=5"
    if z >= 4.0:
        return "z[4,5)"
    if z >= 3.0:
        return "z[3,4)"
    if z >= -2.0:
        return "z[-2,3)"
    if z >= -3.0:
        return "z[-3,-2)"
    if z >= -4.0:
        return "z[-4,-3)"
    return "z<-4"


def mliq_magnitude(b: float | None) -> str:
    if b is None:
        return "unknown"
    if b >= 0.30:
        return "loose_strong"
    if b >= 0.10:
        return "loose"
    if b >= -0.05:
        return "neutral"
    if b >= -0.20:
        return "tight"
    return "tight_strong"


def alt_vs_majors(s: float | None, b: float | None) -> str:
    if s is None or b is None:
        return "unknown"
    d = s - b
    if d >= 0.30:
        return "alt_outperform_strong"
    if d >= 0.10:
        return "alt_outperform"
    if d >= -0.10:
        return "in_line"
    if d >= -0.30:
        return "alt_underperform"
    return "alt_underperform_strong"


def main() -> int:
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    data = json.loads(OUT.read_text())
    events = data["events"]

    need = [r for r in events
            if r.get("btc_ret_30d") is None or r.get("sym_ret_30d") is None]
    print(f"[recompute] events to backfill: {len(need)}")

    def px(sym: str, d_iso: str) -> float | None:
        row = con.execute(
            "SELECT close FROM ohlcv_11yr_daily WHERE symbol=? AND trade_date=?",
            (sym, d_iso)
        ).fetchone()
        return row["close"] if row else None

    filled = 0
    for r in need:
        sym = r["_symbol"]
        d = r["_d"]
        try:
            d30 = (date(*map(int, d.split("-"))) + timedelta(days=30)).isoformat()
        except Exception:
            continue
        p0 = px(sym, d)
        p30 = px(sym, d30)
        bp0 = px("BTC", d)
        bp30 = px("BTC", d30)
        if p0 and p30 and bp0 and bp30:
            r["sym_ret_30d"] = round(p30 / p0 - 1.0, 6)
            r["btc_ret_30d"] = round(bp30 / bp0 - 1.0, 6)
            filled += 1
    print(f"[recompute] filled: {filled}/{len(need)}")

    # recompute y_beat_btc_30d for dumps
    for r in events:
        if r["kind"] == "dump":
            s = r.get("sym_ret_30d")
            b = r.get("btc_ret_30d")
            if s is not None and b is not None:
                r["y_beat_btc_30d"] = int((1 + s) > (1 + b))

    # structural features
    for r in events:
        z = r["_z30"]
        r["z30_bucket"] = z30_bucket(z)
        r["mliq_magnitude"] = mliq_magnitude(r.get("btc_ret_30d"))
        r["alt_vs_majors_bucket"] = alt_vs_majors(
            r.get("sym_ret_30d"), r.get("btc_ret_30d"))

    print(f"[recompute] z30 dist: {dict(Counter(r['z30_bucket'] for r in events))}")
    print(f"[recompute] mliq_mag dist: {dict(Counter(r['mliq_magnitude'] for r in events))}")
    print(f"[recompute] alt_vs dist: {dict(Counter(r['alt_vs_majors_bucket'] for r in events))}")

    # experience layer (expanding window)
    def _minus_days(iso: str, k: int) -> str:
        y, m, d = iso.split("-")
        return (date(int(y), int(m), int(d)) - timedelta(days=k)).isoformat()

    def exp_layer(target: dict) -> dict:
        z_t = z30_bucket(target["_z30"])
        ml_t = target["marginal_liq_sign"]
        btc_t = bool(target["btc_above_ma200"])
        pool: list[dict] = []
        for r in events:
            if r["_d"] >= target["_d"]:
                continue
            if r["_d"] > _minus_days(target["_d"], 30):
                continue
            if r["kind"] != target["kind"]:
                continue
            if z30_bucket(r["_z30"]) != z_t:
                continue
            if r["marginal_liq_sign"] != ml_t:
                continue
            if bool(r["btc_above_ma200"]) != btc_t:
                continue
            pool.append(r)
        n = len(pool)
        ys = [r["y_beat_btc_30d"] for r in pool if r.get("y_beat_btc_30d") is not None]
        x_pct = round(sum(ys) / len(ys), 4) if ys else None
        return {
            "_d": target["_d"],
            "_symbol": target["_symbol"],
            "kind": target["kind"],
            "bucket": z_t,
            "n": n,
            "x_pct_beat_btc_30d": x_pct,
            "y_actual_at_target": target.get("y_beat_btc_30d") or target.get("y_pos_90d"),
        }

    exp_layers = [exp_layer(r) for r in events]
    n_lt10 = sum(1 for el in exp_layers if el["n"] < 10)
    n_ge10 = sum(1 for el in exp_layers if el["n"] >= 10)
    print(f"[recompute] exp_layer: n_lt10={n_lt10}, n_ge10={n_ge10}/{len(exp_layers)}")

    data["events"] = events
    data["n_events"] = len(events)
    data["experience_layers_per_event"] = exp_layers
    data["experience_layer_summary"] = {
        "events_total": len(exp_layers),
        "events_with_pool_lt_10": n_lt10,
        "events_with_pool_ge_10": n_ge10,
    }
    data["feature_additions"] = [
        "z30_bucket", "mliq_magnitude", "alt_vs_majors_bucket",
        "funding_band(unknown=no source)", "experience_layer",
    ]
    data["note"] = ("augmented: btc_ret_30d/sym_ret_30d 回填 via SQLite; "
                   "y_beat_btc_30d 对 dumps 也重算;experience layer 用 z30 档 × mliq 符"
                   "号 × BTC 趋势分桶 + same_kind + 扩张窗口 d-30 截止")

    OUT.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    print(f"[recompute] wrote {OUT} ({OUT.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
