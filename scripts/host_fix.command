#!/bin/bash
# 双击:修东京主机的两件事 —— ① SSH 443 没监听(Connection refused)② HL_ACCOUNT_ADDRESS 改成主钱包地址 —— 然后重跑安装自检。
# 你只需要:必要时断开 VPN、输一次 root 密码。
IP="45.32.39.6"
MAIN="0x958ba81eb9660a92699d5a2cb7ba8c278592524d"   # HL 自检里 agent_of 给出的主账户(10-19 记录 0x958B…524D)
SOCK="/tmp/cc-fix-$$"
OPTS=(-o ConnectTimeout=10 -o StrictHostKeyChecking=accept-new -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if ssh "${OPTS[@]}" -p "$p" "root@$IP" true; then PORT="$p"; break; fi
  [ "$p" = 443 ] && echo "443 还没开(这正是要修的)。**断开 VPN**,然后回车走 22。" && read -r -p "回车继续 "
done
[ -n "$PORT" ] || { echo "连不上 —— 看 Vultr 上机器是否 Running。"; read -r -p "回车关闭"; exit 1; }

ssh "${OPTS[@]}" -p "$PORT" "root@$IP" "MAIN=$MAIN bash -s" <<'REMOTE'
set -u
echo "── 1/3 SSH 443 ──"
listening() { ss -tln | grep -qE "[:.]443[[:space:]]"; }
systemctl daemon-reload
if systemctl is-active --quiet ssh.socket; then
  echo "SSH 由 ssh.socket 监听(Ubuntu 新版的做法,端口要在 socket 上开)"
  systemctl restart ssh.socket || true          # 生成器会把 sshd_config 里的 Port 443 带进 socket
  sleep 1
  if ! listening; then
    D=/etc/systemd/system/ssh.socket.d; mkdir -p "$D"
    printf '[Socket]\nListenStream=0.0.0.0:443\nListenStream=[::]:443\n' > "$D/10-cometcloud-443.conf"
    systemctl daemon-reload
    if ! systemctl restart ssh.socket; then       # 起不来就撤回,保住 22
      rm -f "$D/10-cometcloud-443.conf"; systemctl daemon-reload; systemctl restart ssh.socket
      echo "🔴 socket 上开 443 失败,已撤回(22 照常)"
    fi
  fi
else
  grep -qsE '^[[:space:]]*Port[[:space:]]+443' /etc/ssh/sshd_config /etc/ssh/sshd_config.d/*.conf \
    || printf 'Port 22\nPort 443\n' > /etc/ssh/sshd_config.d/10-cometcloud-ports.conf
  sshd -t && (systemctl restart ssh 2>/dev/null || systemctl restart sshd)
fi
command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active" && ufw allow 443/tcp >/dev/null
sleep 1
ss -tln | grep -E "[:.](22|443)[[:space:]]" | awk '{print "  监听", $4}'
listening && echo "✅ 443 在监听" || echo "🔴 443 还是没开 —— 把上面几行发给 Seth"

echo "── 2/3 主钱包地址 ──"
sed -i "s/^HL_ACCOUNT_ADDRESS=.*/HL_ACCOUNT_ADDRESS=$MAIN/" /etc/cometcloud/executor.env
grep -c "^HL_ACCOUNT_ADDRESS=$MAIN" /etc/cometcloud/executor.env >/dev/null && echo "✅ 已改为主钱包"

echo "── 3/3 更新代码 + 自检 + 启动 ──"
bash /opt/cometcloud/repo/deploy/executor/install.sh
REMOTE
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "完成。把上面的输出(尤其 agent / balances / 三个服务的状态)发给 Seth。"
read -r -p "回车关闭"
