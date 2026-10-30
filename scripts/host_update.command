#!/bin/bash
# 双击:东京主机拉最新代码、自检、重启三个服务(deploy/executor/install.sh)。不改 env、不碰私钥。
# 10-29 这一版:统一账户的净值改从现货 USDC 读(R-v2 原来读成 0);X1V 只用加密腿额度 $180;R-v2 名义 ≤ 净值 30%。
# 你只需要:输一次 root 密码(VPN 开着也行,走 443)。
#
# 10-30:443 报「REMOTE HOST IDENTIFICATION HAS CHANGED」—— known_hosts 里 [IP]:443 那条是**重建之前那台旧机器**的钥匙
# (10-29 重建时只在 22 上认了新机器)。脚本先核:443 现在给出的钥匙 = 昨天在 22 上认过的新机器钥匙 ⇒ 才删掉旧记录重连;
# 对不上就停下,不连。
IP="45.32.39.6"
SOCK="/tmp/cc-upd-$$"
ERR="/tmp/cc-upd-err-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

try443() { ssh "${OPTS[@]}" -p 443 "root@$IP" true 2>"$ERR"; }

PORT=""
echo "── 试端口 443 ──"
if try443; then
  PORT=443
elif grep -q "REMOTE HOST IDENTIFICATION HAS CHANGED" "$ERR"; then
  # 只抠 SHA256:… 那一段 —— macOS 的 `ssh-keygen -F -l` 输出列序与 Linux 不同(第一版按第 2 列取,在 Mac 上取到的是「ED25519」)
  NEW=$(ssh-keyscan -T 10 -t ed25519 -p 443 "$IP" 2>/dev/null | ssh-keygen -lf - 2>/dev/null | grep -oE 'SHA256:[A-Za-z0-9+/=]+' | head -1)
  KNOWN=$(ssh-keygen -F "$IP" -l 2>/dev/null | grep -v '^#' | grep -i 'ED25519' | grep -oE 'SHA256:[A-Za-z0-9+/=]+' | head -1)
  echo "443 现在给出的钥匙:   ${NEW:-读不到}"
  echo "昨天在 22 上认过的钥匙:${KNOWN:-没有记录}"
  if [ -n "$NEW" ] && [ "$NEW" = "$KNOWN" ]; then
    echo "✅ 是同一台机器(10-29 重建后的新机器)—— 删掉 known_hosts 里 [$IP]:443 那条旧钥匙,重连"
    ssh-keygen -R "[$IP]:443" >/dev/null 2>&1
    try443 && PORT=443
  else
    echo "🔴 两把钥匙对不上(或读不到)—— 不连。把上面两行发给 Seth。"
    rm -f "$ERR"; read -r -p "回车关闭"; exit 1
  fi
else
  tail -2 "$ERR"
fi
if [ -z "$PORT" ]; then
  echo "443 不通 —— 断开 VPN 后回车走 22(VPN 开着时 22 会 Connection refused)。"
  read -r -p "回车继续 "
  echo "── 试端口 22 ──"
  ssh "${OPTS[@]}" -p 22 "root@$IP" true && PORT=22
fi
rm -f "$ERR"
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
