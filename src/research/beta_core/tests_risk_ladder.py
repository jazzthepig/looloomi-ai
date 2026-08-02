"""守住 S-90 的 bug:冷冻期满必须恢复且重置高水位。Run: python3 -m src.research.beta_core.tests_risk_ladder"""
import os, sys
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))
from src.research.beta_core.risk_ladder import DrawdownLadder

def test_ladder_steps():
    L=DrawdownLadder(); L.update(1.0)
    assert L.update(0.95)==1.0, "−5% 仍满仓"
    assert L.update(0.91)==0.5, "−9% 削半"
    assert L.update(0.87)==0.25, "−13% ×0.25"
    assert L.update(0.84)==0.0, "−16% 归零"

def test_unfreeze_resets_peak_and_recovers():
    """S-90 的致命 bug:解冻若不重置 peak,dd 立刻又 ≤−15% ⇒ 永久锁死。"""
    L=DrawdownLadder(freeze_days=3); L.update(1.0); L.update(0.80)   # 触发冷冻
    assert L.frozen_left==3 and L.mult==0.0
    L.update(0.80); L.update(0.80)
    m=L.update(0.80)                       # 第3次递减 → 解冻
    assert m==1.0, f"解冻后必须恢复满仓, got {m}"
    assert abs(L.peak-0.80)<1e-9, "解冻必须把高水位重置到当前 nav(回撤时钟归零)"
    assert L.update(0.79)==1.0, "重置后小幅回撤不应立即再冻(否则=永久锁死)"

def test_no_permanent_lock():
    """横盘不恢复的场景:不许出现连续冷冻导致 mult 永远为 0。"""
    L=DrawdownLadder(freeze_days=2); nav=1.0; L.update(nav)
    nav=0.8; muls=[L.update(nav) for _ in range(20)]   # 价格不动
    assert max(muls)==1.0, "价格企稳后必须恢复暴露,不能永久锁死"

T=[v for k,v in sorted(globals().items()) if k.startswith("test_")]
if __name__=="__main__":
    for t in T: t(); print(f"  ✓ {t.__name__}")
    print(f"\n✅ {len(T)}/{len(T)} 回撤阶梯单元测试通过(守住 S-90 的 bug)")
