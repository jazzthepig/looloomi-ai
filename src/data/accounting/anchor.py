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
  (S-560:v1 实际没按起点过滤 —— core_variants / feature_arms 的回放行进了锚,multiplier / portfolio_layer
  只锚了 mult_v1 / pl_v2,新臂没进。v2 起按每行 inception 过滤、所有臂都锚。)
- **锚「今天 − 2」那一天**(S-560,v2):那一天的前向行刚被 forward_lock 冻结,之后不会再变;
  锚昨天的话,当天收盘还可能被修订,锚到的是初值、表里留的是修订值。
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
CODE_REF = "T-073 anchor v2"
CALENDARS = ("https://a.pool.opentimestamps.org", "https://b.pool.opentimestamps.org",
             "https://finney.calendar.eternitywall.com")
OTS_MAGIC = b"\x00OpenTimestamps\x00\x00Proof\x00\xbf\x89\xe2\xe8\x84\xe8\x92\x94"
OTS_VERSION = b"\x01"
OTS_SHA256 = b"\x08"
DROP = {"computed_at", "updated_at", "recorded_at", "written_at"}

#: (表, 额外过滤, 排序键)。只锚前向:回放行(d < inception)在 build_payload 里按行过滤掉。
KEYS = {}  # 下面按 SOURCES 填:表 → 一天之内区分行的键
SOURCES: tuple[tuple[str, dict, Any], ...] = (
    ("core_cap_daily", {}, "arm"),
    ("cis_tilt_daily", {}, "arm"),
    ("beta_plus_daily", {}, "arm"),
    ("tokenization_tilt_daily", {}, "arm"),
    ("multiplier_daily", {}, "arm"),
    ("portfolio_layer_daily", {}, "arm"),
    ("core_variants_daily", {}, "arm"),
    ("meta_allocator_daily", {}, "arm"),
    ("feature_arms_daily", {}, "arm"),
    ("cis_official_daily", {}, "symbol"),
    ("allocation_daily", {}, "book"),
    ("allocation_nav_daily", {}, "d"),
    ("exploration_ideas", {}, "id"),
    # 10-29(P1):真钱账户快照 + 组合层目标 + 它要对照的纸面前向账本(T25 / World50 / 交易层)
    ("live_account_daily", {}, "d"),
    ("portfolio_targets_daily", {}, "sleeve"),
    ("execution_quality_daily", {}, ("sleeve", "span")),     # 10-30:真钱执行质量(滑点 / 费 / 成交率),事后改不了
    ("forward_book_nav", {}, ("book", "arm")),
    ("world50_book_nav", {}, "arm"),
)


KEYS.update({t: k for t, _f, k in SOURCES})


def canonical(payload: dict) -> bytes:
    """纯函数。键排序、紧凑分隔、UTF-8 —— 同一份内容永远同一串字节。"""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def key_of(row: dict, key: Any) -> str:
    """纯函数。一天之内区分行的键;复合键(元组)用 `|` 连起来。"""
    if isinstance(key, tuple):
        return "|".join(str(row.get(k)) for k in key)
    return str(row.get(key))


def clean_rows(rows: list[dict], key: Any) -> list[dict]:
    """纯函数。去掉重算时间列,按排序键排好。"""
    out = [{k: v for k, v in r.items() if k not in DROP} for r in rows]
    return sorted(out, key=lambda r: key_of(r, key))


def digest_of(payload: dict) -> str:
    return hashlib.sha256(canonical(payload)).hexdigest()


def ots_file(digest_hex: str, calendar_response: bytes) -> bytes:
    """纯函数。OpenTimestamps 分离式证明文件:文件头 + 版本 + SHA-256 操作 + 摘要 + 日历给的时间戳。"""
    return OTS_MAGIC + OTS_VERSION + OTS_SHA256 + bytes.fromhex(digest_hex) + calendar_response


def waiting_for(prev: dict, cur: dict) -> list[str]:
    """纯函数。前一天有行、这一天没有的来源。"""
    return sorted(t for t, rows in prev["sources"].items() if rows and not cur["sources"].get(t))


def forward_rows(rows: list[dict]) -> list[dict]:
    """纯函数。只留前向行(d ≥ inception;没有 inception 的表 = 全部)。"""
    from src.data.accounting.forward_lock import is_forward
    return [r for r in rows if is_forward(r)]


async def build_payload(d: date) -> dict:
    from src.data.style.header import _read_all
    sources: dict[str, list] = {}
    for table, flt, key in SOURCES:
        rows = await _read_all(table, {"select": "*", "d": f"eq.{d.isoformat()}", **flt})
        sources[table] = clean_rows(forward_rows(rows), key)
    return {"d": d.isoformat(), "schema": CODE_REF, "sources": sources}


def _ident(table: str, row: dict) -> str:
    k = KEYS.get(table, "arm")
    return key_of(row, k) if k != "d" else "-"


#: v1 锚只收了这两张表的这一个臂;核对 v1 锚时现表按同一范围取,否则 v1 没收的新臂会被报成「锚后补进」。
V1_SCOPE = {"multiplier_daily": ("arm", "mult_v1"), "portfolio_layer_daily": ("arm", "pl_v2")}


def compare(anchored: dict, current: dict) -> dict[str, Any]:
    """纯函数。锚里存的 payload 对现表(同一天、同几张表)逐行比:改了哪几行、哪些字段;锚里有现在没了的;锚后才补进的。
    回放行(v1 锚误收的)不计,只报个数。"""
    changed, gone, added, replay, checked = [], [], [], 0, 0
    v1 = anchored.get("schema") == "T-073 anchor v1"
    for table, rows in (anchored.get("sources") or {}).items():
        fwd = forward_rows(rows)
        replay += len(rows) - len(fwd)
        cur = forward_rows(current.get(table) or [])
        if v1 and table in V1_SCOPE:
            col, val = V1_SCOPE[table]
            cur = [r for r in cur if r.get(col) == val]
        now = {_ident(table, r): r for r in cur}
        seen = set()
        for r in fwd:
            i = _ident(table, r)
            seen.add(i)
            checked += 1
            c = now.get(i)
            if c is None:
                gone.append({"table": table, "key": i})
                continue
            fields = sorted(f for f in set(r) | set(c) if canonical({"v": r.get(f)}) != canonical({"v": c.get(f)}))
            if fields:
                changed.append({"table": table, "key": i, "fields": fields})
        added += [{"table": table, "key": i} for i in sorted(set(now) - seen)]
    return {"matches_current_tables": not changed and not gone, "forward_rows_checked": checked,
            "changed": changed, "gone": gone, "added_after_anchor": added, "replay_rows_excluded": replay}


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
    from src.data.accounting.forward_lock import FINAL_LAG_DAYS
    today = today or datetime.now(timezone.utc).date()
    d = today - timedelta(days=FINAL_LAG_DAYS)
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
    """现场核对:锚里存的前向行与今天的表逐行比(S-560)。不一致 = 那一天的前向记录后来被改过 —— 报出是哪几行、哪些字段。

    v1 曾用「按现在的 SOURCES 重建 payload 再比摘要」:加一个臂、加一张表,旧锚就全红,分不清谁改了什么。"""
    from src.data.style.header import _read_all
    rows = await _read_all(TABLE, {"select": "d,digest,n_rows,ots,submitted_at,payload", "d": f"eq.{d.isoformat()}"})
    if not rows:
        return {"d": d.isoformat(), "anchored": False}
    a = rows[0]
    payload = a.get("payload") or {}
    current: dict[str, list] = {}
    for table in (payload.get("sources") or {}):
        cur = await _read_all(table, {"select": "*", "d": f"eq.{d.isoformat()}"})
        current[table] = clean_rows(cur, KEYS.get(table, "arm"))
    return {"d": d.isoformat(), "anchored": True, "digest": a["digest"], "submitted_at": a["submitted_at"],
            "n_rows": a["n_rows"], "calendars": sorted((a.get("ots") or {}).keys()),
            "schema": payload.get("schema"), **compare(payload, current)}
