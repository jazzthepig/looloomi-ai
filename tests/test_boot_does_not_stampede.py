"""S-482:部署后循环别同时开火。上限 180 秒那版,51 个循环里 43 个落在同一个 30 秒窗口,Supabase 熔断每次部署都打开。

11-06:反方向的病 —— 最慢的第一轮在 23 分钟,构建只活 15–18 分钟,40 个循环整个上午没跑过。
两条判据一起守:**窗口密度**和**最慢的那一个**。
"""
import random
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _wants():
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    return [int(x) for x in re.findall(r"_boot_delay\((\d+)\)", src)]


def _schedule(seed):
    from src.api.main import _boot_slot
    ws = _wants()
    random.Random(seed).shuffle(ws)          # 调用次序未知 → 随机多试几种
    seen = Counter()
    out = []
    for seq, w in enumerate(ws):
        out.append(_boot_slot(w, seen[w], seq))
        seen[w] += 1
    return sorted(out)


def test_no_30s_window_holds_more_than_ten_first_runs():
    for seed in range(50):
        ds = _schedule(seed)
        worst = max(sum(1 for d in ds if a <= d < a + 30) for a in ds)
        assert worst <= 10, f"{worst} 个循环在同一个 30 秒窗口里第一次开火 (seed {seed})"


def test_slowest_first_run_beats_a_busy_build():
    from src.api.main import _BOOT_DELAY_CAP_S
    assert _BOOT_DELAY_CAP_S <= 14 * 60
    assert max(_schedule(0)) <= _BOOT_DELAY_CAP_S + 1


def test_boot_delay_keeps_order_and_bounded():
    from src.api.main import _BOOT_DELAY_CAP_S, _boot_delay
    for _ in range(14):                     # 走一圈错开序列,次序都得保住
        assert _boot_delay(120) < _boot_delay(150) < _boot_delay(300) < _boot_delay(900) < _boot_delay(3600)
    assert _boot_delay(3600) <= _BOOT_DELAY_CAP_S + 150


def test_order_preserved_across_every_distinct_want():
    from src.api.main import _boot_slot
    ws = sorted(set(_wants()))
    lo = [_boot_slot(w, 0, 0) for w in ws]          # 同值里最早的
    hi = [_boot_slot(w, 99, 6) for w in ws]         # 同值里最晚的(槽 + 最大错开量)
    for a in range(len(ws) - 1):
        if ws[a + 1] <= 300:                         # 头部原样(S-482),不归这次管
            continue
        assert hi[a] < lo[a + 1], (ws[a], ws[a + 1], hi[a], lo[a + 1])
