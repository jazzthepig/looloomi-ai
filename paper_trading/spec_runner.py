"""Paper-trade 执行器:按 spec JSON 跑,拒绝比成交更有信息 (S-254).

## 这是谁的活,以及它欠了多久

`Shadow/cometcloud-local/paper_trading_specs/m86_r22_k1_hold14_ret3d_README.md`:

    - **minimax-c (engine):** SHIP - 2026-08-26 (「直接走」)
    - **Seth/Austin (execution):** PENDING - wire up execution per pseudo-code above
    - **Jazz (strategic):** SHIP - 2026-08-26

**三个 spec 已经 ship 到 Mac 侧,而 `paper_trading/` 目录不存在。**
M-86(④ 卫星)· M-87(② beta+,OOS +19.94% / SR +2.270)·
M-88(③ beta multiplier,OOS +29.90% / SR +1.912)——
全部 OOS 验证过、全部等着一条执行路径。

## 为什么是 spec-driven 而不是给 M-86 写一个

三个 spec 现在,还会有更多(M-93 ① 也要接)。给每个 spec 写一个 runner,
就是给每个 spec 一份会各自漂移的成交逻辑 —— 今天已经因为
「两个展平器 / 四个 regime 规范化实现」被抓过两次(S-249)。
一份 runner,spec 是数据。

## 但实测发现:三个 spec 是三种 schema,不是一种

接线时才发现的,值得记下来:

    M-86  cross_sectional_momentum_ls    K · rank_by · n_lookback · hold · cadence
    M-87  cluster_tilt_cross_sectional_ls K_long/K_short · score_formula · rebalance:"daily"
    M-88  regime_switch_beta_multiplier   regime_proxy · if_btc_21d_gt_0 / _le_0

**M-88 根本不是横截面排名** —— 它是一个 regime 开关,按 BTC 21d 收益的符号
在两个完全不同的子策略之间切。用一份"通用" runner 硬吃三种,只会在
M-88 上产生一个**语义上错误但语法上成功**的成交。

所以按 `spec_family` 分派,而**没有接线的 family 明确拒绝**:
`Spec.load` 缺字段抛异常(S-122:不填默认值),`FAMILIES` 表说清楚谁通了。
把"这个 family 还没接"变成一个可读的失败,而不是一次静默的错误成交。

**当前状态:1/3 接通。** 这不是好消息,但它是真的,而且现在可查。

## 它必须拒绝的场景,而不是硬着头皮成交

**这条是本模块的核心,不是防御性编程。**

实测 2026-08-27(S-251):M-86 的 `data_source.primary = "binance_hist"`,
而 binance_hist **最近 3 天 0/212 个标的**,自 08-09 起每天只写 BCH 一个。
一个照着 spec 跑的 runner 会:拿到历史面板 → 排序 → **开一笔仓**,
而那笔仓是按 7 天前的价格排的。**它会产生一条看起来正常的 paper 记录。**

纸面账的价值全部来自它是不是一份诚实的前向记录。一笔在死数据上开的仓
污染的不是这一笔,是整条曲线 —— 而且**不可分辨**,因为记录里不会写
"这天的价格是 7 天前的"。所以:panel 不新鲜 → `BLOCKED`,不开仓,写下原因。

三值,不是两值:

    ENTERED   开了仓,附标的与 regime
    SKIPPED   规则说不开(排不出两条腿 / regime 被跳过 / 已达 max_open)
    BLOCKED   我们【算不了】(价源死了 / 覆盖不足 / 跨源)

`SKIPPED` 是策略在工作,`BLOCKED` 是我们瞎了。把它们压成"今天没开仓"
正是 S-207 那一课(规则拒绝 vs 规则跑不起来 → 一个"没开仓")。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Any, Mapping, Optional, Sequence

if TYPE_CHECKING:
    from src.data.market.regime_quorum import RegimeQuorum
    from paper_trading.jev_regime import JevRegimeDecision

#: Re-export Jev gate type for callers that prefer `from spec_runner import JevRegimeDecision`.
#: Pattern A pre-filter (per docs/jev_nautilus_integration_plan_2026-09-21.md) lives in
#: paper_trading.jev_regime; spec_runner only consumes it.
from paper_trading.jev_regime import JevRegimeDecision  # noqa: E402,F401

log = logging.getLogger("spec_runner")

#: panel 最后一根 bar 距今超过这个天数 → BLOCKED。
#: 加密 24/7,所以 2 天已经很宽松;这不是"容错",是"再宽就等于用旧价开仓"。
MAX_PANEL_AGE_DAYS = 2

#: 排序至少需要几个标的。K=1 的多空需要 2 条腿,但只有 2 个标的时
#: "最高"和"最低"是同一次比较,没有横截面信息可言。
MIN_UNIVERSE_FOR_RANK = 3


#: 哪些 spec_family 真的有 decide() 实现。**True 才会被执行。**
#:
#: 把它写成一张表而不是一句 if,是因为"哪些通了"必须是**可查的事实**,
#: 不是读代码读出来的推断。今天 S-244 那一课:写了 ≠ 被执行;
#: 这里是它的反面 —— **没写的必须说出来自己没写。**
FAMILIES: dict[str, bool] = {
    "cross_sectional_momentum_ls": True,        # M-86:本模块实现
    "cluster_tilt_cross_sectional_ls": True,    # M-87:实现于此;外部特征须带出处
    "regime_switch_beta_multiplier": False,     # M-88:regime 开关切两个子策略,机制不同
    "survivors_only_lag1_book": True,           # M-113 V3 / M-115 Book B:2-sleeve book
                                                # (① regime-gated BTC + ④ cross-section L/S)
    "btc_trend_regime_ladder": True,            # M-152 Path π:① BTT-LEX standalone
                                                # (BTC MA{N}+mom{N}, lag-1) × regime ladder
                                                # SHIP-READY: SR +1.115 / cum +178.0% / MaxDD -20.44%
    "panel_long_only": True,                    # A-17 形态 A:panel-wide long-only hold
                                                # (整个 universe 等权 / CIS 权, lag-1, 可选
                                                # regime gate + rebalance cadence) ——
                                                # §5b ① 的 panel-wide 形态,基准本应
                                                # 只回报 beta,excess ≤ cost bps
    "panel_long_only_simple_factor": True,      # S-393 arm C: A-17 形态 A + per-symbol
                                                # factor AND-gate (SMA60 + mom_60 > 0 +
                                                # realized_vol_30 < threshold);仅 long
                                                # 通过的子集;0/N → SKIPPED。
                                                # Comparison arm for Jev vs baseline vs
                                                # simple-factor (JAZZ 2026-09-21)。
                                                # 复用 panel_long_only 的 BLOCKED / SKIPPED
                                                # 纪律,只在 step ⑦ 加 factor gate。
}
#: 2026-09-04 K fix: 双名字 `survivors_only_lag1_book_bookB` 在 S-249 形状下
#: 是一个漂移 hazard —— bookB 和 bookA 在运行时只是同一个家族的两个 alias,
#: 但 report / config / spec JSON 三处都会各自写一份,各自漂移。统一为单名字;
#: 任何带 `_bookB` 后缀的 spec JSON 在加载时就拒绝。
_RETIRED_FAMILIES: dict[str, str] = {
    "survivors_only_lag1_book_bookB": (
        "spec_family 'survivors_only_lag1_book_bookB' 已退役 (2026-09-04 K fix)。"
        " 改用 'survivors_only_lag1_book' —— 它现在是 M-113 V3 / M-115 Book B 的单名字。"
    ),
}


class UnwiredFamily(NotImplementedError):
    """这个 spec 的机制还没有实现 —— 明确拒绝,不要用别的 family 的逻辑凑合。"""


@dataclass(frozen=True)
class ExternalFeature:
    """spec 的打分公式里引用的、**不由本模块计算**的特征 + 它的出处。

    ## 为什么这必须带出处,而不是我自己算一个

    M-87 的 `score_formula = "ret_3d + 0.3 * asset_embedding.momentum_60d"`。
    `momentum_60d` **不在 Supabase 的 `asset_embeddings` 里** —— 那张表的
    `vec_full` 是位置数组(v3)或字典(v2,已陈旧 34 天),而 embedder 的维度里
    根本没有这个名字。它是 autoresearch_v5 在 Mac 侧算的资产特征,
    spec 的 `data_source.vdb_path` 指的就是那个 sqlite。

    我试过把它当作"60 日收益"自己算。实测 2026-08-27,对着研究窗口末端 07-27:

        symbol   60 日收益(我算)   报告的 momentum_60d
        BTC        −12.16%            −38.91%
        ETH         −3.50%            −49.43%
        LINK        −3.40%            −47.34%
        AVAX       −25.49%            −66.84%

    **不只是量级差 3–14 倍,排序是反的** —— 我算 ETH 优于 BTC,报告里 ETH 劣于 BTC。
    而这个策略就是按分数取 top-3/bottom-3,**排序反了就是完全不同的持仓**。

    > **自己定义这一维,跑出来的就不是那个被 OOS 验证过 +19.94% / SR +2.270 的 M-87。**

    那个数字会继续挂在报告上,而实际在跑的是另一个策略 —— 「shipped spec ≠
    validated spec」,并且**静默发生**。所以:特征必须显式喂进来并声明出处,
    拿不到就 BLOCK。宁可不跑,不可跑一个名字对、内容不对的策略。
    """

    name: str
    values: Mapping[str, float]
    provenance: str          # 这些数从哪来 —— 空字符串不接受
    as_of: Optional[str] = None

    def __post_init__(self) -> None:
        if not self.provenance.strip():
            raise ValueError(
                f"外部特征 '{self.name}' 必须声明出处 —— 一个说不出自己从哪来的"
                f"打分项,会让 OOS 声明悄悄地不再适用于正在跑的东西")


class Verdict:
    ENTERED = "ENTERED"
    SKIPPED = "SKIPPED"
    BLOCKED = "BLOCKED"


#: verdict → verdict_kind 分桶映射(J fix,2026-09-04)。分开了「规则拒绝」
#: 与「数据算不出」(S-207)。**模块级**而不是 Decision 类属性 —— Decision 是
#: `@dataclass(frozen=True)`,把可变 dict 放成字段会让 dataclass 抛
#: "mutable default <class 'dict'> for field VERDICT_KIND"。模块级常量的
#: lifetime 等于进程,等价。
VERDICT_KIND: dict[str, str] = {
    Verdict.ENTERED: "entered",
    Verdict.SKIPPED: "skipped",
    Verdict.BLOCKED: "blocked",
}


@dataclass(frozen=True)
class Leg:
    symbol: str
    side: str            # "long" | "short"
    weight: float
    price: float


@dataclass(frozen=True)
class Decision:
    """一天的判定 = 结论 + 为什么。没有 reason 的 SKIPPED/BLOCKED 不接受。"""

    d: str
    spec_name: str
    verdict: str
    reason: str = ""
    legs: tuple[Leg, ...] = ()
    regime: Optional[str] = None
    panel_source: Optional[str] = None
    panel_last_bar: Optional[str] = None

    def __post_init__(self) -> None:
        if self.verdict in (Verdict.SKIPPED, Verdict.BLOCKED) and not self.reason:
            raise ValueError(
                f"{self.verdict} 必须带原因 —— 一个说不出'为什么没开仓'的判定,"
                f"和一次静默失败在下游长得一样 (S-207)")
        if self.verdict == Verdict.ENTERED and not self.legs:
            raise ValueError("ENTERED 却没有腿 —— 那不是开仓")

    # verdict_kind 分开了「规则拒绝」与「数据算不出」(S-207,2026-09-04 J fix)。
    # 之前 SKIPPED 和 BLOCKED 都被压进同一个 `reason` 字段,
    # 下游拿到 JSON 分不清"规则说不开"和"我们瞎了"。
    # 现在 verdict_kind 在 verdict 同层,consumer 可以按 kind 分桶。
    # VERDICT_KIND 是模块级常量(见 class Verdict 之后)。
    def as_payload(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "date": self.d, "spec": self.spec_name, "verdict": self.verdict,
            "verdict_kind": VERDICT_KIND[self.verdict],
            "regime": self.regime,
            "panel": {"source": self.panel_source, "last_bar": self.panel_last_bar},
        }
        if self.legs:
            out["legs"] = [{"symbol": l.symbol, "side": l.side,
                            "weight": l.weight, "price": l.price} for l in self.legs]
        if self.verdict != Verdict.ENTERED:
            out["reason"] = self.reason
        return out


@dataclass
class Spec:
    """spec JSON 的最小契约。多的字段忽略,少的字段必须报错而不是默认。"""

    name: str
    universe: tuple[str, ...]
    rank_by: str
    n_lookback: int
    hold: int
    cadence: int
    k: int
    weight_per_leg: float
    cost_bps_rt: float
    dd_stop_pct: float
    max_open_trades: int
    skip_regimes: frozenset[str]
    source: str
    dry_run: bool
    raw: Mapping[str, Any] = field(default_factory=dict)

    family: str = "cross_sectional_momentum_ls"
    #: cluster_tilt 专用。cross_sectional 家族里 k_long == k_short == k。
    k_long: int = 0
    k_short: int = 0
    tilt_weight: float = 0.0
    #: 打分公式里引用的外部特征名(本模块不计算,必须带出处喂进来)。
    external_features: tuple[str, ...] = ()

    @classmethod
    def load(cls, path: str | Path) -> "Spec":
        """从 JSON 读。**缺字段抛异常,不填默认值。**

        一个默认的 `cost_bps_rt = 0` 会让每条曲线都好看一点,而且不会有人发现 ——
        MEMORY.md:「默认值越接近多数类越查不出,危害与可发现性成反比」(S-122)。
        """
        raw = json.loads(Path(path).read_text())
        fam = str(raw.get("spec_family") or "")
        # K fix (2026-09-04): 拒绝已退役的 family 名,带原因。S-249 形状下双名字
        # 会让 spec JSON、report、config 三处各自漂移 —— 在加载时拒绝比让它静默
        # 跑到 produce 一个错误家族的成交要好。
        if fam in _RETIRED_FAMILIES:
            raise ValueError(_RETIRED_FAMILIES[fam])
        if fam not in FAMILIES:
            raise UnwiredFamily(
                f"spec_family '{fam}' 还没有接线(spec={raw.get('spec_name')})。"
                f"已接:{sorted(k for k, v in FAMILIES.items() if v)};"
                f"已知未接:{sorted(k for k, v in FAMILIES.items() if not v)}。"
                f"用通用 runner 硬吃一个不同机制的 family,会产生语法成功、"
                f"语义错误的成交 —— 那比不跑更糟。")
        if not FAMILIES[fam]:
            raise UnwiredFamily(
                f"spec_family '{fam}' 已知但【尚未接线】(spec={raw.get('spec_name')})。"
                f"它的机制与 cross_sectional_momentum_ls 不同,需要自己的 decide()。")
        p = raw.get("parameters") or {}
        ds = raw.get("data_source") or {}
        ex = raw.get("execution") or {}

        def need(container: Mapping[str, Any], key: str, where: str):
            if key not in container or container[key] is None:
                raise ValueError(f"spec 缺 {where}.{key} —— 不填默认值 (S-122)")
            return container[key]

        if fam == "cluster_tilt_cross_sectional_ls":
            # M-87 的 schema 与 M-86 不同 —— 逐字段映射,不猜。
            formula = str(need(p, "score_formula", "parameters"))
            # 公式里 `asset_embedding.X` 的 X 就是外部特征名。
            import re as _re
            ext = tuple(sorted(set(_re.findall(r"asset_embedding\.([a-z_0-9]+)", formula))))
            kl, ks = int(need(p, "K_long", "parameters")), int(need(p, "K_short", "parameters"))
            return cls(
                name=need(raw, "spec_name", "spec"),
                universe=tuple(need(raw, "universe", "spec")),
                rank_by=formula,
                n_lookback=int(need(p, "lookback_ret_n", "parameters")),
                hold=0,                       # daily rebalance:没有固定持仓期
                cadence=1,                    # rebalance="daily"
                k=max(kl, ks),
                k_long=kl, k_short=ks,
                tilt_weight=float(need(p, "tilt_weight", "parameters")),
                external_features=ext,
                weight_per_leg=float(need(p, "weight_per_leg", "parameters")),
                cost_bps_rt=float(need(p, "cost_bps_rt_max", "parameters")),
                dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
                max_open_trades=int(need(p, "max_open_trades", "parameters")),
                skip_regimes=frozenset(str(r).upper() for r in (p.get("skip_regimes") or [])),
                source=str(need(ds, "primary", "data_source")),
                family=fam,
                dry_run=bool(ex.get("dry_run", True)),
                raw=raw,
            )

        if fam == "btc_trend_regime_ladder":
            # M-152 Path π BTT-LEX: ① BTC trend (MA{N} + mom{N}, lag-1) ×
            # Regime Multiplier Ladder. First standalone ① slot — §5b 的
            # "long-only panel hold" 在 BTC 单资产上的形态;panel-wide 1 后续。
            ma_lookback = int(need(p, "ma_lookback", "parameters"))
            mom_lookback = int(need(p, "mom_lookback", "parameters"))
            mults = need(p, "regime_multipliers", "parameters")
            if not isinstance(mults, dict) or not mults:
                raise ValueError(
                    "spec 缺 parameters.regime_multipliers — 必须提供一个 "
                    "regime → weight 的映射,key 是规范化的 regime 名 "
                    "(EASING/TIGHTENING/RISK_OFF/RISK_ON/STAGFLATION/NEUTRAL)")
            canonical = {
                str(k).upper(): float(v) for k, v in mults.items()
                if v is not None
            }
            if not canonical:
                raise ValueError(
                    "spec 的 regime_multipliers 全是 None —— 没法决定仓位")
            return cls(
                name=need(raw, "spec_name", "spec"),
                universe=tuple(need(raw, "universe", "spec")),   # 通常 ["BTC"]
                rank_by="btc_trend_ma_mom",       # family 决定走哪条 decide
                n_lookback=mom_lookback,          # 兼容 decide() 默认字段
                hold=1,                           # 每日 mark
                cadence=1,
                k=1, k_long=1, k_short=0,
                weight_per_leg=1.0,               # 占位 —— 实际权重由 regime ladder 决定
                cost_bps_rt=float(need(p, "cost_bps_rt", "parameters")),
                dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
                max_open_trades=int(need(p, "max_open_trades", "parameters")),
                skip_regimes=frozenset(),          # regime ladder 自带
                source=str(need(ds, "primary", "data_source")),
                family=fam,
                dry_run=bool(ex.get("dry_run", True)),
                raw=raw,
            )

        if fam == "panel_long_only":
            # A-17 / docs/PANEL_LONG_ONLY_SPEC.md — §5b ① 形态 A:panel-wide
            # long-only hold。是 **基准本**,应该只回报 beta,excess ≤ cost bps
            # (equal-weight 形态下)。Panel-wide 比 M-152 BTT-LEX(单 BTC)多覆盖
            # 整个 benchmark universe —— 两者合起来才是完整的 ①。
            #
            # Parameters:
            #   allocation: equal_weight | cis_weight | market_cap_weight
            #   target_size: int  (0 = 整个 universe;>0 = 按 allocation 取 top N)
            #   rebalance_cadence: int  (days between rebalances)
            #   max_position_pct: float (cap any single position)
            #   min_position_pct: float (floor)
            #   regime_gate: dict {REGIME: bool, default: bool}  (可选)
            #   min_history_days: int  (panel needs at least N days per symbol)
            allocation = str(need(p, "allocation", "parameters")).lower()
            if allocation not in ("equal_weight", "cis_weight", "market_cap_weight"):
                raise ValueError(
                    f"spec allocation '{allocation}' 不是合法值 —— v1 ship 只接 "
                    f"'equal_weight';cis_weight / market_cap_weight 在下一档 "
                    f"(PANEL_LONG_ONLY_SPEC §'Allocation helpers')")
            target_size = int(need(p, "target_size", "parameters"))
            if target_size < 0:
                raise ValueError(
                    f"target_size = {target_size} 非法 —— 0 = 全 universe,>0 = top N")
            rebalance_cadence = int(need(p, "rebalance_cadence", "parameters"))
            if rebalance_cadence < 1:
                raise ValueError(
                    f"rebalance_cadence = {rebalance_cadence} 非法 —— 至少 1 天")
            max_pos = float(p.get("max_position_pct", 1.0))
            min_pos = float(p.get("min_position_pct", 0.0))
            if max_pos <= 0 or max_pos > 1.0:
                raise ValueError(f"max_position_pct={max_pos} 非法 —— (0, 1]")
            if min_pos < 0 or min_pos >= max_pos:
                raise ValueError(f"min_position_pct={min_pos} 非法 —— [0, max_position_pct)")
            min_history_days = int(need(p, "min_history_days", "parameters"))
            if min_history_days < 30:
                raise ValueError(
                    f"min_history_days = {min_history_days} 太短 —— ① 候选至少需要 "
                    f"30 天,默认 365 (PANEL_LONG_ONLY_SPEC §'Why long-only')")
            return cls(
                name=need(raw, "spec_name", "spec"),
                universe=tuple(need(raw, "universe", "spec")),
                rank_by=f"panel_long_only_{allocation}",  # family 决定走哪条 decide
                n_lookback=min_history_days,              # 兼容 decide() 默认字段
                hold=rebalance_cadence,                   # 兼容 decide() 默认字段
                cadence=rebalance_cadence,
                k=1, k_long=1, k_short=0,                 # 全 long,no short
                weight_per_leg=1.0 / max(len(need(raw, "universe", "spec")), 1),
                cost_bps_rt=float(need(p, "cost_bps_rt", "parameters")),
                dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
                max_open_trades=int(need(p, "max_open_trades", "parameters")),
                skip_regimes=frozenset(),                 # regime gate 由 spec 处理
                source=str(need(ds, "primary", "data_source")),
                family=fam,
                dry_run=bool(ex.get("dry_run", True)),
                raw=raw,
            )

        if fam == "panel_long_only_simple_factor":
            # S-393 arm C: A-17 panel_long_only + per-symbol factor AND-gate.
            # Parameters mirror `panel_long_only` (allocation / cadence / cap /
            # min_history) PLUS `factor_filter` (sma_window / mom_window /
            # vol_window / vol_threshold_daily_stdev / sma_ok_rule).
            #
            # Why a separate family instead of a `panel_long_only + factor` flag:
            # 1. Same universe + same cadence + same allocation — but the
            #    decide() step ⑦ differs (factor filter vs unconditional).
            # 2. `min_history_days` MUST be ≥ max(sma_window, mom_window + 1,
            #    vol_window + 1). For default (60/60/30) the floor is 90.
            #    `panel_long_only` ships with 60d floor → reusing that family
            #    would silently let an under-built factor symbol slip through.
            # 3. _meta separation: comparison arm writes different _meta
            #    fields than the production-shape benchmark — better to have
            #    distinct family so consumers don't accidentally compare.
            allocation = str(need(p, "allocation", "parameters")).lower()
            if allocation not in ("equal_weight", "cis_weight", "market_cap_weight"):
                raise ValueError(
                    f"spec allocation '{allocation}' 不是合法值 —— v1 ship 只接 "
                    f"'equal_weight';cis_weight / market_cap_weight 在下一档 "
                    f"(PANEL_LONG_ONLY_SPEC §'Allocation helpers')")
            target_size = int(need(p, "target_size", "parameters"))
            if target_size < 0:
                raise ValueError(
                    f"target_size = {target_size} 非法 —— 0 = 全 universe,>0 = top N")
            rebalance_cadence = int(need(p, "rebalance_cadence", "parameters"))
            if rebalance_cadence < 1:
                raise ValueError(
                    f"rebalance_cadence = {rebalance_cadence} 非法 —— 至少 1 天")
            ff = need(p, "factor_filter", "parameters")
            if not isinstance(ff, dict):
                raise ValueError(
                    "parameters.factor_filter 必须是一个 dict —— {sma_window, "
                    "mom_window, vol_window, vol_threshold_daily_stdev, sma_ok_rule}")
            sma_window = int(need(ff, "sma_window", "parameters.factor_filter"))
            mom_window = int(need(ff, "mom_window", "parameters.factor_filter"))
            vol_window = int(need(ff, "vol_window", "parameters.factor_filter"))
            vol_th = float(need(ff, "vol_threshold_daily_stdev",
                                "parameters.factor_filter"))
            sma_rule = str(ff.get("sma_ok_rule", "above"))
            if sma_rule not in ("above", "below_or_equal"):
                raise ValueError(
                    f"factor_filter.sma_ok_rule='{sma_rule}' 非法 —— "
                    f"v1 只接 'above'(trend-following);'below_or_equal' "
                    f"留给 mean-reversion 扩展")
            max_pos = float(p.get("max_position_pct", 1.0))
            min_pos = float(p.get("min_position_pct", 0.0))
            if max_pos <= 0 or max_pos > 1.0:
                raise ValueError(f"max_position_pct={max_pos} 非法 —— (0, 1]")
            if min_pos < 0 or min_pos >= max_pos:
                raise ValueError(f"min_position_pct={min_pos} 非法 —— [0, max_position_pct)")
            min_history_days = int(need(p, "min_history_days", "parameters"))
            # min_history_days 必须够算全部三个 factor —— 否则符号会"已经 ENTERED"
            # 但 factor 算不出 (sma=None → factor fails) → 当天该符号被 skip,
            # 看起来像"factor 太严" 实际是 min_history_days 太松。
            # 缓冲 +1 是因为 mom_window 需要 mom_window+1 个 close(分母).
            floor = max(sma_window, mom_window + 1, vol_window + 1) + 1
            if min_history_days < floor:
                raise ValueError(
                    f"min_history_days = {min_history_days} 不足以算全部三个 factor"
                    f"(sma={sma_window}, mom={mom_window}+1, vol={vol_window}+1) "
                    f"—— 至少 {floor}")
            return cls(
                name=need(raw, "spec_name", "spec"),
                universe=tuple(need(raw, "universe", "spec")),
                rank_by=f"panel_long_only_simple_factor_{allocation}",  # dispatcher key
                n_lookback=min_history_days,                # 兼容 decide() 默认字段
                hold=rebalance_cadence,                     # 兼容 decide() 默认字段
                cadence=rebalance_cadence,
                k=1, k_long=1, k_short=0,                   # 全 long, no short
                weight_per_leg=1.0 / max(len(need(raw, "universe", "spec")), 1),
                cost_bps_rt=float(need(p, "cost_bps_rt", "parameters")),
                dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
                max_open_trades=int(need(p, "max_open_trades", "parameters")),
                skip_regimes=frozenset(),                   # regime gate 由 spec 处理
                source=str(need(ds, "primary", "data_source")),
                family=fam,
                dry_run=bool(ex.get("dry_run", True)),
                raw=raw,
            )

        if fam == "survivors_only_lag1_book":
            # M-113 V3 (M-93 + R19-Lite) / M-115 Book B (M-93 + R14-Lite):
            # 2-sleeve book combining ① regime-gated BTC long + ④ cross-section L/S.
            # Per M-115: R14-Lite retention 0.614 PASSES M-114, R19-Lite 0.493
            # borderline FAIL — Book B is the clean honest baseline.
            sleeve_weights = need(p, "sleeve_weights", "parameters")
            sleeve_m93 = need(p, "sleeve_M93", "parameters")
            sleeve_xs = need(p, "sleeve_R14-Lite", "parameters") if "sleeve_R14-Lite" in p \
                else need(p, "sleeve_R19-Lite", "parameters")
            xs_rank_by = need(sleeve_xs, "rank_by", "parameters.sleeve_R*-Lite")
            xs_k_long = int(need(sleeve_xs, "K_long", "parameters.sleeve_R*-Lite"))
            xs_k_short = int(need(sleeve_xs, "K_short", "parameters.sleeve_R*-Lite"))
            xs_cadence = int(need(sleeve_xs, "cadence_days", "parameters.sleeve_R*-Lite"))
            xs_hold = int(need(sleeve_xs, "hold_days", "parameters.sleeve_R*-Lite"))
            xs_w = float(need(sleeve_xs, "weight_per_leg", "parameters.sleeve_R*-Lite"))
            # n_lookback: derive from rank_by "ret_Nd" → N
            n_lookback = 14
            if xs_rank_by.startswith("ret_") and xs_rank_by.endswith("d"):
                try:
                    n_lookback = int(xs_rank_by[4:-1])
                except ValueError:
                    pass
            # M-93 skip_regimes = cash_when_regime_in
            m93_skip = frozenset(str(r).upper() for r in
                                 sleeve_m93.get("cash_when_regime_in", []))
            return cls(
                name=need(raw, "spec_name", "spec"),
                universe=tuple(need(raw, "universe", "spec")),
                rank_by=xs_rank_by,            # sub-sleeve ranking source
                n_lookback=n_lookback,
                hold=xs_hold,
                cadence=xs_cadence,
                k=max(xs_k_long, xs_k_short),
                k_long=xs_k_long, k_short=xs_k_short,
                weight_per_leg=xs_w,
                cost_bps_rt=float(need(p, "cost_bps_rt_max", "parameters")),
                dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
                max_open_trades=int(need(p, "max_open_trades", "parameters")),
                skip_regimes=m93_skip,
                source=str(need(ds, "primary", "data_source")),
                family=fam,
                dry_run=bool(ex.get("dry_run", True)),
                raw=raw,
            )

        return cls(
            name=need(raw, "spec_name", "spec"),
            universe=tuple(need(raw, "universe", "spec")),
            rank_by=need(p, "rank_by", "parameters"),
            n_lookback=int(need(p, "n_lookback", "parameters")),
            hold=int(need(p, "hold", "parameters")),
            cadence=int(need(p, "cadence", "parameters")),
            k=int(need(p, "K", "parameters")),
            k_long=int(need(p, "K", "parameters")),
            k_short=int(need(p, "K", "parameters")),
            weight_per_leg=float(need(p, "weight_per_leg", "parameters")),
            cost_bps_rt=float(need(p, "cost_bps_rt", "parameters")),
            dd_stop_pct=float(need(p, "dd_stop_pct", "parameters")),
            max_open_trades=int(need(p, "max_open_trades", "parameters")),
            skip_regimes=frozenset(str(r).upper() for r in (p.get("skip_regimes") or [])),
            source=str(need(ds, "primary", "data_source")),
            family=fam,
            dry_run=bool(ex.get("dry_run", True)),   # 缺省必须是 dry_run,不是实盘
            raw=raw,
        )


# ── 面板 ──────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Panel:
    """`{symbol: {day: close}}` + 它的源与末端。值 + 可信域,和今天其余模块同一个模式。"""

    closes: Mapping[str, Mapping[str, float]]
    source: str
    last_bar: Optional[str]
    n_symbols: int

    def age_days(self, as_of: date) -> Optional[int]:
        if not self.last_bar:
            return None
        return (as_of - date.fromisoformat(self.last_bar)).days


def build_panel(rows: Sequence[Mapping[str, Any]], *, source: str) -> Panel:
    """从行构面板,并**断言单源** (S-230)。

    `assert_single_source` 会在混源时抛 `CrossSourceError` —— 不在这里 catch。
    一个在跨源面板上排出来的名次,是在拼接跳变上排的:三个源对同一个 BTC
    同一窗口给 +1.6% / +21.3% / +19.1%,谁排第一取决于哪个源赢了那一天。
    """
    from src.data.market.single_source import assert_single_source

    src = assert_single_source(rows, job=f"paper panel {source}", source_key="source")
    closes: dict[str, dict[str, float]] = {}
    for r in rows:
        c = r.get("close")
        d = str(r.get("trade_date") or "")[:10]
        if c is None or not d:
            continue
        closes.setdefault(str(r["symbol"]), {})[d] = float(c)
    last = max((d for s in closes.values() for d in s), default=None)
    return Panel(closes, src.source, last, len(closes))


def _return_over(closes: Mapping[str, float], upto: str, n: int) -> Optional[float]:
    """`upto` 当天回看 n 天的收益。**PIT:只用 <= upto 的 bar。**"""
    ds = sorted(d for d in closes if d <= upto)
    if len(ds) < n + 1:
        return None
    a, b = closes[ds[-(n + 1)]], closes[ds[-1]]
    return (b / a - 1.0) if a else None


# ── 决策 ──────────────────────────────────────────────────────────────────────

def decide_gated(spec: Spec, panel: Panel, *, as_of: date, regime: Optional[str],
                 n_open: int,
                 features: Optional[Mapping[str, "ExternalFeature"]] = None,
                 quorum: Optional["RegimeQuorum"] = None) -> Decision:
    """`decide()` 的 wrapper,加 regime_quorum 闸 (S-284 C fix, 2026-09-04)。

    ## 为什么 book 该被 quorum 卡住

    M-115 Book B 的 M-93 sleeve 按 regime 决定 BTC long / long / cash。一个
    「全票通过」的 regime 标签如果**票数本身已经塌了**(`verdict=COLLAPSED`),
    它通过 SKIPPED 看起来像「regime 在 TIGHTENING 不开仓」—— 而真相是
    「regime 这个标签今天不可信,不该用来定仓位」。S-263 把不可信的标签换
    `None` 是错的:它让「没有标签」和「标签不可信」共用一个表示,纸面账分不出
    「regime 被纪律地跳过」与「regime 标签死了」。

    `RegimeQuorum.usable` 是 `verdict in (OK, THIN)` —— `thin` 是「可用但须
    标注」,不放行会让「高源数低票数」的好日子被误杀。这条闸只挡 COLLAPSED /
    frozen / no_baseline / no_data。

    ## 调用约定

    `quorum=None` → 不加闸,直接调 `decide()`(向后兼容,旧 caller 不变)。
    `quorum` 传了但 `not quorum.usable` → 返回 SKIPPED,reason 写出 verdict
    与 quorum 自己写的 reason;consumer 可从 reason 反向定位。

    调用者如果想自己 fetch:
        from src.data.market.regime_quorum import classify, SELECT_COLS
        rows = supabase_fetch(daily_macro_regime, ...)
        quorum = classify(rows, today=as_of)
        decide_gated(spec, panel, ..., quorum=quorum)
    """
    if quorum is not None and not quorum.usable:
        d = as_of.isoformat()
        base = dict(d=d, spec_name=spec.name,
                    panel_source=panel.source, panel_last_bar=panel.last_bar,
                    regime=regime)
        return Decision(
            **base, verdict=Verdict.SKIPPED,
            reason=(f"regime quorum={quorum.verdict} — {quorum.reason}"
                    f" (S-263: 一个标签的可信度不只看它多新,还看它几票通过)"))
    return decide(spec, panel, as_of=as_of, regime=regime,
                  n_open=n_open, features=features)


def decide_gated_2d(spec: Spec, panel: Panel, *, as_of: date,
                    regime: Optional[str], n_open: int,
                    composite_z: Optional[float] = None,
                    composite_z_source: Optional["CompositeZSource"] = None,
                    features: Optional[Mapping[str, "ExternalFeature"]] = None,
                    quorum: Optional["RegimeQuorum"] = None) -> Decision:
    """`decide_gated()` 的 wrapper,加 M-128d Path γ 2D gate (CASH in RISK_OFF × weak breadth)。

    ## 为什么 gate 在 decide 之前

    M-128c/d 验证: RISK_OFF × NEUTRAL 是 SR -1.546 的失败 zone。
    如果走 `decide()` 拿到 ENTERED,再被 gate 截胡,记录里会写 "今天策略说要开仓"
    —— 而真相是「策略本不该开,gate 救了它」。这会让 gate 看起来像一个事后的
    风控补丁,而**它是一个先验的条件**(我们不需要一个会跳进 RISK_OFF × NEUTRAL
    的策略)。

    所以在 decide() 之前先 gate:CASH → 直接返回 SKIPPED,gate 的 reason
    写进 Decision.reason(consumer 看得到「策略说 HOLD 但 gate 让它 CASH」 vs
    「regime 说跳过」 vs 「面板 BLOCKED」)。

    ## 调用约定

    - `composite_z` 显式传入 → 用它
    - `composite_z_source` 传入 → 用它查 (as_of - LAG_DAYS)
    - 都没传 → gate 走保守 CASH (unknown composite_z in RISK_OFF)

    `quorum=None` → 不加 quorum 闸(向后兼容)。
    """
    import sys as _gate_sys
    # Lazy import: gate module lives in Minimax-C lane (cometcloud-local).
    # Vendored copy at paper_trading/_vendor/m128d_2d_gate.py for Railway;
    # if not vendored, try the local Minimax-C path; if neither, no-gate.
    gate = None
    for _try in (
        "paper_trading._vendor.m128d_2d_gate",
        "m128d_2d_gate",
    ):
        try:
            _gate_sys.path.insert(0, "/Volumes/CometCloudAI/cometcloud-local")
            _mod = __import__(_try, fromlist=["Gate2D"])
            gate = _mod.Gate2D()
            break
        except ImportError:
            continue

    if gate is not None:
        # Resolve composite_z: explicit > source > unknown
        cz = composite_z
        if cz is None and composite_z_source is not None:
            cz = composite_z_source.get(as_of)
        d = as_of.isoformat()
        gd = gate.evaluate(as_of=as_of, regime=regime, composite_z=cz)
        if gd.action == "CASH":
            base = dict(d=d, spec_name=spec.name, panel_source=panel.source,
                        panel_last_bar=panel.last_bar, regime=gd.regime)
            return Decision(
                **base, verdict=Verdict.SKIPPED,
                reason=(f"M-128d 2D gate CASH — {gd.reason} "
                        f"(Path γ ship-ready, threshold=±{gate.threshold})"))
    # Gate HOLD or no-gate-available → defer to existing decide_gated
    return decide_gated(spec, panel, as_of=as_of, regime=regime,
                        n_open=n_open, features=features, quorum=quorum)


def decide(spec: Spec, panel: Panel, *, as_of: date, regime: Optional[str],
           n_open: int,
           features: Optional[Mapping[str, "ExternalFeature"]] = None,
           last_rebalance: Optional["date"] = None) -> Decision:
    """一天的判定。**不写任何东西** —— 纯函数,便于重放与测试。

    顺序有意为之:**先判我们能不能算(BLOCKED),再判规则说什么(SKIPPED)。**
    反过来的话,一个价源死掉的日子会被记成"regime 跳过",
    而那会让停摆看起来像纪律。

    `last_rebalance` (Optional[date]): 上一次再平衡的日期。A-17 形态 A
    panel_long_only 用它来判「今天该不该 rebalance」。None = 第一次运行,
    视为「需要 rebalance」。其他 family 忽略这个参数。
    """
    # Multi-sleeve book (M-113 V3 / M-115 Book B) routes to its own decide().
    # 2-sleeve book needs different BLOCKED checks (BTC presence for M-93 sleeve)
    # and different leg composition (regime-gated long + cross-section L/S).
    if spec.family == "survivors_only_lag1_book":
        return decide_survivors_book(spec, panel, as_of=as_of, regime=regime,
                                      n_open=n_open, features=features)
    # M-152 Path π BTT-LEX: standalone ① — BTC trend × regime ladder.
    if spec.family == "btc_trend_regime_ladder":
        return decide_btc_trend(spec, panel, as_of=as_of, regime=regime,
                                  n_open=n_open)
    # A-17 形态 A: §5b ① panel-wide long-only hold.
    if spec.family == "panel_long_only":
        return decide_panel_long_only(spec, panel, as_of=as_of, regime=regime,
                                      n_open=n_open, last_rebalance=last_rebalance)
    # S-393 arm C: A-17 + per-symbol factor AND-gate.
    if spec.family == "panel_long_only_simple_factor":
        return decide_panel_long_only_simple_factor(
            spec, panel, as_of=as_of, regime=regime,
            n_open=n_open, last_rebalance=last_rebalance,
        )
    d = as_of.isoformat()
    base = dict(d=d, spec_name=spec.name, panel_source=panel.source,
                panel_last_bar=panel.last_bar)

    # ① 面板本身能不能用 ─────────────────────────────────────────────────────
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"这不等于'今天没有机会' (S-180)")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天。用旧价开的仓会产生一条"
                               f"看起来正常、而不可分辨的污染记录 (S-251:"
                               f"binance_hist 自 08-09 起每天只写 1 个标的)")
    missing = [s for s in spec.universe if s not in panel.closes]
    if missing:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 里 {len(missing)}/{len(spec.universe)} 个标的"
                               f"不在面板里:{missing} —— 在残缺宇宙上排名不是这个 spec")

    # ② 规则说什么 ───────────────────────────────────────────────────────────
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon
    if canon and canon in spec.skip_regimes:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"regime {canon} 在 skip_regimes 里 —— 规则在工作")
    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades}")

    # ③ 外部特征:spec 引用了本模块不计算的维,必须带出处喂进来 ─────────────
    feats = dict(features or {})
    for fname in spec.external_features:
        f = feats.get(fname)
        if f is None:
            return Decision(**base, verdict=Verdict.BLOCKED,
                            reason=f"打分公式引用了外部特征 '{fname}',而它没有被提供。"
                                   f"公式:{spec.rank_by}。"
                                   f"自己造一个同名的维会让 OOS 声明悄悄不再适用于"
                                   f"正在跑的东西 —— 实测该维与 60 日收益【排序相反】。"
                                   f"要跑这个 spec,必须由 Mac 侧 VDB 提供并声明出处。")
        missing_f = [s for s in spec.universe if s not in f.values]
        if missing_f:
            return Decision(**base, verdict=Verdict.BLOCKED,
                            reason=f"外部特征 '{fname}'(出处:{f.provenance})缺 "
                                   f"{len(missing_f)}/{len(spec.universe)} 个标的:"
                                   f"{missing_f} —— 在残缺特征上排名不是这个 spec")

    rets = {s: _return_over(panel.closes[s], d, spec.n_lookback) for s in spec.universe}
    usable = {s: v for s, v in rets.items() if v is not None}
    if len(usable) < MIN_UNIVERSE_FOR_RANK:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"只有 {len(usable)}/{len(spec.universe)} 个标的算得出 "
                               f"{spec.n_lookback}d 收益(需要 >= {MIN_UNIVERSE_FOR_RANK})"
                               f" —— 算不出名次不等于名次是平的")

    # 打分。cross_sectional 家族就是 ret_n 本身;cluster_tilt 加外部特征的 tilt;
    # survivors_only_lag1_book 在此分支之前已经返回 (见下)。
    if spec.family == "cluster_tilt_cross_sectional_ls" and spec.external_features:
        fname = spec.external_features[0]
        fv = feats[fname].values
        score = {s: usable[s] + spec.tilt_weight * float(fv[s]) for s in usable}
    else:
        score = dict(usable)

    ranked = sorted(score, key=lambda s: score[s], reverse=True)
    longs, shorts = ranked[: spec.k_long], ranked[-spec.k_short:]
    if set(longs) & set(shorts):
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"K={spec.k} 在 {len(ranked)} 个标的上让多空腿重叠")

    def px(s: str) -> float:
        return panel.closes[s][max(x for x in panel.closes[s] if x <= d)]

    legs = tuple(
        [Leg(s, "long", spec.weight_per_leg, px(s)) for s in longs]
        + [Leg(s, "short", spec.weight_per_leg, px(s)) for s in shorts])
    return Decision(**base, verdict=Verdict.ENTERED, legs=legs)


# ── Multi-sleeve book (M-113 V3 / M-115 Book B) ─────────────────────────────
# 2-sleeve book combining:
#   ① regime-gated BTC long (M-93): long when regime ∉ skip_regimes; cash otherwise
#   ④ cross-section L/S (R19-Lite or R14-Lite): K_long long + K_short short on
#     rank_by (= ret_Nd momentum), weekly cadence, hold = hold_days
# Legs are combined in a single Decision with the cross-section weight_per_leg
# for the L/S sleeve and an explicit M-93 BTC long leg when regime permits.
# Spec-level dd_stop / max_open_trades apply at the book.

def decide_survivors_book(spec: Spec, panel: Panel, *, as_of: date,
                          regime: Optional[str], n_open: int,
                          features: Optional[Mapping[str, "ExternalFeature"]] = None
                          ) -> Decision:
    """Multi-sleeve book: ① regime-gated BTC long + ④ cross-section L/S.

    Mirrors the upstream BLOCKED / SKIPPED checks from `decide()` to honor the
    spec_runner discipline (no same-bar look-ahead, panel freshness, etc.).

    Returns Decision with combined legs from both sleeves when ENTERED.
    """
    d = as_of.isoformat()
    base = dict(d=d, spec_name=spec.name, panel_source=panel.source,
                panel_last_bar=panel.last_bar)

    # BLOCKED checks (same shape as decide())
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"这不等于'今天没有机会' (S-180)")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天。用旧价开的仓会产生一条"
                               f"看起来正常、而不可分辨的污染记录 (S-251)")
    if "BTC" not in panel.closes:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"M-93 sleeve 需要 BTC —— 不在面板里。"
                               f"book 不能在残缺宇宙上开仓")

    # ② 规则说
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon

    def px(s: str) -> float:
        return panel.closes[s][max(x for x in panel.closes[s] if x <= d)]

    # ① M-93 sleeve: regime-gated BTC long (50% book weight)
    m93_in_pos = canon is None or canon not in spec.skip_regimes
    m93_legs: list[Leg] = []
    if m93_in_pos:
        m93_legs = [Leg("BTC", "long", 0.5, px("BTC"))]

    # ④ R*-Lite sleeve: cross-section 14d (or N-day) momentum, K_long/K_short
    if len(spec.universe) < max(MIN_UNIVERSE_FOR_RANK, spec.k_long + spec.k_short):
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"universe={len(spec.universe)} 不足以排 "
                               f"{spec.k_long}+{spec.k_short} 条腿")
    rets_xs = {s: _return_over(panel.closes[s], d, spec.n_lookback)
               for s in spec.universe}
    usable_xs = {s: v for s, v in rets_xs.items() if v is not None}
    if len(usable_xs) < MIN_UNIVERSE_FOR_RANK:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"只有 {len(usable_xs)}/{len(spec.universe)} 个标的"
                               f"算得出 {spec.n_lookback}d 收益 —— 不开仓")
    ranked = sorted(usable_xs, key=lambda s: usable_xs[s], reverse=True)
    xs_longs = ranked[: spec.k_long]
    xs_shorts = ranked[-spec.k_short:] if spec.k_short > 0 else []
    if set(xs_longs) & set(xs_shorts):
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"K={spec.k} 在 {len(ranked)} 个标的上让多空腿重叠")
    xs_legs = ([Leg(s, "long", spec.weight_per_leg, px(s)) for s in xs_longs]
               + [Leg(s, "short", spec.weight_per_leg, px(s)) for s in xs_shorts])

    # Book-level DD-stop / max_open_trades check
    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades}")

    legs = tuple(m93_legs + xs_legs)
    if not legs:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"regime {canon} 让 M-93 sleeve 在 cash,"
                               f"且 R*-Lite sleeve 也无腿 —— book 当天空仓")
    return Decision(**base, verdict=Verdict.ENTERED, legs=legs)


# ── BTT-LEX (M-152 Path π) — ① standalone BTC trend × regime ladder ─────────
# §5b 把 ① 写成 "long-only panel hold — FoF core"。Panel-wide 实现要等更长
# 的 panel rebuild,但 BTC-as-the-bellwether 的 standalone 形态 (M-152) 已经
# SHIP-READY: SR +1.115 / cum +178.0% / MaxDD -20.44% / 2025 vs BTC -8.42pp。
# 这条 spec 把 BTT-LEX 接进 runner,后续 CDCB-A v2 book (50% BTT-LEX +
# 50% CCCL) 可以直接引用。
#
# Signal (lag-1, S-114 / S-122):
#   ma{N} = mean of last N bars <= d-1
#   mom{N} = N-day return up to d-1
#   trend_on = (close_{d-1} > ma{N}) AND (mom{N} > 0)
#
# Weight from regime ladder:
#   multipliers = {REGIME: weight} (默认 M-152 5 档: 1.30/1.15/1.00/0.80/0.00)
#   canon = canonical_regime_strict(regime); 未知 / None → 退回 NEUTRAL
#   mult <= 0 → SKIPPED "regime ladder says zero"
#   mult > 0  → ENTERED 单条 BTC long 腿,weight = mult
#   mult > 1.0 是 leverage,不是 raw long —— spec.weight_per_leg 在这条 family
#   里被忽略,实际权重由 ladder 决定。
#
# BLOCKED vs SKIPPED:
#   BLOCKED: panel empty, BTC 缺失, panel 太旧, BTC 历史 < ma_lookback + 1
#   SKIPPED: max_open_trades hit, trend OFF, regime ladder = 0

def decide_btc_trend(spec: Spec, panel: Panel, *, as_of: date,
                     regime: Optional[str], n_open: int) -> Decision:
    from datetime import timedelta as _td

    raw_params = (spec.raw.get("parameters") or {})
    ma_lookback = int(raw_params.get("ma_lookback", 200))
    mom_lookback = int(raw_params.get("mom_lookback", 60))
    raw_mults = raw_params.get("regime_multipliers") or {}
    multipliers = {str(k).upper(): float(v)
                   for k, v in raw_mults.items() if v is not None}
    if not multipliers:
        # M-152 默认 ladder。缺省时给一条 ship-ready 的兜底,而不是 spec 错。
        multipliers = {"EASING": 1.30, "TIGHTENING": 1.15, "NEUTRAL": 1.00,
                       "STAGFLATION": 0.80, "RISK_OFF": 0.00, "RISK_ON": 1.15}

    d = as_of.isoformat()
    d_lag1 = (as_of - _td(days=1)).isoformat()
    base = dict(d=d, spec_name=spec.name,
                panel_source=panel.source, panel_last_bar=panel.last_bar)

    # ① BLOCKED checks (mirror decide() 的 shape)
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"BTT-LEX 不能在空面板上判定 trend。")
    if "BTC" not in panel.closes:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="BTC 不在面板里 —— BTT-LEX 必须有 BTC 才能算 trend。")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天 —— BTT-LEX 用旧价会污染 trend 判定")
    btc_closes = panel.closes["BTC"]
    if len(btc_closes) < ma_lookback + 1:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"BTC 只有 {len(btc_closes)} 天历史,BTT-LEX 需要 "
                               f"至少 {ma_lookback + 1} 天算 MA{ma_lookback}")

    # ② regime canonical (skip_regimes 由 ladder 处理,不在 family 层 skip)
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon

    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades} —— 不重复开 BTT-LEX")

    # ③ Trend (lag-1: signal uses bars <= d-1; entry price = bar at d)
    bars_signal = sorted(x for x in btc_closes if x <= d_lag1)
    if len(bars_signal) < ma_lookback:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"BTC 在 {d_lag1} 及之前只有 {len(bars_signal)} 根 bar,"
                               f"算不出 MA{ma_lookback}")
    ma_n = sum(btc_closes[b] for b in bars_signal[-ma_lookback:]) / ma_lookback
    close_signal = btc_closes[bars_signal[-1]]
    mom = _return_over(btc_closes, d_lag1, mom_lookback)
    if mom is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"BTC 在 {d_lag1} 及之前算不出 {mom_lookback}d 动量")

    trend_on = (close_signal > ma_n) and (mom > 0)
    if not trend_on:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"BTC trend OFF — close_{d_lag1}={close_signal:.4f} ≤ "
                               f"MA{ma_lookback}={ma_n:.4f} 或 "
                               f"mom{mom_lookback}={mom:+.4%} ≤ 0")

    # ④ Multiplier from regime ladder
    mult = multipliers.get(canon, multipliers.get("NEUTRAL", 1.0))
    if mult <= 0:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"BTC trend ON,但 regime {canon} ladder = {mult} "
                               f"—— 不开仓")

    # Entry price = bar at d (今天的 mark price)
    bars_today = sorted(x for x in btc_closes if x <= d)
    if not bars_today:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"BTC 在 {d} 当天没有 bar —— 无法定价入场")
    px_entry = btc_closes[bars_today[-1]]

    legs = (Leg("BTC", "long", float(mult), float(px_entry)),)
    return Decision(**base, verdict=Verdict.ENTERED, legs=legs)


# ── panel_long_only (A-17 形态 A) — §5b ① panel-wide long-only hold ─────────
# §5b 把 ① 写成「long-only hold of the panel — the FoF core;the benchmark
# every sleeve is measured against is 'hold the panel', NEVER 0」。
# 这是 panel-wide 形态,M-152 BTT-LEX 是单 BTC 形态 —— 两者合起来才是
# 完整的 ① doctrine。
#
# Signal 与 trade logic:
#   target_symbols = universe(或 top N by allocation rank)
#   weights        = equal / cis / mcap,normalised,cap 在 max_position_pct
#   rebalance day  = (last_rebalance is None) OR
#                    (as_of - last_rebalance).days >= rebalance_cadence
#   BLOCKED:       panel empty,panel too old,universe < MIN,symbols missing,
#                    symbol 历史不够 min_history_days
#   SKIPPED:       regime gated off,dd_stop hit,not rebalance day,
#                    n_open >= max_open_trades
#   ENTERED:       N legs,all long,weight = target,price = bar at d
#
# lag-1 PIT discipline (S-114 / S-122):
#   signal/target size 决定在 bars <= d-1 上做
#   entry price         = bar at d(今天的 mark price)
#
# 整条 spec 的全部目的就是「把整个 universe 按既定权重持有」 —— 没有 alpha,
# 没有横截面,没有 lever,只有再平衡。回报应该长得像 buy-and-hold,
# excess ≤ cost bps。**任何超过 cost bps 的 excess 都值得审查 —— 那意味着
# spec 偷偷装了一个 §5b 不允许的机制。**
def decide_panel_long_only(spec: Spec, panel: Panel, *, as_of: date,
                           regime: Optional[str], n_open: int,
                           last_rebalance: Optional[date],
                           jev_regime: Optional["JevRegimeDecision"] = None) -> Decision:
    """§5b ① 形态 A:panel-wide long-only hold。

    `jev_regime` (optional, Pattern A pre-filter per
    `docs/jev_nautilus_integration_plan_2026-09-21.md`): if provided and
    `regime_ok=False`, return SKIPPED with the Jev reason before ANY other
    check. This is gate **⓪** (downside protection), separate from the
    spec's own regime_gate (gate ③). Both gates honor the same regime-blinded
    benchmark for §5b ①, but ⓪ fires on Jev's structural "is this regime
    tradeable" call while ③ fires on the spec's regime mapping.
    """
    from datetime import timedelta as _td

    raw_params = (spec.raw.get("parameters") or {})
    allocation = str(raw_params.get("allocation", "equal_weight")).lower()
    rebalance_cadence = int(raw_params.get("rebalance_cadence", 7))
    max_pos = float(raw_params.get("max_position_pct", 1.0))
    min_pos = float(raw_params.get("min_position_pct", 0.0))
    regime_gate = raw_params.get("regime_gate") or {}
    min_history_days = int(raw_params.get("min_history_days", 365))

    d = as_of.isoformat()
    d_lag1 = (as_of - _td(days=1)).isoformat()
    base = dict(d=d, spec_name=spec.name,
                panel_source=panel.source, panel_last_bar=panel.last_bar)

    # ⓪ Jev gate (Pattern A — optional). Fires BEFORE any other check:
    # if Jev says the regime is not tradeable, the strategy skips this bar
    # regardless of panel freshness, regime mapping, or rebalance cadence.
    # `None` (default) = Jev not wired → behavior unchanged (backward compat).
    if jev_regime is not None and not jev_regime.regime_ok:
        return Decision(
            **base, verdict=Verdict.SKIPPED,
            reason=(f"jev_gate closed at {d} (Pattern A pre-filter): "
                    f"direction_bias={jev_regime.direction_bias}, "
                    f"confidence={jev_regime.confidence}, "
                    f"backend={jev_regime.backend_name}, "
                    f"mock={jev_regime.mock}, "
                    f"latency={jev_regime.jev_latency_ms}ms, "
                    f"tokens={jev_regime.jev_input_tokens} — "
                    f"§5b ⓪ OVERRIDE 命中,① 形态 A 不开仓 (per "
                    f"docs/jev_nautilus_integration_plan_2026-09-21.md)"),
        )

    # ① BLOCKED: panel 必须能用
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"这不等于'今天没有机会' (S-180)")
    if len(spec.universe) < MIN_UNIVERSE_FOR_RANK:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 只有 {len(spec.universe)} 个标的,"
                               f"< MIN_UNIVERSE_FOR_RANK={MIN_UNIVERSE_FOR_RANK} "
                               f"—— 没有横截面信息可言 (spec_runner MIN)")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天 —— 用旧价 rebalance "
                               f"会污染 §5b ① 基准")

    # ② universe 必须在面板里;每个 symbol 历史都要够 min_history_days
    missing = [s for s in spec.universe if s not in panel.closes]
    if missing:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 中有 {len(missing)} 个不在面板里:"
                               f"{missing[:5]}{'...' if len(missing) > 5 else ''} "
                               f"—— ① 必须持完整 universe,缺一个就不是 'hold the panel'")
    too_short = []
    threshold_date = (as_of - _td(days=min_history_days)).isoformat()
    for s in spec.universe:
        s_closes = panel.closes[s]
        if not s_closes:
            too_short.append((s, 0))
            continue
        # First bar <= as_of
        sorted_dates = sorted(d_ for d_ in s_closes if d_ <= d_lag1)
        if not sorted_dates or sorted_dates[0] > threshold_date:
            too_short.append((s, len(sorted_dates)))
    if too_short:
        sym_list = ", ".join(f"{s} ({n}d)" for s, n in too_short[:5])
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"{len(too_short)}/{len(spec.universe)} 个 universe "
                               f"symbol 历史不足 {min_history_days}d:{sym_list}"
                               f"{'...' if len(too_short) > 5 else ''} "
                               f"—— ① 形态 A 候选至少需要 {min_history_days}d")

    # ③ Regime gate (per spec.parameters.regime_gate)
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon
    if regime_gate:
        if canon in regime_gate:
            allow = bool(regime_gate[canon])
            if not allow:
                return Decision(**base, verdict=Verdict.SKIPPED,
                                reason=f"regime_gate 把 {canon} 关掉了 "
                                       f"(parameters.regime_gate.{canon}=False) "
                                       f"—— ① 形态 A 在该 regime 不持仓")
        elif "default" in regime_gate:
            allow = bool(regime_gate["default"])
            if not allow:
                return Decision(**base, verdict=Verdict.SKIPPED,
                                reason=f"regime_gate.default=False,{canon} "
                                       f"未在 gate 里显式列出 —— 默认不放")

    # ④ n_open 容量
    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades}")

    # ⑤ Rebalance day 检查 —— ① 的纪律就是「cadence 到了才动」
    if last_rebalance is not None:
        elapsed = (as_of - last_rebalance).days
        if elapsed < rebalance_cadence:
            return Decision(**base, verdict=Verdict.SKIPPED,
                            reason=f"上次再平衡 {last_rebalance.isoformat()},"
                                   f"已 {elapsed}d < cadence {rebalance_cadence}d "
                                   f"—— ① 形态 A 不在 cadence 上不动仓")

    # ⑥ Compute target weights (v1 only: equal_weight;cis / mcap 在下档 ship)
    n = len(spec.universe)
    if allocation != "equal_weight":
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"v1 ship 只接 allocation='equal_weight'; "
                               f"'{allocation}' 在下一档 "
                               f"(PANEL_LONG_ONLY_SPEC §'Allocation helpers')")
    raw_w = {sym: 1.0 / n for sym in spec.universe}
    # HARD cap + floor —— **不 renormalize**。如果用户把 max_position_pct 设到
    # 比 1/N 还小,他们就是在明确说「我接受 cash drag」,而不是「请把多余的
    # 钱按比例塞回每个仓位」。Renormalize 会把 cap 偷偷抹平,变成「我说要
    # cap 但其实没 cap」 —— 那种撒谎 ① 基准不能有。
    capped = {sym: min(max_pos, max(min_pos, w)) for sym, w in raw_w.items()}
    s_w = sum(capped.values())
    if s_w <= 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"权重重整后总和 {s_w} ≤ 0 —— max/min_position_pct "
                               f"配置让所有权重被剪没了 (max={max_pos}, min={min_pos})")
    if s_w > 1.0 + 1e-9:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"权重重整后总和 {s_w:.4f} > 1.0 —— "
                               f"min_position_pct 把总和推过了 1,会出现隐式杠杆;"
                               f"max={max_pos}, min={min_pos}, N={n}")
    weights = capped

    # ⑦ Entry price = bar at d (今天的 mark price);lag-1 已用于历史深度检查
    legs_list = []
    for sym in spec.universe:
        sym_closes = panel.closes[sym]
        bars_today = sorted(x for x in sym_closes if x <= d)
        if not bars_today:
            return Decision(**base, verdict=Verdict.BLOCKED,
                            reason=f"{sym} 在 {d} 当天没有 bar —— 无法定价入场")
        px_entry = sym_closes[bars_today[-1]]
        legs_list.append(Leg(sym, "long", float(weights[sym]), float(px_entry)))
    legs = tuple(legs_list)

    return Decision(**base, verdict=Verdict.ENTERED, legs=legs,
                    reason=f"rebalance {d},n_legs={len(legs)},allocation={allocation}")


# ── panel_long_only_simple_factor (S-393 arm C) ─────────────────────────────
# A-17 形态 A 的扩展:在 step ⑦ 用 per-symbol factor AND-gate 过滤 universe,
# 只 long 通过的子集。这是 JAZZ 2026-09-21 3-arm 对比的 arm C —— 跟 arm B
# (panel_long_only) 共用 universe + cadence + BLOCKED 纪律,只在 leg
# 构造阶段不同。
#
# **设计纪律(S-393):**
# - 0/0 跟 1/0 一样 → SKIPPED with reason。不是 bug,是设计:factor gate 在
#   全 universe 都不达标的窗口(如 RISK_OFF + 高波)就该空仓,这是 factor model
#   的"看空"信号,不是错误。
# - 通过的子集上 1/N 等权 —— 不是 1/原 universe。差异正是 factor gate 的
#   "value added"。报告里要分开报:(a) absolute 1/N passing,(b) 与 arm B
#   等权的 SR / MaxDD 差异。
# - 跟 arm B 同样 lag-1 PIT:factor 信号 ≤ d_lag1,entry price = bar at d。
# - 不接 Jev gate(arm C 是"纯 factor model",Jev 是另一维 —— 已在 arm A
#   测过 wire 路径,arm C 不重复)。

def decide_panel_long_only_simple_factor(spec: Spec, panel: Panel, *,
                                          as_of: date, regime: Optional[str],
                                          n_open: int,
                                          last_rebalance: Optional[date],
                                          jev_regime: Optional["JevRegimeDecision"] = None,
                                          ) -> Decision:
    """S-393 arm C: §5b ① panel_long_only + per-symbol factor AND-gate.

    Mirrors `decide_panel_long_only` step ⓪-⑥ exactly. Step ⑦ replaces the
    unconditional leg construction with a factor-filtered construction.

    `jev_regime` accepted for symmetry with `decide_panel_long_only` but the
    arm-C spec does NOT wire Jev (per S-393 — comparison isolates factor gate).
    """
    from datetime import timedelta as _td
    from paper_trading.factors import compute_factor_signals

    raw_params = (spec.raw.get("parameters") or {})
    allocation = str(raw_params.get("allocation", "equal_weight")).lower()
    rebalance_cadence = int(raw_params.get("rebalance_cadence", 7))
    max_pos = float(raw_params.get("max_position_pct", 1.0))
    min_pos = float(raw_params.get("min_position_pct", 0.0))
    regime_gate = raw_params.get("regime_gate") or {}
    min_history_days = int(raw_params.get("min_history_days", 90))

    # factor_filter was validated in Spec.load (min_history_days ≥ floor
    # for the windows). Read here without re-validation — load() is the gate.
    ff = raw_params.get("factor_filter") or {}
    sma_window = int(ff.get("sma_window", 60))
    mom_window = int(ff.get("mom_window", 60))
    vol_window = int(ff.get("vol_window", 30))
    vol_threshold = float(ff.get("vol_threshold_daily_stdev", 0.05))
    sma_ok_rule = str(ff.get("sma_ok_rule", "above"))

    d = as_of.isoformat()
    d_lag1 = (as_of - _td(days=1)).isoformat()
    base = dict(d=d, spec_name=spec.name,
                panel_source=panel.source, panel_last_bar=panel.last_bar)

    # ⓪ Jev gate (accepted but not used by arm C — see docstring)
    if jev_regime is not None and not jev_regime.regime_ok:
        return Decision(
            **base, verdict=Verdict.SKIPPED,
            reason=(f"jev_gate closed at {d} (Pattern A pre-filter): "
                    f"direction_bias={jev_regime.direction_bias}, "
                    f"confidence={jev_regime.confidence}, "
                    f"backend={jev_regime.backend_name}, "
                    f"mock={jev_regime.mock}, "
                    f"latency={jev_regime.jev_latency_ms}ms, "
                    f"tokens={jev_regime.jev_input_tokens} — "
                    f"§5b ⓪ OVERRIDE 命中 (S-393 arm C 兼容但 spec 不 wire Jev)"),
        )

    # ① BLOCKED checks (mirror decide_panel_long_only:1047-1066)
    if panel.n_symbols == 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板 0 个标的 —— 源 {spec.source} 没有返回任何行。"
                               f"factor gate 在空面板上算不了 (S-180)")
    if len(spec.universe) < MIN_UNIVERSE_FOR_RANK:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 只有 {len(spec.universe)} 个标的,"
                               f"< MIN_UNIVERSE_FOR_RANK={MIN_UNIVERSE_FOR_RANK} "
                               f"—— factor gate 至少需要 {MIN_UNIVERSE_FOR_RANK} 个标的"
                               f"才能跟 arm B 比较 (spec_runner MIN)")
    age = panel.age_days(as_of)
    if age is None:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason="面板没有可读的最后一根 bar")
    if age > MAX_PANEL_AGE_DAYS:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"面板最后一根 bar 是 {panel.last_bar},已 {age} 天 "
                               f"> {MAX_PANEL_AGE_DAYS} 天 —— factor 信号基于旧价会"
                               f"产生一条看起来正常的污染记录 (S-251)")

    # ② universe 在面板里 + 每个 symbol 历史够 min_history_days
    missing = [s for s in spec.universe if s not in panel.closes]
    if missing:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"universe 中有 {len(missing)} 个不在面板里:"
                               f"{missing[:5]}{'...' if len(missing) > 5 else ''} "
                               f"—— arm C 必须持完整 universe 才能跟 arm B 比较")
    too_short = []
    threshold_date = (as_of - _td(days=min_history_days)).isoformat()
    for s in spec.universe:
        s_closes = panel.closes[s]
        if not s_closes:
            too_short.append((s, 0))
            continue
        sorted_dates = sorted(d_ for d_ in s_closes if d_ <= d_lag1)
        if not sorted_dates or sorted_dates[0] > threshold_date:
            too_short.append((s, len(sorted_dates)))
    if too_short:
        sym_list = ", ".join(f"{s} ({n}d)" for s, n in too_short[:5])
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"{len(too_short)}/{len(spec.universe)} 个 universe "
                               f"symbol 历史不足 {min_history_days}d:{sym_list}"
                               f"{'...' if len(too_short) > 5 else ''} "
                               f"—— arm C factor gate 至少需要 {min_history_days}d")
    # 又多一道:每个 symbol 必须能算 factor (depth ≥ max(sma, mom+1, vol+1))
    factor_floor = max(sma_window, mom_window + 1, vol_window + 1)
    factor_too_short = []
    for s in spec.universe:
        s_closes = panel.closes[s]
        depth_d_lag1 = sum(1 for d_ in s_closes if d_ <= d_lag1)
        if depth_d_lag1 < factor_floor:
            factor_too_short.append((s, depth_d_lag1))
    if factor_too_short:
        sym_list = ", ".join(f"{s} ({n}d)" for s, n in factor_too_short[:5])
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"{len(factor_too_short)}/{len(spec.universe)} 个 universe "
                               f"symbol 历史不足以算 factor (need ≥ {factor_floor}d):"
                               f"{sym_list} —— arm C factor gate 算不出该符号,"
                               f"应排除而不是跳过整面板")

    # ③ Regime gate (per spec.parameters.regime_gate)
    canon = None
    if regime is not None:
        from src.data.cis.cis_provider import canonical_regime_strict
        canon = canonical_regime_strict(regime)
    base["regime"] = canon
    if regime_gate:
        if canon in regime_gate:
            allow = bool(regime_gate[canon])
            if not allow:
                return Decision(**base, verdict=Verdict.SKIPPED,
                                reason=f"regime_gate 把 {canon} 关掉了 "
                                       f"(parameters.regime_gate.{canon}=False)")
        elif "default" in regime_gate:
            allow = bool(regime_gate["default"])
            if not allow:
                return Decision(**base, verdict=Verdict.SKIPPED,
                                reason=f"regime_gate.default=False,{canon} "
                                       f"未在 gate 里显式列出 —— 默认不放")

    # ④ n_open 容量
    if n_open >= spec.max_open_trades:
        return Decision(**base, verdict=Verdict.SKIPPED,
                        reason=f"已有 {n_open} 笔未平仓 >= max_open_trades "
                               f"{spec.max_open_trades}")

    # ⑤ Cadence — 跟 arm B 同 cadence 纪律
    if last_rebalance is not None:
        elapsed = (as_of - last_rebalance).days
        if elapsed < rebalance_cadence:
            return Decision(**base, verdict=Verdict.SKIPPED,
                            reason=f"上次再平衡 {last_rebalance.isoformat()},"
                                   f"已 {elapsed}d < cadence {rebalance_cadence}d "
                                   f"—— arm C 跟 arm B 同 cadence")

    # ⑥ Allocation weight (v1 only: equal_weight)
    if allocation != "equal_weight":
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"v1 ship 只接 allocation='equal_weight'; "
                               f"'{allocation}' 在下一档 (PANEL_LONG_ONLY_SPEC "
                               f"§'Allocation helpers')")
    n_total = len(spec.universe)

    # ⑦ Per-symbol factor gate — 跟 arm B 的差别就在这一步
    signals: dict[str, dict[str, bool]] = {}
    for s in spec.universe:
        signals[s] = compute_factor_signals(
            panel.closes[s], as_of=as_of,
            sma_window=sma_window, mom_window=mom_window,
            vol_window=vol_window, vol_threshold=vol_threshold,
            sma_ok_rule=sma_ok_rule,
        )
    passing = [s for s in spec.universe if signals[s]["all_ok"]]
    if not passing:
        # 0/N passed → factor model says "no edge today" → SKIPPED
        n_sma = sum(1 for s in spec.universe if signals[s]["sma_ok"])
        n_mom = sum(1 for s in spec.universe if signals[s]["mom_ok"])
        n_vol = sum(1 for s in spec.universe if signals[s]["vol_ok"])
        return Decision(
            **base, verdict=Verdict.SKIPPED,
            reason=(f"0/{n_total} 通过 factor gate "
                    f"(sma={n_sma}/{n_total}, mom={n_mom}/{n_total}, "
                    f"vol={n_vol}/{n_total}) —— factor model 当天空仓 "
                    f"(S-393 arm C design)")
        )

    # Equal-weight over PASSING subset — 1/|passing|, NOT 1/n_total.
    # 这是 arm B vs arm C 的关键差异:arm B 永远 1/5 = 0.20,arm C 在 1/2 .. 1/5
    # 之间跳(取决于当日通过数)。
    n_pass = len(passing)
    raw_w = {sym: 1.0 / n_pass for sym in passing}
    capped = {sym: min(max_pos, max(min_pos, w)) for sym, w in raw_w.items()}
    s_w = sum(capped.values())
    if s_w <= 0:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"权重重整后总和 {s_w} ≤ 0 —— max/min_position_pct 配置"
                               f"让所有权重被剪没了 (max={max_pos}, min={min_pos})")
    if s_w > 1.0 + 1e-9:
        return Decision(**base, verdict=Verdict.BLOCKED,
                        reason=f"权重重整后总和 {s_w:.4f} > 1.0 —— min_position_pct "
                               f"把总和推过了 1 (max={max_pos}, min={min_pos}, "
                               f"n_pass={n_pass})")
    weights = capped

    # Entry price = bar at d (lag-1 已用于 factor 信号)
    legs_list = []
    for sym in passing:
        sym_closes = panel.closes[sym]
        bars_today = sorted(x for x in sym_closes if x <= d)
        if not bars_today:
            return Decision(**base, verdict=Verdict.BLOCKED,
                            reason=f"{sym} 在 {d} 当天没有 bar —— 无法定价入场")
        px_entry = sym_closes[bars_today[-1]]
        legs_list.append(Leg(sym, "long", float(weights[sym]), float(px_entry)))
    legs = tuple(legs_list)

    return Decision(
        **base, verdict=Verdict.ENTERED, legs=legs,
        reason=(f"rebalance {d}, n_legs={len(legs)}/{n_total} passed factor gate "
                f"(sma={sma_window}, mom={mom_window}, vol={vol_window}<"
                f"{vol_threshold}), allocation={allocation}")
    )


def should_run_today(spec: Spec, *, as_of: date, last_entry: Optional[date]) -> bool:
    """cadence 到了没有。第一次运行(无 last_entry)总是跑。"""
    if last_entry is None:
        return True
    return (as_of - last_entry).days >= spec.cadence


def exit_due(spec: Spec, *, entry_date: date, as_of: date,
             pnl_pct: float) -> Optional[str]:
    """该不该平仓 —— 返回原因,None 表示继续持有。

    两个出口都要报出来是哪一个:持满 vs 触止损,在下游是两件不同的事,
    而"平了"把它们压成一件。
    """
    if pnl_pct <= spec.dd_stop_pct:
        return f"dd_stop {pnl_pct:.2f}% <= {spec.dd_stop_pct}%"
    if (as_of - entry_date).days >= spec.hold:
        return f"hold {spec.hold}d reached"
    return None


# ── CLI (S-284 D fix, 2026-09-04) ──────────────────────────────────────────
# 让 BOOK_TRADER_DECISION_2026-09-01.md:119 那条 VERIFY 真正能跑:
#
#     python3 paper_trading/spec_runner.py --spec <path> --as-of YYYY-MM-DD \
#         [--regime EASING] [--n-open N] \
#         [--require-regime {ok|thin|COLLAPSED|frozen|no_baseline|no_data}] \
#         [--book {a|b}] [--dry-run] \
#         [--panel-json <path>] [--quorum-rows-json <path>]
#
# 输出:Decision 的 JSON payload(`as_payload()`)。
#
# --require-regime 是测试闸:它合成一个 RegimeQuorum(verdict=所传值)传给
# decide_gated。要看「quorum=COLLAPSED 时 book 是不是真被挡住」:
#     --require-regime=COLLAPSED --spec <book_b.json> --as-of 2026-09-01
# 默认 panel 是合成的(20 天 / spec.universe 标的);传 --panel-json 覆盖。
# 默认 quorum 是不传(no gate);传 --require-regime 才有闸。
#
# --book {a,b} 是信息性的 —— 当前 spec_runner 不分 a/b;它由 spec JSON 的
# spec_family 决定。保留这个 flag 是因为 BOOK_TRADER_DECISION 用它;留个
# 校验,让命令行错配早失败。
if __name__ == "__main__":                                  # noqa: C901
    import argparse
    import sys as _sys
    # CLI 直跑时 src/ 不在 path 上(Mac-side 从 repo 根目录跑);
    # 调到 repo 根加入 path。
    _here = Path(__file__).resolve().parent
    _root = _here.parent if (_here.name == "paper_trading") else _here
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

    from src.data.market.regime_quorum import (
        RegimeQuorum, OK, THIN, COLLAPSED, FROZEN, NO_BASELINE, NO_DATA)

    VERDICT_CHOICES = [OK, THIN, COLLAPSED, FROZEN, NO_BASELINE, NO_DATA]

    _p = argparse.ArgumentParser(
        description="paper_trading spec_runner CLI (S-284 D)")
    _p.add_argument("--spec", required=True,
                    help="path to spec JSON file")
    _p.add_argument("--as-of", required=True,
                    help="as-of date YYYY-MM-DD")
    _p.add_argument("--regime", default=None,
                    help="regime label (canonical: EASING / TIGHTENING / "
                         "RISK_OFF / RISK_ON / STAGFLATION / NEUTRAL)")
    _p.add_argument("--n-open", type=int, default=0,
                    help="currently open trades (default 0)")
    _p.add_argument("--require-regime", default=None, choices=VERDICT_CHOICES,
                    help="regime_quorum verdict to synthesize (test mode); "
                         "COLLAPSED/frozen/no_baseline/no_data → SKIPPED")
    _p.add_argument("--book", default=None, choices=("a", "b"),
                    help="book a (M-113 V3) or b (M-115 Book B); "
                         "informational, spec_family in JSON is the dispatcher")
    _p.add_argument("--dry-run", action="store_true",
                    help="do not write (informational; spec_runner is pure)")
    _p.add_argument("--panel-json", default=None,
                    help="optional panel rows JSON; default = synthetic 20-day")
    _p.add_argument("--quorum-rows-json", default=None,
                    help="optional regime_quorum input rows JSON; passed to "
                         "regime_quorum.classify() instead of synthesizing")
    _p.add_argument("--gate", default="none",
                    choices=("none", "regime", "2d_composite"),
                    help="pre-decision gate: "
                         "none=no gate (default), "
                         "regime=decide_gated with quorum only, "
                         "2d_composite=M-128d Path γ 2D gate "
                         "(CASH in RISK_OFF × |composite_z|≤0.75)")
    _p.add_argument("--composite-z", type=float, default=None,
                    help="prior-day composite_z for --gate=2d_composite; "
                         "omit to use --composite-z-db lookup")
    _p.add_argument("--composite-z-db", default=None,
                    help="path to composite_z sqlite (trade_date, composite_z); "
                         "only used with --gate=2d_composite and no --composite-z")

    _args = _p.parse_args()

    _spec = Spec.load(_args.spec)
    _as_of = date.fromisoformat(_args.as_of)

    # ── Panel
    if _args.panel_json:
        _rows_in = json.loads(Path(_args.panel_json).read_text())
        _panel = build_panel(_rows_in, source=_spec.source)
    else:
        # Synthetic: 20 天 daily bars for spec.universe (BTC 必须在场 for book family)
        _syms = list(_spec.universe)
        if _spec.family == "survivors_only_lag1_book" and "BTC" not in _syms:
            print(json.dumps({"_warning": "synthetic panel: BTC 不在 universe,"
                              " book family 会 BLOCKED 缺 BTC"}, indent=2))
        _end = _as_of
        _rows_syn: list[dict] = []
        for _i in range(20):
            _d = (_end - timedelta(days=19 - _i)).isoformat()
            for _j, _s in enumerate(_syms):
                _rows_syn.append({"symbol": _s, "trade_date": _d,
                                  "close": 100 + _i * (_j + 1),
                                  "source": _spec.source})
        _panel = build_panel(_rows_syn, source=_spec.source)

    # ── Quorum
    _quorum = None
    if _args.quorum_rows_json:
        from src.data.market.regime_quorum import classify as _classify
        _qrows = json.loads(Path(_args.quorum_rows_json).read_text())
        _quorum = _classify(_qrows, today=_as_of)
    elif _args.require_regime:
        _quorum = RegimeQuorum(
            d=_args.as_of, regime=_args.regime or "EASING",
            n_obs=100, n_sources=2, verdict=_args.require_regime,
            reason="CLI synthetic — --require-regime 测试闸",
        )

    # ── Decide
    if _args.gate == "2d_composite":
        # Path γ: pre-decision 2D gate. If gate says CASH, returns SKIPPED
        # before decide_gated is called.
        _cz = _args.composite_z
        _cz_src = None
        if _cz is None and _args.composite_z_db:
            try:
                from m128d_2d_gate import CompositeZSource as _CZS
                _cz_src = _CZS(db_path=_args.composite_z_db)
            except ImportError:
                pass
        _decision = decide_gated_2d(_spec, _panel, as_of=_as_of,
                                    regime=_args.regime, n_open=_args.n_open,
                                    composite_z=_cz, composite_z_source=_cz_src,
                                    quorum=_quorum)
    else:
        _decision = decide_gated(_spec, _panel, as_of=_as_of,
                                 regime=_args.regime, n_open=_args.n_open,
                                 quorum=_quorum)

    # ── 输出 (含 book 信息 + dry-run 标记,便于人读)
    _payload = _decision.as_payload()
    _payload["_meta"] = {
        "spec_family": _spec.family,
        "book_flag": _args.book,
        "dry_run": _args.dry_run or _spec.dry_run,
        "synthetic_panel": _args.panel_json is None,
        "synthetic_quorum": _args.require_regime is not None
                            and _args.quorum_rows_json is None,
        "gate": _args.gate,
        "composite_z": _args.composite_z,
    }
    print(json.dumps(_payload, indent=2, ensure_ascii=False))


__all__ = ["Spec", "Panel", "Decision", "Leg", "Verdict",
           "build_panel", "decide", "decide_gated", "decide_gated_2d",
           "decide_survivors_book", "decide_btc_trend",
           "decide_panel_long_only",
           "decide_panel_long_only_simple_factor",
           "should_run_today", "exit_due",
           "MAX_PANEL_AGE_DAYS", "MIN_UNIVERSE_FOR_RANK"]
