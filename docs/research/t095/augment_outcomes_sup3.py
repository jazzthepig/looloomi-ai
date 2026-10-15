"""T-095 补 3(S-573): 给 outcomes 增 ① mliq magnitude / ② alt-vs-majors / ③ funding-band
(Gap: 无 funding 数据源,跳过) / ④ y_beat_btc_30d(dumps 回填) / ⑤ experience layer
(扩张窗口 = 只用 e._d ≤ d - 30 的事件)。

扩充后的文件写到 Mac 数据根,后续 run_replay_sup3.py 直接读它。
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

OUTCOMES_IN = Path(
    "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-095_outcomes_2026-10-14.json"
)
OUTCOMES_OUT = Path(
    "/Volumes/CometCloudAI/cometcloud-local/_reports/absorb_input/T-095_outcomes_sup3_2026-10-14.json"
)


def z30_bucket(z: float) -> str:
    """z30 档位 — S-573 z30 × 边际流动性 × BTC 趋势分桶。

    与 T-095 触发桶对齐:
      - pump 触发桶  = z >= 3         (z[3,4) + z[4,5) + z>=5)
      - dump 触发桶  = z <= -2        (z[-3,-2) + z[-4,-3) + z<-4)
      - 中性(z[-2, 3))               —— 不在触发桶,只用于 exp_layer 同桶对齐
    触发桶交界点(z == -2 / z == 3)由 if 顺序保证归入触发桶(>= 优先)。
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


def mliq_magnitude(btc_ret_30d: float | None) -> str:
    """无 mliq 直接量;用 BTC 30d 收益幅度代理。
    强宽松 = BTC 大涨;宽松 = 微涨;中性;收紧 = 微跌;强收紧 = 大跌。
    """
    if btc_ret_30d is None:
        return "unknown"
    r = btc_ret_30d
    if r >= 0.30:
        return "loose_strong"
    if r >= 0.10:
        return "loose"
    if r >= -0.05:
        return "neutral"
    if r >= -0.20:
        return "tight"
    return "tight_strong"


def alt_vs_majors(sym_ret_30d: float | None, btc_ret_30d: float | None) -> str:
    """该名相对 BTC 的相对收益档位 — 用 sym_ret_30d 与 btc_ret_30d 之差。
    注:此代理不完美(只 30d 单窗口),但与 z30 同期,符合「按时点」语义。
    """
    if sym_ret_30d is None or btc_ret_30d is None:
        return "unknown"
    d = sym_ret_30d - btc_ret_30d
    if d >= 0.30:
        return "alt_outperform_strong"
    if d >= 0.10:
        return "alt_outperform"
    if d >= -0.10:
        return "in_line"
    if d >= -0.30:
        return "alt_underperform"
    return "alt_underperform_strong"


def add_y_beat_btc_30d_dumps(r: dict, all_rows: list[dict]) -> int | None:
    """dumps 缺 y_beat_btc_30d;用 sym_ret_30d (后 30d) 与 btc_ret_30d 算。"""
    if r["kind"] != "dump":
        return r.get("y_beat_btc_30d")
    sym = r.get("sym_ret_30d")
    btc = r.get("btc_ret_30d")
    if sym is None or btc is None:
        return None
    return int((1 + sym) > (1 + btc))   # (1+r) > (1+r) 近似 simple return 比较


def exp_layer(
    events: list[dict],
    target: dict,
    *,
    same_kind: bool = True,
) -> dict:
    """扩张窗口经验层 — 对 target 事件找「满足同样 (z30 档 × mliq 符号 × BTC 趋势),
    且 _d ≤ target._d − 30(走完 30 天)的事件」,算 y_beat_btc_30d 的均值。
    N < 10 写「样本不足」。
    """
    target_d = target["_d"]
    target_z = z30_bucket(target["_z30"])
    target_ml = target["marginal_liq_sign"]
    target_btc_above = bool(target["btc_above_ma200"])

    pool: list[dict] = []
    for r in events:
        if r["_d"] >= target_d:
            continue
        # 扩张窗口:d + 30 ≤ target_d,即 r._d ≤ target_d - 30
        # ISO date 比较
        d_r = r["_d"]
        if d_r > _minus_days(target_d, 30):
            continue
        if same_kind and r["kind"] != target["kind"]:
            continue
        if z30_bucket(r["_z30"]) != target_z:
            continue
        if r["marginal_liq_sign"] != target_ml:
            continue
        if bool(r["btc_above_ma200"]) != target_btc_above:
            continue
        pool.append(r)

    n = len(pool)
    if n == 0:
        return {"n": 0, "note": "样本不足", "x_pct_beat_btc_30d": None,
                "y_target_actual": target.get("y_beat_btc_30d") or target.get("y_pos_90d")}
    ys = [r.get("y_beat_btc_30d") for r in pool]
    ys = [y for y in ys if y is not None]
    if not ys:
        return {"n": n, "note": "y_beat_btc_30d 在 pool 全缺", "x_pct_beat_btc_30d": None,
                "y_target_actual": target.get("y_beat_btc_30d") or target.get("y_pos_90d")}
    x = sum(ys) / len(ys)
    return {
        "n": n,
        "note": "ok" if n >= 10 else "样本不足(n<10)",
        "x_pct_beat_btc_30d": round(x, 4),
        "y_target_actual": target.get("y_beat_btc_30d") or target.get("y_pos_90d"),
        "pool_date_range": [min(r["_d"] for r in pool), max(r["_d"] for r in pool)],
        "kind_pool": "same_kind" if same_kind else "all_events",
    }


def _minus_days(iso: str, k: int) -> str:
    from datetime import date, timedelta
    y, m, d = iso.split("-")
    dt = date(int(y), int(m), int(d)) - timedelta(days=k)
    return dt.isoformat()


def main() -> int:
    events = json.loads(OUTCOMES_IN.read_text())
    print(f"[augment] loaded {len(events)} events from {OUTCOMES_IN.name}", flush=True)

    # Step 1: back-fill y_beat_btc_30d for dumps (so experience layer has y for all kinds)
    for r in events:
        r["y_beat_btc_30d"] = add_y_beat_btc_30d_dumps(r, events)

    # Step 2: structural features
    for r in events:
        z = r["_z30"]
        r["z30_bucket"] = z30_bucket(z)
        r["mliq_magnitude"] = mliq_magnitude(r.get("btc_ret_30d"))
        r["alt_vs_majors_bucket"] = alt_vs_majors(
            r.get("sym_ret_30d"), r.get("btc_ret_30d")
        )
        # funding_band: 缺数据源(无 funding_history / state_daily 受限),
        # 暂记 unknown;后续若 Min-A 拉 funding 历史补上
        r["funding_band"] = "unknown"

    # Step 3: experience layer per event (expanding window)
    exp_layers: list[dict] = []
    for r in events:
        el = exp_layer(events, r, same_kind=True)
        el["_d"] = r["_d"]
        el["_symbol"] = r["_symbol"]
        el["kind"] = r["kind"]
        exp_layers.append(el)
    n_too_small = sum(1 for el in exp_layers if el["n"] < 10)
    n_pool_kind = Counter(el.get("kind_pool", "all_events") for el in exp_layers)
    print(f"[augment] experience layer: {len(exp_layers)} events;"
          f" n<10 = {n_too_small}/{len(exp_layers)}; "
          f"kinds={dict(n_pool_kind)}", flush=True)

    # Step 4: write augmented outcomes
    out_obj = {
        "task": "T-095 outcomes (supplement 3: S-573 features + experience layer)",
        "based_on": OUTCOMES_IN.name,
        "n_events": len(events),
        "feature_additions": ["z30_bucket", "mliq_magnitude", "alt_vs_majors_bucket",
                              "funding_band(unknown=no source)", "experience_layer"],
        "events": events,
        "experience_layer_summary": {
            "events_with_pool_lt_10": n_too_small,
            "events_total": len(exp_layers),
            "n_pool_same_kind": n_pool_kind.get("same_kind", 0),
        },
    }
    OUTCOMES_OUT.parent.mkdir(parents=True, exist_ok=True)
    OUTCOMES_OUT.write_text(json.dumps(out_obj, ensure_ascii=False, indent=2))
    print(f"[augment] wrote {OUTCOMES_OUT} ({OUTCOMES_OUT.stat().st_size} bytes)", flush=True)

    # Quick distribution check
    z_dist = Counter(r["z30_bucket"] for r in events)
    print(f"[augment] z30_bucket dist: {dict(z_dist)}", flush=True)
    mliq_mag = Counter(r["mliq_magnitude"] for r in events)
    print(f"[augment] mliq_magnitude dist: {dict(mliq_mag)}", flush=True)
    avm = Counter(r["alt_vs_majors_bucket"] for r in events)
    print(f"[augment] alt_vs_majors dist: {dict(avm)}", flush=True)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
