#!/bin/bash
# Seth 的一键停(Jazz 11-01「要的」)。只能停,不能解除 —— 解除是 Jazz 的事(正常 token)。
# token 值不经过聊天、不进仓库:Jazz 在 Railway 配 INTERNAL_TOKEN_HALT 之后,把同一个值存成
#   ~/Projects/looloomi-ai/.seth_bot/halt_token      (.seth_bot/ 已 gitignore;一行,无空格)
# 沙盒里这个文件读得到,所以 Seth 停得了,但从来不用看见它。
#
# 用法:bash scripts/seth_halt.sh "为什么停(一句话)"
set -eu
API="${COMETCLOUD_API:-https://web-production-0cdf76.up.railway.app}"
HERE="$(cd "$(dirname "$0")/.." && pwd)"
TOK_FILE="$HERE/.seth_bot/halt_token"
REASON="${1:-}"
[ -n "$REASON" ] || { echo "要一句原因:bash scripts/seth_halt.sh \"…\""; exit 2; }
[ -s "$TOK_FILE" ] || { echo "没有 $TOK_FILE —— Jazz 先把 INTERNAL_TOKEN_HALT 的值存进去(一行)"; exit 3; }
BODY=$(python3 -c 'import json,sys; print(json.dumps({"halted": True, "reason": sys.argv[1][:300]}, ensure_ascii=False))' "$REASON")
curl -sS -m 20 -X POST "$API/internal/executor/halt" \
  -H "Content-Type: application/json" -H "X-Internal-Token: $(tr -d '[:space:]' < "$TOK_FILE")" \
  -d "$BODY"
echo
echo "回了 ok + by halt 就是停了(Telegram 同时有一条 HALTED);主机每轮开头读 flag,≤15 分钟生效。解除由 Jazz 用正常 token。"
