#!/usr/bin/env bash
# ============================================================
# wiki-note 服务器一键部署脚本（零参数）
#
# 用法:
#   bash deploy.sh
#
# 特性:
#   - 自动转入后台运行，SSH 断开/关终端均不影响
#   - 单实例锁：已有部署在跑时，重复执行自动跳过
#   - bake 模式：全量构建发生在 docker build 阶段，旧容器
#     全程在线，构建完成后切换，站点中断窗口≈秒级
#   - 部署完自动轮询容器健康，就绪才结束
#
# 日志: /tmp/wiki-note-deploy.log
# 实时查看: tail -f /tmp/wiki-note-deploy.log
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG=/tmp/wiki-note-deploy.log
LOCK=/tmp/wiki-note-deploy.lock

# ---- 1. 未处于后台模式时，把自己转入后台后立即退出 ----
if [[ "${DEPLOY_BG:-0}" != "1" ]]; then
  DEPLOY_BG=1 nohup bash "$SCRIPT_DIR/deploy.sh" >"$LOG" 2>&1 &
  echo "[deploy] 已转入后台运行 (pid $!)，可安全断开终端"
  echo "[deploy] 日志: $LOG"
  echo "[deploy] 实时查看: tail -f $LOG"
  exit 0
fi

# ---- 2. 单实例锁：已有部署在跑则跳过 ----
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 已有部署任务在运行，本次跳过。日志见 $LOG" >&2
  exit 0
fi

# ---- 3. 正式部署流程 ----
{
  echo "===== $(date '+%F %T') deploy start ====="
  cd "$SCRIPT_DIR"

  echo ">> git pull"
  git pull

  echo ">> docker compose up -d --build（旧容器在线，构建完成后秒级切换）"
  docker compose up -d --build

  echo ">> 轮询容器健康状态..."
  for i in $(seq 1 36); do
    st="$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' wiki-note 2>/dev/null || true)"
    echo "[$(date '+%H:%M:%S')] 第 $i 次检查: $st"
    if [[ "$st" == "healthy" || "$st" == "running" ]]; then
      echo ">> 部署完成，站点已就绪: http://<服务器IP>:8826"
      exit 0
    fi
    sleep 5
  done

  echo "!! 等待容器健康超时，当前状态:" >&2
  docker compose ps >&2
  exit 1
} >>"$LOG" 2>&1
