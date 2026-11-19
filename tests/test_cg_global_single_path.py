"""`/global` **单一活路**守卫(S-895 阶段 2)。

## 为什么要有这个测试

收口前仓库里有**四个** CoinGecko `/global` 的实现:

| # | 位置 | 形状 | 降级 |
|---|---|---|---|
| 1 | `data_layer.get_cg_global()` | 扁平化 + CMC 兜底 | `{"error": ...}` |
| 2 | `data_layer.get_macro_pulse()` 内嵌 | 扁平化 + CMC 兜底 | 空 dict |
| 3 | `cis_provider.fetch_cg_global()` | CG 原始 `data` 段 | `None` |
| 4 | `global_history.fetch_today()` | 总市值 + 主导率 | 抛异常 |

四个实现 ⇒ **四个额度池、四种降级语义、四个缓存键** ⇒ 「今天 `/global`
打了几次」没人答得上来(`/internal/cg-quota` 只报总数,分不出是哪条路打的)。
而 `/global` 是**全站最重的那个端点**(global 市值 + 全市场活跃币数 + 主导率)。

判据不是「长得像不像」,是 `docs/SPINE.md:188-191`:
**「不能给出不同答案 ⇒ 是重复」**。这四个**给出的是同一个答案**
(CG 的 `data` 段)⇒ 重复 ⇒ 必须收敛成一条活路。

收敛后的形状:

```
                    ┌─ get_cg_global()          前端路由(扁平化 + CMC 兜底)
                    ├─ get_macro_pulse()         前端 widget(扁平化 + CMC 兜底)
  data_layer.get_cg_global_raw() ─┼─ cis_provider.fetch_cg_global()  宏观因子(原始 + source)
   ↑ 唯一 HTTP 实现 + 180s 缓存   └─ global_history.fetch_today()    轨迹(原始,永不换源)
```

**形状不同不是重复,机制相同才是** —— 上面四个消费者各自的形状与降级
语义都保留了(那是它们**给下游的契约**),只有 HTTP 实现合并了。

## 三条断言

1. 仓库内打 `/global` 的**文件数 = 1**。
2. `fetch_cg_global` 的返回值**带 `source`**。
3. `fetch_cg_global` **不污染**共享缓存(加 `source` 不能原地改缓存对象)。
"""
from __future__ import annotations

import ast
import asyncio
import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.data.cis import cis_provider                    # noqa: E402
from src.data.market import data_layer, global_history    # noqa: E402

#: 唯一允许打 `/global` 的文件。**多一个就红。**
ALLOWED_GLOBAL_FILES = ("src/data/market/data_layer.py",)

#: `/global` 后面**不跟**路径字符 ⇒ 精确指 `/global` 这个端点。
#: (`/global/market_cap_chart` 是**另一个**端点 —— 它有自己的登记。)
_GLOBAL_RE = re.compile(r"/global(?![A-Za-z0-9_{}.%/-])")


# ── ① `/global` 只在一个文件里被打 ──────────────────────────────────────────

def _files_hitting_global() -> dict[str, list[int]]:
    """哪些文件真的打 `/global`(AST,不看注释)。"""
    out: dict[str, list[int]] = {}
    for dirpath, dirnames, filenames in os.walk(ROOT / "src"):
        dirnames[:] = [d for d in dirnames if d != "research" and not d.startswith(".")]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            p = Path(dirpath) / fn
            try:
                text = p.read_text(encoding="utf-8")
                tree = ast.parse(text)
            except Exception:
                continue
            lines: list[int] = []
            for n in ast.walk(tree):
                if not (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                        and n.func.attr in ("get", "post", "request")):
                    continue
                seg = ast.get_source_segment(text, n) or ""
                if _GLOBAL_RE.search(seg):
                    lines.append(n.lineno)
            if lines:
                out[str(p.relative_to(ROOT))] = lines
    return out


def test_global_只在一个文件里被打():
    """**四个实现 ⇒ 四个额度池。** 收口后只剩一个。"""
    hits = _files_hitting_global()
    extra = {rel: lines for rel, lines in hits.items() if rel not in ALLOWED_GLOBAL_FILES}
    assert not extra, (
        "这些文件还在自己打 CoinGecko `/global` ⇒ 第二个额度池:"
        f"\n  {extra}\n"
        "  取数走 `data_layer.get_cg_global_raw()`(唯一实现)。")
    assert "src/data/market/data_layer.py" in hits, (
        "唯一实现自己不见了 —— `/global` 现在没人打了(检查 "
        "`data_layer.get_cg_global_raw()`)")


def test_cis_provider_不再自己打CG():
    """`cis_provider` 曾经是第二份 `/global` + 第二份 `/coins/markets`。

    现在它**一个 CG 的 HTTP client 都不该有** —— 取数全部委托给
    `data_layer` 的单一活路。
    """
    src = (ROOT / "src/data/cis/cis_provider.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    has_cg_client = any(
        (isinstance(n, ast.Name) and n.id == "GuardedCGClient")
        or (isinstance(n, ast.Attribute) and n.attr == "GuardedCGClient")
        or (isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
            and n.func.id == "_get_cg_client")
        for n in ast.walk(tree)
    )
    assert not has_cg_client, (
        "cis_provider 又自己造 CG client 了 —— 取数必须走 "
        "`data_layer` 的单一活路(SPINE:184-213)")
    # 而且它也不该再打 `/global` 字面量。
    assert 'f"{_cg_base()}/global"' not in src, (
        "cis_provider 又自己打 `/global` 了 —— 走 `get_cg_global_raw()`")


# ── ② `fetch_cg_global` 带 `source` ─────────────────────────────────────────

_RAW = {
    "market_cap_percentage": {"btc": 57.31, "eth": 12.04},
    "total_market_cap": {"usd": 2_650_000_000_000},
}


@pytest.fixture()
def _no_cg_cache(monkeypatch):
    """`cis_provider` 与 `data_layer` 的进程内缓存清空 ⇒ 每个用例都真取。"""
    monkeypatch.setattr(cis_provider, "_cache", {})
    monkeypatch.setattr(data_layer, "_cache", {})
    monkeypatch.setenv("COINGECKO_API_KEY", "test-key")


def test_fetch_cg_global_带source(monkeypatch, _no_cg_cache):
    """**`source` 是键,不是备注**(DATA_ARCHITECTURE.md:70)。

    收口前 `fetch_cg_global()` 的返回值**没有来源标记** ⇒ 拿到这份数据的
    下游无法判断它来自 CoinGecko 还是别的家。那是现存违例,顺手修掉。
    """
    async def _fake_raw():
        return dict(_RAW)

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    out = asyncio.run(cis_provider.fetch_cg_global())
    assert out is not None, "没拿到 `/global`"
    assert "source" in out, (
        f"返回值没有 `source` ⇒ 下游分不清这是谁家的数据: {sorted(out)}")
    assert out["source"] in ("coingecko_pro", "coingecko"), \
        f"source 不是规范名: {out['source']!r}"


def test_fetch_cg_global_形状不变(monkeypatch, _no_cg_cache):
    """形状适配不许改形状 —— 调用方 `fetch_macro_data` 读的是
    `cg_global["market_cap_percentage"]["btc"]`。"""
    async def _fake_raw():
        return dict(_RAW)

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    out = asyncio.run(cis_provider.fetch_cg_global())
    assert out["market_cap_percentage"]["btc"] == 57.31
    assert out["total_market_cap"]["usd"] == 2_650_000_000_000


def test_fetch_cg_global_不污染共享缓存(monkeypatch, _no_cg_cache):
    """**加 `source` 必须先复制。**

    `get_cg_global_raw()` 返回的是**共享缓存对象**(进程内 + Redis)。
    原地加一个 `source` 字段 ⇒ 缓存里就多了一个键 ⇒ 下一个消费者拿到的
    「原始」数据带着一个不该有的字段 —— 而且这个污染会**跨进程**(Redis)。
    """
    shared = dict(_RAW)

    async def _fake_raw():
        return shared

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    out = asyncio.run(cis_provider.fetch_cg_global())
    assert out is not None and "source" in out
    assert "source" not in shared, (
        "共享缓存对象被原地改了 —— `dict(raw)` 复制漏了。"
        "这个污染会跨进程(Redis)传下去。")
    assert shared == _RAW, f"共享缓存对象被改了: {shared}"


def test_fetch_cg_global_拿不到就说没拿到(monkeypatch, _no_cg_cache):
    """**没测量 ≠ 0。** 拿不到就返回 `None`(未测量),不是 `{}`(看着像「没有数据」)。

    消费者 `fetch_macro_data` 用 `if cg_global:` 判真假 ⇒ `{}` 与 `None`
    在那里等价,但**语义上** `None` 才是「没拿到」。
    """
    async def _fake_raw():
        return None

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    out = asyncio.run(cis_provider.fetch_cg_global())
    assert out is None, f"没拿到却返回了 {out!r} —— 「没测量」塌成了「有值」"


# ── ③ `global_history.fetch_today` 走同一条路,且**永不换源** ─────────────────

def test_fetch_today_走唯一活路(monkeypatch, _no_cg_cache):
    """轨迹类的消费者也要共用这一次取数 —— 但**不换源**。

    `fetch_today` 记的是**厂商自己算的** BTC 主导率轨迹。轨迹要**同源可比**:
    换一次源就污染一次(`DATA_ARCHITECTURE.md:70`)。所以它吃
    `get_cg_global_raw()`(纯 CG),**不吃** `get_cg_global()` 的 CMC 兜底。
    """
    async def _fake_raw():
        return dict(_RAW)

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    out = asyncio.run(global_history.fetch_today())
    assert out["source"] == "coingecko_pro:/global"
    assert out["dominance_is_vendor_computed"] is True
    assert out["btc_dominance"] == pytest.approx(0.5731, abs=1e-6)
    assert out["total_market_cap_usd"] == 2_650_000_000_000
    assert out["d"], "日期没落"


def test_fetch_today_拿不到就抛_不落0(monkeypatch, _no_cg_cache):
    """**一个缺失的主导率和一个 0% 的主导率是两回事**(I1)。

    落 0 会让任何依赖它的判据全部翻向 —— 而曲线看起来完全正常。
    """
    async def _fake_raw():
        return None

    monkeypatch.setattr(data_layer, "get_cg_global_raw", _fake_raw)
    with pytest.raises(RuntimeError):
        asyncio.run(global_history.fetch_today())
