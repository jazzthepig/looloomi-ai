"""S-482:部署后循环别同时开火。上限 180 秒那版,51 个循环里 43 个落在同一个 30 秒窗口,Supabase 熔断每次部署都打开。"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _base(want, cap):
    return min(want, cap) + want / 3600 * 120


def test_no_30s_window_holds_more_than_ten_first_runs():
    from src.api.main import _BOOT_DELAY_CAP_S
    src = (ROOT / "src/api/main.py").read_text(encoding="utf-8")
    wants = [int(x) for x in re.findall(r"_boot_delay\((\d+)\)", src)]
    ds = sorted(_base(w, _BOOT_DELAY_CAP_S) for w in wants)
    worst = max(sum(1 for d in ds if a <= d < a + 30) for a in ds)
    assert worst <= 10, f"{worst} 个循环在同一个 30 秒窗口里第一次开火"


def test_boot_delay_keeps_order_and_bounded():
    from src.api.main import _BOOT_DELAY_CAP_S, _boot_delay
    for _ in range(14):                     # 走一圈错开序列,次序都得保住
        assert _boot_delay(120) < _boot_delay(150) < _boot_delay(300) < _boot_delay(900) < _boot_delay(3600)
    assert _boot_delay(3600) <= _BOOT_DELAY_CAP_S + 150
