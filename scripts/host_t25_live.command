#!/bin/bash
# 双击:东京主机把 T25 黄金 / 股票腿切成真单(EXECUTOR_T25_MODE=live),重启执行器。
# 先跑过 host_set_navcap.command、Seth 核过空跑意图之后再点这个。切完之后执行器当场跑一轮(当天空跑过也会):
# 在 HL 现货上 IOC 买 XAUT0(约 $120)和 SPYX(约 $180),限价离中间价 0.5% 以内,吃不到就作废、不挂单。
# 只改这一行;私钥 / token 不动。要退回空跑:把下面 MODE 改成 dry_run 再点一次。
IP="45.32.39.6"
MODE="live"
SOCK="/tmp/cc-t25-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

echo "这会让东京执行器在 HL 现货上下真单(黄金约 \$120、股票约 \$180)。"
read -r -p "确认切 $MODE 就输入 yes 回车:" OKAY
[ "$OKAY" = "yes" ] || { echo "没切。"; read -r -p "回车关闭"; exit 0; }

PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if ssh "${OPTS[@]}" -p "$p" "root@$IP" true; then PORT="$p"; break; fi
  [ "$p" = 443 ] && echo "443 不通 —— 断开 VPN 后回车走 22。" && read -r -p "回车继续 "
done
[ -n "$PORT" ] || { echo "连不上 —— 看 Vultr 上机器是否 Running。"; read -r -p "回车关闭"; exit 1; }

ssh "${OPTS[@]}" -p "$PORT" "root@$IP" "MODE=$MODE bash -s" <<'REMOTE'
set -eu
ENVF=/etc/cometcloud/executor.env
if grep -q '^EXECUTOR_T25_MODE=' "$ENVF"; then
  sed -i "s/^EXECUTOR_T25_MODE=.*/EXECUTOR_T25_MODE=$MODE/" "$ENVF"
else
  echo "EXECUTOR_T25_MODE=$MODE" >> "$ENVF"
fi
echo "── env ──"; grep '^EXECUTOR_T25_MODE=' "$ENVF"
systemctl restart cometcloud-executor
sleep 45
echo "── 执行器 ──"
systemctl is-active cometcloud-executor
journalctl -u cometcloud-executor --since "-1 min" --no-pager | grep -E "t25 cycle|executor up|ERROR|Traceback" || true
REMOTE
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "应看到 EXECUTOR_T25_MODE=$MODE、active、一行「t25 cycle … 2 orders」。Telegram 会收到「T25 腿真单」那条。把这几行发给 Seth。"
read -r -p "回车关闭"
