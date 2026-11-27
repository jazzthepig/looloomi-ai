"""现行交易规则的数值部分 —— 研究脚本、模拟与生产共用的那一份(说明见 `docs/RULEBOOK.md`)。

S-930(2026-11-27):S-926 → S-929 连续四轮模拟不合标准,共同的根是「同一条规则在好几个地方各写一份」——
空单定稿只在 `tasks/T-370.json` 的备注里,教义还留着旧写法,每个研究脚本自己重写一遍口径。
从这里起:**改规则 = 同一次提交里改这个文件和 `docs/RULEBOOK.md`**(`tests/test_house_rules.py` 校验两边一致);
生产代码与新研究脚本 import 这里的值,不再各写常量。新研究脚本另要声明 `HOUSE_RULES`(用了哪些、改了哪一条)。
"""
from __future__ import annotations

#: 空头票 —— T-370 v1(11-15 定稿;S-612 / S-865 / S-874 / S-929)。⓪ short 状态要 Jazz 签名,系统只管止损 / 到期 / 上限。
T370 = {
    "lookback": 20,              # 收盘 < 此前 20 根日线的最低价(不含当天)
    "stop_above": 1.01,          # 认错线 = 被破那一档 × 1.01
    "stop_cap": 1.08,            # 且离进场 ≤ 8%
    "horizon_d": 28,             # 拿满 28 天
    "take_profit": None,         # 不提前止盈
    "breakeven_move": False,     # 不移保本
    "auto_add": False,           # 不自动加仓(冲高加仓 = Jazz 单独签名的一笔)
    "tiers": (0.10, 0.20, 0.30),  # 空头总名义占账户,均分到各币
    "funding_7d_positive": True,  # S-886
}

#: 多头票 —— R-v2(真钱:S-829 / S-831;机构规格:S-834 / S-835)
RV2 = {
    "slots": 10,
    "notional_cap": 0.80,
    "risk_per_ticket": 0.0075,
    "risk_per_ticket_institutional": 0.0025,
    "single_source_risk_cap": 0.40,
}

#: ③ 敞口(DECISIONS 10-21 / 11-12):裁定允许的区间 与 生产里现在截的区间
EXPOSURE = {"allowed": (-0.3, 1.3), "production": (0.0, 1.0)}
PORTFOLIO = {"leverage_max": 5}

RULE_SETS = {"T370": T370, "RV2": RV2, "EXPOSURE": EXPOSURE, "PORTFOLIO": PORTFOLIO}
