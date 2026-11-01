#!/bin/bash
# 双击:东京主机 ① 设 EXECUTOR_MAX_NAV_USD(主机侧的记账净值天花板)② 拉最新代码、自检、重启。
# 只改 nav_cap 这一行;私钥 / token 不动。你只需要:输一次 root 密码(VPN 开着也行,走 443)。
IP="45.32.39.6"
# 11-01 起资本跟着真钱快照走(加钱当天再平衡);这个数只是主机侧的天花板(X1V 实际额度 = min(它, 组合层加密腿额度))。
# 加钱之后把它抬到够用的高度即可 —— 输入新值,回车用默认。
read -r -p "EXECUTOR_MAX_NAV_USD(回车 = 600): " CAP_IN
CAP="${CAP_IN:-600}"
case "$CAP" in ''|*[!0-9.]*) echo "要一个数字"; read -r -p "回车关闭"; exit 1 ;; esac
SOCK="/tmp/cc-cap-$$"
OUT="/tmp/cc-cap-out-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if ssh "${OPTS[@]}" -p "$p" "root@$IP" true; then PORT="$p"; break; fi
  [ "$p" = 443 ] && echo "443 不通 —— 断开 VPN 后回车走 22。" && read -r -p "回车继续 "
done
[ -n "$PORT" ] || { echo "连不上 —— 看 Vultr 上机器是否 Running。"; read -r -p "回车关闭"; exit 1; }

ssh "${OPTS[@]}" -p "$PORT" "root@$IP" "CAP=$CAP bash -s" <<'REMOTE' 2>&1 | tee "$OUT"
set -eu
ENVF=/etc/cometcloud/executor.env
if grep -q '^EXECUTOR_MAX_NAV_USD=' "$ENVF"; then
  sed -i "s/^EXECUTOR_MAX_NAV_USD=.*/EXECUTOR_MAX_NAV_USD=$CAP/" "$ENVF"
else
  echo "EXECUTOR_MAX_NAV_USD=$CAP" >> "$ENVF"
fi
echo "── env ──"
grep -E '^EXECUTOR_(MAX_NAV_USD|T25_MODE)=' "$ENVF" || true
bash /opt/cometcloud/repo/deploy/executor/install.sh
REMOTE
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "── 要看的几行 ──"
grep -E '^EXECUTOR_MAX_NAV_USD=|^代码:|"nav_cap":' "$OUT" | head -4
grep -A 3 '"nav_cap_effective"' "$OUT" | head -4
grep -A 40 '"t25": {' "$OUT" | head -40
grep -E "Active:" "$OUT" | head -3
rm -f "$OUT"
echo
echo "应看到 EXECUTOR_MAX_NAV_USD=$CAP、nav_cap $CAP、t25 段、三个服务 active。把这几行发给 Seth。"
read -r -p "回车关闭"
