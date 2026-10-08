"""探索仓的入口:机会提交(T-074 / S-522)。

Jazz 10-08:「必须留黑箱敞口 —— 从来未有过的,只要是机会就抓进来,事后研究归因」「探索仓 5–30%,视乎市场风格;
要和我主动获取的信息匹配」。这里只做入口与证据:提交即写、只追加;每天的前向锚把当天的提交一起锚进比特币时间戳,
证明「先于结果」。纸面生命周期与额度档在下一步(T-074)。
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

TABLE = "exploration_ideas"
WRITES_TABLES = (TABLE,)
MAX_TEXT = 2000
HORIZONS = ("hours", "days", "weeks", "months")


def validate(body: dict) -> tuple[dict | None, list[str]]:
    """纯函数。返回 (要写的行, 问题列表)。缺资产或缺因果假设 ⇒ 不收 —— 没有假设就没有事后归因。"""
    probs: list[str] = []
    asset = str(body.get("asset") or "").strip()
    thesis = str(body.get("thesis") or "").strip()
    if not asset:
        probs.append("asset 必填(代号 / coin_id / 合约地址)")
    if len(thesis) < 10:
        probs.append("thesis 必填,至少一句话:为什么、会怎样、什么情况下算错")
    horizon = str(body.get("horizon") or "days")
    if horizon not in HORIZONS:
        probs.append(f"horizon 只能是 {HORIZONS}")
    if probs:
        return None, probs
    now = datetime.now(timezone.utc)
    return {"d": now.date().isoformat(), "submitted_at": now.isoformat(),
            "asset": asset[:200], "chain": (str(body.get("chain") or "") or None),
            "contract": (str(body.get("contract") or "") or None),
            "thesis": thesis[:MAX_TEXT], "source": (str(body.get("source") or "") or None),
            "submitted_by": str(body.get("submitted_by") or "jazz")[:64], "horizon": horizon,
            "status": "open"}, []


async def submit(body: dict) -> dict[str, Any]:
    from src.api.store import supabase_insert_table
    row, probs = validate(body)
    if probs:
        return {"ok": False, "problems": probs}
    res = await supabase_insert_table(TABLE, [row])
    if not res.ok:
        return {"ok": False, "problems": [f"写入失败:{res.why}"]}
    return {"ok": True, "row": row,
            "note": "当天的前向锚会把这条一起挂到比特币时间戳上(/api/v1/proof/anchors)。"}
