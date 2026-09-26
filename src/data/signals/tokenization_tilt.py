"""② β+:代币化基础设施倾斜 —— 前向记录(S-427,Jazz 2026-09-26)。

## 为什么有这本账

Jazz:「这类和 tokenization 高度相关的 infra 都是必须重点关注的……我们需要 capture 这些传统金融到链上的长期增长。
价值投资永远不会死。」他 09-01 已说过同一论点(S-264),当时只建了观测面板(S-266 `/rwas`),**没有进任何账本**;
09-24/25 LINK 两天 +12.7%,只有 ① 的等权 3.8% 吃到。这本账把论点变成一条可验证的前向记录。

## 预注册(改任何一项 = 新起点,旧记录留档)

    ① 基准臂  panel_hold             ① 的 24 币面板等权(causal_positioning.DEFAULT_UNIVERSE)
    ② 倾斜臂  tokenization_tilt_25   75% 面板等权 + 25% 篮子等权(重叠的币两份相加)
    篮子(Jazz 选「通路+发行」)        LINK · ONDO · PENDLE · POLYX · AAVE · UNI · HYPE
        不在账上:QNT(执行场所未挂牌,只做研究)· MKR(场所已下架;SKY 价格序列回填后替换)
    只持现货、无杠杆(DECISIONS 08-23);每月 1 日(UTC)收盘再平衡;起点 2026-09-25 收盘
    成本:换手 × 10 bps,在再平衡当天扣
    判据:倾斜臂 − 基准臂 的累计差,按 regime 分段报;≥60 天前向才谈结论(strategy discipline)

历史对照(不是证据,见 S-427):2022-10 → 2026-09 倾斜臂 +154% vs 面板 +78%,但**篮子是 2026 年
带着后见之明挑的**(HYPE/ONDO/PENDLE 事后是赢家)。唯一算数的是从起点往后的记录。

## 不存状态 —— 每次从起点重算

fusion 那本账的状态表是空的,于是 22 天只扣成本、从不按价格记盈亏(S-427)。这里**没有状态可丢**:
每轮读起点以来的收盘价,整条路径重算、整条 upsert。数据量 ~31 币 × 天数,可以忽略。

## 判活判据(规则 5b ②)

    select arm, max(d), count(*) from tokenization_tilt_daily group by 1;   -- UTC 06:00 后 max(d) 应 = 昨天
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pandas as pd

TABLE = "tokenization_tilt_daily"
WRITES_TABLES = (TABLE,)
ARMS = ("panel_hold", "tokenization_tilt_25")
BASKET = ("LINK", "ONDO", "PENDLE", "POLYX", "AAVE", "UNI", "HYPE")
RESEARCH_ONLY = {"QNT": "执行场所未挂牌", "MKR": "场所已下架,待 SKY 回填后替换"}
TILT = 0.25
COST_BPS = 10.0
INCEPTION = pd.Timestamp("2026-09-25")
PRICE_SOURCE = "coingecko_pro_ohlc"
#: 某天有真实收盘的持仓权重低于这个比例 ⇒ 这一天不记(读不到 ≠ 没涨跌)
MIN_QUOTED_WEIGHT = 0.90
CODE_REF = "S-427 tokenization_tilt v1"


def panel_universe() -> tuple[str, ...]:
    from src.research.strategies.causal_positioning import DEFAULT_UNIVERSE
    return tuple(DEFAULT_UNIVERSE)


def _ew(names) -> dict[str, float]:
    names = list(names)
    return {s: 1.0 / len(names) for s in names} if names else {}


def targets(arm: str, available: set[str], panel: tuple[str, ...]) -> dict[str, float]:
    """再平衡日的目标权重。只在当天有真实收盘的币上分配(没报价的不买)。"""
    p = _ew([s for s in panel if s in available])
    if arm == "panel_hold":
        return p
    b = _ew([s for s in BASKET if s in available])
    if not b:                         # 篮子一个报价都没有:不假装倾斜
        return p
    out: dict[str, float] = {}
    for s, w in p.items():
        out[s] = out.get(s, 0.0) + (1 - TILT) * w
    for s, w in b.items():
        out[s] = out.get(s, 0.0) + TILT * w
    return out


def compute_path(px: pd.DataFrame, panel: tuple[str, ...], barred: list[str],
                 source: str, end: pd.Timestamp | None = None) -> list[dict]:
    """纯函数:起点到 `end` 的每日行(两臂)。

    `px`:行 = 日期,列 = 币;**NaN = 那天没有真实收盘**(前推价已在调用方抹掉)。
    某天持仓里有真实报价的权重 < MIN_QUOTED_WEIGHT ⇒ 抛 ValueError(不记一个假的平 NAV)。
    """
    px = px.sort_index()
    days = [d for d in px.index if d >= INCEPTION and (end is None or d <= end)]
    if not days or days[0] != INCEPTION:
        raise ValueError(f"起点 {INCEPTION.date()} 那天没有面板行 —— 不从别的日子悄悄开始")
    rows: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    for arm in ARMS:
        w: dict[str, float] = {}
        last: dict[str, float] = {}
        nav = 1.0
        for i, d in enumerate(days):
            row_px = px.loc[d]
            quoted = {s for s in row_px.index if pd.notna(row_px[s])}
            ret, n_filled = 0.0, 0
            if i > 0:
                qw = sum(v for s, v in w.items() if s in quoted)
                if qw < MIN_QUOTED_WEIGHT:
                    raise ValueError(f"{d.date()} {arm}:有真实收盘的持仓权重只有 {qw:.0%} "
                                     f"< {MIN_QUOTED_WEIGHT:.0%} —— 读不到,不记成没涨跌")
                rets = {}
                for s in w:
                    if s in quoted and s in last:
                        rets[s] = float(row_px[s]) / last[s] - 1
                    else:
                        rets[s] = 0.0
                        n_filled += 1
                ret = sum(w[s] * rets[s] for s in w)
                nav *= 1 + ret
                w = {s: v * (1 + rets[s]) / (1 + ret) for s, v in w.items()}
            for s in quoted:
                last[s] = float(row_px[s])
            rebalanced, turnover = False, 0.0
            if i == 0 or d.day == 1:
                tgt = targets(arm, quoted, panel)
                keys = set(tgt) | set(w)
                turnover = sum(abs(tgt.get(s, 0.0) - w.get(s, 0.0)) for s in keys)
                cost = turnover * COST_BPS / 1e4
                nav *= 1 - cost
                ret = (1 + ret) * (1 - cost) - 1
                w, rebalanced = tgt, True
            rows.append({
                "d": d.date().isoformat(), "arm": arm,
                "nav": round(nav, 8), "ret": round(ret, 8),
                "weights": {s: round(v, 5) for s, v in sorted(w.items(), key=lambda kv: -kv[1])},
                "basket_weight": round(sum(v for s, v in w.items() if s in BASKET), 5),
                "rebalanced": rebalanced, "turnover": round(turnover, 6),
                "n_quoted": len(quoted & set(w)), "n_filled": n_filled,
                "barred": barred, "source": source,
                "inception": INCEPTION.date().isoformat(), "code_ref": CODE_REF,
                "computed_at": now,
            })
    return rows


async def run_once() -> dict[str, Any]:
    """重算到昨天那根已收盘日线并整条 upsert。幂等。"""
    from src.data.market.panel_read import read_panel
    from src.data.signals.hl_book_daily import _supabase_get
    from src.api.store import supabase_upsert_table

    target = pd.Timestamp.now(tz="UTC").tz_localize(None).normalize() - pd.Timedelta(days=1)
    if target < INCEPTION:
        return {"ok": True, "refused": True, "written": 0, "reason": "起点未到"}
    panel = panel_universe()
    syms = list(dict.fromkeys(list(panel) + list(BASKET)))
    start = (INCEPTION - pd.Timedelta(days=3)).date().isoformat()
    p = await read_panel(syms, start=start, source=PRICE_SOURCE)
    idx = pd.to_datetime(p.days)
    px = pd.DataFrame(p.close, index=idx, columns=p.symbols, dtype=float)
    px = px.mask(pd.DataFrame(p.filled, index=idx, columns=p.symbols))   # 前推的价格不是价格

    # 就绪:target 那根 bar 须是收盘之后写入的终值(同 S-413 的判据),占 ≥90% 的币
    rec = await _supabase_get(
        f"ohlcv_daily?select=symbol,recorded_at&source=eq.{PRICE_SOURCE}"
        f"&symbol=in.({','.join(p.symbols)})&trade_date=eq.{target.date().isoformat()}")
    close_ts = target + pd.Timedelta(days=1)
    final = {r["symbol"] for r in rec if r.get("recorded_at")
             and pd.Timestamp(r["recorded_at"]).tz_convert("UTC").tz_localize(None) >= close_ts}
    if len(final) < 0.9 * len(p.symbols):
        late_h = (pd.Timestamp.now(tz="UTC").tz_localize(None) - close_ts).total_seconds() / 3600
        msg = f"{target.date()} 收盘后终值只有 {len(final)}/{len(p.symbols)} 个币"
        if late_h > 30:
            return {"ok": False, "refused": False, "written": 0, "reason": f"收盘后 {late_h:.0f}h:{msg}"}
        return {"ok": True, "refused": True, "written": 0, "reason": f"未就绪:{msg}"}
    px.loc[target, [c for c in px.columns if c not in final]] = float("nan")

    rows = await asyncio.to_thread(compute_path, px, panel, list(p.barred), p.source, target)
    res = await supabase_upsert_table(TABLE, rows, on_conflict="d,arm")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    last = {r["arm"]: r["nav"] for r in rows if r["d"] == target.date().isoformat()}
    return {"ok": True, "refused": False, "written": len(rows),
            "reason": f"重算至 {target.date()}", "nav": last, "barred": list(p.barred)}
