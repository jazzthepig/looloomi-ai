#!/usr/bin/env python3
"""T-417 第①步:清单扫描 —— 找出仓库里所有报过「站住 / HOLDS / 成立 / n_signal」的表。

只读扫描,不改任何既有文件。输出 t417_inventory_raw.json。
"""
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))

# 「站住」同义键名(小写后匹配)
KEY_PAT = re.compile(
    r"(holds?|_hold|holds\b|passed?|_pass\b|n_signal|signal_n|surviv\w*|站住|成立|"
    r"confirmed|verified|stands)",
    re.I,
)


def keys_of(obj, path="", out=None, depth=0):
    """收集路径中所有匹配同义键的位置(限深度)。"""
    if out is None:
        out = []
    if depth > 7:
        return out
    if isinstance(obj, dict):
        for k, v in obj.items():
            p = f"{path}.{k}" if path else str(k)
            if KEY_PAT.search(str(k)):
                out.append(p)
            keys_of(v, p, out, depth + 1)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:3]):
            keys_of(v, f"{path}[{i}]", out, depth + 1)
    return out


def main():
    files = sorted(f for f in os.listdir(ROOT) if f.endswith(".json"))
    inventory = []
    for fn in files:
        p = os.path.join(ROOT, fn)
        try:
            raw = open(p, encoding="utf-8", errors="replace").read()
        except Exception as e:  # pragma: no cover
            inventory.append({"file": fn, "error": str(e)})
            continue
        try:
            d = json.loads(raw)
        except Exception:
            # 可能是 jsonl
            if raw.lstrip().startswith(("{", "[")):
                inventory.append({"file": fn, "not_json": True, "bytes": len(raw)})
            continue
        hits = keys_of(d)
        if not hits:
            continue
        # 归一化路径:去掉 [i] 数组下标,统计不同 key 名
        norm = {}
        for h in hits:
            k = re.sub(r"\[\d+\]", "[]", h)
            norm[k] = norm.get(k, 0) + 1
        inventory.append({
            "file": fn,
            "bytes": len(raw),
            "top_keys": list(d.keys())[:14] if isinstance(d, dict) else f"LIST[{len(d)}]",
            "hold_like_paths": sorted(norm.items(), key=lambda kv: -kv[1])[:12],
            "n_hold_like_paths": len(hits),
        })
    json.dump(inventory, open(os.path.join(ROOT, "t417_inventory_raw.json"), "w"),
              ensure_ascii=False, indent=1)
    print(f"scanned json files: {len(files)}")
    print(f"with hold-like keys: {len(inventory)}")
    for it in inventory:
        if "not_json" in it or "error" in it:
            print(f"  !! {it['file']}: {it.get('not_json') or it.get('error')}")
    print("\n-- top 60 by hold-like path count --")
    for it in sorted([i for i in inventory if "hold_like_paths" in i],
                     key=lambda x: -x["n_hold_like_paths"])[:60]:
        ks = ",".join(k for k, _ in it["hold_like_paths"][:5])
        print(f"{it['file']:44s} n={it['n_hold_like_paths']:4d}  {ks}")


if __name__ == "__main__":
    sys.exit(main())
