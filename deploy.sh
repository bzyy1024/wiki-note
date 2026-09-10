#!/usr/bin/env bash
# ============================================================
# wiki-note 服务器一键部署脚本（零参数）
#
# 用法:
#   bash deploy.sh                          # 前台执行，日志直接打印到终端
#   bash deploy.sh 2>&1 | tee deploy.log    # 需要留档时这样跑
#
# 说明:
#   - 单实例锁：已有部署在跑时，重复执行自动跳过
#   - bake 模式：全量构建发生在 docker build 阶段，旧容器
#     全程在线，构建完成后切换，站点中断窗口≈秒级
#   - 部署完自动轮询容器健康，就绪才结束
# ============================================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOCK=/tmp/wiki-note-deploy.lock

# ---- 1. 单实例锁：已有部署在跑则跳过 ----
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "[$(date '+%F %T')] 已有部署任务在运行，本次跳过" >&2
  exit 0
fi

# ---- 2. 正式部署流程 ----
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
