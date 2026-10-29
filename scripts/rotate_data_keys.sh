#!/bin/bash
# rotate_data_keys.sh — 换 CoinGecko Pro key / EODHD token(Jazz 在自己的 Mac 上跑)
#
#   bash scripts/rotate_data_keys.sh            # 换 key:本机文件 + 重启 Mac 引擎 + 引导 Railway
#   bash scripts/rotate_data_keys.sh --check    # 只看:各处用的是不是同一把、是否还活着(不改任何东西)
#
# 规矩(CLAUDE.md / 轮换手册):key 只经过 Jazz 的手。这个脚本
#   - 用隐藏输入读新 key,**从不打印**;只显示指纹(sha256 前 8 位)用来比对各处是否一致;
#   - 调厂商接口验证时 key 走 curl 的 stdin 配置(-K -),不出现在命令行 / 进程列表里;
#   - 改 .env 先写临时文件再原子替换,保留权限;成功后删掉临时备份(备份里是旧 key);
#   - Railway 变量只能 Jazz 在控制台改 —— 脚本给步骤、等你回车、再看到新部署起来才往下走。
#
# 会动的地方(只改已存在的那一行,不新增):
#   /Volumes/CometCloudAI/cometcloud-local/.env   CG_PRO_API_KEY · EODHD_API_KEY   (Mac 引擎,cis_scheduler 启动时读)
#   ~/.cometcloud/engine.env                       同上(存在才改)
#   ~/Projects/looloomi-ai/.env                    COINGECKO_API_KEY · EODHD_API_KEY (仓库本地脚本)
# 不碰:Shadow/ 下的副本(只读镜像;旧 key 作废后那里只剩死值)、东京主机(不用这两把)。

set -euo pipefail

RAILWAY="https://web-production-0cdf76.up.railway.app"
MAC_ENV="/Volumes/CometCloudAI/cometcloud-local/.env"
ENGINE_ENV="$HOME/.cometcloud/engine.env"
REPO_ENV="$HOME/Projects/looloomi-ai/.env"
CHECK_ONLY=0
[ "${1:-}" = "--check" ] && CHECK_ONLY=1

NEW_CG=""; NEW_EOD=""
cleanup() { NEW_CG=""; NEW_EOD=""; unset NEW_CG NEW_EOD ROT_VALUE 2>/dev/null || true; }
trap cleanup EXIT

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ✅ %s\n' "$*"; }
bad()  { printf '  🔴 %s\n' "$*"; }
warn() { printf '  🟡 %s\n' "$*"; }

fp() {  # 指纹:sha256 前 8 位(从 stdin 读,不进 argv)
  python3 -c 'import hashlib,sys; v=sys.stdin.read().strip(); print(hashlib.sha256(v.encode()).hexdigest()[:8] if v else "(空)")'
}

read_var() {  # read_var FILE NAME → 打印值到 stdout(只在本进程管道里用,不落盘、不显示)
  python3 - "$1" "$2" <<'PY'
import re, sys
path, name = sys.argv[1], sys.argv[2]
try:
    for line in open(path, encoding="utf-8"):
        m = re.match(r'^\s*(?:export\s+)?' + re.escape(name) + r'\s*=\s*(.*?)\s*$', line)
        if m:
            v = m.group(1)
            if len(v) >= 2 and v[0] == v[-1] and v[0] in "'\"":
                v = v[1:-1]
            print(v)
            break
except FileNotFoundError:
    pass
PY
}

set_var() {  # set_var FILE NAME   (新值从环境变量 ROT_VALUE 读;只替换已存在的行,保留引号风格与权限)
  python3 - "$1" "$2" <<'PY'
import os, re, sys, stat, tempfile
path, name = sys.argv[1], sys.argv[2]
val = os.environ["ROT_VALUE"]
lines = open(path, encoding="utf-8").read().splitlines(keepends=True)
pat = re.compile(r'^(\s*(?:export\s+)?' + re.escape(name) + r'\s*=\s*)(.*?)(\s*)$')
n = 0
for i, line in enumerate(lines):
    m = pat.match(line.rstrip("\n"))
    if m:
        old = m.group(2)
        q = old[0] if len(old) >= 2 and old[0] == old[-1] and old[0] in "'\"" else ""
        lines[i] = f"{m.group(1)}{q}{val}{q}\n"
        n += 1
if n == 0:
    print("MISSING"); sys.exit(0)
mode = stat.S_IMODE(os.stat(path).st_mode)
d = os.path.dirname(path) or "."
fd, tmp = tempfile.mkstemp(dir=d, prefix=".rot.")
with os.fdopen(fd, "w", encoding="utf-8") as f:
    f.writelines(lines)
os.chmod(tmp, mode)
os.replace(tmp, path)
print(f"OK {n}")
PY
}

cg_status() {  # stdin = key → HTTP 状态码(CoinGecko Pro /ping)
  local k; k="$(cat)"
  [ -z "$k" ] && { echo "000"; return; }
  local code
  code="$(printf 'header = "x-cg-pro-api-key: %s"\nurl = "https://pro-api.coingecko.com/api/v3/ping"\n' "$k" \
    | curl -s -o /dev/null -w '%{http_code}' -m 20 -K - 2>/dev/null || true)"
  echo "${code:0:3}"
}

eod_status() {  # stdin = token → "HTTP码 套餐"(EODHD /user;只取套餐名,不打印邮箱 / 姓名)
  local k; k="$(cat)"
  [ -z "$k" ] && { echo "000 -"; return; }
  { printf 'url = "https://eodhd.com/api/user?api_token=%s&fmt=json"\n' "$k" \
    | curl -s -m 20 -w '\n%{http_code}' -K - 2>/dev/null || true; } \
    | python3 -c '
import json, sys
raw = sys.stdin.read().rsplit("\n", 1)
code = raw[-1] if len(raw) == 2 else "000"
try:
    plan = json.loads(raw[0]).get("subscriptionType") or "-"
except Exception:
    plan = "-"
print(code[:3] or "000", plan)'
}

deploy_id() { curl -s -m 20 "$RAILWAY/internal/build-state" | python3 -c 'import json,sys
try: print(json.load(sys.stdin).get("deployment_id") or "")
except Exception: print("")'; }

push_age() { curl -s -m 20 "$RAILWAY/internal/build-state" | python3 -c 'import json,sys
try: print(int((json.load(sys.stdin).get("last_cis_push") or {}).get("age_seconds") or -1))
except Exception: print(-1)'; }

# ── 0 · 现状 ─────────────────────────────────────────────────────────────────
say ""
say "=== 0 · 现状(指纹 = sha256 前 8 位;同一把 key 指纹相同)==="
for spec in "$MAC_ENV:CG_PRO_API_KEY" "$MAC_ENV:EODHD_API_KEY" "$ENGINE_ENV:CG_PRO_API_KEY" "$ENGINE_ENV:EODHD_API_KEY" \
            "$REPO_ENV:COINGECKO_API_KEY" "$REPO_ENV:EODHD_API_KEY"; do
  f="${spec%:*}"; n="${spec##*:}"
  [ -f "$f" ] || continue
  v="$(read_var "$f" "$n")"
  [ -z "$v" ] && continue
  if [[ "$n" == *EODHD* ]]; then s="$(printf '%s' "$v" | eod_status)"; else s="$(printf '%s' "$v" | cg_status)"; fi
  printf '  %-48s %-18s 指纹 %s  厂商返回 %s\n' "${f/#$HOME/~}" "$n" "$(printf '%s' "$v" | fp)" "$s"
  v=""
done
say "  (200 = 这把还活着;401/403 = 已作废或不对)"

# launchd plist 里写死的同名变量会盖过 .env(cis_scheduler 用 setdefault,环境里已有就不读 .env)
SHADOWED="$(grep -l -E 'CG_PRO_API_KEY|COINGECKO_API_KEY|EODHD_API_KEY' "$HOME"/Library/LaunchAgents/com.cometcloud*.plist 2>/dev/null || true)"
if [ -n "$SHADOWED" ]; then
  warn "这些 launchd plist 里直接写了 key —— 它们会盖过 .env,要一起改(改完 launchctl unload/load):"
  printf '%s\n' "$SHADOWED" | sed 's/^/       /'
fi
[ "$CHECK_ONLY" = 1 ] && { say ""; say "(--check:只看,没有改任何东西)"; exit 0; }

# ── 1 · 读新 key(隐藏输入)并先验活 ──────────────────────────────────────────
say ""
say "=== 1 · 粘贴新 key(输入不显示;直接回车 = 这一把不换)==="
read -rs -p "  新的 CoinGecko Pro key: " NEW_CG; echo
read -rs -p "  新的 EODHD token     : " NEW_EOD; echo
NEW_CG="$(printf '%s' "$NEW_CG" | tr -d '[:space:]')"
NEW_EOD="$(printf '%s' "$NEW_EOD" | tr -d '[:space:]')"
[ -z "$NEW_CG$NEW_EOD" ] && { say "  两把都没填,什么都没改。"; exit 0; }

if [ -n "$NEW_CG" ]; then
  c="$(printf '%s' "$NEW_CG" | cg_status)"
  [ "$c" = "200" ] && ok "CoinGecko 新 key 可用(/ping 200)· 指纹 $(printf '%s' "$NEW_CG" | fp)" \
                   || { bad "CoinGecko 新 key 验证失败(HTTP $c)—— 什么都没改,退出"; exit 1; }
fi
if [ -n "$NEW_EOD" ]; then
  e="$(printf '%s' "$NEW_EOD" | eod_status)"
  [ "${e%% *}" = "200" ] && ok "EODHD 新 token 可用(套餐 ${e#* })· 指纹 $(printf '%s' "$NEW_EOD" | fp)" \
                         || { bad "EODHD 新 token 验证失败(HTTP ${e%% *})—— 什么都没改,退出"; exit 1; }
fi

# 记下旧值的指纹与旧值本身(只在内存),最后用来确认旧 key 已作废
OLD_CG="$( [ -f "$MAC_ENV" ] && read_var "$MAC_ENV" CG_PRO_API_KEY || true)"
[ -z "$OLD_CG" ] && OLD_CG="$( [ -f "$REPO_ENV" ] && read_var "$REPO_ENV" COINGECKO_API_KEY || true)"

# ── 2 · 本机文件 ─────────────────────────────────────────────────────────────
say ""
say "=== 2 · 写本机文件(只改已存在的行)==="
upd() {  # upd FILE NAME VALUE
  local f="$1" n="$2" v="$3" r
  [ -f "$f" ] || return 0
  [ -n "$v" ] || return 0
  r="$(ROT_VALUE="$v" set_var "$f" "$n")"
  case "$r" in
    OK*)     ok "${f/#$HOME/~} · $n 已更新" ;;
    MISSING) : ;;
    *)       bad "${f/#$HOME/~} · $n 写入失败:$r"; exit 1 ;;
  esac
}
if [ -d "$(dirname "$MAC_ENV")" ]; then
  upd "$MAC_ENV" CG_PRO_API_KEY "$NEW_CG"
  upd "$MAC_ENV" EODHD_API_KEY  "$NEW_EOD"
else
  warn "Mac 引擎盘没挂上($(dirname "$MAC_ENV"))—— Mac 引擎这一处没改,挂上后重跑本脚本"
fi
upd "$ENGINE_ENV" CG_PRO_API_KEY    "$NEW_CG"
upd "$ENGINE_ENV" EODHD_API_KEY     "$NEW_EOD"
upd "$REPO_ENV"   COINGECKO_API_KEY "$NEW_CG"
upd "$REPO_ENV"   EODHD_API_KEY     "$NEW_EOD"

# ── 3 · 重启 Mac 引擎(它只在启动时读 .env)──────────────────────────────────
say ""
say "=== 3 · 重启 Mac 引擎 ==="
LABELS="$(launchctl list 2>/dev/null | awk '/com\.cometcloud\./ {print $3}' | sort || true)"
if [ -z "$LABELS" ]; then
  warn "launchctl 里没有 com.cometcloud.* —— 引擎若是手动起的,请手动重启 cis_scheduler"
else
  say "  在跑的引擎任务:"; printf '%s\n' "$LABELS" | sed 's/^/     /'
  AGE0="$(push_age)"
  if printf '%s\n' "$LABELS" | grep -qx 'com.cometcloud.cis_scheduler'; then
    launchctl kickstart -k "gui/$(id -u)/com.cometcloud.cis_scheduler" && ok "cis_scheduler 已重启(读到新 key)"
  else
    warn "没找到 com.cometcloud.cis_scheduler 这个标签 —— 上面哪一个是 CIS 调度器,请手动 kickstart -k"
  fi
  say "  其余任务每次运行都重新读 .env,不用重启;常驻的(KeepAlive)如有用到这两把 key,也可以:"
  say "     launchctl kickstart -k gui/\$(id -u)/<标签>"
fi

# ── 4 · Railway(只有 CoinGecko 需要;EODHD 你已经换过)──────────────────────
if [ -n "$NEW_CG" ]; then
  say ""
  say "=== 4 · Railway:COINGECKO_API_KEY(控制台里 Jazz 自己改)==="
  D0="$(deploy_id)"
  read -r -p "  回车 = 把新 CG key 放进剪贴板 60 秒(粘贴进 Railway 用);输入 n 回车 = 不用剪贴板: " yn
  if [ "${yn:-}" != "n" ] && command -v pbcopy >/dev/null; then
    printf '%s' "$NEW_CG" | pbcopy
    ( sleep 60; printf '' | pbcopy ) >/dev/null 2>&1 &
    ok "已放进剪贴板,60 秒后自动清空(剪贴板历史类工具会另存一份 —— 用了的话记得删)"
  fi
  say "  Railway → looloomi 服务 → Variables → COINGECKO_API_KEY → 粘贴 → 保存(Railway 会自动重新部署)"
  read -r -p "  改好后回车,我等新部署起来…" _
  for i in $(seq 1 40); do
    D1="$(deploy_id)"
    if [ -n "$D1" ] && [ "$D1" != "$D0" ]; then ok "Railway 新部署已上线($D1)—— 它现在用的是新 key"; break; fi
    sleep 15
    [ "$i" = 40 ] && warn "10 分钟没看到新部署 —— 去 Railway 看部署是否在排队;变量确实保存了吗?"
  done
fi

# ── 5 · 收尾验证 ─────────────────────────────────────────────────────────────
say ""
say "=== 5 · 收尾 ==="
if [ -n "$NEW_CG" ] && [ -n "$OLD_CG" ]; then
  if [ "$(printf '%s' "$OLD_CG" | fp)" = "$(printf '%s' "$NEW_CG" | fp)" ]; then
    warn "新旧 CG key 是同一把?(指纹相同)"
  else
    oc="$(printf '%s' "$OLD_CG" | cg_status)"
    if [ "$oc" = "200" ]; then
      warn "旧 CG key 仍然有效 —— Railway 和 Mac 都确认在用新 key 之后,去 CoinGecko 开发者后台把旧的那把删掉"
    else
      ok "旧 CG key 已作废(HTTP $oc)"
    fi
  fi
fi
OLD_CG=""
if [ -n "${AGE0:-}" ] && [ "${AGE0:-}" -ge 0 ] 2>/dev/null; then
  say "  Mac → Railway 的 CIS 推送:重启前距上次 $((AGE0/60)) 分钟;下一次推送应在 30 分钟内。到时看:"
  say "     curl -s $RAILWAY/internal/build-state | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"last_cis_push\"])'"
fi
say "  再跑一次只看不改:bash scripts/rotate_data_keys.sh --check   (各处指纹一致、全是 200 就算完)"
say "  完成后告诉 Seth —— 我从 Supabase 侧核 CG / EODHD 的写入在新部署后继续。"
