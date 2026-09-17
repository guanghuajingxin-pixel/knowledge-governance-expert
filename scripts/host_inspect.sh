#!/usr/bin/env bash
# 本机资源巡检（macOS + colima/Docker）
# 用法：
#   ./scripts/host_inspect.sh          # 全量（含服务延迟探测）
#   ./scripts/host_inspect.sh --quick  # 跳过服务延迟探测
# 输出：负载 / 内存 / swap / 宿主 Top 进程 / colima VM / 容器资源 / 服务延迟 / 结论建议
set -uo pipefail

QUICK=0
[ "${1:-}" = "--quick" ] && QUICK=1

hr() { printf '%s\n' "------------------------------------------------------------"; }

echo "== 1. 负载 =="
uptime
CORES=$(sysctl -n hw.ncpu)
LOAD1=$(uptime | sed 's/.*load averages: //' | awk -F' ' '{print $1}')

echo
echo "== 2. 内存 / swap =="
top -l 1 -n 0 | grep -E "PhysMem"
sysctl vm.swapusage
memory_pressure 2>/dev/null | sed -n '2p'

SWAP_LINE=$(sysctl vm.swapusage)
SWAP_TOTAL=$(echo "$SWAP_LINE" | sed 's/.*total = \([0-9.]*\)M.*/\1/')
SWAP_USED=$(echo "$SWAP_LINE" | sed 's/.*used = \([0-9.]*\)M.*/\1/')
SWAP_PCT=$(python3 -c "print(round($SWAP_USED*100/$SWAP_TOTAL))" 2>/dev/null || echo "?")
UNUSED_MB=$(top -l 1 -n 0 | grep PhysMem | sed 's/.*, \([0-9]*\)M unused.*/\1/')

echo
echo "== 3. 宿主 Top10 内存进程 =="
ps -Ao rss,pmem,comm -m | head -11 | awk '{printf "%8.0fMB  %5.1f%%  ", $1/1024, $2; for(i=3;i<=NF;i++) printf "%s ", $i; print ""}'
echo "-- Top10 CPU 进程 --"
ps -Ao pcpu,rss,comm -r | head -11 | awk '{printf "%6.1f%%  %8.0fMB  ", $1, $2/1024; for(i=3;i<=NF;i++) printf "%s ", $i; print ""}'

echo
echo "== 4. colima 虚拟机进程 =="
ps -Ao pid,pcpu,rss,comm | grep -i "Virtualization.VirtualMachine" | grep -v grep | awk '{printf "pid=%s cpu=%s%% rss=%.0fMB\n", $1, $2, $3/1024}'

echo
echo "== 5. 容器资源（按内存降序）=="
if command -v docker >/dev/null 2>&1; then
  docker stats --no-stream --format "{{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}" 2>/dev/null \
    | sort -t$'\t' -k3 -h -r | awk -F'\t' '{printf "%-28s %8s  %s\n", $1, $2, $3}'
  echo "运行中容器数: $(docker ps -q | wc -l | tr -d ' ')"
else
  echo "docker 不可用"
fi

if [ "$QUICK" = "0" ]; then
  echo
  echo "== 6. 服务延迟探测 =="
  probe() { printf "%-42s " "$1"; curl -s -m 30 -o /dev/null -w "%{http_code}  %{time_total}s\n" "$2"; }
  probe "kb-api  :8000/health" http://localhost:8000/health
  probe "web     :3000/"       http://localhost:3000/
  probe "mineru-kit :8010"     http://127.0.0.1:8010/v1/health
  probe "mineru-webui :7860"   http://127.0.0.1:7860/
  PG_START=$(python3 -c "import time;print(time.time())")
  docker exec dev-postgres psql -U dev -d dev_db -tAc "select 1" >/dev/null 2>&1 && PG_OK=yes || PG_OK=no
  PG_END=$(python3 -c "import time;print(time.time())")
  printf "%-42s %s  %.3fs\n" "dev-postgres (docker exec)" "$PG_OK" "$(python3 -c "print($PG_END-$PG_START)")"
fi

echo
echo "== 7. 结论 =="
WARN=0
if [ "$SWAP_PCT" != "?" ] && [ "$SWAP_PCT" -ge 75 ]; then
  echo "[WARN] swap 已用 ${SWAP_PCT}%（${SWAP_USED}M/${SWAP_TOTAL}M）：内存长期超卖，建议关闭闲置重应用并择机重启 Mac 清零 swap/压缩机"
  WARN=1
fi
if [ "${UNUSED_MB:-0}" -lt 500 ]; then
  echo "[WARN] 物理内存未用仅 ${UNUSED_MB}M：处于耗尽边缘，新峰值会触发抖动"
  WARN=1
fi
if python3 -c "exit(0 if $LOAD1 > $CORES else 1)" 2>/dev/null; then
  echo "[WARN] 1min 负载 ${LOAD1} 超过核心数 ${CORES}：存在 CPU 排队"
  WARN=1
fi
[ "$WARN" = "0" ] && echo "[OK] 负载/内存/swap 均在安全水位"
hr
echo "提示：Dify 栈恢复命令 = cd dify/docker && docker compose start ；停止 = docker compose stop"
