#!/bin/bash
# 双击:东京主机 ① 拉最新代码、自检、重启执行器 ② 跑一次「现货止损触发单」探针(Jazz 11-02「先直接在这个主机做测试」)。
# 探针在真钱账户上挂两张 XAUT0 卖出止损(触发价 = 现价 × 50%、限价 × 45%,不会成交),几秒后撤掉,报回挂没挂上、hold 有没有被锁、撤没撤掉。
# 你只需要:输一次 root 密码(VPN 开着也行,走 443)。不要在 UTC 00:00–01:00 跑(每日一轮)。
IP="45.32.39.6"
SOCK="/tmp/cc-probe-$$"
OUT="/tmp/cc-probe-out-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)
PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if ssh "${OPTS[@]}" -p "$p" "root@$IP" true; then PORT="$p"; break; fi
  [ "$p" = 443 ] && echo "443 不通 —— 断开 VPN 后回车走 22。" && read -r -p "回车继续 "
done
[ -n "$PORT" ] || { echo "连不上 —— 看 Vultr 上机器是否 Running。"; read -r -p "回车关闭"; exit 1; }
ssh "${OPTS[@]}" -p "$PORT" "root@$IP" "bash -s" <<'REMOTE' 2>&1 | tee "$OUT"
set -eu
ENVF=/etc/cometcloud/executor.env
REPO=/opt/cometcloud/repo
VENV=/opt/cometcloud/venv
bash "$REPO/deploy/executor/install.sh"
echo "── 现货触发单探针 ──"
systemd-run --quiet --wait --pipe --collect \
  -p User=cometcloud -p Group=cometcloud \
  -p EnvironmentFile="$ENVF" -p StateDirectory=cometcloud \
  -p Environment=EXECUTOR_STATE_DIR=/var/lib/cometcloud -p Environment=HOME=/var/lib/cometcloud \
  -p Environment=PYTHONDONTWRITEBYTECODE=1 -p WorkingDirectory="$REPO" \
  "$VENV/bin/python" -m src.exec_host.probe_spot_trigger --token XAUT0 --yes
REMOTE
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "── 要看的几行 ──"
grep -E '^代码:' "$OUT" | head -1
grep -A 8 '"answers"' "$OUT" | head -9
grep -E '"left_open"|"why"' "$OUT" | head -3
grep -E "Active:" "$OUT" | head -3
rm -f "$OUT"
echo
echo "left_open 必须是 []。不是 [] ⇒ 去 HL 网页「Open Orders」把那几张撤掉。结果 Railway 那边也收到了,不用发给 Seth。"
read -r -p "回车关闭"
