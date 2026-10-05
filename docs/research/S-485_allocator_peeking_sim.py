"""S-485:L3 准入门(均值 − 2 标准误 > 0,且 ≥ 20 天)每天重算一次 —— 零超额账本被放进去的概率。

零均值日超额(正态 / t3),每天按 allocator.evidence 的同一公式算下界,数「曾经被放进去」的比例。
复现:python3 docs/research/S-485_allocator_peeking_sim.py
"""
import numpy as np

rng = np.random.default_rng(7)


def sim(T: int, R: int = 20000, dist: str = "normal", z: float = 2.0, start: int = 20):
    x = rng.standard_normal((R, T)) if dist == "normal" else rng.standard_t(3, (R, T)) / np.sqrt(3)
    c, c2, n = np.cumsum(x, 1), np.cumsum(x * x, 1), np.arange(1, T + 1)
    m = c / n
    s = np.sqrt((c2 - n * m * m) / np.maximum(n - 1, 1))
    adm = ((m - z * s / np.sqrt(n)) > 0)[:, start - 1:]
    return adm.any(1).mean(), adm.mean(), adm[:, -1].mean()


if __name__ == "__main__":
    for dist in ("normal", "t3"):
        for T in (60, 120, 250, 365):
            ever, share, last = sim(T, dist=dist)
            pool = 1 - (1 - ever) ** 10
            print(f"{dist:6s} T={T:3d} 曾被放进={ever:.1%} 被放进的天数占比={share:.2%} "
                  f"末日被放进={last:.2%} 10本里至少一本={pool:.0%}")
