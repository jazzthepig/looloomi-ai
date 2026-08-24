#!/usr/bin/env bash
# 部署后验证 —— preflight 拦 push,这个拦「它在生产里到底跑了没有」(S-227).
#
# 今天(2026-08-24)一个问题来回了三次:
#
#   Jazz 贴 /internal/vdb-health → asset_embeddings 仍 31d
#   我猜"没部署" → 查 payload 发现新字段在,所以【部署了】
#   我猜"写失败" → 写了三段诊断 → 最后发现【最后一个 commit 根本没推】
#
# 三次来回的全部内容,是在区分四个状态,而我们没有任何东西能把它们分开:
#
#     没推送        本地 HEAD ≠ 线上 git_sha
#     推了没部署    SHA 不符且已过 build 时间
#     部署了没跑到  SHA 相符,但 uptime < 该 loop 的首次延迟   ← 现在就是这个
#     跑了但写失败  SHA 相符,uptime 够,而表没动
#
# **「太早」是一个独立结论,不是"坏了"。** 把它们合并,就是今天那三次来回 ——
# 和本 session 每一个缺陷同一个形状:两个不同的事实压成一个数字。
#
# 不需要任何密钥:只读线上已经公开的 HTTP 面,和本地的 git。所以沙箱、CI、
# 你的终端上跑出来是同一个结果。
#
#   bash scripts/postdeploy_verify.sh [BASE_URL]
set -uo pipefail
cd "$(dirname "$0")/.."

BASE="${1:-https://looloomi.ai}"
FAIL=0
WARN=0

_get() { curl -s --max-time 20 "$1" 2>/dev/null; }
_jq()  { python3 -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception: print(''); sys.exit(0)
for k in '$1'.split('.'):
    if isinstance(d, dict): d = d.get(k)
    else: d = None
print('' if d is None else d)
" 2>/dev/null; }

echo "→ 部署后验证 · $BASE"
echo ""

# ── 1/5 这版代码到底在不在线上 ───────────────────────────────────────────────
# 第一个问题,永远。今天的三次来回里有两次是因为跳过了它。
LOCAL_SHA=$(git rev-parse --short HEAD 2>/dev/null || echo "?")
UNPUSHED=$(git rev-list --count origin/main..HEAD 2>/dev/null || echo "?")
BS=$(_get "$BASE/internal/build-state")
PROD_SHA=$(echo "$BS" | _jq "git_sha_short")
UPTIME=$(echo "$BS" | _jq "uptime_seconds")

echo "[1/5] 版本"
if [[ -z "$PROD_SHA" ]]; then
  echo "  ✗ /internal/build-state 读不到 —— 服务没起来,后面四项都不用看"
  exit 1
fi
echo "      本地 HEAD=$LOCAL_SHA · 线上=$PROD_SHA · 未推送 commit=$UNPUSHED · uptime=${UPTIME}s"
if [[ "$UNPUSHED" != "0" && "$UNPUSHED" != "?" ]]; then
  echo "  ✗ 本地有 $UNPUSHED 个 commit 没推 —— 线上不可能有这次的改动。"
  echo "    这正是今天那三次来回的第三次:我在诊断一份根本没上线的代码。"
  FAIL=1
# 比较必须在【共同前缀】上做:本地 rev-parse --short 给 7 位,线上 git_sha_short
# 给 8 位。第一次跑这个脚本时它就报了一次假不符 —— 一个把相同判成不同的比较,
# 会让人去查一个不存在的部署问题,这和今天那三次来回是同一种浪费。
elif [[ "${LOCAL_SHA:0:7}" != "${PROD_SHA:0:7}" ]]; then
  echo "  ⚠ SHA 不符 —— 推了但 Railway 还在 build,或 build 失败。等 ~90s 重跑。"
  WARN=1
else
  echo "  ✓ 线上就是这一版"
fi
echo ""

# ── 2/5 「太早」不是「坏了」 ─────────────────────────────────────────────────
# 每个 loop 都有自己的首次延迟。uptime 小于它的时候,表没动是【正确的】。
ROLE=$(echo "$BS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin).get('runtime_role') or {}
    print(f\"{d.get('role')}|{d.get('may_write_shared_record')}|{d.get('refusals_note','')}\")
except Exception: print('|||')")
R_NAME="${ROLE%%|*}"; R_REST="${ROLE#*|}"; R_WRITE="${R_REST%%|*}"; R_NOTE="${R_REST#*|}"
if [[ "$R_NAME" == "None" || -z "$R_NAME" ]]; then
  echo "  ⚠ build-state 没有 runtime_role —— 线上还是旧版,这一项无法判断"
  WARN=1
elif [[ "$R_WRITE" != "True" ]]; then
  # 这是最贵的一种沉默:role 未设 fail-closed 成 replica,每个经过 role gate 的
  # 写入都被拒,而拒绝只在日志里留一行、每个目标只留一次。
  echo "  ✗ role=$R_NAME 且【不能写】共享记录 —— 所有经过 role gate 的写入都在被拒"
  echo "    $R_NOTE"
  echo "    APP_ROLE 未设时 fail-closed 成 replica。生产必须显式 APP_ROLE=production。"
  FAIL=1
else
  echo "  ✓ role=$R_NAME,可写共享记录 · $R_NOTE"
fi
echo ""

echo "[2/5] 时间窗"
declare -A FIRST_RUN=( ["embedding_rebuild"]=900 ["forward_return_backfill"]=1200
                       ["t2_precompute"]=600 ["forward_record"]=300 )
TOO_EARLY=""
for L in "${!FIRST_RUN[@]}"; do
  d=${FIRST_RUN[$L]}
  if python3 -c "import sys; sys.exit(0 if float('${UPTIME:-0}') < $d else 1)" 2>/dev/null; then
    TOO_EARLY="$TOO_EARLY $L(${d}s)"
  fi
done
if [[ -n "$TOO_EARLY" ]]; then
  echo "  ⓘ uptime ${UPTIME}s —— 这些 loop 还没到首次运行:$TOO_EARLY"
  echo "    它们对应的表【现在还没动是正确的】。不要在这个窗口内诊断写入失败。"
else
  echo "  ✓ uptime ${UPTIME}s，所有 loop 都已过首次延迟 —— 表没动就是真没动"
fi
echo ""

# ── 3/5 循环健康 ─────────────────────────────────────────────────────────────
echo "[3/5] loop_health"
LH=$(_get "$BASE/internal/loop-health")
LH_OVERALL=$(echo "$LH" | _jq "overall")
echo "      overall=$LH_OVERALL"
echo "$LH" | python3 -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for s in d.get('stages', []):
    mark = {'flowing':'✓','stale':'⚠','broken':'✗'}.get(s.get('status'), '?')
    print(f\"      {mark} {s.get('stage')}: {str(s.get('detail'))[:96]}\")
"
[[ "$LH_OVERALL" == "broken" ]] && FAIL=1
[[ "$LH_OVERALL" == "stale"  ]] && WARN=1
echo ""

# ── 4/5 矢量基底 ─────────────────────────────────────────────────────────────
echo "[4/5] vdb-health"
VH=$(_get "$BASE/internal/vdb-health")
VH_OVERALL=$(echo "$VH" | _jq "overall")
echo "      overall=$VH_OVERALL"
echo "$VH" | python3 -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception: sys.exit(0)
for s in d.get('stores', []):
    mark = {'flowing':'✓','stale':'⚠','empty':'✗','unreadable':'✗','unknown':'?'}.get(s.get('status'),'?')
    extra = '' if s.get('readable_rows') is None else f\" readable={s['readable_rows']}\"
    print(f\"      {mark} {s.get('store')}: {s.get('status')} rows={s.get('rows')}{extra} age={s.get('age_days')}d\")
"
[[ "$VH_OVERALL" == "broken" ]] && FAIL=1
[[ "$VH_OVERALL" == "stale"  ]] && WARN=1
echo ""

# ── 5/5 契约回显 —— 线上的端点自己就是契约(CLAUDE.md 规则 #2) ─────────────
echo "[5/5] 契约"
CSV=$(echo "$BS" | _jq "contract_schema_version")
CIS=$(_get "$BASE/api/v1/cis/universe")
N_ASSETS=$(echo "$CIS" | python3 -c "
import sys, json
try: d = json.load(sys.stdin); print(len(d.get('universe') or []))
except Exception: print(0)")
TIER=$(echo "$CIS" | python3 -c "
import sys, json
try:
    d = json.load(sys.stdin)
    print(sorted({str((a or {}).get('data_tier')) for a in (d.get('universe') or [])})[:3])
except Exception: print('?')")
echo "      contract_schema_version=$CSV · CIS universe=$N_ASSETS assets · data_tier=$TIER"
if [[ "${N_ASSETS:-0}" -lt 20 ]]; then
  echo "  ✗ CIS universe 只有 $N_ASSETS 个资产 —— 服务活着但脊柱是空的"
  FAIL=1
else
  echo "  ✓ CIS 脊柱有内容"
fi
echo ""

# ── 判决 ─────────────────────────────────────────────────────────────────────
# ⚠ 判决必须说清是哪一种,不能只说红或绿 —— 那个区分就是这个脚本存在的理由。
if (( FAIL )); then
  echo "🔴 部署未通过 —— 上面的 ✗ 是原因,不是症状"
  exit 1
fi
if [[ -n "$TOO_EARLY" ]]; then
  echo "🟡 太早,不是坏了 —— uptime ${UPTIME}s，等这些 loop 跑过首次:$TOO_EARLY"
  echo "   这【不是】失败。$(( $(date +%s) )) 之后重跑本脚本再下结论。"
  exit 0
fi
if (( WARN )); then
  echo "🟡 部署上线了,但有环节 stale —— 是运维问题,不是这次发布的问题"
  exit 0
fi
echo "🟢 部署已验证 —— 线上是这一版,循环在流动,基底可读,脊柱有内容"
