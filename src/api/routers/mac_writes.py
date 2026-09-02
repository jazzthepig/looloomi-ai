"""Mac 侧四个 daily writer 的代理写入路径 (S-277).

## 这条 lane 欠的债,不是 Minimax 的纪律问题

`MINIMAX_SYNC` §IN-FLIGHT 有三行卡着,全部写着「等 Seth 开 endpoint」:

    risk_meter_history          🟡 自 2026-08-15 —— **18 天**
    asset_embeddings_history    🟡 M-WO-D1
    signal_journal              🟡 signal_outcome_tracker.py
    trade_results               🟡 export_backtest_to_supabase.py

`memory/local-no-supabase-write.md` 定了原则:Mac 侧不直写 Supabase,
一律走 Railway 代理。原则是对的(见 `strategy_intake.py` 那两条论证:
blast radius + **让门无法绕过**),但**只立原则不开口子,等于把对方逼回直写**。
Minimax-A 老老实实等了 18 天,这是他的纪律,不是他的问题。

## 与 `strategy_intake` 同一个模式,不是第二种

逐条裁决(20 条里 3 条坏,落 17 条并报 3 条)· 拒绝带原文理由 ·
`X-Internal-Token` 认证 · **校验在插入之前**。

## 本模块唯一新增的那条守卫:未知列必须拒绝,不能静默丢弃

PostgREST 收到表里没有的列会报错,但**如果我们先做一次「挑出已知列」的过滤**,
一个拼错的字段(`regime` vs `macro_regime`)就会被悄悄丢掉,
于是写进去一行带 NULL 的记录,而两边都以为成功了。

    静默丢弃 → 一行看起来正常、实际缺列的数据
    显式拒绝 → 一条说明「你发的 regime 不是列名,你要的是 macro_regime」

**这正是今天反复出现的那个形状**(S-273…S-276):两个不同的状态
(「这个字段没值」和「这个字段名写错了」)塌进同一个表示。
所以 `ALLOWED` 是白名单,而多出来的键是 **reject**,不是 drop。
"""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Header, HTTPException

log = logging.getLogger(__name__)
router = APIRouter()

#: 每张表的列白名单 + 冲突键。列取自 information_schema(2026-09-02 实查),
#: **不是从 Mac 侧代码抄的** —— 抄来的列名会把对方的笔误一起抄过来。
TABLES: dict[str, dict] = {
    "risk-meter-history": {
        "table": "risk_meter_history",
        "on_conflict": "d",
        "required": {"d"},
        "allowed": {"d", "regime", "band", "score", "long_gross",
                    "interpretation", "components", "computed_at"},
    },
    "asset-embeddings-history": {
        "table": "asset_embeddings_history",
        "on_conflict": "d,symbol",
        "required": {"d", "symbol"},
        "allowed": {"d", "symbol", "asset_class", "macro_regime",
                    "schema_version", "dims", "vec", "vec_full", "computed_at",
                    "measured_dims", "source_completeness", "price_source",
                    "provenance_note"},
    },
    "signal-journal": {
        "table": "signal_journal",
        "on_conflict": None,          # 追加,不 upsert(id 是 bigint 自增)
        "required": {"symbol", "signal_date"},
        "allowed": {
            "symbol", "asset_class", "grade", "signal", "cis_score",
            "raw_cis_score", "las", "pillar_f", "pillar_m", "pillar_o",
            "pillar_s", "pillar_a", "macro_regime", "strategy", "data_tier",
            "entry_price", "exit_price", "exit_date", "exit_reason",
            "return_pct", "holding_days", "signal_date", "recorded_at",
            "outcome_30d", "return_pct_30d", "price_at_30d", "mcap_at_30d",
            "circ_supply_at_entry", "outcome_source", "outcome_at",
            "benchmark_symbol", "benchmark_return_30d", "alpha_30d"},
    },
    "trade-results": {
        "table": "trade_results",
        "on_conflict": None,
        "required": {"symbol", "entry_time"},
        "allowed": {
            "symbol", "side", "entry_time", "exit_time", "entry_price",
            "exit_price", "profit_pct", "profit_abs", "realized_return_7d",
            "exit_reason", "enter_tag", "strategy", "cis_score", "cis_grade",
            "pillar_f", "pillar_m", "pillar_o", "pillar_s", "pillar_a",
            "macro_regime", "data_tier", "created_at"},
    },
}

#: 一批最多多少行。上界存在的理由是**它让失败可诊断** ——
#: 一个 10,000 行的批次失败时,你不知道是哪一行。
MAX_ROWS = 500


def _auth(token: str | None) -> None:
    expected = os.environ.get("INTERNAL_TOKEN", "")
    if not expected:
        # **未配置必须 fail-closed。** S-262 修的 telegram webhook 正是
        # 「没配 secret 就放行」—— 一个空字符串比较通过了。
        raise HTTPException(503, "INTERNAL_TOKEN is not configured on the server")
    if token != expected:
        raise HTTPException(403, "bad or missing X-Internal-Token")


def _vet(row: dict, spec: dict, idx: int) -> tuple:
    """一行 → `(clean_row | None, 拒绝理由 | None)`。

    **未知列是拒绝,不是丢弃。** 见模块 docstring。
    """
    if not isinstance(row, dict):
        return None, f"[{idx}] 不是一个对象(收到 {type(row).__name__})"
    keys = set(row.keys())
    unknown = keys - spec["allowed"]
    if unknown:
        # ⚠️ 第一版用子串匹配(`u in a or a in u`),于是 `bandd` 被建议成 `d` ——
        # 因为 `"d" in "bandd"` 为真。**而集合迭代顺序不定,所以那个测试是
        # 随机通过的**:一个看 hash seed 的守卫比一个失败的守卫更坏。
        # `difflib` 按相似度排序且确定性,列名短的不会因为共用一个字母而胜出。
        import difflib
        near = {}
        for u in sorted(unknown):
            cand = difflib.get_close_matches(u, sorted(spec["allowed"]),
                                             n=1, cutoff=0.7)
            if cand:
                near[u] = cand[0]
        hint = ("；你可能是想写 " + "、".join(f"`{k}`→`{v}`" for k, v in near.items())
                if near else "")
        return None, (f"[{idx}] 未知列 {sorted(unknown)} —— **拒绝而不是丢弃**,"
                      f"因为丢弃会写进一行看起来正常、实际缺列的数据{hint}")
    missing = spec["required"] - keys
    if missing:
        return None, f"[{idx}] 缺必填列 {sorted(missing)}"
    # 空值保留原样传给 PG。**不把 None 变成 0** —— 未测 ≠ 零 (I1)。
    return row, None


@router.post("/internal/mac-write/{dataset}")
async def mac_write(dataset: str, payload: dict,
                    x_internal_token: str = Header(None)):
    """Mac 侧 daily writer 的代理写入。

    Auth:`X-Internal-Token`(与 CIS push / strategy-records 同一个)。
    Body:`{"rows": [...]}`。

    逐条裁决:坏的那几条被拒并附理由,好的那些照样落库 ——
    因为要求整批重发,是一条 lane 开始绕过端点的起点。
    """
    _auth(x_internal_token)

    spec = TABLES.get(dataset)
    if not spec:
        raise HTTPException(404, {
            "error": f"未知 dataset '{dataset}'",
            "available": sorted(TABLES),
            "note": "dataset 名是 kebab-case,表名是 snake_case",
        })

    rows = payload.get("rows")
    if not isinstance(rows, list) or not rows:
        raise HTTPException(422, "body 需要非空的 `rows` 数组")
    if len(rows) > MAX_ROWS:
        raise HTTPException(422, {
            "error": f"一批最多 {MAX_ROWS} 行(收到 {len(rows)})",
            "why": "上界让失败可诊断 —— 一个巨批失败时你不知道是哪一行",
        })

    clean, rejected = [], []
    for i, r in enumerate(rows):
        ok, why = _vet(r, spec, i)
        (clean.append(ok) if ok is not None else rejected.append(why))

    written = 0
    write_error = None
    if clean:
        from src.api.store import supabase_insert_table, supabase_upsert_table
        try:
            ok = (await supabase_upsert_table(spec["table"], clean,
                                              spec["on_conflict"])
                  if spec["on_conflict"] else
                  await supabase_insert_table(spec["table"], clean))
            written = len(clean) if ok else 0
            if not ok:
                write_error = "Supabase 写入返回 false"
        except Exception as e:                                    # noqa: BLE001
            write_error = f"{type(e).__name__}: {str(e)[:160]}"

    # **三个状态分开报**:收到 / 落库 / 拒绝。
    # 一个只报 "ok" 的响应,会让「20 条收到、17 条落库」读起来像全都成功了。
    verdict = ("ok" if written == len(clean) and not rejected else
               "partial" if written else "failed")
    return {
        "verdict": verdict,
        "dataset": dataset, "table": spec["table"],
        "n_received": len(rows), "n_written": written,
        "n_rejected": len(rejected),
        "rejections": rejected[:20],
        "write_error": write_error,
        "note": ("未知列被**拒绝**而不是丢弃 —— 丢弃会写进一行看起来正常、"
                 "实际缺列的数据,而两边都以为成功了"),
    }


@router.get("/internal/mac-write/schema")
async def mac_write_schema():
    """契约回声 —— 只有形状,没有数值。无凭证可读(与该族其余端点一致)。

    Mac 侧照着它构造 payload,**不要照着 Mac 侧代码猜列名** ——
    抄来的列名会把笔误一起抄过来。
    """
    return {
        "auth": "X-Internal-Token header",
        "endpoint": "POST /internal/mac-write/{dataset}",
        "body": {"rows": ["<object>", "…"]},
        "max_rows": MAX_ROWS,
        "datasets": {
            k: {"table": v["table"], "on_conflict": v["on_conflict"],
                "required": sorted(v["required"]),
                "allowed": sorted(v["allowed"])}
            for k, v in TABLES.items()
        },
        "semantics": {
            "per_row_verdict": "坏的被拒并附理由,好的照样落库",
            "unknown_column": "**拒绝,不丢弃**",
            "null": "None 原样传给 PG —— 未测 ≠ 0 (I1)",
        },
    }
