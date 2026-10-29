#!/bin/bash
# 双击:东京主机拉最新代码、自检、重启三个服务(deploy/executor/install.sh)。不改 env、不碰私钥。
# 10-29 这一版:统一账户的净值改从现货 USDC 读(R-v2 原来读成 0);X1V 只用加密腿额度 $180;R-v2 名义 ≤ 净值 30%。
# 你只需要:输一次 root 密码(VPN 开着也行,走 443)。
IP="45.32.39.6"
SOCK="/tmp/cc-upd-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if ssh "${OPTS[@]}" -p "$p" "root@$IP" true; then PORT="$p"; break; fi
  [ "$p" = 443 ] && echo "443 不通 —— 断开 VPN 后回车走 22。" && read -r -p "回车继续 "
done
[ -n "$PORT" ] || { echo "连不上 —— 看 Vultr 上机器是否 Running。"; read -r -p "回车关闭"; exit 1; }

ssh "${OPTS[@]}" -p "$PORT" "root@$IP" "bash /opt/cometcloud/repo/deploy/executor/install.sh" 2>&1 | tee /tmp/cc-upd-out-$$
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "── 要看的三行 ──"
grep -E '"(mode|basis|equity)":' /tmp/cc-upd-out-$$ | head -6
grep -A 3 '"nav_cap_effective"' /tmp/cc-upd-out-$$ | head -4
grep -E "Active:" /tmp/cc-upd-out-$$ | head -3
rm -f /tmp/cc-upd-out-$$
echo
echo "perp_account 里应是 mode = unifiedAccount、equity ≈ 630;nav_cap_effective = 180。把这几行发给 Seth。"
read -r -p "回车关闭"
