"""S-561 / S-566:纸面账本的状态写进了表里不存在的列,每次保存都被拒(fusion 因此 51 天只记成本)。

factor_tilt / pod_aggregator 同一类:写 last_mark_date / state_json,线上表是 inception / last_mark / weights / cell …
它们的 NAV 还正常,是因为 Redis 缓存与磁盘续接 —— Redis 一丢就会和 fusion 一样。这里钉住:保存的键只能是线上列。
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LIVE = {   # information_schema,2026-10-14
    "factor_tilt_paper": {"id", "inception", "last_mark", "nav", "weights", "factor_sharpe_attribution",
                          "n_days_marked", "cell", "updated_at"},
    "pod_aggregator_paper": {"id", "inception", "last_mark", "nav", "weights", "survivors", "pods_dropped",
                             "breakers_tripped", "max_corr_retained", "n_days_marked", "cell", "updated_at"},
}


def _payload_keys(mod: str) -> set[str]:
    src = (ROOT / f"src/data/signals/{mod}.py").read_text(encoding="utf-8")
    fn = next(n for n in ast.parse(src).body if isinstance(n, ast.AsyncFunctionDef) and n.name == "_save_state")
    for node in ast.walk(fn):
        if isinstance(node, ast.Assign) and any(getattr(t, "id", None) == "payload" for t in node.targets):
            return {k.value for k in node.value.keys if isinstance(k, ast.Constant)}
    raise AssertionError(f"{mod}: no payload dict in _save_state")


def test_state_writes_use_live_column_names() -> None:
    for mod, cols in LIVE.items():
        keys = _payload_keys(mod)
        assert keys <= cols, f"{mod}: {sorted(keys - cols)} are not columns of the live table"
        src = (ROOT / f"src/data/signals/{mod}.py").read_text(encoding="utf-8")
        assert '["state_json"]' not in src, f"{mod}: still reads a state_json column that does not exist"
