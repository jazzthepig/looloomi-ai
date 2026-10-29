#!/usr/bin/env bash
# 东京主机:写 /etc/cometcloud/executor.env(重建主机后用一次)。以 root 运行。
#   bash /opt/cometcloud/repo/deploy/executor/write_env.sh
# 规矩:key 只经过 Jazz 的手 —— 私钥 / token 用隐藏输入读,从不打印;只显示能对照的指纹。
# 粘贴「NAME=值」整行也行,脚本会去掉前面的「NAME=」。
set -euo pipefail

ENVF=/etc/cometcloud/executor.env
[ "$(id -u)" = 0 ] || { echo "需要 root"; exit 1; }
umask 077
mkdir -p /etc/cometcloud

if [ -f "$ENVF" ]; then
  read -r -p "$ENVF 已存在(主机是从快照恢复的?)。覆盖吗?[y/N] " yn
  [ "${yn:-}" = "y" ] || { echo "保留原文件,没改。下一步直接跑 install.sh。"; exit 0; }
fi

strip() { local v="$1" n="$2"; v="${v#"$n="}"; v="${v#\"}"; v="${v%\"}"; printf '%s' "$v" | tr -d '[:space:]'; }
ask()   { local n="$1" d="$2" v; read -r -p "  $n [$d]: " v; v="$(strip "${v:-$d}" "$n")"; printf '%s' "$v"; }
secret() { local n="$1" v; read -rs -p "  $n(输入不显示): " v; echo >&2; strip "$v" "$n"; }

echo "── 账户 ──"
echo "  HL_ACCOUNT_ADDRESS = 你的主钱包地址(资金所在的那个),**不是** API 钱包自己的地址"
ACC="$(ask HL_ACCOUNT_ADDRESS "")"
[[ "$ACC" =~ ^0x[0-9a-fA-F]{40}$ ]] || { echo "  🔴 HL_ACCOUNT_ADDRESS 要是主钱包地址(0x + 40 位)"; exit 1; }
SUB="$(ask HL_SUBACCOUNT_ADDRESS "")"
[ -z "$SUB" ] || [[ "$SUB" =~ ^0x[0-9a-fA-F]{40}$ ]] || { echo "  🔴 子账户地址格式不对"; exit 1; }

echo "── 密钥(隐藏输入)──"
PK="$(secret HL_API_WALLET_PRIVATE_KEY)"
[[ "$PK" =~ ^(0x)?[0-9a-fA-F]{64}$ ]] || { echo "  🔴 API 钱包私钥要是 64 位十六进制"; exit 1; }
TOK="$(secret EXECUTOR_TOKEN)"
[ "${#TOK}" -ge 16 ] || { echo "  🔴 EXECUTOR_TOKEN 太短(从 Railway → Variables 复制)"; exit 1; }
JK="$(secret JAZZ_CALL_KEY)"
if [ -n "$JK" ]; then
  [[ "$JK" =~ ^[0-9a-fA-F]{64}$ ]] || { echo "  🔴 JAZZ_CALL_KEY 要是 64 位十六进制(Mac:python3 scripts/regime_call.py keygen --show)"; exit 1; }
  echo "  JAZZ_CALL_KEY 指纹 $(printf '%s' "cometcloud-regime-call:$JK" | sha256sum | cut -c1-8)(Mac 上 keygen 打印的指纹应相同;上一台主机是 8ec89132)"
else
  echo "  🟡 没填 JAZZ_CALL_KEY:⓪ 判断照记分,但不开 J 票、风险倍数按 1"
fi

echo "── 开关(回车用默认)──"
MODE="$(ask EXECUTOR_MODE live)"
TMODE="$(ask EXECUTOR_TICKETS_MODE live)"
case "$MODE" in live|dry_run) ;; *) echo "  🔴 EXECUTOR_MODE 只能是 live / dry_run"; exit 1 ;; esac
case "$TMODE" in live|dry_run|off) ;; *) echo "  🔴 EXECUTOR_TICKETS_MODE 只能是 live / dry_run / off"; exit 1 ;; esac
VER="$(ask EXECUTOR_VERIFY report)"
HOSTN="$(ask EXECUTOR_HOST_NAME vultr-tokyo)"
TCAP="$(ask EXECUTOR_TICKETS_MAX_EQUITY_USD 1000)"
NCAP="$(ask EXECUTOR_MAX_NAV_USD 3000)"

TMP="$(mktemp /etc/cometcloud/.env.XXXXXX)"
{
  echo "# 写于 $(date -u +'%Y-%m-%d %H:%M UTC'),deploy/executor/write_env.sh。600 root;私钥只在这里。"
  echo "HL_ACCOUNT_ADDRESS=$ACC"
  [ -n "$SUB" ] && echo "HL_SUBACCOUNT_ADDRESS=$SUB"
  echo "HL_API_WALLET_PRIVATE_KEY=$PK"
  echo "EXECUTOR_TOKEN=$TOK"
  [ -n "$JK" ] && echo "JAZZ_CALL_KEY=$JK"
  echo "EXECUTOR_MODE=$MODE"
  echo "EXECUTOR_TICKETS_MODE=$TMODE"
  echo "EXECUTOR_VERIFY=$VER"
  echo "EXECUTOR_HOST_NAME=$HOSTN"
  echo "EXECUTOR_TICKETS_MAX_EQUITY_USD=$TCAP"
  echo "EXECUTOR_MAX_NAV_USD=$NCAP"
} > "$TMP"
chown root:root "$TMP"; chmod 600 "$TMP"; mv "$TMP" "$ENVF"
PK=""; TOK=""; JK=""
echo "  ✅ 写好 $ENVF(600 root)。下一步:bash /opt/cometcloud/repo/deploy/executor/install.sh"
