"""把循环的 `detail` 变成一定能序列化的 JSON(10-29)。

为什么:`_meta_allocator_loop` 10-28 23:30 真的写进了 `meta_allocator_daily`,而 `loop_attempt` 里它最后一次
`ok` 停在 10-08 —— 成功那一轮的 `detail` 带着评估结果(numpy 标量 / NaN),`json` 序列化在记录器里抛出,
记录器按设计吞掉一切异常,于是**只有成功的那几轮没有记录**,面板上它只剩「refused」。
一个只在成功时失声的记录器,比一个总失声的更会骗人。
"""
from __future__ import annotations

import math
from typing import Any


def json_safe(obj: Any, _depth: int = 0) -> Any:
    """递归转换:numpy 标量 → Python 原生;NaN / ±inf → None;日期 → ISO 字符串;其余不认识的 → str。"""
    if _depth > 12:
        return str(obj)[:200]
    if obj is None or isinstance(obj, (bool, str, int)):
        return obj
    if isinstance(obj, float):
        return obj if math.isfinite(obj) else None
    if isinstance(obj, dict):
        return {str(k): json_safe(v, _depth + 1) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, frozenset)):
        return [json_safe(v, _depth + 1) for v in obj]
    item = getattr(obj, "item", None)                 # numpy 标量
    if callable(item) and not hasattr(obj, "__len__"):
        try:
            return json_safe(item(), _depth + 1)
        except Exception:                             # noqa: BLE001
            pass
    iso = getattr(obj, "isoformat", None)             # date / datetime / pd.Timestamp
    if callable(iso):
        try:
            return iso()
        except Exception:                             # noqa: BLE001
            pass
    tolist = getattr(obj, "tolist", None)             # numpy 数组 / pandas Series
    if callable(tolist):
        try:
            return json_safe(tolist(), _depth + 1)
        except Exception:                             # noqa: BLE001
            pass
    return str(obj)[:200]
