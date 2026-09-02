"""Mac 侧代理写入的守卫 (S-277)。

这个文件里只有一条真正重要的断言:

    **未知列必须拒绝,不能静默丢弃。**

如果先做一次「挑出已知列」的过滤,一个拼错的字段(`regime` vs `macro_regime`)
就会被悄悄丢掉,于是写进去一行看起来正常、实际缺列的数据,而两边都以为成功了。
**这正是 S-273…S-276 反复出现的形状**:两个不同的状态
(「这个字段没值」和「这个字段名写错了」)塌进同一个表示。

第二条:**列名取自 information_schema,不是从 Mac 侧代码抄的** ——
抄来的列名会把对方的笔误一起抄过来,而那时守卫会为笔误背书。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.routers.mac_writes import MAX_ROWS, TABLES, _vet   # noqa: E402

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def t_unknown_column_is_rejected_not_dropped():
    """**本文件的理由。**"""
    spec = TABLES["risk-meter-history"]
    row, why = _vet({"d": "2026-09-02", "regime": "TIGHTENING", "bandd": "x"}, spec, 0)
    _check("拼错的列 → 拒绝(row 是 None)", row is None)
    _check("理由点破「拒绝而不是丢弃」", "拒绝而不是丢弃" in why, why[:80])
    _check("给出近似列名的提示", "`band`" in why, why[-70:])

    # ⚠️ 第一版用子串匹配,`bandd` 被建议成 `d`(因为 "d" in "bandd"),
    # 而集合迭代顺序不定 ⇒ **这条断言曾经随机通过**。
    # 跑多次必须每次同一个答案 —— 一个看 hash seed 的守卫比失败的守卫更坏。
    answers = {_vet({"d": "x", "bandd": "y"}, spec, 0)[1] for _ in range(8)}
    _check("同一输入多次给同一个提示(确定性)", len(answers) == 1, str(answers))
    _check("不会把长列名匹配到单字母列", "→`d`" not in why, why[-70:])

    # 判别性:合法行必须通过,否则这就是「见谁都拒」
    ok_row, ok_why = _vet({"d": "2026-09-02", "regime": "TIGHTENING",
                           "score": 0.4}, spec, 1)
    _check("合法行通过", ok_row is not None and ok_why is None, str(ok_why))
    _check("通过的行原样传下去(没有被裁剪)", ok_row == {
        "d": "2026-09-02", "regime": "TIGHTENING", "score": 0.4}, str(ok_row))


def t_missing_required_is_its_own_rejection():
    spec = TABLES["asset-embeddings-history"]
    _, why = _vet({"asset_class": "L1"}, spec, 0)
    _check("缺必填 → 拒绝", why is not None)
    _check("理由列出缺了哪些", "d" in why and "symbol" in why, why)
    _check("与「未知列」是不同的理由(两个状态不同形)",
           "未知列" not in why, why)


def t_none_is_passed_through_not_coerced_to_zero():
    """未测 ≠ 0 (I1)。一个 None 的 score 不是 0 分。"""
    spec = TABLES["risk-meter-history"]
    row, _ = _vet({"d": "2026-09-02", "score": None}, spec, 0)
    _check("None 原样传下去", row is not None and row["score"] is None, str(row))
    _check("键仍然在(不是被删掉)", "score" in row, str(row))


def t_every_dataset_declares_conflict_and_required():
    for name, spec in TABLES.items():
        _check(f"{name}:required ⊆ allowed",
               spec["required"] <= spec["allowed"],
               str(spec["required"] - spec["allowed"]))
        _check(f"{name}:声明了 on_conflict(None 表示纯追加)",
               "on_conflict" in spec)
    _check("四张表都在", len(TABLES) == 4, str(sorted(TABLES)))
    _check("upsert 的表都有冲突键",
           all(s["on_conflict"] for n, s in TABLES.items()
               if n in ("risk-meter-history", "asset-embeddings-history")))


def t_batch_cap_exists_so_failures_are_diagnosable():
    _check(f"批上限 {MAX_ROWS} 存在且不是天文数字", 0 < MAX_ROWS <= 2000, str(MAX_ROWS))


def t_columns_match_information_schema_not_mac_side_code():
    """列名必须是我们从库里查出来的。**抄 Mac 侧代码会把笔误一起抄过来。**"""
    # 实查 2026-09-02 的关键列,写死在这里作为回归锚
    _check("risk_meter_history 有 long_gross(不是 gross)",
           "long_gross" in TABLES["risk-meter-history"]["allowed"])
    _check("asset_embeddings_history 有 macro_regime(不是 regime)",
           "macro_regime" in TABLES["asset-embeddings-history"]["allowed"]
           and "regime" not in TABLES["asset-embeddings-history"]["allowed"])
    _check("signal_journal 有 alpha_30d",
           "alpha_30d" in TABLES["signal-journal"]["allowed"])
    _check("trade_results 有 realized_return_7d",
           "realized_return_7d" in TABLES["trade-results"]["allowed"])
    # 两张表都有 macro_regime 但 risk_meter 用的是 regime —— **这正是会写错的地方**
    _check("risk_meter 用 regime、embeddings 用 macro_regime(不同表不同名)",
           "regime" in TABLES["risk-meter-history"]["allowed"]
           and "macro_regime" in TABLES["asset-embeddings-history"]["allowed"])


def main() -> int:
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("t_")]:
        print(f"\n▸ {fn.__name__}")
        fn()
    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
