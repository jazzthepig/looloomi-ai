"""
回撤阶梯 — RISK_ALLOCATOR_SPEC §3 的可复用实现 (Seth, 2026-07-27)

存在的理由:S-89 报了一组不可复现的数字,根因是**冷冻期满未重置高水位**导致永久锁死
(解冻瞬间 dd 仍 ≤ −15% ⇒ 立刻再冻)。这个 bug 在纯回测脚本里不可见,必须有单元测试守住。
Millennium 语义:pod 冷冻重启后,**回撤时钟归零** —— 新的高水位从重启点开始算。
"""
from __future__ import annotations


class DrawdownLadder:
    """机械回撤阶梯:−8% 削半 · −12% ×0.25 · −15% 归零+冷冻N日 · 回到 −4% 内恢复满仓。

    用法:每个 bar 调用 `update(nav)`,乘 `mult` 到当期收益上。
    `mult` 是仓位乘数,不是信号 —— 它与⓪层闸门相乘,两者独立。
    """

    def __init__(self, freeze_days: int = 30):
        self.freeze_days = freeze_days
        self.peak = None
        self.mult = 1.0
        self.frozen_left = 0
        self.freezes = 0

    def update(self, nav: float) -> float:
        if self.peak is None:
            self.peak = nav
        if self.frozen_left > 0:
            self.frozen_left -= 1
            self.mult = 0.0
            if self.frozen_left == 0:
                # ★ 关键:解冻时重置高水位 —— 回撤时钟归零,否则永久锁死(S-90 的 bug)
                self.peak = nav
                self.mult = 1.0
            return self.mult
        self.peak = max(self.peak, nav)
        dd = nav / self.peak - 1.0
        if dd <= -0.15:
            self.mult = 0.0
            self.frozen_left = self.freeze_days
            self.freezes += 1
        elif dd <= -0.12:
            self.mult = 0.25
        elif dd <= -0.08:
            self.mult = 0.5
        elif dd > -0.04:
            self.mult = 1.0
        return self.mult
