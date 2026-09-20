"""`/internal/loops` 后端的守卫 — S-390 P1.

只测**纯函数部分**(`build_report` + `to_dict`),HTTP 端点测留给集成。
测试用的 JSONL 文件走 `tmp_path` 隔离,不写 `/Volumes`。

核心判据:
- 文件不存在 ≠ "Mac 一切正常"
- 多个 envelope 按 `job_name` 去重,**最新一条覆盖旧的**
- 解析失败的行**丢掉,继续**(一个坏行不能废掉整次读取)
- 大文件截尾丢老不丢新(`max_lines` 保护)
- canary_zero 等扩展词表在 mirror 文件里 (`mac_failed_step_values`) 与
  MacErrorEnvelope 真源保持一致
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.loops_envelopes import (                                # noqa: E402
    DEFAULT_ENVELOPE_PATH, ENV_POSTMORTEM_PATH, _read_envelopes,
    _summarize_one, build_report, to_dict,
)
from src.api.contracts.mac_failed_step_values import (                # noqa: E402
    FAILED_STEP_VALUES, is_known_failed_step,
)

_FAIL: list = []


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


# ── build_report:文件状态 ─────────────────────────────────────────────────

def t_missing_file_is_unreadable_not_ok(tmp_path: Path = None):
    """JSONL 不存在 → readable=False + note 解释,**不是 verdict=ok**。"""
    r = build_report(path="/no/such/file/abc.jsonl")
    _check("missing → readable=False", r.readable is False)
    _check("missing → jobs={}", r.jobs == {}, repr(r.jobs))
    _check("missing → note 解释读不到 ≠ 正常",
           "读不到" in r.note or "不存在" in r.note, r.note[:80])


def t_empty_file_returns_readable_with_zero_jobs(tmp_path: Path = None):
    """0 行文件存在 → readable=True + 0 jobs + note 解释 '文件是空的'。"""
    p = tmp_path / "empty.jsonl"
    p.write_text("")
    r = build_report(path=str(p))
    _check("empty → readable=True", r.readable is True)
    _check("empty → jobs={}", r.jobs == {})
    _check("empty → n_envelopes=0", r.n_envelopes == 0)
    _check("empty → note 解释 0 行",
           "0 行" in r.note or "未写入" in r.note, r.note[:80])


def t_garbled_line_is_dropped_not_fatal(tmp_path: Path = None):
    """JSONL 里 1 行 parse 不出来 → 那行丢掉,其他行继续读。"""
    p = tmp_path / "mixed.jsonl"
    p.write_text(
        'this is not json\n'
        + json.dumps({"job_name": "cis_scheduler", "ok": True,
                      "started_at": "2026-09-20T08:00:00+00:00",
                      "finished_at": "2026-09-20T08:01:00+00:00",
                      "duration_s": 60.0}) + "\n"
        + '{also not json}\n'
    )
    r = build_report(path=str(p))
    _check("garbled → readable=True", r.readable is True)
    _check("garbled → 1 行有效被读",
           r.n_envelopes == 1 and r.n_jobs == 1,
           f"n_envelopes={r.n_envelopes} n_jobs={r.n_jobs}")
    _check("garbled → job 被识别",
           "cis_scheduler" in r.jobs)


# ── 去重 + 覆盖 ─────────────────────────────────────────────────────────

def t_latest_envelope_overrides(tmp_path: Path = None):
    """同名 job 多条 envelope → 只保留最新(按文件中出现顺序,append-only)。"""
    p = tmp_path / "dup.jsonl"
    lines = [
        json.dumps({"job_name": "cis_scheduler", "ok": True,
                    "started_at": "2026-09-19T08:00:00+00:00",
                    "finished_at": "2026-09-19T08:01:00+00:00",
                    "duration_s": 60.0}),
        json.dumps({"job_name": "cis_scheduler", "ok": False,
                    "failed_step": "supabase_push",
                    "error": "ConnectError",
                    "error_message": "Connection refused",
                    "started_at": "2026-09-20T08:00:00+00:00",
                    "finished_at": "2026-09-20T08:01:30+00:00",
                    "duration_s": 90.0}),
    ]
    p.write_text("\n".join(lines) + "\n")
    r = build_report(path=str(p))
    _check("dup → 1 个 job", len(r.jobs) == 1, repr(list(r.jobs.keys())))
    s = r.jobs["cis_scheduler"]
    _check("dup → 最新失败覆盖旧成功", s.last_ok is False,
           f"last_ok={s.last_ok}")
    _check("dup → failed_step 保留", s.last_failed_step == "supabase_push",
           f"last_failed_step={s.last_failed_step}")
    _check("dup → n_observed=2", s.n_observed == 2,
           f"n_observed={s.n_observed}")
    _check("dup → n_failures=1", s.n_failures == 1,
           f"n_failures={s.n_failures}")


def t_canary_zero_failed_step_survives(tmp_path: Path = None):
    """`failed_step="canary_zero"` 在 mirror 词表里 —— 不被静默归一。"""
    p = tmp_path / "canary.jsonl"
    p.write_text(json.dumps({
        "job_name": "active_monitor", "ok": False,
        "failed_step": "canary_zero",
        "error": "AssertionError",
        "error_message": "expected ≥1 row, got 0",
        "started_at": "2026-09-20T08:00:00+00:00",
        "finished_at": "2026-09-20T08:01:00+00:00",
        "duration_s": 60.0}) + "\n")
    r = build_report(path=str(p))
    s = r.jobs["active_monitor"]
    _check("canary_zero 保留为字面值",
           s.last_failed_step == "canary_zero",
           f"got {s.last_failed_step!r}")
    _check("canary_zero 在 Seth-side mirror 词表里",
           is_known_failed_step("canary_zero"))


# ── to_dict shape ───────────────────────────────────────────────────────

def t_to_dict_is_json_friendly(tmp_path: Path = None):
    """`to_dict` 给 FastAPI 直接 return,不能有 dataclass 实例残留。"""
    p = tmp_path / "shape.jsonl"
    p.write_text(json.dumps({
        "job_name": "cis_scheduler", "ok": True,
        "started_at": "2026-09-20T08:00:00+00:00",
        "finished_at": "2026-09-20T08:01:00+00:00",
        "duration_s": 60.0}) + "\n")
    r = build_report(path=str(p))
    d = to_dict(r)
    # FastAPI 会再过 json.dumps —— 必须没有不可序列化对象
    import json as _j
    _j.dumps(d)  # 不能 raise
    _check("to_dict 有 readable / checked_at / source_path / jobs",
           all(k in d for k in ("readable", "checked_at", "source_path", "jobs")))
    _check("to_dict jobs 是 dict[dict] 不是 dataclass",
           all(isinstance(v, dict) for v in d["jobs"].values()))


# ── 词表契约 ────────────────────────────────────────────────────────────

def t_mirror_includes_canary_zero_and_matches_shape():
    """Seth-side mirror 必须包含 Shadow 真源的全部词表 + canary_zero 扩展。"""
    _check("FAILED_STEP_VALUES 含 canary_zero",
           "canary_zero" in FAILED_STEP_VALUES)
    _check("FAILED_STEP_VALUES 含 unknown (兜底)",
           "unknown" in FAILED_STEP_VALUES)
    _check("FAILED_STEP_VALUES 含 None (ok=True 标记)",
           None in FAILED_STEP_VALUES)
    # Shadow 真源 + canary_zero = 这份 mirror 的最小集合
    _check("mirror 至少 12 项",
           len(FAILED_STEP_VALUES) >= 12,
           f"len={len(FAILED_STEP_VALUES)}")


def t_is_known_failed_step_handles_unknown():
    """未识别 step 不算"已知" —— 静默归一是 MacErrorEnvelope 的事,本函数
    只查词表。"""
    _check("known step → True",
           is_known_failed_step("validation"))
    _check("None → True (ok=True marker)",
           is_known_failed_step(None))
    _check("unknown → True (in 词表)",
           is_known_failed_step("unknown"))
    _check("随机新词 → False (unrecognised, lets caller decide)",
           not is_known_failed_step("totally_new_step_xyz"))


# ── 大文件截尾 ──────────────────────────────────────────────────────────

def test_max_lines_drops_old_not_new(tmp_path: Path = None):
    """文件超过 `max_lines` → 丢掉最老,保留最新(append-only 语义)。"""
    p = tmp_path / "large.jsonl"
    lines = []
    for i in range(100):
        lines.append(json.dumps({
            "job_name": "x", "ok": (i == 99),
            "started_at": f"2026-09-{(i % 30) + 1:02d}T08:00:00+00:00",
            "finished_at": f"2026-09-{(i % 30) + 1:02d}T08:01:00+00:00",
            "duration_s": 60.0}))
    p.write_text("\n".join(lines) + "\n")
    # 限制 max_lines=10 → 只看最后 10 行(索引 90-99)
    r = build_report(path=str(p), max_lines=10)
    _check("max_lines 截到 ≤10 行 envelope",
           r.n_envelopes <= 10,
           f"n_envelopes={r.n_envelopes}")
    s = r.jobs["x"]
    _check("最新一条 (ok=True) 覆盖",
           s.last_ok is True,
           f"last_ok={s.last_ok}")
    _check("n_observed 等于实际读取数(不是 100)",
           s.n_observed <= 10,
           f"n_observed={s.n_observed}")


def main(tmp_path=None) -> int:
    # 没传 tmp_path 时造一个
    import tempfile
    _tp = tmp_path or tempfile.mkdtemp(prefix="loops_env_test_")
    from pathlib import Path
    _tp_p = Path(_tp)

    funcs = [v for k, v in sorted(globals().items()) if k.startswith("t_")]
    for fn in funcs:
        print(f"\n▸ {fn.__name__}")
        # t_xxx 接受 tmp_path 参数
        import inspect
        if "tmp_path" in inspect.signature(fn).parameters:
            fn(tmp_path=_tp_p)
        else:
            fn()

    print("\n" + ("✓ 全部通过" if not _FAIL else f"✗ {len(_FAIL)} 条失败"))
    for f in _FAIL:
        print("   " + f)
    return 1 if _FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
