"""前向记录锚定 —— 每天把所有前向账本的行做哈希,挂到比特币时间戳上(T-073 / S-519)。

## 为什么

「可验证的前向记录就是产品」,而我们的表在设计上会被改写:回放与配置层每轮整条重算(S-514 当天就按新规则
重写了 10-02 以来的配置历史)。外人没法证明我们没改过。这个模块不阻止改写 —— 它让改写**看得见**:
每天把前一天的前向行固定成一个摘要,挂到 OpenTimestamps 的公共日历上(几小时内进比特币区块,免费、无 key)。
之后任何人拿 payload 重算摘要、再用 `ots verify` 对比特币核对时间,就知道那一天的记录在那一刻就是这样。

## 规则

- 锚**只追加不覆盖**:某天锚过就不再锚,即便表后来变了 —— 变了正是要暴露的东西(端点现场重算、标出不一致)。
- payload = 固定顺序的规范 JSON(键排序、紧凑分隔);去掉 computed_at / updated_at(重算时间不是记录内容)。
- 只锚**前向**行:各账本的起点之后;回放臂(*_replay)不锚。
- .ots 文件 = OpenTimestamps 文件头 + SHA-256 操作 + 摘要 + 日历返回的时间戳;`ots upgrade` 补全比特币证明。

## 判活判据(规则 5b ②)

    select max(d) from forward_anchor_daily;   -- UTC 09:00 后应 = 昨天
"""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

TABLE = "forward_anchor_daily"
WRITES_TABLES = (TABLE,)
CODE_REF = "T-073 anchor v1"
CALENDARS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org",
             "https://finney.calendar.eternitywall.com")
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
OTS_VERSION = b"\x01"
OTS_SHA256 = b"\x08"
DROP = {"computed_at", "updated_at", "recorded_at"}

#: (表, 额外过滤, 排序键)。只锚前向:回放臂不进。
SOURCES: tuple[tuple[str, dict, str], ...] = (
    ("core_cap_daily", {}, "arm"),
    ("cis_tilt_daily", {}, "arm"),
    ("beta_plus_daily", {}, "arm"),
    ("tokenization_tilt_daily", {}, "arm"),
    ("multiplier_daily", {"arm": "eq.mult_v1"}, "arm"),
    ("portfolio_layer_daily", {"arm": "eq.pl_v2"}, "arm"),
    ("core_variants_daily", {}, "arm"),
    ("meta_allocator_daily", {}, "arm"),
    ("allocation_daily", {}, "book"),
    ("allocation_nav_daily", {}, "d"),
    ("exploration_ideas", {}, "id"),
)


def canonical(payload: dict) -> bytes:
    """纯函数。键排序、紧凑分隔、UTF-8 —— 同一份内容永远同一串字节。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def clean_rows(rows: list[dict], key: str) -> list[dict]:
    """纯函数。去掉重算时间列,按排序键排好。"""
    out = [{k: v for k, v in r.items() if k not in DROP} for r in rows]
    return sorted(out, key=lambda r: str(r.get(key)))


def digest_of(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def ots_file(digest_hex: str, calendar_response: bytes) -> bytes:
    """纯函数。OpenTimestamps 分离式证明文件:文件头 + 版本 + SHA-256 操作 + 摘要 + 日历给的时间戳。"""
    return OTS_MAGIC + OTS_VERSION + OTS_SHA256 + bytes.fromhex(digest_hex) + calendar_response


def waiting_for(prev: dict, cur: dict) -> list[str]:
    """纯函数。前一天有行、这一天没有的来源。"""
    return sorted(t for t, rows in prev["sources"].items() if rows and not cur["sources"].get(t))


async def build_payload(d: date) -> dict:
    from src.data.style.header import _read_all
    sources: dict[str, list] = {}
    for table, flt, key in SOURCES:
        rows = await _read_all(table, {"select": "*", "d": f"eq.{d.isoformat()}", **flt})
        sources[table] = clean_rows(rows, key)
    return {"d": d.isoformat(), "schema": CODE_REF, "sources": sources}


async def submit(digest_hex: str) -> dict[str, str]:
    """把摘要交给每个日历;返回 {日历: .ots 的 base64}。一个都没成功 ⇒ 抛错(不写一个没锚上的锚)。"""
    import httpx
    out, errs = {}, {}
    async with httpx.AsyncClient(timeout=20) as c:
        for cal in CALENDARS:
            try:
                r = await c.post(f"{cal}/digest", content=bytes.fromhex(digest_hex),
                                 headers={"Accept": "application/vnd.opentimestamps.v1",
                                          "User-Agent": "cometcloud-anchor"})
                if r.status_code == 200 and r.content:
                    out[cal] = base64.b64encode(ots_file(digest_hex, r.content)).decode()
                else:
                    errs[cal] = f"HTTP {r.status_code}"
            except Exception as e:                          # noqa: BLE001
                errs[cal] = f"{type(e).__name__}: {str(e)[:60]}"
    if not out:
        raise RuntimeError(f"所有日历都没收下:{errs}")
    return out


async def run_once(today: Optional[date] = None) -> dict[str, Any]:
    """锚昨天(UTC)。已锚过 ⇒ 不动(只追加);前向行一行都没有 ⇒ 拒绝(不锚空集)。"""
    from src.api.store import supabase_upsert_table
    from src.data.style.header import _read_all
    today = today or datetime.now(timezone.utc).date()
    d = today - timedelta(days=1)
    have = await _read_all(TABLE, {"select": "d", "d": f"eq.{d.isoformat()}"})
    if have:
        return {"ok": True, "refused": False, "written": 0, "reason": f"{d} 已锚过 —— 只追加不覆盖"}
    payload = await build_payload(d)
    n = sum(len(v) for v in payload["sources"].values())
    if n == 0:
        return {"ok": False, "refused": True, "written": 0, "reason": f"{d} 的前向行一行都没有 —— 不锚空集"}
    # 锚只追加:锚早了就永远少几本账。前一天有行、这一天还没有的账本 = 还没记完 ⇒ 等;
    # 等到 UTC 22 点还没齐就照锚,并把缺的写进 payload(缺本身也是记录)。
    prev = await build_payload(d - timedelta(days=1))
    missing = waiting_for(prev, payload)
    now = datetime.now(timezone.utc)
    if missing and now.hour < 22:
        return {"ok": True, "refused": True, "written": 0,
                "reason": f"{d} 还在等 {missing} 记完 —— UTC 22 点前不锚"}
    if missing:
        payload["missing_at_anchor_time"] = missing
    dg = digest_of(payload)
    proofs = await submit(dg)
    row = {"d": d.isoformat(), "digest": dg, "payload": payload, "n_rows": n, "ots": proofs,
           "submitted_at": datetime.now(timezone.utc).isoformat(), "code_ref": CODE_REF}
    res = await supabase_upsert_table(TABLE, [row], on_conflict="d")
    if not res.ok:
        return {"ok": False, "refused": False, "written": 0, "reason": f"写入失败:{res.why}"}
    return {"ok": True, "refused": False, "written": 1, "reason": f"{d} 锚定 {n} 行 → {dg[:16]}… ({len(proofs)} 个日历)"}


async def verify_now(d: date) -> dict[str, Any]:
    """现场重算:当天的表与锚定时是否一致。不一致 = 那一天的前向记录后来被改过。"""
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "d,digest,n_rows,ots,submitted_at", "d": f"eq.{d.isoformat()}"})
    if not rows:
        return {"d": d.isoformat(), "anchored": False}
    a = rows[0]
    now_digest = digest_of(await build_payload(d))
    return {"d": d.isoformat(), "anchored": True, "digest": a["digest"], "submitted_at": a["submitted_at"],
            "n_rows": a["n_rows"], "calendars": sorted((a.get("ots") or {}).keys()),
            "matches_current_tables": now_digest == a["digest"], "current_digest": now_digest}
