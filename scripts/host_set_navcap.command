#!/bin/bash
# 双击:东京主机 ① EXECUTOR_MAX_NAV_USD 改成 600(Jazz 10-30「change the nav_cap to 600」= T25 起始资金)
# ② 拉最新代码(T25 黄金 / 股票腿接进执行器,EXECUTOR_T25_MODE 默认 dry_run —— 只记意图、不下单)、自检、重启。
# 只改 nav_cap 这一行;私钥 / token 不动。你只需要:输一次 root 密码(VPN 开着也行,走 443)。
# 改完之后 X1V 实际用的仍是 min(600, 组合层加密腿额度 $180) = $180;600 是整个执行器记账净值的天花板。
IP="45.32.39.6"
CAP="600"
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
echo "应看到 EXECUTOR_MAX_NAV_USD=600、nav_cap 600.0、t25 段 mode = dry_run、pairs XAUT0 @182 / SPYX @703、"
echo "would_trade 两笔(黄金约 \$120、股票约 \$180)、三个服务 active。这是空跑:不下单。把这几行发给 Seth。"
read -r -p "回车关闭"
