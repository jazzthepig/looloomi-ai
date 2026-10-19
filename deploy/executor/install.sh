#!/usr/bin/env bash
# 东京主机:安装或更新执行器(T-015)。以 root 运行,幂等。
#   首次:git clone --depth 1 https://github.com/jazzthepig/looloomi-ai.git /opt/cometcloud/repo && bash /opt/cometcloud/repo/deploy/executor/install.sh
#   更新:bash /opt/cometcloud/repo/deploy/executor/install.sh
# 顺序:拉代码 → 装依赖 → 装 systemd 单元 → 自检(不下单,发一条心跳)→ 自检通过才(重)启服务。
# 整个脚本包在 main 里:git reset 会改写这个文件本身,bash 先读完函数再执行,不会读到一半换了内容。
set -euo pipefail

main() {
  local REPO=/opt/cometcloud/repo VENV=/opt/cometcloud/venv ENVF=/etc/cometcloud/executor.env
  [ "$(id -u)" = 0 ] || { echo "需要 root"; exit 1; }
  # 建 env 文件时用过 umask 077:同一个 shell 里建的 venv / 克隆的仓库会是 600,服务用户读不了
  umask 022
  [ -f "$ENVF" ] || { echo "缺 $ENVF"; exit 1; }
  id cometcloud >/dev/null 2>&1 || useradd --system --create-home --shell /usr/sbin/nologin cometcloud
  if [ -d "$REPO/.git" ]; then
    git -C "$REPO" fetch -q --depth 1 origin main
    git -C "$REPO" reset -q --hard origin/main
  else
    git clone -q --depth 1 https://github.com/jazzthepig/looloomi-ai.git "$REPO"
  fi
  echo "代码: $(git -C "$REPO" log -1 --format='%h %s' | cut -c1-90)"
  [ -x "$VENV/bin/python" ] || python3 -m venv "$VENV"
  "$VENV/bin/pip" install -q --upgrade pip
  "$VENV/bin/pip" install -q -r "$REPO/deploy/executor/requirements.txt"
  chmod -R go+rX "$REPO" "$VENV"
  install -m 644 "$REPO/deploy/executor/cometcloud-executor.service" /etc/systemd/system/cometcloud-executor.service
  # T-129 / T-130:只读的录制器(盘口与成交、头部账户持仓)。不读私钥;文件在才装。
  local EXTRA=()
  for u in cometcloud-recorder cometcloud-whales; do
    if [ -f "$REPO/deploy/executor/$u.service" ]; then
      install -m 644 "$REPO/deploy/executor/$u.service" "/etc/systemd/system/$u.service"
      EXTRA+=("$u")
    fi
  done
  systemctl daemon-reload
  echo "── 自检(不下单)──"
  systemd-run --quiet --wait --pipe --collect \
    -p User=cometcloud -p Group=cometcloud \
    -p EnvironmentFile="$ENVF" -p StateDirectory=cometcloud \
    -p Environment=EXECUTOR_STATE_DIR=/var/lib/cometcloud -p Environment=HOME=/var/lib/cometcloud \
    -p Environment=PYTHONDONTWRITEBYTECODE=1 -p WorkingDirectory="$REPO" \
    "$VENV/bin/python" -m src.exec_host.runner --check
  systemctl enable -q cometcloud-executor
  systemctl restart cometcloud-executor
  for u in "${EXTRA[@]}"; do
    systemctl enable -q "$u"
    systemctl restart "$u"
  done
  sleep 3
  systemctl --no-pager --lines=8 status cometcloud-executor "${EXTRA[@]}" || true
  echo "── 完成。日志:journalctl -u cometcloud-executor -f ──"
}

main "$@"
