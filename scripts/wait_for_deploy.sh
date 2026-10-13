#!/usr/bin/env bash
# 等 Railway 上跑的版本 = 本地 HEAD,再做推送后的核对(S-498)。
#
# 为什么:交接块里推送后写的是固定的 `sleep 120`。10-06 那次部署用了约 3 分钟,
# 核对的 curl 打到了旧版本,报 KeyError —— 看起来像修复没生效,其实是还没上线。
# 现在按 /internal/build-state 的 git_sha 判,最多等 15 分钟;超时退出码 1(核对不跑)。
#
# 用法:bash scripts/wait_for_deploy.sh && curl ...
set -u
# 10-13:railway.app 域名连续两次给出旧的 build-state(bf039869 / 92c32f71 都已在 looloomi.ai 上线,脚本却等满 900 秒报失败)。
# 先看对外域名(经 Cloudflare 转发到同一服务),再看 railway.app;任一处等于目标即算上线。
BASES="${COMETCLOUD_BASE:-https://looloomi.ai https://web-production-0cdf76.up.railway.app}"
WANT="${WANT_SHA:-$(git rev-parse HEAD)}"
DEADLINE=$(( $(date +%s) + ${WAIT_SECONDS:-900} ))
while [ "$(date +%s)" -lt "$DEADLINE" ]; do
  for BASE in $BASES; do
    LIVE="$(curl -s --max-time 10 "$BASE/internal/build-state?t=$(date +%s)" | python3 -c 'import sys,json
try: print(json.load(sys.stdin).get("git_sha",""))
except Exception: print("")')"
    if [ "$LIVE" = "$WANT" ]; then
      echo "✅ live = ${WANT:0:8}"
      exit 0
    fi
  done
  echo "… live=${LIVE:0:8} want=${WANT:0:8}"
  sleep 15
done
echo "✗ ${WAIT_SECONDS:-900}s 内没有等到 ${WANT:0:8} 上线 —— 去 Railway 看部署日志" >&2
exit 1
