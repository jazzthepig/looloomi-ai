"""研究数据的只读入口:每个读的人都有名字,每次读都留一行(Jazz 11-13「不能 anonymous,必须 register 或者留痕」)。

## 为什么

10-20 那次 service_role 泄露之后,lane 改成只拿公开 key(Postgres 角色 anon)、对一张名单上的表只读 ——
权限是收小了,但**所有 lane 共用一把匿名 key**:谁读了什么分不出来,漏了也只能整把换。11-13 实测匿名可读的对象有 149 个。
这里是替换它的那条路:

    lane ──(自己的 token)──> /lane/rest/v1/<表>?<PostgREST 查询串>  ──(服务端 key)──> Supabase
                                   │
                                   └── data_access_log:谁、哪张表、什么查询、几行、多久

- **路径与查询串跟 PostgREST 一模一样** ⇒ lane 的脚本不用改,只换两个环境变量(地址指到这里、key 换成自己的 token)。
- **只有 GET / HEAD,只有名单上的对象**(`lane_read_allowlist.json`,从库里当天的匿名可读清单生成,去掉了不是研究数据的两张)。
- **token 一人一把**:环境变量 `LANE_READ_TOKENS = "lane-a:<token>,lane-b:<token>,…"`(Jazz 生成、Jazz 放;代码与日志里都不出现 token)。
  没配这个变量 ⇒ 整个入口 401(不是放行)。
- 以后给外部 agent / 合作方开读权限,用同一套:再加一个名字。

## 切换(三步;做完第三步才算「不能匿名」)

1. Jazz 在 Railway 配 `LANE_READ_TOKENS`,把各自的 token 放进各 lane 的环境(地址改成 `<本服务>/lane`);
2. 看 `data_access_log` 一整天:三条 lane 都在这里读、Supabase 的边缘日志里不再有匿名 GET;
3. 迁移:删掉全部 `to anon` 的只读策略、收回匿名对视图的 SELECT。

判活:`select reader, count(*), max(at) from data_access_log where at > now() - interval '1 day' group by 1`。
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request, Response

router = APIRouter()

TABLE = "data_access_log"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("reader", "obj", "query", "status", "n_rows", "ms")}
ENV = "LANE_READ_TOKENS"
MIN_TOKEN_LEN = 24
PASS_REQUEST_HEADERS = ("range", "range-unit", "prefer", "accept")
PASS_RESPONSE_HEADERS = ("content-range", "content-type", "preference-applied")
ALLOW = frozenset(json.loads((Path(__file__).resolve().parents[1] / "lane_read_allowlist.json").read_text(encoding="utf-8"))["objects"])


def readers(raw: Optional[str] = None) -> dict[str, str]:
    """纯函数。`"lane-a:tok,lane-b:tok"` → {token: 名字};太短的 token、没有名字的项一律不认。"""
    out: dict[str, str] = {}
    for item in (raw if raw is not None else os.environ.get(ENV, "")).split(","):
        name, _, tok = item.strip().partition(":")
        name, tok = name.strip(), tok.strip()
        if name and len(tok) >= MIN_TOKEN_LEN:
            out[tok] = name
    return out


def who(apikey: Optional[str], authorization: Optional[str], table: Optional[dict[str, str]] = None) -> Optional[str]:
    """纯函数。请求带来的凭证(`apikey` 头或 `Authorization: Bearer`)是哪个读者的;逐个做等时比较,对不上 ⇒ None。"""
    given = [x for x in ((apikey or "").strip(), (authorization or "").strip().removeprefix("Bearer ").strip()) if x]
    for tok, name in (table if table is not None else readers()).items():
        if any(hmac.compare_digest(tok, g) for g in given):
            return name
    return None


def rows_of(status: int, content_range: Optional[str], body: bytes) -> Optional[int]:
    """纯函数。PostgREST 的 Content-Range(`0-999/*`)→ 行数;没有就不猜(None),空集(`*/0`)是 0。"""
    if status >= 300:
        return None
    cr = (content_range or "").split("/")[0]
    if cr == "*":
        return 0
    lo, _, hi = cr.partition("-")
    return int(hi) - int(lo) + 1 if lo.isdigit() and hi.isdigit() else None


async def _upstream(obj: str, query: list[tuple[str, str]], headers: dict[str, str], method: str) -> tuple[int, bytes, dict[str, str]]:
    """把查询原样交给 PostgREST(服务端 key)。单独成函数是为了测试里能换掉它。"""
    import httpx
    from src.api.store import _SB_KEY, _SB_URL
    if not _SB_URL or not _SB_KEY:
        raise HTTPException(503, "后端没配 Supabase")
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.request(method, f"{_SB_URL}/rest/v1/{obj}", params=query,
                            headers={**headers, "apikey": _SB_KEY, "Authorization": f"Bearer {_SB_KEY}"})
    return r.status_code, r.content, {k: v for k, v in r.headers.items() if k.lower() in PASS_RESPONSE_HEADERS}


async def _log(row: dict[str, Any]) -> None:
    try:
        from src.api.store import supabase_insert_table
        await supabase_insert_table(TABLE, [row])
    except Exception:                                            # noqa: BLE001 —— 记不上日志不该让读失败;判活看的是这张表有没有行
        pass


@router.api_route("/lane/rest/v1/{obj}", methods=["GET", "HEAD"])
async def lane_read(obj: str, request: Request) -> Response:
    reader = who(request.headers.get("apikey"), request.headers.get("authorization"))
    if reader is None:
        raise HTTPException(401, "需要读者自己的 token(apikey 头或 Authorization: Bearer)")
    query = list(request.query_params.multi_items())
    qs = "&".join(f"{k}={v}" for k, v in query)[:500]
    t0 = time.monotonic()
    if obj not in ALLOW:
        asyncio.create_task(_log({"reader": reader, "obj": obj[:120], "query": qs, "status": 403, "n_rows": None, "ms": 0}))
        raise HTTPException(403, f"{obj} 不在只读名单上")
    status, body, hdrs = await _upstream(obj, query, {k: v for k, v in request.headers.items() if k.lower() in PASS_REQUEST_HEADERS},
                                         request.method)
    asyncio.create_task(_log({"reader": reader, "obj": obj, "query": qs, "status": status,
                              "n_rows": rows_of(status, hdrs.get("content-range") or hdrs.get("Content-Range"), body),
                              "ms": int((time.monotonic() - t0) * 1000)}))
    return Response(content=body, status_code=status, headers=hdrs)
