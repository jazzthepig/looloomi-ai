# AUTH_DESIGN.md — `INTERNAL_TOKEN` 边界的第一性原理设计

> **Status:** 冻结的设计(2026-09-17,Seth/Cowork lane,Jazz 拍板)。
> 解冻时按此实施 —— 不要再重新想一遍。
> 关联:`PROJECT_STATE.md` OPEN RISK **#0b** · `tests/test_internal_token_contract.py` · S-371 · A-1 / A-2

---

## 0 · 一句话

**所有 auth 知识集中在一个函数里;token 永不进源码;每次请求重新读 env,而不是 import 时缓存一次。**
端点不动 = 旋转、加 lane、加 rate limit、加审计、加 HSM,只要动这一个函数(或它的包装器)。

---

## 1 · 这不是「整理代码」

| 现状(36 处独立比较) | 这条设计要还的债 |
|---|---|
| Token 在源码里**间接**出现(env.get + 模块常量 = 实际上 freeze)| 轮换半生效(S-371 实测)|
| 36 份比较逻辑 = 36 种写法 | 加 lane / 加策略 = 改 N 处 |
| 比对用 `!=` | 时间侧信道(token 长度可被放大)|
| 没有 lane 归属 | 泄露之后无法定位、无法局部撤销 |
| 端点自己处理 401 | 报错形状不一致,audit log 没法对齐 |
| 端点 `Depends(...)` / 直接调 两种风格并存 | 难以做统一的中间件层 |

这就是「之后很难调整」的具体内容。第一性原理反过来:

> **第一性原理 #1:身份是一个断言,不是一个门。** 边界守的是「谁在调」,不是「他们能不能调」—— 之后所有的策略(rate limit / audit / 配额 / region)都依赖「调用方是可识别的」这个事实。

> **第一性原理 #2:复杂度待在边界,不在端点。** 端点是业务逻辑,边界是身份;一旦身份说清,业务可以独立演化。

> **第一性原理 #3:token 不进源码,源码描述 token 的容器。** 容器换(token 换、装 token 的地方换 Vault 换 HSM)是配置变化,不该触发代码 redeploy。

---

## 2 · 设计

### 2.1 单点收口

```python
# src/api/auth_internal.py
from __future__ import annotations
import os
import secrets
from typing import Optional
from fastapi import Header, HTTPException, status

def _lane_for(token_value: str) -> Optional[str]:
    """读 env INTERNAL_TOKEN_* 系列,找到匹配 token,返回 lane 名(小写)或 None。"""
    prefix = "INTERNAL_TOKEN_"
    for k, v in os.environ.items():
        if not k.startswith(prefix) or not v:
            continue
        if secrets.compare_digest(token_value, v):
            return k[len(prefix):].lower() or "default"
    return None

def require_internal_token(
    x_internal_token: Optional[str] = Header(None, alias="X-Internal-Token"),
) -> str:
    """调用方身份断言 —— 返回 lane 名(用于审计 / rate limit / 配额)。

    关键:
      ① **每次调用读 env** —— 旋转不需要 restart
      ② **常量时间比对** —— `secrets.compare_digest`,不暴露长度
      ③ **单点收口** —— 36 处都调这一个函数,改一处生效 36 处
      ④ **空 header / 没配 token 一律拒绝** —— 不因为 env 没配就放行
      ⑤ **返回值是 lane 名** —— 端点决定怎么用(目前先 print/log,以后接 rate limit)
    """
    if not x_internal_token:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "missing internal token")

    lane = _lane_for(x_internal_token)
    if lane is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "internal token mismatch")
    return lane
```

### 2.2 FastAPI 接入两种风格,选一种就用到底

**风格 A · Depends(默认推荐)**
```python
from fastapi import Depends
from src.api.auth_internal import require_internal_token

@router.post("/internal/backfill-cg-pro")
async def backfill(lane: str = Depends(require_internal_token)):
    ...
```

**风格 B · 显式调用(用于需要条件短路的端点)**
```python
from src.api.auth_internal import require_internal_token

@router.post("/internal/...")
async def endpoint(request: Request):
    lane = require_internal_token(request.headers.get("X-Internal-Token"))
    ...
```

**两条规则:**
- 同一端点内风格一致(不混)
- 项目内尽量风格 A;只有特殊场景(比如 Depends 与别的注入冲突)才用风格 B
- 这一约束由 lint / review 守,**不是结构限制**

### 2.3 不存在的东西(为什么)

| 不做 | 原因 |
|---|---|
| 不写 middleware 拦截所有请求 | 跨路由的强制中间件会让端点看不见 lane(难以做 per-lane policy);依赖注入把 lane 当参数流过去,更显式 |
| 不放配置文件 | 配置应该集中在 Railway env,文件配置会变成第二个 source-of-truth |
| 不做 OAuth / JWT / mTLS 现在 | token 轮换能力之外的事是另议;JWT 也有 key rotation 自己的半生效坑 |
| 不在响应 body 里回 lane 名 | leak 风险 + 没有调用方需要这样用 |

---

## 3 · 调整性轴线 (Adaptability Axes)

每条轴线**只改一个文件**(`auth_internal.py`)或只改 env —— 端点不动。

| 轴 | 现在怎么调整 | 之后要更复杂时 |
|---|---|---|
| **token 轮换** | 改 Railway env var,下一个请求用新值,零重启 | 引入 Vault / HSM,**只改 `_lane_for`** |
| **加 lane** | 加 env `INTERNAL_TOKEN_<NAME>=<value>`,零代码 | 同上 |
| **撤 lane** | 删 env var,该 lane 立刻 401,**不影响别的 lane** | 同上 |
| **per-lane rate limit** | 同一函数套一层 `@rate_limit_per_lane` 装饰器 | 同上 |
| **审计** | 函数里加一行 `audit_log(lane, endpoint)`,端点不用改 | 换 sink 时也只动函数 |
| **结构化日志 / 指标** | 返回值已经是 lane 名;调用方 `lane` 参数已可用 | Prometheus metrics 同理 |
| **多 region** | 同一函数;再加一个 region 时**只动 env** | 引入 proxy 时只动函数 |
| **mTLS / OAuth / JWT** | 抽象:`def _identity(req) -> str`,这一层存在,只换实现 | 调用方零变更 |
| **测试 bypass** | `app.dependency_overrides[require_internal_token] = lambda: "test"` | 标准 FastAPI 模式,无需特殊处理 |
| **轮换原子性** | 函数读 env 在调用时,**无 import-time cache** | — |

**对照:**当前 36 处独立实现的「调整性」为零。
**任何**一个变化(轮换、加 lane、换 HSM、加 audit)都要改 N 处文件 + 一次 redeploy + 一段时间的半轮换状态。

---

## 4 · 迁移路径(A-1 / A-2 / 轮换)

```
  ┌──────────────────────────────────────────────────────────────────┐
  │  Phase 0(今天,冻结中)                                            │
  │   • 这份设计落到 docs/AUTH_DESIGN.md                             │
  │   • paid-first 在本地 hold(它经过的 ohlcv.py 落 36 处之一)        │
  │   • 不往 /internal/* 加新写入口(扩大要收拾的面积)                  │
  └──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Phase 1 · A-1 · 收敛 36→1                                       │
  │   • 写 src/api/auth_internal.py(本 doc §2.1)                    │
  │   • 36 处 endpoint 全部改成 require_internal_token               │
  │   • tests/test_internal_token_contract.py 进 scripts/preflight  │
  │   VERIFY: preflight 全绿 + 该测试全绿                             │
  │                                                                  │
  │   解冻信号:OPEN RISK #0b 解除条件 ①(开发冲刺结束,Jazz 拍)        │
  └──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Phase 2 · key rotation(只在 A-1 收敛之后可以做)                  │
  │   • Jazz 生成新的 INTERNAL_TOKEN 值(经手唯一,不经 lane / 不经我)│
  │   • 改 Railway env 当前值 → 旧值立即 401(下一个请求)             │
  │   • 不需要 restart,不需要部署,无 half-state                      │
  │                                                                  │
  │   解冻信号:A-1 全绿                                              │
  └──────────────────────────────────────────────────────────────────┘
                              │
                              ▼
  ┌──────────────────────────────────────────────────────────────────┐
  │  Phase 3 · A-2 · 拆 lane token(归属 + 局部撤销)                    │
  │   • 加 INTERNAL_TOKEN_MAIN / _MAC / _DEV 等 lane token           │
  │   • 旧共享 token 作废                                            │
  │   • 调用方按 lane 整改(caller 自行签发 lane 身份)                │
  │   • 审计首次落地                                                  │
  │                                                                  │
  │   VERIFY: 单 token 走 A-1;多 token 走 test_per_lane_tokens_  那个│
  │          参数化测试                                               │
  └──────────────────────────────────────────────────────────────────┘
```

---

## 5 · 关键判断 / 写给未来再读这份设计的人

1. **「单点收口」不是「整洁偏好」,是「调整能力」的可计算前提**。N 个独立实现的调整成本 ≈ N · 单点实现的调整成本。这就是 36 的成本。
2. **「env 读每次重新读」不是性能问题**,是**正确性问题**:64 字节的字符串比对,env 读一次 100ns 量级,完全可以忽略;import-time freeze 才是真问题。
3. **`secrets.compare_digest` 不是装饰**,是 **timing-attack 防护**。`!=` 在 Go / Rust 这层语言都不强制常量时间,Python 也一样。
4. **lane 名作返回值是「身份即数据」**,不是「多 token 的副产品」。一旦返回值是 lane,rate limit / 配额 / 审计 / region / 告警 全部可以挂同一根线,端点零变更。
5. **「不写 middleware」** 是因为 middleware 把 lane 藏起来,端点看不见 —— 而我们要的是「端点看得见」「policy 可挂」。Depends 是这两个需求的最简实现。
6. **A-1 必须在轮换之前**(判据已经写过)。今天轮换是破产的:旧 token 在 router 还生效。**不接受在 A-1 完成之前尝试轮换**。OPEN RISK #0b 的解除条件已写。
7. **新 INTERNAL_TOKEN 真值只经 Jazz 一人**。派活给 agent 跑 A-1 时,**agent 只写引用,看到值的只能是 Jazz 自己**。把凭据处理派给 agent = 把泄露路径当成修复路径。

---

## 6 · 不在范围内(写这条是为了挡反复)

- OAuth / JWT / mTLS —— token 换装的下一层议题
- per-lane rate limit 真正落地 —— 之后再写
- 审计日志落 sink(Postgres / S3 / Loki)—— A-2 之后
- token TTL / 短时 token —— token 旋转的另一种实现,A-2 后再议
- paid-first 的 4 处改动 —— 跟本设计正交,只在 A-1 收敛后才能 push

---

## 7 · 等 Jazz 拍的事

| 项 | 选择 |
|---|---|
| A-1 是否在 paid-first 之前做(建议:是,但不一定本 session)| |
| A-1 实施时,保留旧 `_INTERNAL_TOKEN = ...` 常量为 `DeprecationWarning` 多久才删(建议:一个 sprint)| |
| 是否要把 paid-first 4 处改动跟 A-1 合并成一个 PR(建议:**合并**,因为 paid-first 经过的 ohlcv.py 端点会被 A-1 触碰,拆 commit 会浪费一轮 preflight)| |
| A-1 期间 deploy 是否 canary(建议:不,内部端点,可全切)| |

拍完之后,把 A/B 派活解除冻结,MINIMAX_SYNC §A-1 段立刻可读、可执行。
