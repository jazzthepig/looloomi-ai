#!/usr/bin/env bash
# 东京主机一键装好(重建后用;已装好的机器上跑也安全,每一步都先看再做)。以 root 运行:
#   curl -fsSL https://raw.githubusercontent.com/jazzthepig/looloomi-ai/main/deploy/executor/bootstrap.sh -o b.sh && bash b.sh
# 做四件事:① 装 git / python3-venv ② SSH 同时开 22 和 443(你的 VPN 封了 22;不关 22,免得把自己锁在外面)
#           ③ 拉代码 ④ 没有 env 就问你要值(write_env.sh,隐藏输入)→ install.sh(自检 → 起服务)
set -euo pipefail
[ "$(id -u)" = 0 ] || { echo "需要 root"; exit 1; }
REPO=/opt/cometcloud/repo
say() { printf '\n── %s ──\n' "$*"; }

say "1/4 系统包"
if ! command -v git >/dev/null || ! python3 -c "import venv, ensurepip" >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -qq
  apt-get install -y -qq git python3-venv curl
fi
echo "git $(git --version | cut -d' ' -f3) · $(python3 --version)"

say "2/4 SSH 端口(22 + 443)"
CONF_FILES="/etc/ssh/sshd_config $(ls /etc/ssh/sshd_config.d/*.conf 2>/dev/null || true)"
if grep -qsE '^[[:space:]]*Port[[:space:]]+443([[:space:]]|$)' $CONF_FILES; then
  echo "已经在 443 上,不改"
else
  if grep -qsE '^[[:space:]]*Port[[:space:]]+' $CONF_FILES; then PORTS="Port 443"; else PORTS=$'Port 22\nPort 443'; fi
  if [ -d /etc/ssh/sshd_config.d ] && grep -qE '^[[:space:]]*Include[[:space:]]+/etc/ssh/sshd_config.d' /etc/ssh/sshd_config; then
    printf '%s\n' "$PORTS" > /etc/ssh/sshd_config.d/10-cometcloud-ports.conf
  else
    printf '%s\n' "$PORTS" >> /etc/ssh/sshd_config
  fi
  sshd -t                                   # 配置写错就停在这里,不重启
  # Ubuntu 22.10 之后 SSH 由 ssh.socket 监听,端口不看 sshd_config —— 有它就关掉,改由 ssh.service 自己监听
  if systemctl is-enabled ssh.socket >/dev/null 2>&1; then
    systemctl disable --now ssh.socket
    systemctl enable ssh.service >/dev/null 2>&1 || true
  fi
  systemctl restart ssh.service 2>/dev/null || systemctl restart sshd
  echo "已改,当前连接不会断"
fi
if command -v ufw >/dev/null && ufw status 2>/dev/null | grep -q "Status: active"; then
  ufw allow 443/tcp >/dev/null && echo "防火墙 ufw 已放行 443"
fi
ss -tlnp | grep -E 'sshd|ssh' | awk '{print "  监听", $4}' || true

say "3/4 代码"
mkdir -p /opt/cometcloud
if [ -d "$REPO/.git" ]; then
  git -C "$REPO" fetch -q --depth 1 origin main && git -C "$REPO" reset -q --hard origin/main
else
  git clone -q --depth 1 https://github.com/jazzthepig/looloomi-ai.git "$REPO"
fi
echo "$(git -C "$REPO" log -1 --format='%h %s' | cut -c1-80)"

say "4/4 执行器"
if [ -f /etc/cometcloud/executor.env ]; then
  echo "/etc/cometcloud/executor.env 在(主机是从原盘恢复的)—— 不重写,直接更新并重启"
else
  bash "$REPO/deploy/executor/write_env.sh" < /dev/tty
fi
bash "$REPO/deploy/executor/install.sh"
