"""文字空间(VDB 最后一块,Jazz 11-05「use minimax」)—— 新闻与事件标题 → MiniMax 嵌入 → `text_vectors`(pgvector)。

## 为什么这样

其余五个空间(资产 / 市场态 / 策略 / 实体 / 时间窗 / 结果)都是数字向量;新闻与事件只有文字。嵌入走 MiniMax
(`embo-01`,和 agent 臂、新闻帖同一把 key,`LLM_BASE_URL` + `/embeddings`),不占本地 Qwen(Jazz:Qwen 在做别的)。
库里存 `type=db` 的向量;查询时用 `type=query` 嵌入问题,`text_vectors_nearest` 按余弦距离取最近的。

## 纪律

- 只嵌已落表的文字(`feed_items` 标题 + 摘要前 400 字;`events` 的 kind + 标题),不改原文、不做摘要。
- 每轮最多 `MAX_PER_RUN` 条、每批 `BATCH` 条;模型不通 ⇒ refused + 原因(不写半截向量)。
- 维数写进 `dim`;换模型 ⇒ 新的 (source, item_id, model) 行,旧的不覆盖。

判活:`select source, model, dim, count(*) from text_vectors group by 1, 2, 3`;待嵌数看视图 `text_vectors_todo`。
"""
from __future__ import annotations

import json
import os
from typing import Any, Optional

TABLE = "text_vectors"
WRITES_TABLES = (TABLE,)
WRITES_COLUMNS = {TABLE: ("source", "item_id", "model", "dim", "embedding", "text", "published_at")}
TODO_VIEW = "text_vectors_todo"
NEAREST_RPC = "text_vectors_nearest"
LOOP_NAME = "_text_vectors_loop"
MODEL = (os.environ.get("TEXT_EMBED_MODEL") or "embo-01").strip()
BATCH = 16
MAX_PER_RUN = 512
PAUSE_S = 4.0                # 11-05 15:44 第一轮:base_resp 1002「rate limit exceeded(RPM)」—— 每批之间停一下
RETRY_WAITS = (20.0, 60.0)   # 撞到 1002 再等这么久重试;还不行 ⇒ refused,下一轮接着嵌
TIMEOUT_S = 60.0
TEXT_MAX = 600


def text_for(row: dict) -> Optional[str]:
    """纯函数。待嵌行 {source, title, body, kind} → 要嵌的文字;没有标题 ⇒ None。"""
    title = " ".join(str(row.get("title") or "").split())
    if not title:
        return None
    kind = str(row.get("kind") or "").strip()
    body = " ".join(str(row.get("body") or "").split())[:400]
    t = (f"[{kind}] " if kind else "") + title + (f" — {body}" if body else "")
    return t[:TEXT_MAX]


def parse_vectors(data: Any, n: int) -> tuple[Optional[list[list[float]]], Optional[str]]:
    """纯函数。MiniMax(`vectors` + `base_resp`)或 OpenAI 形状(`data[].embedding`)→ (向量, 错误)。条数不等 / 非数 ⇒ 错误。"""
    if not isinstance(data, dict):
        return None, "回的不是 JSON 对象"
    br = data.get("base_resp") or {}
    if br and int(br.get("status_code") or 0) != 0:
        return None, f"base_resp {br.get('status_code')}: {str(br.get('status_msg'))[:160]}"
    vecs = data.get("vectors")
    if vecs is None and isinstance(data.get("data"), list):
        vecs = [d.get("embedding") for d in sorted(data["data"], key=lambda d: d.get("index", 0))]
    if not isinstance(vecs, list) or len(vecs) != n:
        return None, f"向量条数 {len(vecs) if isinstance(vecs, list) else '—'} ≠ 文字条数 {n}"
    out = []
    for v in vecs:
        if not isinstance(v, list) or not v or not all(isinstance(x, (int, float)) and x == x for x in v):
            return None, "向量里有非数"
        out.append([float(x) for x in v])
    if len({len(v) for v in out}) != 1:
        return None, "同一批向量维数不一"
    return out, None


def vec_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def rate_limited(err: Optional[str]) -> bool:
    return bool(err) and ("1002" in err or "rate limit" in err.lower() or "HTTP 429" in err)


async def embed(texts: list[str], kind: str = "db", waits: tuple[float, ...] = RETRY_WAITS) -> tuple[Optional[list[list[float]]], Optional[str]]:
    """MiniMax 嵌入,撞到频率限制按 `waits` 重试。"""
    import asyncio
    vecs, err = await _embed_once(texts, kind)
    for w in waits:
        if not rate_limited(err):
            break
        await asyncio.sleep(w)
        vecs, err = await _embed_once(texts, kind)
    return vecs, err


async def _embed_once(texts: list[str], kind: str = "db") -> tuple[Optional[list[list[float]]], Optional[str]]:
    """MiniMax 嵌入一次。kind = db(入库)/ query(查询)。"""
    import httpx

    from src.data.narrative import llm_narrator as llm
    if not llm._BASE:
        return None, "LLM_BASE_URL 未配"
    url = f"{llm._BASE}/embeddings"
    gid = (os.environ.get("MINIMAX_GROUP_ID") or "").strip()
    params = {"GroupId": gid} if gid else None
    headers = {"Content-Type": "application/json", **({"Authorization": f"Bearer {llm._KEY}"} if llm._KEY else {})}
    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_S) as cli:
            r = await cli.post(url, params=params, headers=headers, content=json.dumps({"model": MODEL, "texts": texts, "type": kind}))
    except Exception as e:                                                # noqa: BLE001
        return None, f"{type(e).__name__}: {str(e)[:160]}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:160]}"
    try:
        data = r.json()
    except ValueError:
        return None, f"回的不是 JSON:{r.text[:120]}"
    return parse_vectors(data, len(texts))


async def run_once(max_items: int = MAX_PER_RUN) -> dict[str, Any]:
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    todo = await _read_all(TODO_VIEW, {"select": "source,item_id,title,body,kind,published_at", "order": "published_at.desc.nullslast",
                                       "limit": str(max_items)})
    items = [(r, text_for(r)) for r in todo]
    items = [(r, t) for r, t in items if t]
    if not items:
        return {"ok": True, "status": "skipped", "why": "没有待嵌的文字"}
    written, dim = 0, None
    for i in range(0, len(items), BATCH):
        chunk = items[i:i + BATCH]
        vecs, err = await embed([t for _, t in chunk], "db")
        if err:
            return {"ok": False, "refused": True, "status": "refused", "written": written,
                    "why": f"嵌入失败(已写 {written} 条):{err}"}
        dim = len(vecs[0])
        rows = [{"source": r["source"], "item_id": r["item_id"], "model": MODEL, "dim": dim, "embedding": vec_literal(v),
                 "text": t, "published_at": r.get("published_at")} for (r, t), v in zip(chunk, vecs)]
        w = await supabase_upsert_table(TABLE, rows, on_conflict="source,item_id,model")
        if not w:
            return {"ok": False, "written": written, "why": f"写 {TABLE} 失败:{(getattr(w, 'why', '') or '')[:200]}"}
        written += len(rows)
        if i + BATCH < len(items):
            import asyncio
            await asyncio.sleep(PAUSE_S)
    return {"ok": True, "written": written, "dim": dim, "model": MODEL, "why": f"嵌了 {written} 条({MODEL},{dim} 维)"}


async def nearest(q: str, k: int = 10, source: Optional[str] = None) -> dict[str, Any]:
    """问题 → 最近的 k 条新闻 / 事件(余弦距离)。"""
    from src.api.store import supabase_rpc
    vecs, err = await embed([q[:TEXT_MAX]], "query")
    if err:
        return {"ok": False, "why": err}
    rows = await supabase_rpc(NEAREST_RPC, {"q": vec_literal(vecs[0]), "k": int(max(1, min(k, 50))), "src": source, "mdl": MODEL})
    return {"ok": rows is not None, "q": q, "model": MODEL, "rows": rows or []}
