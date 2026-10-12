"""基金规模与费率口径 —— 一处定义(Jazz 10-12,S-544)。

「AUM 先解决 30M,之后再达到 500M。我们需要定好设计和工程的冗余,不用我中途再升级。」
所以:当下按 TARGET_AUM_USD 运作,所有容量 / 流动性 / 执行的检查同时按 DESIGN_AUM_USD 算 —— 到 500M 时不需要
改任何口径,只需要看哪些检查早就标红了。

「策略按照管理费 0%,只收业绩费;管理费 + 业绩费是合规基金框架覆盖管理成本而设计的,两者不冲突。」
"""
from __future__ import annotations

TARGET_AUM_USD = 30_000_000          # 第一期
DESIGN_AUM_USD = 500_000_000         # 设计与工程按这个留冗余(不中途升级)

#: 流动性口径(calculate_las 与容量报告共用)
SATELLITE_POSITION_PCT = 0.05        # 单个非核心名字的满仓位
PARTICIPATION_RATE = 0.10            # 一天最多吃掉日成交额的这一比例
BUILD_DAYS = 5                       # 建 / 平一个满仓位允许的交易日数

FEES = {
    "strategies": {"management_fee": 0.0, "performance_fee": True,
                   "note": "Strategies: 0% management fee, performance fee only."},
    "regulated_fund_wrapper": {"management_fee": "covers fund costs", "performance_fee": True,
                               "note": "A regulated fund wrapper charges a management fee to cover fund costs, "
                                       "plus a performance fee. The two structures do not conflict."},
}
