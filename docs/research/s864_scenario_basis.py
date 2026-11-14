"""S-864 情景条目的定标 —— 从 s864_same_cell.py 的同一格子里量出概率,再查到期日上读数存不存在。

只读。跑法(仓库根目录,环境里有只读的 SUPABASE_URL / SUPABASE_KEY):
    python3 docs/research/s864_scenario_basis.py > docs/research/s864_scenario_basis.json

为什么单独一个脚本:情景文件里的概率与阈值必须能从原始数据重算出来,不能抄表。
本脚本不重算 s864 的表(那是 s864_same_cell.py 的活),只做三件事:
  ① 把「今天这一格」的历史基率按**自然日**重算一遍(与 s864 的 describe() 同一口径,并交叉核对);
  ② 核对索引口径:序列里 +30 行是不是 +30 自然日(周末有行才是);
  ③ 报出到期日(2026-12-11 / 2027-01-08,都是周五)上 close:BTC 与 state:dist_200 的行是否存在 ——
     state_daily 的周末行有缺口,到期日落在周日会取到 None,命题就白登记了。
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import os

import numpy as np

_BASE = os.path.dirname(os.path.abspath(__file__))
H28 = dt.date(2026, 12, 11)      # 今天 + 28 自然日(周五)
H56 = dt.date(2027, 1, 8)       # 今天 + 56 自然日(周五)—— 与 s864 的 56 天窗口同长


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(_BASE, name + ".py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


S = _load("s851_watch_base_rate")
S864 = _load("s864_same_cell")


def main() -> dict:
    days, close, dist200, taker, stable, y2_d, y2_v = S.load_live()
    cell = S864.cells(days, close, dist200, stable, y2_d, y2_v)
    labelled = [d for d in days if d in cell]
    today = labelled[-1]
    target = cell[today]
    idx = {d: i for i, d in enumerate(days)}

    def at(d, off):
        """d 之后第 off 个自然日的收盘(按日历查表,不是按索引)"""
        tgt = d + dt.timedelta(days=off)
        return close.get(tgt), tgt

    def ep_starts(ds):
        """把同格的连续日子并成段,返回每段的第一天(s864 的 episodes(),间隔 ≤5 天算同一段)。"""
        eps, cur = [], []
        for d in sorted(ds):
            if cur and (d - cur[-1]).days > 5:
                eps.append(cur)
                cur = []
            cur.append(d)
        if cur:
            eps.append(cur)
        return [e[0] for e in eps]

    # 可用日:留出最后 56 天(结果还没发生)
    usable = [d for d in labelled if idx[d] + 56 < len(days)]
    in_cell = [d for d in usable if cell[d] == target]
    starts = ep_starts(in_cell)

    def stats(ds, off):
        r, back = [], []
        for d in ds:
            c, _ = at(d, off)
            if c is None:
                continue
            r.append(c / close[d] - 1)
            nxt = dist200.get(d + dt.timedelta(days=off))
            if nxt is not None and dist200.get(d) is not None and dist200[d] < 0:
                back.append(1.0 if nxt > 0 else 0.0)
        r = np.array(r)
        if not len(r):
            return None
        return {"n": len(r), "p_down_big": round(float((r < -0.10).mean()), 4),
                "p_up_big": round(float((r > 0.10).mean()), 4),
                "median": round(float(np.median(r)), 4), "mean": round(float(r.mean()), 4),
                "dist200_back_above_0": (round(float(np.mean(back)), 4), len(back)) if back else None}

    out = {
        "asof": today.isoformat(),
        "today_cell": target,
        "p0_close": close[today],
        "n_in_cell_usable": len(in_cell),
        "n_episodes": len(starts),
        "episode_starts": [d.isoformat() for d in starts],
        "cell_all_days": {"d28": stats(in_cell, 28), "d56": stats(in_cell, 56)},
        "cell_by_episode_start": {"d28": stats(starts, 28), "d56": stats(starts, 56)},
        "unconditional_all_days": {"d28": stats(usable, 28), "d56": stats(usable, 56)},
        "readings_today": {"dist_200": dist200.get(today), "stable_supply_30d": stable.get(today),
                           "taker_buy_share_30d": taker.get(today), "ust_2y_asof": S.asof(y2_d, y2_v, today, 7)},
        "horizon_rows": {},
        "weekdays": {today.isoformat(): today.strftime("%a"), H28.isoformat(): H28.strftime("%a"),
                     H56.isoformat(): H56.strftime("%a")},
    }

    # 今天的 T 轴读数只有 −0.072,而格子里很多日子深在线下;再按「离线的深度」分层,
    # 找一个跟今天读数更像的参照类(预先定,不看结果)。
    for lo_d, hi_d in ((-0.15, 0.0), (-0.10, 0.0), (-0.20, 0.0)):
        sub = [d for d in in_cell if dist200.get(d) is not None and lo_d <= dist200[d] < hi_d]
        out.setdefault("cell_by_dist200_depth", {})[f"dist200_in_[{lo_d},{hi_d})"] = {
            "n_days": len(sub), "n_episodes": len(ep_starts(sub)),
            "d28": stats(sub, 28), "d56": stats(sub, 56)}
    # 深度分层里,s865 之外的另一半:无条件里同深度的日子(对照)
    for lo_d, hi_d in ((-0.15, 0.0),):
        sub = [d for d in usable if dist200.get(d) is not None and lo_d <= dist200[d] < hi_d]
        out.setdefault("unconditional_by_dist200_depth", {})[f"dist200_in_[{lo_d},{hi_d})"] = {
            "n_days": len(sub), "d28": stats(sub, 28), "d56": stats(sub, 56)}


    # 索引口径核对:序列里的 +28 行是不是 +28 自然日
    probe = [d for d in days if d <= today - dt.timedelta(days=200)][-1]
    out["index_vs_calendar"] = {
        "probe_date": probe.isoformat(),
        "index_plus_28": days[idx[probe] + 28].isoformat(),
        "calendar_plus_28": (probe + dt.timedelta(days=28)).isoformat(),
        "same": days[idx[probe] + 28] == probe + dt.timedelta(days=28),
        "n_close_rows_weekend": sum(1 for d in days if d.weekday() >= 5),
        "n_close_rows": len(days),
    }

    # 到期日上,自动结算要读的那几个值在不在(过去日期查覆盖;未来日期查不到是正常的,看是否周末缺口)
    for h in (H28, H56):
        rec = {}
        for kind, path, params in (
            ("close:BTC", "ohlcv_daily", {"select": "close", "symbol": "eq.BTC", "source": "eq.binance_hist",
                                          "trade_date": f"eq.{h.isoformat()}"}),
            ("state:dist_200", "state_daily", {"select": "value", "entity": "eq.panel", "feature": "eq.dist_200",
                                               "d": f"eq.{h.isoformat()}"}),
        ):
            rows = S.get(path, params)
            rec[kind] = rows[0] if rows else None
        out["horizon_rows"][h.isoformat()] = rec

    # 周末缺口:过去 120 天里 state_daily 的 dist_200 缺了哪些日子
    srows = S.get("state_daily", {"select": "d", "entity": "eq.panel", "feature": "eq.dist_200",
                                  "d": "gte.2026-07-15", "order": "d.asc"})
    have = {str(r["d"])[:10] for r in srows}
    miss = [(today - dt.timedelta(days=k)).isoformat() for k in range(0, 120)
            if (today - dt.timedelta(days=k)).isoformat() not in have]
    out["panel_missing_days_last120"] = miss

    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=1))
