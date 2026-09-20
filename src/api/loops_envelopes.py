"""Mac-side job envelope reader — **/internal/loops 的后端** (S-390 P1).

## 这是什么

`Shadow/cometcloud-local/MacErrorEnvelope.py` 由 Minimax-C 维护(Mac 侧),
每次 Mac job 退出时把观察结果(成功 / 失败 / 失败在哪一步 / 错误信息)
按 JSONL 写进 `COMETCLOUD_ENVELOPE_POSTMORTEM` 文件。本模块做**读取端**:
把这个 JSONL 流式解析、按 `job_name` 去重(最新一条覆盖旧的),交给
`/internal/loops` 端点返回。

## 为什么需要它

§S-364 (2026-09-16):Min-C 把所有 loop 落地工作接过去,**envelope 现在只到
stderr + postmortem JSONL**,而 Seth-side 的 `loop_beat.py` 是另一套心跳
(每轮 Redis key),两套**没有交叉**。结果是:
- Mac 侧 job 出错时,Railway 这边**完全看不见** —— 因为 loop_beat 写到 Redis
  的心跳只覆盖 Seth lane 起的 loop;Min-C 的 launchd job 不调 Seth 的 `_beat()`
- `/internal/data-freshness` 里 `loops.rows` 也只覆盖 Seth lane
- ops-console 的 `_classify_loops` 拿不到 Mac 侧任何信号

**装上这个端点后**,Mac job 失败能在 Seth 的 ops-console / data-freshness /
任何调用 `/internal/loops` 的下游里看见。trading module 通后 A 的 loop
落地也需要这个端点(per §S-364 l.380-381:"A 留给 Seth 的两条")。

## 数据来源

JSONL 文件路径走环境变量,默认是 Mac 侧约定路径:

    COMETCLOUD_ENVELOPE_POSTMORTEM = /Volumes/CometCloudAI/cometcloud-local/_logs/mac_envelopes.jsonl

Cowork sandbox / Railway 容器里**通常不存在这个文件**,返回的就是
`{"verdict": "unreadable", ...}` —— **这不是"Mac 一切正常",是"读不到"**。
Mac-side 部署后文件会被 launchd 写入。

## 与 `loop_beat.py` 的关系

- `loop_beat.py`:Seth lane loop 的 Redis 心跳(每轮 ok=True/False/refused)
- 本模块:Mac lane job 的 postmortem envelope(每次退出写一行)

两套数据源**不重叠,不应该合并** —— 它们的发送方不同、节流不同、字段不同。
合并会让"哪个 lane 失败"这个最该被看见的信号消失。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

#: 默认 Mac-side postmortem 路径。**与 Shadow/cometcloud-local/MacErrorEnvelope.py
#: 的 `ENVELOPE_POSTMORTEM_PATH` 保持一致** —— 这是约定路径,改这里时要同时
#: 改那里,否则双源分裂。
DEFAULT_ENVELOPE_PATH = (
    "/Volumes/CometCloudAI/cometcloud-local/_logs/mac_envelopes.jsonl"
)

#: 环境变量名。**与 Shadow 的 MacErrorEnvelope 一致**。
ENV_POSTMORTEM_PATH = "COMETCLOUD_ENVELOPE_POSTMORTEM"


@dataclass
class JobSummary:
    """一个 Mac job 的最新一次观察。"""
    job_name: str
    last_run_at: Optional[str]      # ISO8601 UTC
    last_finished_at: Optional[str]
    last_ok: bool
    last_failed_step: Optional[str]
    last_error: Optional[str]
    last_error_message: Optional[str]
    n_observed: int                 # 这个 job 在 JSONL 里出现过多少次
    n_failures: int                 # 出现里有多少次 failed
    duration_s_last: Optional[float]


@dataclass
class EnvelopesReport:
    """`/internal/loops` 端点的整体响应。"""
    checked_at: str
    source_path: str                # 实际读取的路径
    readable: bool
    n_envelopes: int                # JSONL 总行数
    n_jobs: int                     # 不同 job_name 数
    jobs: dict[str, JobSummary]     # job_name → 最新观察
    note: str = ""                  # 读不到 / 部分读到的解释


def _resolve_path(env_var: Optional[str] = None) -> str:
    """读哪个文件。`env_var` 优先,否则走 `COMETCLOUD_ENVELOPE_POSTMORTEM`,
   最后回退到 Mac 默认约定路径。"""
    if env_var is not None:
        return env_var
    return os.environ.get(ENV_POSTMORTEM_PATH, DEFAULT_ENVELOPE_PATH)


def _parse_iso(s: str) -> Optional[datetime]:
    try:
        # ISO8601 with optional trailing Z
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        return datetime.fromisoformat(s)
    except Exception:                                          # noqa: BLE001
        return None


def _read_envelopes(path: str, *, max_lines: int = 5000) -> list[dict]:
    """流式读 JSONL,**最新在末尾**(postmortem 是 append-only)。

    `max_lines` 是为了防一个文件被滚成几 GB 把内存吃光 —— 实际上 Mac-side
    每个 job 一天写几次,5000 行覆盖几周到几个月。超出时从末尾截,意味着
    我们只丢掉最老的若干行,最新的 job 状态永远在。
    """
    p = Path(path)
    if not p.exists():
        return []
    out: list[dict] = []
    try:
        with p.open("r", encoding="utf-8", errors="replace") as f:
            # 文件可能很大;先统计总行数,需要时跳到尾部
            tail: list[str] = []
            for line in f:
                line = line.strip()
                if not line:
                    continue
                tail.append(line)
                if len(tail) > max_lines:
                    tail = tail[-max_lines:]
            for line in tail:
                try:
                    out.append(json.loads(line))
                except Exception:                              # noqa: BLE001
                    # 一行 parse 不出来不该把整个读取废掉 —— **丢掉那行,继续**
                    continue
    except Exception:                                          # noqa: BLE001
        return []
    return out


def _summarize_one(job: str, envelopes: list[dict]) -> JobSummary:
    """一个 job 的所有 envelope → 一次最终观察。**最新一条覆盖旧的。**"""
    n = len(envelopes)
    n_fail = sum(1 for e in envelopes if not e.get("ok", False))
    if not envelopes:
        return JobSummary(
            job_name=job, last_run_at=None, last_finished_at=None,
            last_ok=False, last_failed_step=None, last_error=None,
            last_error_message=None, n_observed=0, n_failures=0,
            duration_s_last=None)
    last = envelopes[-1]
    return JobSummary(
        job_name=job,
        last_run_at=last.get("started_at"),
        last_finished_at=last.get("finished_at"),
        last_ok=bool(last.get("ok", False)),
        last_failed_step=last.get("failed_step"),
        last_error=last.get("error"),
        last_error_message=last.get("error_message"),
        n_observed=n,
        n_failures=n_fail,
        duration_s_last=(float(last.get("duration_s")) if isinstance(last.get("duration_s"), (int, float)) else None),
    )


def build_report(path: Optional[str] = None, *, max_lines: int = 5000) -> EnvelopesReport:
    """读 JSONL → 按 `job_name` 去重 → 返回最新观察。

    `path=None` 走 `_resolve_path()` 默认值(env → Mac 约定)。
    `path=""` 显式空字符串也会走默认值(避免 None vs 空字符串的歧义)。

    文件不存在 / 不可读 → 返回 `readable=False` + `jobs={}` + 解释 note;
    **不是"一切正常"**。
    """
    actual = _resolve_path(path)
    checked_at = datetime.now(timezone.utc).isoformat()
    p = Path(actual)
    if not p.exists():
        return EnvelopesReport(
            checked_at=checked_at, source_path=actual,
            readable=False, n_envelopes=0, n_jobs=0, jobs={},
            note=f"envelope postmortem 不存在 ({actual}) —— Mac-side 未部署或路径不对。"
                 "**读不到 ≠ Mac 一切正常**。")
    if not p.is_file():
        return EnvelopesReport(
            checked_at=checked_at, source_path=actual,
            readable=False, n_envelopes=0, n_jobs=0, jobs={},
            note=f"envelope postmortem 路径存在但不是文件 ({actual}) —— 配置错误。")
    envelopes = _read_envelopes(actual, max_lines=max_lines)
    by_job: dict[str, list[dict]] = {}
    for e in envelopes:
        jn = str(e.get("job_name") or "").strip()
        if not jn:
            continue
        by_job.setdefault(jn, []).append(e)
    jobs = {jn: _summarize_one(jn, evs) for jn, evs in sorted(by_job.items())}
    return EnvelopesReport(
        checked_at=checked_at, source_path=actual,
        readable=True,
        n_envelopes=len(envelopes),
        n_jobs=len(jobs),
        jobs=jobs,
        note="" if envelopes else f"文件存在但 0 行 envelope —— Mac-side 未写入或文件被截断。")


def to_dict(report: EnvelopesReport) -> dict[str, Any]:
    """JSON-friendly dict,给 `/internal/loops` 端点直接 return."""
    d = asdict(report)
    d["jobs"] = {k: v for k, v in d["jobs"].items()}
    return d
