"""Seth-side mirror of `Shadow/cometcloud-local/MacErrorEnvelope.py:FAILED_STEP_VALUES`.

## 这是什么(以及为什么不是单源)

`Shadow/cometcloud-local/MacErrorEnvelope.py:76-89` 是 Mac 侧 (Minimax-C 维护)
的标准 `failed_step` 枚举 —— Mac job 退出时**只能从这套词表里选一个**。

但 `Shadow/` 是 **READ-ONLY**(CLAUDE.md Rule 2),Seth 不能改它。所以:

- **Mac-side 真源**:`Shadow/.../MacErrorEnvelope.py:FAILED_STEP_VALUES`
- **Seth-side mirror**(本文件):在 Seth lane 需要校验 `failed_step` 时,
  引用这里。**两份内容必须一致**(这是契约,不是参考)。

## 为什么会有 `canary_zero`

S-390 P2:A lane 的 `active_monitor` 写错 step 名时,会被 MacErrorEnvelope 的
`make_envelope` 静默归一为 `"unknown"`(MacErrorEnvelope.py:113-114):
> *"We do not raise — we silently normalise to 'unknown' because A-N7 says
> '装观测,不装猜测'; an unrecognised step is itself an observation."*

这是对的(观测不装猜测),但**真正的 `canary_zero`(canary 行写 0 行)是有
诊断意义的失败** —— 把它静默归一就丢失了一个信号。

**修法**:把 `canary_zero` 加进 Mac-side 的 `FAILED_STEP_VALUES`(C-N3 contract
update + Seth SYNC ack per MacErrorEnvelope.py:75-76) + 加进 Seth-side mirror
(本文件)。两侧 ack 之后,A 的 `active_monitor` 报 `canary_zero` 才会真
保留这个标签。

## 两侧 ack 状态

- [x] **Seth-side ack**(本文件)—— ship 2026-09-20 (S-390)
- [ ] **Mac-side ack** —— 等 Min-C 改 `Shadow/.../MacErrorEnvelope.py` + bump
      `SCHEMA_VERSION`。本文件是契约参考,**改了这里必须同时改那边**,反过来亦然。
"""
from __future__ import annotations

#: Mac-side 真源在 Shadow/,这里镜像一份。**两侧必须一致**。
#: Mac-side 真源:`Shadow/cometcloud-local/MacErrorEnvelope.py:76-89`
#:
#: 每加一个值必须同时:
#: 1. 在这里加(本文件)
#: 2. 在 MacErrorEnvelope.py 的 FAILED_STEP_VALUES 里加
#: 3. 在 MacErrorEnvelope.py 的 SCHEMA_VERSION 上 bump(消费方按版本迁移)
#: 4. 在 MINIMAX_SYNC §S-390 P2 标 ack
FAILED_STEP_VALUES: frozenset = frozenset({
    "launchd_pickup",         # launchd failed to start the script
    "import_or_env",          # import error / missing env var
    "config_load",            # config.py / paths.py failure
    "data_fetch",             # upstream data not reachable
    "data_parse",             # upstream data wrong shape
    "sqlite_write",           # local SQLite write failed
    "supabase_push",          # Railway / Supabase POST failed
    "redis_cache",            # redis read/write failed
    "breaker_open",           # circuit breaker tripped, job aborted by design
    "validation",             # strategy discipline / paper gate / OOS check failed
    # 🆕 S-390 P2:canary 行写 0 行 —— A lane active_monitor 新增。
    # MacErrorEnvelope 的 silent normalisation 会把它折叠进 `unknown`,
    # 所以显式加入词表保留诊断信息。
    "canary_zero",
    "unknown",                # caught an exception we don't classify yet
    None,                     # ok=True — no failure
})


def is_known_failed_step(step: object) -> bool:
    """`step` 是不是 `FAILED_STEP_VALUES` 里的一员。**未识别不算失败** —
    MacErrorEnvelope 把未识别静默归一为 `unknown`,本函数只是查询词表,
    归一化由调用方决定。
    """
    return step in FAILED_STEP_VALUES
