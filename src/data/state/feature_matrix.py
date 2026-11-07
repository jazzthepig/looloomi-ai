"""融合特征矩阵的物化刷新(`feature_matrix_daily`,11-06)。

`feature_matrix_daily_live` 是视图:把每个日度状态维度按日拼成一行 jsonb(状态 27 维 + 宏观 + ⓪ 周期 + DVOL 分位 +
期权面 + 稳定币发行方 + 跨资产相关 + 交易所储备 + 政治强度 + 全市场永续 + **风格(PIT,2020 起)+ 链上活动 + 多空持仓结构 + RWA/代币化渠道**)。
后四组是表里早就有、却从没并进来的维度 —— 每天 33 个键 → 54–59 个。实时视图要 ~3 秒,所以读的人读物化副本,
本模块每小时调 `refresh_feature_matrix()` 刷一次(并发刷新,读者不被锁)。

判活:`select max(d), count(*) from feature_matrix_daily` —— max(d) 应为今天或昨天(UTC)。
"""
from __future__ import annotations

import datetime as dt
from typing import Any, Optional

VIEW = "feature_matrix_daily"
RPC = "refresh_feature_matrix"
LOOP_NAME = "_feature_matrix_loop"
STALE_DAYS = 2


def verdict(n_rows: Optional[int], latest: Optional[str], n_keys: Optional[int], today: dt.date) -> dict[str, Any]:
    """纯函数。刷新结果 → 判活。行数没有、或最新一天落后两天以上 = 不算通。"""
    if not n_rows:
        return {"ok": False, "why": "refresh_feature_matrix 没返回行数"}
    if not latest:
        return {"ok": False, "why": "物化视图里没有日期"}
    lag = (today - dt.date.fromisoformat(latest[:10])).days
    if lag > STALE_DAYS:
        return {"ok": False, "why": f"最新一天 {latest[:10]} 落后 {lag} 天 —— 上游 state_daily 停了?"}
    return {"ok": True, "rows": n_rows, "latest": latest[:10], "keys": n_keys,
            "why": f"{n_rows} 天 · 最新 {latest[:10]} 有 {n_keys} 个键"}


REFRESH_TIMEOUT_S = 60.0


async def run_once(now: Optional[dt.datetime] = None) -> dict[str, Any]:
    from src.api.store import supabase_rpc_write
    from src.data.vector.market_state_writer import _sb_get
    now = (now or dt.datetime.now(dt.timezone.utc)).astimezone(dt.timezone.utc)
    # 11-06:两个物化视图一起刷,实测均值 9.2 s、最大 12.2 s;共享客户端 10 s 就放弃 ⇒ 24 小时里 4 次「没返回行数」(其实刷完了)
    r = await supabase_rpc_write(RPC, {}, timeout=REFRESH_TIMEOUT_S)
    if not r.ok:
        return {"ok": False, "why": f"{RPC} 调用失败(客户端 {REFRESH_TIMEOUT_S:.0f} s):{(r.why or '')[:160]}"}
    n = r.value
    if isinstance(n, list):
        n = n[0] if n else None
    if isinstance(n, dict):
        n = next(iter(n.values()), None)
    rd = await _sb_get(VIEW, {"select": "d,f", "order": "d.desc", "limit": "1"})   # 不走 _read_all:它会把 limit 改成 1000
    if not rd.ok:
        return {"ok": False, "why": f"{VIEW} 读不到:{rd.reason}"}
    rows = rd.rows or []
    latest = rows[0]["d"] if rows else None
    keys = len(rows[0].get("f") or {}) if rows else None
    out = verdict(int(n) if isinstance(n, (int, float)) else None, latest, keys, now.date())
    # 11-07:按币的那一层(`asset_flow_daily`)跟市场层同一个循环 —— 上游 metrics 有新的一天才刷(~40 s);它出错不挡市场层的判活
    try:
        from src.data.state.asset_flow import refresh as _af_refresh
        af = await _af_refresh(now)
    except Exception as e:                                                # noqa: BLE001
        af = {"ok": False, "why": f"{type(e).__name__}: {str(e)[:120]}"}
    out["asset_flow"] = {k: af.get(k) for k in ("ok", "rows", "skipped", "latest", "source_latest")}
    out["why"] = f"{out.get('why')} | 按币:{af.get('why')}"
    return out
