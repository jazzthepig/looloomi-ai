"""判活响应必须在**顶层**给一个裁决 (S-272)。

## 起因

2026-09-02 Jazz:「系统检测说 ohlcv 又停了,是否如此?」

查下来:**没有任何东西是新停的。** coingecko 完整日连续 12 天 25/25、
eodhd 33/33;停的是 hyperliquid(10d)和 binance_hist(13d),而它们从
08-23 / 08-20 就停了,当天只是各自又老了一天。

但 `/internal/data-freshness` 的响应里有**两个嵌套裁决而顶层一个都没有**:

    by_source.verdict    "domain_without_usable_source"   ← 权威
    ohlcv_daily.verdict  "fresh"                          ← 更浅、词更眼熟

**两个裁决都没说错。** 错的是没有一个字段回答「所以我该担心吗」——
于是告警只能在两者里挑一个,而 `fresh` 更像一个整体健康判断。

## 我先前把这件事说错了,值得记下来

我第一反应是「旧那块是 S-251 要替掉却还留着的」。**代码里的注释明写它是
有意保留的**:「不替换上面的判据(它对『这一轮跑完没有』仍然有效),
而是并排给出第二个维度……『某个东西是新的』和『这个管道是活的』从此是两个字段。」

**我没读那段注释就断言了动机。** 真正的缺陷比我说的窄:不是多了一块,
是少了一个顶层字段。
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

_FAIL: list[str] = []
MAIN = ROOT / "src" / "api" / "main.py"


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _handler_src() -> str:
    from tests._source import code_only        # AST 剥注释+docstring,不手写第四个
    src = MAIN.read_text()
    i = src.find("async def data_freshness")
    if i < 0:
        i = src.find('"/internal/data-freshness"')
    j = src.find("\n@app.", i + 1)
    return code_only(src[i:j if j > 0 else len(src)])


def t_the_response_carries_a_top_level_verdict():
    """**本文件的理由。** 顶层没有裁决 ⇒ 告警只能在嵌套的里挑一个。"""
    body = _handler_src()
    _check('顶层写入 out["verdict"]', 'out["verdict"]' in body,
           "顶层没有裁决 —— 消费者只能挑一个嵌套的")
    _check("顶层裁决取自 by_source(权威的那个)",
           'out["verdict_source"] = "by_source"' in body)
    _check("有一条说明指出该读哪个、为什么",
           'verdict_note' in body and "我该担心吗" in body)


def t_each_block_declares_which_question_it_answers():
    """两块并排是有意的(S-251),但它们不能看起来在回答同一个问题。"""
    body = _handler_src()
    _check("ohlcv_daily 块声明了 answers", '"answers"' in body)
    _check("answers 明说它【不】回答管道存活",
           "不回答" in body and "by_source" in body, "两块仍可能被读成同一个问题")
    _check("读取失败的分支也带 answers(否则失败时又退回同形)",
           body.count('"answers"') >= 2,
           f"只有 {body.count(chr(34) + 'answers' + chr(34))} 处 —— 异常分支漏了")


def t_the_authoritative_dimension_is_per_source_coverage():
    """权威维度是「每源 × 覆盖标的数」,不是全表 max。

    S-251 的实测:binance_hist 自 08-09 起每天只写 BCH 一个标的,连写 19 天,
    全表 max 天天前进,而 260 个标的已经死了 —— 端点照报 fresh。
    **一个还活着的写入者掩护了 260 个死掉的。**
    """
    from src.data.market.source_freshness import classify

    # ⚠️ 裁决在 source_freshness 里是**裸字符串字面量**,没有导出常量 ——
    # 调用点打错一个字母会静默不匹配。记在这里,不在本次范围内改。
    alive = classify("coingecko", last_bar="2026-09-02", age_days=0,
                     symbols_recent=25, symbols_typical=25)
    masked = classify("binance_hist", last_bar="2026-09-02", age_days=0,
                      symbols_recent=1, symbols_typical=221)
    _check("满覆盖 → flowing", alive.verdict == "flowing", alive.verdict)
    _check("**同样 0 天停滞、但只剩 1/221 个标的 → 不是 flowing**",
           masked.verdict != "flowing", f"{masked.verdict}: {masked.detail}")
    _check("两者的停滞天数完全相同 —— **只有覆盖率能分开它们**",
           alive.verdict != masked.verdict,
           "全表 max 口径下这两个同形,这就是 S-251 存在的理由")


def t_the_measured_state_on_the_day_of_the_alarm():
    """把 2026-09-02 的实测钉住,免得下次「又停了」时重新猜一遍。

    这不是断言生产现状(那会随时间变),而是断言**判活层对这组输入的裁决**。
    """
    from src.data.market.source_freshness import classify
    cases = [
        ("coingecko", 0, 25, 25, "flowing"),
        ("eodhd", 1, 33, 33, "flowing"),
        ("hyperliquid", 10, 0, 177, "DEAD"),
        ("binance_hist", 13, 0, 162, "DEAD"),
    ]
    for src, age, recent, typ, want in cases:
        got = classify(src, last_bar="2026-09-02", age_days=age,
                       symbols_recent=recent, symbols_typical=typ)
        _check(f"{src}: {age}d, {recent}/{typ} → {want}", got.verdict == want,
               f"{got.verdict}: {got.detail}")


if __name__ == "__main__":
    print("── 判活顶层裁决守卫 (S-272) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 判活顶层裁决守卫全绿")
