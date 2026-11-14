"""冻结的账本(Jazz 10-20「先冻结了」;台账 S-631)—— 一处登记,四处生效。

冻结 ≠ 证伪、≠ 删除:**停写新行,历史一行不动**,登记表照样列出它(status = frozen),L3 不可选,
判活器对它的表判「不适用」而不是「死了」(否则停写五天后它会被报成故障,下一个人会去「修好」它 ——
S-323i 的教训:一个靠人记住的停用,会被下一个把它判成坏了的人重新打开)。

生效的四处:
- `src/api/main.py` —— 这几个循环的 startup 不再起任务,改为记一条 loop_attempt(outcome = refused,写明冻结);
- `src/data/accounting/registry.py` —— Book.status = frozen;
- `src/data/accounting/combine.py` / `proof.py` —— 不可选,证据等级 = frozen;
- `src/data/market/producer_freshness.py` —— 表的判活 = not_applicable。

另有三处后来接上:`src/api/liveness.py`(判活)、`scripts/ops_console.py`(指挥台,S-862)、以及 `also` 里登记的
附属循环(S-863:只为某本冻结账本服务的循环,如信号工厂之于 combined book)。

**恢复 = 删掉下面一行**(再部署)。这里只放 ④ 多空 / 事件类;①②③ 不在这里冻结。
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Frozen:
    book_id: str
    table: str
    loop: str
    since: str          # UTC 日期:最后一行之后不再写
    why: str
    #: 只为这本账服务的其它循环(S-863):账本冻结,它们跟着停、跟着解冻。
    also: tuple[str, ...] = ()


_RULING = "Jazz 10-20「先冻结了」,S-631:④ 排在回报层级最后,自起点以来绝对收益为负"

FROZEN: dict[str, Frozen] = {f.book_id: f for f in (
    Frozen("causal_paper", "causal_paper_nav", "_causal_paper_loop", "2026-10-20",
           f"{_RULING};07-13 起 −4.1%(价格 −5.1%、资金费 +1.4%、成本 −0.4%)"),
    Frozen("scalable_book", "scalable_book_nav", "_scalable_book_loop", "2026-10-20",
           f"{_RULING};07-16 起 −10.7%(Jazz 批的是前四本,这本同属 ④ 多空,同一条理由一并冻结)"),
    Frozen("combined_book", "combined_book_nav", "_combined_book_loop", "2026-10-20",
           f"{_RULING};07-15 起 −10.7%(同上,一并冻结)",
           # 信号工厂每周(以及每次部署)重算的就是这本账的权重:账本不写了,重算没有读者。11-14 量到它每次部署
           # 同步拉 Binance 43.8 秒(S-862 补三);Jazz 11-14「修复」。
           also=("_factory_recalibrate_loop",)),
    Frozen("dingge_paper", "dingge_paper_nav", "_dingge_paper_loop", "2026-10-20",
           f"{_RULING};07-15 起 −3.3%"),
    Frozen("fusion_paper", "fusion_paper_nav", "_fusion_paper_loop", "2026-10-20",
           f"{_RULING};v2 09-19 → 10-13 −1.2%,全部是成本;v3 10-20 刚重开即冻结"),
    Frozen("two_layer_paper", "two_layer_paper_nav", "_two_layer_paper_loop", "2026-10-20",
           f"{_RULING};07-22 起 ≈ 0(核心多数日子不触发,本就按设计退役)"),
)}


def is_frozen(book_id: str) -> bool:
    return book_id in FROZEN


def frozen_tables() -> dict[str, Frozen]:
    return {f.table: f for f in FROZEN.values()}


def frozen_loops() -> dict[str, Frozen]:
    """循环名 → 它所属的冻结登记。含 `also` 里那些只为这本账服务的循环。"""
    out = {f.loop: f for f in FROZEN.values()}
    for f in FROZEN.values():
        for name in f.also:
            out[name] = f
    return out


def startup_note(book_id: str) -> str:
    f = FROZEN[book_id]
    return f"冻结({f.since} 起不再写新行;历史保留;恢复 = 删 src/data/accounting/frozen.py 里这一行):{f.why}"
