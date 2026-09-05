"""paper_trading spec_runner CLI (S-284 D fix).

CLI 是 decide_gated + argparse 的胶水。回归点不是逻辑(那个在
test_regime_quorum_blocks_book.py 已盖),而是:
  · argparse 接受/拒绝该接受的 flag
  · --require-regime=COLLAPSED 真的产出 SKIPPED
  · --require-regime=ok 真的产出 ENTERED
  · 缺 --spec / --as-of 时 exit 2(usage)
  · JSON 输出含 _meta,synthetic_panel / synthetic_quorum 标记对
"""
from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

_BOOK_B_SPEC: dict = {
    "spec_name": "M115_BOOK_B_CLI_TEST",
    "spec_family": "survivors_only_lag1_book",
    "universe": ["BTC", "ETH", "SOL", "AVAX"],
    "data_source": {"primary": "binance_hist"},
    "parameters": {
        "sleeve_weights": {"m93": 0.5, "xs": 0.5},
        "sleeve_M93": {"cash_when_regime_in": ["RISK_OFF"]},
        "sleeve_R14-Lite": {
            "rank_by": "ret_14d", "K_long": 2, "K_short": 2,
            "cadence_days": 7, "hold_days": 7, "weight_per_leg": 0.05,
        },
        "cost_bps_rt_max": 5.0,
        "dd_stop_pct": -0.20,
        "max_open_trades": 10,
    },
    "execution": {"dry_run": True},
}

_FAILURES: list[str] = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    if ok:
        print(f"  ✓ {label}")
    else:
        _FAILURES.append(f"{label}{(' — ' + detail) if detail else ''}")
        print(f"  ✗ {label}\n      {detail}")


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "paper_trading/spec_runner.py", *args],
        cwd=ROOT, capture_output=True, text=True, timeout=30,
    )


def _with_spec(tmpdir: Path) -> Path:
    spec_path = tmpdir / "book_b.json"
    spec_path.write_text(json.dumps(_BOOK_B_SPEC))
    return spec_path


def test_cli_ok_quorum_enters():
    """--require-regime=ok → ENTERED,verdict_kind=entered,synthetic_quorum=true。"""
    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp = _run_cli("--spec", str(spec), "--as-of", "2026-09-01",
                      "--regime", "EASING",
                      "--require-regime", "ok", "--book", "b", "--dry-run")
        _check("exit 0", cp.returncode == 0,
               f"exit={cp.returncode} stderr={cp.stderr[:80]}")
        out = json.loads(cp.stdout)
        _check("verdict == ENTERED", out["verdict"] == "ENTERED", out["verdict"])
        _check("verdict_kind == 'entered'", out["verdict_kind"] == "entered",
               out["verdict_kind"])
        _check("5 条腿(BTC long + 4 xs)", len(out["legs"]) == 5,
               str(len(out.get("legs", []))))
        _check("_meta.synthetic_panel == true", out["_meta"]["synthetic_panel"] is True)
        _check("_meta.synthetic_quorum == true", out["_meta"]["synthetic_quorum"] is True)
        _check("_meta.book_flag == 'b'", out["_meta"]["book_flag"] == "b")
        _check("_meta.dry_run == true", out["_meta"]["dry_run"] is True)


def test_cli_collapsed_quorum_skips():
    """--require-regime=COLLAPSED → SKIPPED,reason 写出 verdict。"""
    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp = _run_cli("--spec", str(spec), "--as-of", "2026-09-01",
                      "--regime", "EASING",
                      "--require-regime", "COLLAPSED", "--book", "b", "--dry-run")
        _check("exit 0", cp.returncode == 0,
               f"exit={cp.returncode} stderr={cp.stderr[:80]}")
        out = json.loads(cp.stdout)
        _check("verdict == SKIPPED", out["verdict"] == "SKIPPED", out["verdict"])
        _check("verdict_kind == 'skipped'", out["verdict_kind"] == "skipped",
               out["verdict_kind"])
        _check("SKIPPED 没有 legs 字段", "legs" not in out, str(out.keys()))
        _check("reason 写 COLLAPSED", "COLLAPSED" in out["reason"], out["reason"][:80])
        _check("reason 引用 S-263",
               "S-263" in out["reason"], out["reason"][:120])


def test_cli_no_quorum_passes_through():
    """不传 --require-regime → 不加闸,与 decide() 等价 → ENTERED。"""
    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp = _run_cli("--spec", str(spec), "--as-of", "2026-09-01",
                      "--regime", "EASING", "--book", "b", "--dry-run")
        _check("exit 0", cp.returncode == 0, f"stderr={cp.stderr[:80]}")
        out = json.loads(cp.stdout)
        _check("verdict == ENTERED(闸未启用)", out["verdict"] == "ENTERED",
               out["verdict"])
        _check("_meta.synthetic_quorum == false(没合成)",
               out["_meta"]["synthetic_quorum"] is False)


def test_cli_requires_spec_and_as_of():
    """缺 --spec 或 --as-of → argparse exit 2 + stderr 写 usage。"""
    cp = _run_cli("--regime", "EASING")
    _check("缺 --spec → exit 2",
           cp.returncode == 2, f"exit={cp.returncode}")
    _check("stderr 写 spec 是 required",
           "spec" in cp.stderr.lower() or "--spec" in cp.stderr,
           cp.stderr[:80])

    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp2 = _run_cli("--spec", str(spec))
        _check("缺 --as-of → exit 2",
               cp2.returncode == 2, f"exit={cp2.returncode}")
        _check("stderr 写 as-of 是 required",
               "as-of" in cp2.stderr or "as_of" in cp2.stderr,
               cp2.stderr[:80])


def test_cli_rejects_unknown_quorum_verdict():
    """--require-regime=foo(非六值之一)→ argparse exit 2。"""
    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp = _run_cli("--spec", str(spec), "--as-of", "2026-09-01",
                      "--require-regime", "foo")
        _check("--require-regime=foo → exit 2", cp.returncode == 2,
               f"exit={cp.returncode}")
        _check("stderr 写 invalid choice",
               "invalid choice" in cp.stderr.lower()
               or "foo" in cp.stderr, cp.stderr[:120])


def test_cli_book_flag_only_a_or_b():
    """--book 必须是 a 或 b;c 拒。"""
    with tempfile.TemporaryDirectory() as td:
        spec = _with_spec(Path(td))
        cp = _run_cli("--spec", str(spec), "--as-of", "2026-09-01",
                      "--book", "c")
        _check("--book=c → exit 2", cp.returncode == 2, f"exit={cp.returncode}")


if __name__ == "__main__":
    print("── paper_trading spec_runner CLI (S-284 D) ──")
    for fn in [v for k, v in sorted(globals().items()) if k.startswith("test_")]:
        fn()
    if _FAILURES:
        print(f"\n🔴 {len(_FAILURES)} FAILED:")
        for f in _FAILURES:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ CLI 守卫全绿")