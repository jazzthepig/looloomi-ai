#!/bin/bash
# 双击即用:连上东京执行主机并跑一键安装(deploy/executor/bootstrap.sh)。
# 你只需要输入两类东西:① 服务器 root 密码(Vultr → Overview 复制);② write_env.sh 问的私钥 / token。
# 其余命令都由本脚本发出 —— 不经过 Vultr 网页控制台(它的键盘映射会打错符号)。
cd "$(dirname "$0")/.." || exit 1
BOOT="deploy/executor/bootstrap.sh"
[ -f "$BOOT" ] || { echo "找不到 $BOOT"; read -r -p "回车关闭"; exit 1; }

read -r -p "服务器 IP [45.32.39.6]: " IP
IP="${IP:-45.32.39.6}"
SOCK="/tmp/cc-host-$$"
OPTS=(-o ConnectTimeout=10 -o ServerAliveInterval=30 -o StrictHostKeyChecking=accept-new
      -o ControlMaster=auto -o "ControlPath=$SOCK" -o ControlPersist=120)

try() {  # try PORT → 0 = 连上
  ssh "${OPTS[@]}" -p "$1" "root@$IP" true 2>/tmp/cc-host-err-$$
}

PORT=""
for p in 443 22; do
  echo "── 试端口 $p ──"
  if try "$p"; then PORT="$p"; break; fi
  if grep -q "REMOTE HOST IDENTIFICATION HAS CHANGED" /tmp/cc-host-err-$$; then
    echo "主机指纹变了 —— 机器重建过时这是正常的。"
    read -r -p "确认是重建过的那台、删掉旧指纹再连?[y/N] " yn
    if [ "$yn" = "y" ]; then
      ssh-keygen -R "$IP" >/dev/null 2>&1; ssh-keygen -R "[$IP]:$p" >/dev/null 2>&1
      try "$p" && { PORT="$p"; break; }
    fi
  fi
  tail -2 /tmp/cc-host-err-$$
  [ "$p" = 443 ] && echo "443 不通:多半是新机器只开了 22。**如果 VPN 开着,现在断开它**,然后回车试 22。" && read -r -p "回车继续 "
done
rm -f /tmp/cc-host-err-$$
[ -n "$PORT" ] || { echo "两个端口都连不上 —— 看 Vultr 上机器是否 Running、IP 对不对。"; read -r -p "回车关闭"; exit 1; }

echo "── 连上了(端口 $PORT),上传安装脚本 ──"
scp "${OPTS[@]}" -P "$PORT" -q "$BOOT" "root@$IP:/root/b.sh" || { echo "上传失败"; read -r -p "回车关闭"; exit 1; }
echo "── 在主机上运行(要你输入私钥 / token 时,输入不显示)──"
ssh "${OPTS[@]}" -t -p "$PORT" "root@$IP" "bash /root/b.sh"
ssh "${OPTS[@]}" -O exit -p "$PORT" "root@$IP" >/dev/null 2>&1
echo
echo "完成。以后连:ssh -p 443 root@$IP(VPN 开着也行)。把上面自检的输出告诉 Seth。"
read -r -p "回车关闭"
