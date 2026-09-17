"""S-371 — `INTERNAL_TOKEN` 校验的行为契约。

这份测试是 Minimax-A 的 A-1(收敛 36 处比较)的**判据**。
它不检查"有没有 auth_internal.py",它检查**行为**:
收敛之后旧行为不变,而且轮换从半生效变成全生效。

为什么是行为不是拼写(这一周踩过四次):
`test_production_can_write` 检查的是"字符串里有没有 supabase",
`test_mac_push_wrappers` 检查的是"函数名对不对" —— 两个都在真实故障时是绿的。
所以这里一条断言都不看名字,全看"打进去会发生什么"。

判据由 Seth 在派活前跑过(2026-09-17),不是照着想象写的。

⏸ **这项工作 2026-09-17 由 Jazz 裁定暂缓**(先赶开发进度,做完再收回和更换 key)。
这个文件先落地,是因为**解冻时不该重新想一遍判据** —— 想的时候和做的时候
隔着几周,重想一次就是重新犯一次当时已经排除掉的错。
解除条件与到期日:`PROJECT_STATE.md` OPEN RISK **#0b**(日期兜底 2026-10-08)。

⚠️ **这个文件现在故意不在 `scripts/preflight.sh` 的清单里。**
它是「待办工作的判据」,今天必然是红的;进清单会挡住所有 push。
**但 preflight 跑的是显式清单不是 glob —— 没进清单的测试永远不跑,
那看起来像有覆盖,实际什么都没守。这比没有测试更糟。**
所以:**A-1 的完成定义包含"把 `python3 -m pytest tests/test_internal_token_contract.py -q`
加进 preflight.sh"**。收敛绿了那一刻加,不是以后再说。
"""

from __future__ import annotations

import ast
import os
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
API = ROOT / "src" / "api"

# 收敛前的实测基线(2026-09-17)。A-1 做完这些数必须降到 0 / 1。
BASELINE_COMPARE_SITES = 36  # 17 个文件
BASELINE_SHAPES = 10
BASELINE_IMPORT_TIME_FILES = 12

# ⚠️ 这条正则改过一次,原因值得留着。
# 第一版是 `!=\s*expected\b`,它匹配到了 contracts/cis_push.py:229 的
#   f"schema_version '{x}' != expected '{SCHEMA_VERSION}'"
# —— 一句 f-string 里的散文。**又一次匹配了字面而不是语义**,和这周
# test_production_can_write / test_mac_push_wrappers 同一种错。
# 修法:真正的守卫**一定是 if 语句**,散文不是。所以只在 `if ...:` 行上匹配。
_COMPARE_TOKENS = (
    r"x_internal_token\s*!=|!=\s*_?INTERNAL_TOKEN\b|"
    r"\btoken\s*!=|!=\s*_tok\b|!=\s*\btok\b|!=\s*expected\b"
)
_COMPARE = re.compile(rf"(?m)^\s*(?:el)?if\b[^\n]*(?:{_COMPARE_TOKENS})")
_IMPORT_TIME = re.compile(
    r"(?m)^_?INTERNAL_TOKEN\s*=\s*os\.(environ\.get|getenv)\(\s*[\"']INTERNAL_TOKEN[\"']"
)


def _py_files() -> list[Path]:
    return [p for p in API.rglob("*.py") if "__pycache__" not in p.parts]


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


# ---------------------------------------------------------------- 结构不变量


def test_no_module_level_internal_token_constant():
    """模块常量 = 轮换半生效。这是 S-371 的核心缺陷,不是风格问题。

    在 Railway 改掉 INTERNAL_TOKEN 之后,import 期读进常量的 router 仍然接受旧值,
    而请求期读 environ 的 main.py 端点已经拒绝 —— 同一个凭据一半有效一半无效,
    从外面看「已轮换」和「轮换了一半」长得一模一样。
    """
    offenders = [
        str(p.relative_to(ROOT)) for p in _py_files() if _IMPORT_TIME.search(_read(p))
    ]
    assert not offenders, (
        f"{len(offenders)} 个文件在 import 期读 INTERNAL_TOKEN(基线 "
        f"{BASELINE_IMPORT_TIME_FILES} 个)。轮换会对这些文件半生效。\n"
        "改成在校验函数内部、请求期读 os.environ:\n  " + "\n  ".join(offenders)
    )


def test_token_comparison_happens_in_exactly_one_place():
    """36 处抄来抄去的比较 = 36 次写错的机会,而 10 种写法证明漂移已经发生。

    收敛的价值不是整洁,是让「加一个 lane」从改 36 处变成改 1 处。
    """
    sites: dict[str, int] = {}
    for p in _py_files():
        if p.name == "auth_internal.py":
            continue  # 唯一允许比较的地方
        n = len(_COMPARE.findall(_read(p)))
        if n:
            sites[str(p.relative_to(ROOT))] = n
    total = sum(sites.values())
    assert total == 0, (
        f"仍有 {total} 处 token 比较散落在 {len(sites)} 个文件(基线 {BASELINE_COMPARE_SITES} 处)。\n"
        "全部换成 require_internal_token();留一处就是留一条旧路。\n"
        + "\n".join(f"  {k}: {v}" for k, v in sorted(sites.items(), key=lambda kv: -kv[1]))
    )


def test_auth_helper_exists_and_reads_env_at_call_time():
    """校验函数必须在**函数体内**读 environ —— 在模块顶层读等于没改。"""
    helper = API / "auth_internal.py"
    if not helper.exists():
        pytest.skip("A-1 未开始:src/api/auth_internal.py 尚不存在")

    tree = ast.parse(_read(helper))
    top_level_reads = [
        n
        for n in tree.body
        if isinstance(n, ast.Assign)
        and "INTERNAL_TOKEN" in ast.dump(n)
        and "environ" in ast.dump(n)
    ]
    assert not top_level_reads, (
        "auth_internal.py 在模块顶层读 INTERNAL_TOKEN —— 这把同一个 bug 搬了个家。"
        "environ 的读取必须在函数体内,每次请求重新读。"
    )

    fn = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
            and n.name == "require_internal_token"
        ),
        None,
    )
    assert fn is not None, "auth_internal.py 里没有 require_internal_token()"
    assert "environ" in ast.dump(fn) or "getenv" in ast.dump(fn), (
        "require_internal_token() 函数体里没有读环境变量 —— 那它读的是什么?"
    )


# ---------------------------------------------------------------- 行为不变量


def _load_helper():
    helper = API / "auth_internal.py"
    if not helper.exists():
        pytest.skip("A-1 未开始:src/api/auth_internal.py 尚不存在")
    import importlib

    mod = importlib.import_module("src.api.auth_internal")
    importlib.reload(mod)
    return mod


@pytest.mark.parametrize(
    "header,env,should_pass",
    [
        ("secret", {"INTERNAL_TOKEN": "secret"}, True),
        ("wrong", {"INTERNAL_TOKEN": "secret"}, False),
        (None, {"INTERNAL_TOKEN": "secret"}, False),
        ("", {"INTERNAL_TOKEN": "secret"}, False),
        # env 没配 = 拒绝一切。**不能**因为没配就放行。
        ("anything", {}, False),
        ("", {}, False),
    ],
)
def test_behaviour_matches_pre_convergence(header, env, should_pass, monkeypatch):
    """收敛后行为必须和收敛前一致。空 header 统一拒绝(唯一允许的行为变化)。"""
    mod = _load_helper()
    for k in ("INTERNAL_TOKEN", "INTERNAL_TOKEN_A", "INTERNAL_TOKEN_B",
              "INTERNAL_TOKEN_C", "INTERNAL_TOKEN_SETH"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)

    try:
        mod.require_internal_token(header)
        passed = True
    except Exception:
        passed = False
    assert passed is should_pass, (
        f"header={header!r} env={env} → 期望 {'通过' if should_pass else '401'},实际相反"
    )


def test_rotation_takes_effect_without_restart(monkeypatch):
    """S-371 的那条:轮换必须立刻全生效,不能等进程重启。"""
    mod = _load_helper()
    monkeypatch.setenv("INTERNAL_TOKEN", "OLD")
    assert mod.require_internal_token("OLD"), "旧值应当通过"

    monkeypatch.setenv("INTERNAL_TOKEN", "NEW")
    with pytest.raises(Exception):
        mod.require_internal_token("OLD")  # 轮换后旧值必须立刻失效
    assert mod.require_internal_token("NEW"), "轮换后新值应当通过"


def test_per_lane_tokens_are_attributable(monkeypatch):
    """A-2:命中哪个 lane 要能说出来,否则泄露之后无法归因、无法局部撤销。"""
    mod = _load_helper()
    for k in ("INTERNAL_TOKEN", "INTERNAL_TOKEN_A", "INTERNAL_TOKEN_B",
              "INTERNAL_TOKEN_C", "INTERNAL_TOKEN_SETH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("INTERNAL_TOKEN_A", "tok-a")
    monkeypatch.setenv("INTERNAL_TOKEN_C", "tok-c")

    try:
        lane_a = mod.require_internal_token("tok-a")
        lane_c = mod.require_internal_token("tok-c")
    except AttributeError:
        pytest.skip("A-2 未开始:多 token 尚未实现")

    assert lane_a != lane_c, "两条 lane 的 token 必须返回不同身份,否则无法归因"
    assert "a" in str(lane_a).lower(), f"A 的 token 应返回可识别的 lane 名,得到 {lane_a!r}"
    assert "c" in str(lane_c).lower(), f"C 的 token 应返回可识别的 lane 名,得到 {lane_c!r}"

    with pytest.raises(Exception):
        mod.require_internal_token("tok-b")  # 未配置的 lane 必须拒绝
