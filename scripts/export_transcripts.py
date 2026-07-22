"""Export Claude session .jsonl transcripts to readable markdown archives.

Preserves conversation substance (user messages verbatim, assistant prose in full) while
collapsing tool payloads to one-line summaries — that's where ~95% of the bulk lives.
Never prints transcript content to stdout; writes files and reports stats only.
"""
import json
import os
import sys
from datetime import datetime, timezone

SRC = sys.argv[1]
DST = sys.argv[2]
os.makedirs(DST, exist_ok=True)

TRUNC_TOOL_INPUT = 300
TRUNC_TOOL_RESULT = 200


def ts_of(rec):
    t = rec.get("timestamp")
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    except Exception:
        return None


def blocks(content):
    """Yield ('text'|'tool_use'|'tool_result', payload) from a message content field."""
    if isinstance(content, str):
        yield "text", content
        return
    if not isinstance(content, list):
        return
    for b in content:
        if not isinstance(b, dict):
            continue
        t = b.get("type")
        if t == "text":
            yield "text", b.get("text", "")
        elif t == "tool_use":
            yield "tool_use", (b.get("name", "?"), b.get("input", {}))
        elif t == "tool_result":
            c = b.get("content")
            if isinstance(c, list):
                c = " ".join(x.get("text", "") for x in c if isinstance(x, dict))
            yield "tool_result", str(c or "")
        elif t == "thinking":
            pass  # omit reasoning traces


def convert(path, out_path):
    n_user = n_asst = n_tool = 0
    first = last = None
    lines = []
    with open(path, "r", errors="replace") as f:
        for raw in f:
            raw = raw.strip()
            if not raw:
                continue
            try:
                rec = json.loads(raw)
            except Exception:
                continue
            t = ts_of(rec)
            if t:
                first = first or t
                last = t
            msg = rec.get("message") or {}
            role = msg.get("role") or rec.get("type")
            content = msg.get("content")
            if role not in ("user", "assistant") or content is None:
                continue

            parts = list(blocks(content))
            # skip pure tool-result turns (they're plumbing, summarised on the call side)
            if parts and all(k == "tool_result" for k, _ in parts):
                continue

            stamp = t.strftime("%Y-%m-%d %H:%M") if t else ""
            if role == "user":
                txt = "\n".join(v for k, v in parts if k == "text").strip()
                if not txt:
                    continue
                # drop injected system-reminder noise
                if txt.startswith("<system-reminder>") and txt.endswith("</system-reminder>"):
                    continue
                n_user += 1
                lines.append(f"\n\n---\n\n### 🧑 Jazz — {stamp}\n\n{txt}\n")
            else:
                buf = []
                for k, v in parts:
                    if k == "text" and v.strip():
                        buf.append(v.strip())
                    elif k == "tool_use":
                        name, inp = v
                        n_tool += 1
                        s = json.dumps(inp, ensure_ascii=False)[:TRUNC_TOOL_INPUT]
                        buf.append(f"> 🔧 `{name}` — `{s}`")
                if not buf:
                    continue
                n_asst += 1
                lines.append(f"\n**🤖 Claude — {stamp}**\n\n" + "\n\n".join(buf) + "\n")

    header = (
        f"# Session transcript — {os.path.basename(path).split('.')[0][:8]}\n\n"
        f"- **Source:** `{os.path.basename(path)}`\n"
        f"- **Span:** {first.strftime('%Y-%m-%d %H:%M') if first else '?'} → "
        f"{last.strftime('%Y-%m-%d %H:%M') if last else '?'} UTC\n"
        f"- **Messages:** {n_user} from Jazz · {n_asst} from Claude · {n_tool} tool calls\n\n"
        f"*Tool payloads collapsed to one-line summaries; reasoning traces omitted. "
        f"User messages verbatim.*\n"
    )
    with open(out_path, "w") as o:
        o.write(header + "".join(lines))
    return n_user, n_asst, n_tool, first, last


rows = []
for fn in sorted(os.listdir(SRC)):
    if not fn.endswith(".jsonl"):
        continue
    p = os.path.join(SRC, fn)
    try:
        u, a, tc, f0, f1 = convert(p, os.path.join(DST, "tmp.md"))
    except Exception as e:
        print(f"FAIL {fn}: {e}")
        continue
    day = f0.strftime("%Y-%m-%d") if f0 else "unknown"
    out = os.path.join(DST, f"{day}_{fn[:8]}.md")
    os.replace(os.path.join(DST, "tmp.md"), out)
    rows.append((day, u, a, tc, os.path.getsize(p), os.path.getsize(out), out))

print(f"{'date':12s} {'Jazz':>5s} {'Claude':>7s} {'tools':>6s} {'src':>8s} {'out':>8s}")
for day, u, a, tc, s0, s1, out in rows:
    print(f"{day:12s} {u:5d} {a:7d} {tc:6d} {s0/1e6:7.1f}M {s1/1e6:7.2f}M")
print(f"\nwrote {len(rows)} archives to {DST}")
