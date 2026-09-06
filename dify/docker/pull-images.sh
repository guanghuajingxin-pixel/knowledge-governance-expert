#!/usr/bin/env bash
# 逐个拉取 Dify 所需镜像，单镜像失败自动重试，已下载层会续传。
# 用法：./pull-images.sh
set -u
IMAGES=(
  "busybox:latest"
  "nginx:latest"
  "postgres:15-alpine"
  "redis:6-alpine"
  "ubuntu/squid:latest"
  "semitechnologies/weaviate:1.27.0"
  "langgenius/dify-sandbox:0.2.15"
  "langgenius/dify-plugin-daemon:0.6.3-local"
  "langgenius/dify-web:1.16.1"
  "langgenius/dify-api:1.16.1"
  "langgenius/dify-agent-backend:1.16.1"
  "langgenius/dify-agent-local-sandbox:1.16.1"
)
MAX_RETRY=20
for img in "${IMAGES[@]}"; do
  if docker image inspect "$img" >/dev/null 2>&1; then
    echo "[SKIP] $img 已存在"
    continue
  fi
  ok=0
  for i in $(seq 1 $MAX_RETRY); do
    echo "[PULL $i/$MAX_RETRY] $img"
    if docker pull "$img" 2>&1 | tail -3; then
      if docker image inspect "$img" >/dev/null 2>&1; then
        echo "[OK] $img"
        ok=1
        break
      fi
    fi
    echo "[RETRY] $img 第 $i 次失败，3s 后重试"
    sleep 3
  done
  if [ "$ok" -eq 0 ]; then
    echo "[FAIL] $img 重试 $MAX_RETRY 次仍失败"
    exit 1
  fi
done
echo "[ALL DONE] 全部镜像拉取完成"
