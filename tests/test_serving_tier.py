"""服务层级必须可见,且兜底不得抹掉自己的报警 (S-265)。

这个文件里最重要的一条不是「四个层级都能出现」,而是:

    **兜底不得写进上游那把钥匙。**

原码:模板兜底生成后执行 `redis_set_key("macro:brief", payload)`,而
`health.py` 判活读的就是 `macro:brief`。于是

    Mac 死 → health 报 missing → 兜底跑一次 → 把自己写进 macro:brief
           → **health 变绿,而 Mac 仍然是死的**

2026-09-01 那次 `macro_brief: missing` 之所以看得见,只是因为兜底那份 15 分钟
TTL 刚好过期。它会自己「好」,而没有人修过任何东西。

> 一个会把自己的报警清掉的兜底,比没有兜底更危险:
> 没有兜底时故障是可见的,有它时故障是可见的**一小会儿**。

第二条:四条返回路径原本有四种 `source` 写法(`mac_mini` / `auto` /
回落取值 / `none`),另有一条用 `model: "template"` —— **两条路径用两个不同的
字段名报告同一件事**,所以下游没有任何一个字段可以问「这是第几层」,
前端也就不可能标出来。现在是一个 `tier`,封闭取值。

第三条:`"mac_mini"` 出现在**面向用户的** `/api/v1/` 响应里。规则 #8 的守卫只扫
`dashboard/src/*.jsx`;S-262 已在 `/internal/` 上发现同一个盲区,这是它在公开
API 上的第二例。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.api.contracts.serving_tier import (          # noqa: E402
    FALLBACK, NONE, STALE, TIERS, UPSTREAM, describe, fallback_key, public_source,
)

_FAIL: list[str] = []
MACRO = ROOT / "src" / "api" / "routers" / "macro.py"


def _check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'✓' if ok else '✗'} {label}" + (f"\n      {detail}" if not ok else ""))
    if not ok:
        _FAIL.append(f"{label}{(' — ' + detail) if detail else ''}")


def _func_body(src: str, name: str) -> str:
    """取一个顶层 async 函数的函数体。

    ⚠️ 判据必须**按函数作用域**取,不能按文件取:`macro.py` 里对 `_REDIS_KEY`
    的写入有两种,而它们的对错相反 ——
      · `receive_macro_brief`(上游推进来)写它 = **正确**,那就是上游键的用途
      · `get_macro_brief`(兜底生成)写它 = **错误**,会抹掉自己的报警
    初版按整个文件搜 `redis_set_key(_REDIS_KEY`,把正确的那处也报成违规。
    **守卫比它要保护的性质更粗,今天第三次。**
    """
    i = src.find(f"async def {name}")
    if i < 0:
        return ""
    j = src.find("\nasync def ", i + 1)
    k = src.find("\n@router", i + 1)
    end = min(x for x in (j, k, len(src)) if x > 0)
    body = src[i:end]
    # **剥掉注释再扫。** 不剥,守卫会被它自己解释的反例绊倒:上面那条修复的注释
    # 里原样引用了 `redis_set_key(_REDIS_KEY, ...)`,于是「服务路径不得写上游键」
    # 这条断言在代码已经修好之后仍然红。S-249 同一课(那次是 docstring 里引用的
    # `.upper().replace()` 绊倒了禁止重复实现 canonical_regime 的守卫)。
    return "\n".join(l for l in body.split("\n") if not l.lstrip().startswith("#"))


def t_fallback_never_writes_the_upstream_key():
    """**本文件的理由。** 兜底写回上游键 = 缓解措施抹掉自己的报警。"""
    src = MACRO.read_text()
    serve = _func_body(src, "get_macro_brief")
    ingest = _func_body(src, "receive_macro_brief")
    _check("能定位到两个函数体", bool(serve) and bool(ingest),
           f"serve={len(serve)} ingest={len(ingest)}")

    bad = re.findall(r"redis_set_key\(\s*_REDIS_KEY\b", serve)
    _check("服务路径没有把兜底写进 _REDIS_KEY(上游键)", not bad,
           f"{len(bad)} 处仍写上游键 —— health.py 读的就是它,写进去 = 自动变绿")

    # 判别性:上游摄取路径**必须**写上游键。少了这条断言,把两处写入
    # 一起删掉也能让上面那条变绿 —— 而那是把上游的存储整个拆掉。
    good = re.findall(r"redis_set_key\(\s*_REDIS_KEY\b", ingest)
    _check("上游摄取路径仍然写上游键(不是把存储拆掉)", bool(good),
           "receive_macro_brief 不再写 _REDIS_KEY —— 上游的值没地方落了")

    _check("兜底走的是 fallback_key()",
           "fallback_key(_REDIS_KEY)" in src,
           "找不到 fallback_key(_REDIS_KEY) —— 兜底落在哪把钥匙上不明确")

    _check("上游键与兜底键确实不同",
           fallback_key("macro:brief") != "macro:brief",
           fallback_key("macro:brief"))


def t_health_distinguishes_dark_upstream_from_nothing_at_all():
    """「上游暗着但兜底在顶」必须与「什么都没有」分开。

    差别对运维是决定性的:后者用户看到空白,前者用户看到一份**阈值兜底算出的
    regime**,页面完全正常,而引擎的判断根本没参与。
    """
    h = (ROOT / "src" / "api" / "health.py").read_text()
    _check("health 会去读兜底键", "fallback_key(\"macro:brief\")" in h,
           "health 只读上游键 ⇒ 两个状态仍然同形")
    _check("有一条明说 FALLBACK 正在服务的分支", "FALLBACK serving" in h)
    _check("『什么都没有』那条的措辞与它不同",
           "上游与兜底都没有内容" in h)


def t_every_return_path_carries_one_tier_field():
    """四条路径,一个字段名。**不是 source/model 各说各的。**"""
    src = MACRO.read_text()
    body = src[src.find("async def get_macro_brief"):]
    body = body[:body.find("\n@router", 1)] if "\n@router" in body[1:] else body

    for tier_const in ("_tier.UPSTREAM", "_tier.FALLBACK", "_tier.STALE", "_tier.NONE"):
        _check(f"get_macro_brief 里出现 {tier_const}", tier_const in body,
               "某条返回路径没有声明自己的层级")

    _check("describe() 被用来生成层级块(而不是各处手写 dict)",
           body.count("_tier.describe(") >= 4,
           f"只有 {body.count('_tier.describe(')} 处 —— 手写的那些会漂")


def t_no_hardware_names_reach_a_public_response():
    """规则 #8 延伸到 /api/v1/,不只是前端 bundle。"""
    _check("mac_mini → upstream", public_source("mac_mini") == UPSTREAM,
           public_source("mac_mini"))
    _check("大小写与连字符都覆盖",
           public_source("Mac-Mini") == UPSTREAM and public_source("MACMINI") == UPSTREAM)
    _check("railway → fallback(厂商名同样不外露)",
           public_source("railway_snapshot") == FALLBACK)
    _check("空 → none(不是伪装成 upstream)", public_source(None) == NONE)

    # 未知取值原样返回,**不是静默改成 upstream** —— 一个没见过的来源名应该
    # 在响应里显眼地出现,而不是被伪装成权威层。
    _check("未知来源原样返回,不伪装成权威层",
           public_source("some_new_engine") == "some_new_engine",
           public_source("some_new_engine"))

    # ⚠️ 初版查「函数体里有没有 mac_mini 字面量」—— 太粗。`get_macro_brief` 里
    # 的 `source = data.get("source", "mac_mini")` 和 `if source == "mac_mini"`
    # 是对**内部标记**的读取与比较,返回值已经过 public_source()。
    # 要查的性质是「**返回出去的** source 是否经过映射」,不是「文件里有没有这个词」。
    serve = _func_body(MACRO.read_text(), "get_macro_brief")
    returned = re.findall(r'"source":\s*([^,\n]+)', serve)
    _check(f"服务路径有 {len(returned)} 处返回 source", bool(returned))
    unmapped = [r.strip() for r in returned
                if "public_source" not in r and not r.strip().startswith("_tier.")]
    _check("每一处返回的 source 都经过 public_source() 或是 _tier 常量",
           not unmapped, f"未映射:{unmapped}")


def t_tier_and_content_stay_separate():
    """一个 FALLBACK 的 brief 仍然是一个 brief(S-263 同一条理由)。"""
    d = describe(FALLBACK, reason="上游过期")
    _check("describe 只产出层级信息,不碰内容",
           set(d) <= {"tier", "tier_reason", "upstream_age_s"}, str(set(d)))
    _check("tier_reason 一定有值(只给 tier 的响应,读的人还得翻代码)",
           bool(describe(UPSTREAM)["tier_reason"]))
    _check("非法 tier 落到 NONE,不是静默通过",
           describe("garbage")["tier"] == NONE)
    _check("四个层级都在 TIERS 里", {UPSTREAM, FALLBACK, STALE, NONE} == set(TIERS))
    _check("age 是可选的(上游没推过就没有 age,不能编一个 0)",
           "upstream_age_s" not in describe(NONE))


if __name__ == "__main__":
    print("── 服务层级契约 (S-265) ──")
    for name, fn in sorted(globals().items()):
        if name.startswith("t_"):
            fn()
    if _FAIL:
        print(f"\n🔴 {len(_FAIL)} FAILED:")
        for f in _FAIL:
            print(f"   - {f}")
        sys.exit(1)
    print("\n✓ 服务层级守卫全绿")
