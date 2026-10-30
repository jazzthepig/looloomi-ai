"""`X-Internal-Token` 校验 —— 全仓库唯一的一处(S-371 A-1;设计 `docs/AUTH_DESIGN.md`,2026-09-17 冻结,2026-10-30 实施)。

## 为什么只能有一处

收敛前:45 处比较、17 个文件、10 种写法;12 个 router 在 **import 期**把 `INTERNAL_TOKEN` 读进常量,`main.py` 在**请求期**读 environ。
于是改掉 Railway 的值之后:旧 token 打 router 仍 200、打 main.py 已 401 —— **同一个凭据一半有效一半无效**,从外面看「已轮换」
和「轮换了一半」长得一模一样(S-371)。Railway 10-21 被入侵、环境变量须全部轮换,而轮换在这个形状下不是原子的。

## 契约(`tests/test_internal_token_contract.py` 是判据,不是文档)

- `require_internal_token(given) -> str`:**每次调用**读 environ;常数时间比较;通过 ⇒ 返回命中的 lane 名(可归因);
  失败 ⇒ `HTTPException(401)`。空 header、没配 env 一律拒绝 —— **不能**因为没配就放行(S-262)。
- 多 token(A-2):`INTERNAL_TOKEN` = seth / 主;`INTERNAL_TOKEN_A` / `_B` / `_C` / `_SETH` = 各 lane。命中哪把就返回哪条 lane,
  泄露之后能归因、能局部作废。没配的 lane 不存在,打进来就是 401。
- 端点改成一行 `require_internal_token(x_internal_token)`;要 lane 名就接返回值。**不要**再写 `if token != …`。
"""
from __future__ import annotations

import hmac
import os
from typing import Optional

from fastapi import HTTPException

#: lane 名 → 环境变量名。主 token 排第一:大多数调用方(Mac 推送、脚本)用的是它。
LANES: tuple[tuple[str, str], ...] = (
    ("seth", "INTERNAL_TOKEN"),
    ("lane-a", "INTERNAL_TOKEN_A"),
    ("lane-b", "INTERNAL_TOKEN_B"),
    ("lane-c", "INTERNAL_TOKEN_C"),
    ("seth-lane", "INTERNAL_TOKEN_SETH"),
)


def require_internal_token(given: Optional[str]) -> str:
    """校验 `X-Internal-Token`。通过 ⇒ 返回 lane 名;否则 401。environ 在**这里**读,每次都读。"""
    if not given:
        raise HTTPException(status_code=401, detail="Invalid token")
    g = str(given).encode()
    for lane, env_name in LANES:
        expected = os.environ.get(env_name, "")
        if expected and hmac.compare_digest(g, expected.encode()):
            return lane
    raise HTTPException(status_code=401, detail="Invalid token")


def internal_token_configured() -> bool:
    """有没有任何一把 token 配着(给健康检查 / 启动自检用;不返回值本身)。"""
    return any(os.environ.get(env_name) for _, env_name in LANES)
