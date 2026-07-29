#!/usr/bin/env bash
# scripts/smoke_test.sh - End-to-end smoke test for the KB MVP.
#
# Runs in DEV MODE: starts kb-api (8000), kb-worker (celery), faq-service (8004)
# natively via uv, and expects Docker dev infra (postgres/redis/elasticsearch/
# minio/kkfileview on the dev-network) to already be running.
#
# Why not Docker full-mode? BGE-M3 + bge-reranker-v2-m3 load in the kb-api
# process (~2-3GB RSS). colima needs >=8GB to host that in-container - the
# dev-mode (native) path uses Mac RAM directly and is the recommended fast-
# iteration loop. See README.md for the Docker full-mode tradeoff.
#
# Usage:
#   ./scripts/smoke_test.sh                # start services, run, tear down
#   KEEP_SERVICES=1 ./scripts/smoke_test.sh  # leave services running after
#   EXTERNAL_SERVICES=1 ./scripts/smoke_test.sh  # services already running externally
#
# Expected output: SMOKE OK (chat step returns a friendly fallback when
# LLM_API_KEY is empty - non-blocking, accepted gate).
set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
KB_API_DIR="$REPO_ROOT/services/kb-api"
FAQ_DIR="$REPO_ROOT/services/faq-service"
KB_API=http://127.0.0.1:8000
FAQ_API=http://127.0.0.1:8004
LOG_DIR="${SMOKE_LOG_DIR:-/tmp/kb-smoke}"
mkdir -p "$LOG_DIR"

PIDS=()

cleanup() {
  if [ -n "${KEEP_SERVICES:-}" ]; then
    echo "[cleanup] KEEP_SERVICES=1 - leaving services running (pids: ${PIDS[*]:-none})"
    return
  fi
  for pid in "${PIDS[@]:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
    fi
  done
  # Give them a moment, then SIGKILL stragglers
  sleep 1
  for pid in "${PIDS[@]:-}"; do
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      kill -9 "$pid" 2>/dev/null || true
    fi
  done
}
trap cleanup EXIT INT TERM

wait_health() {
  local url="$1" name="$2" tries="${3:-60}"
  for i in $(seq 1 "$tries"); do
    if curl -sf "$url/health" >/dev/null 2>&1; then
      echo "  -> $name ready (try $i)"
      return 0
    fi
    sleep 1
  done
  echo "  -> $name NOT ready after $tries tries"
  return 1
}

# --- 0. Start services (unless EXTERNAL_SERVICES=1) -------------------------
if [ -z "${EXTERNAL_SERVICES:-}" ]; then
  echo "[0/9] 启动本地服务 (logs: $LOG_DIR)"
  if ! wait_health "$KB_API" kb-api 1; then
    echo "  -> starting kb-api..."
    (cd "$KB_API_DIR" && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8000) \
      >"$LOG_DIR/kb-api.log" 2>&1 &
    PIDS+=($!)
  fi
  if ! wait_health "$FAQ_API" faq-service 1; then
    echo "  -> starting faq-service..."
    (cd "$FAQ_DIR" && exec uv run uvicorn app.main:app --host 0.0.0.0 --port 8004) \
      >"$LOG_DIR/faq-service.log" 2>&1 &
    PIDS+=($!)
  fi
  # kb-worker (celery) - no health endpoint, just start it
  if ! pgrep -f "celery.*app.worker" >/dev/null 2>&1; then
    echo "  -> starting kb-worker (celery)..."
    (cd "$KB_API_DIR" && exec uv run celery -A app.worker worker -Q ingestion --concurrency=2 -l info) \
      >"$LOG_DIR/kb-worker.log" 2>&1 &
    PIDS+=($!)
  fi
  wait_health "$KB_API" kb-api 90 || { echo "FAIL: kb-api not healthy"; exit 1; }
  wait_health "$FAQ_API" faq-service 30 || { echo "FAIL: faq-service not healthy"; exit 1; }
else
  echo "[0/9] EXTERNAL_SERVICES=1 - assuming services already running"
  wait_health "$KB_API" kb-api 5 || { echo "FAIL: kb-api not healthy"; exit 1; }
  wait_health "$FAQ_API" faq-service 5 || { echo "FAIL: faq-service not healthy"; exit 1; }
fi

# --- 1. Login ---------------------------------------------------------------
echo "[1/9] 登录"
TOKEN=$(curl -s -X POST "$KB_API/api/v1/auth/login" -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"admin123"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['access_token'])")
H="Authorization: Bearer $TOKEN"
# Verify D4: /users/me returns full UserInfo (email/is_active/created_at)
curl -s "$KB_API/api/v1/users/me" -H "$H" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'email' in d and 'is_active' in d and 'created_at' in d, f'/users/me missing fields: {d}'; print('  -> /users/me OK:', d['username'], d['role'])"

# --- 2. Create document KB --------------------------------------------------
echo "[2/9] 创建文档知识库"
KB=$(curl -s -X POST "$KB_API/api/v1/knowledge-bases" -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"冒烟库","kb_type":"DOCUMENT"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "  -> KB id=$KB"

# --- 3. Upload doc ----------------------------------------------------------
echo "[3/9] 上传文档"
echo "hello RAG smoke test. RAG retrieves relevant chunks." > /tmp/s.txt
UPLOAD=$(curl -s -X POST "$KB_API/api/v1/documents/upload?kb_id=$KB" -H "$H" -F 'file=@/tmp/s.txt')
echo "$UPLOAD" | python3 -m json.tool | sed 's/^/  /'
echo "$UPLOAD" | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'document_id' in d, f'upload failed: {d}'; print('  -> document_id OK')"

# --- 4. Wait for processing -------------------------------------------------
echo "[4/9] 等待处理 (BGE 首次加载较慢)"
for i in $(seq 1 60); do
  ST=$(curl -s "$KB_API/api/v1/documents?kb_id=$KB" -H "$H" \
    | python3 -c "import sys,json;d=json.load(sys.stdin);print(d['items'][0]['status'] if d['items'] else 'EMPTY')")
  echo "  -> try $i: $ST"
  [ "$ST" = "COMPLETED" ] && break
  [ "$ST" = "FAILED" ] && { echo "FAIL: doc FAILED"; exit 1; }
  sleep 3
done
[ "$ST" = "COMPLETED" ] || { echo "FAIL: doc not COMPLETED (last=$ST)"; exit 1; }

# --- 5. Search (hybrid RAG) -------------------------------------------------
echo "[5/9] 检索 (hybrid)"
curl -s -X POST "$KB_API/api/v1/search" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"query\":\"RAG\",\"kb_ids\":[\"$KB\"],\"top_k\":3}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'  -> {d[\"total\"]} hit(s), took={d.get(\"took_ms\")}ms');[print(f'     - {h.get(\"document_title\")} p.{h.get(\"page_number\")} score={h.get(\"score\"):.3f}') for h in d['results'][:3]]"

# --- 6. Chat (LLM fallback acceptable) -------------------------------------
echo "[6/9] 问答 (LLM key 未配则返回友好提示)"
curl -s -X POST "$KB_API/api/v1/search/chat" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"query\":\"RAG\",\"kb_ids\":[\"$KB\"],\"top_k\":3}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);a=d['answer'][:80];print(f'  -> answer: {a}...');print(f'  -> citations: {len(d.get(\"citations\",[]))}')"

# --- 7. FAQ KB + entry + search --------------------------------------------
echo "[7/9] FAQ 知识库 + 条目 + 检索"
FAQ_KB=$(curl -s -X POST "$FAQ_API/api/v1/faq/knowledge-bases" -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"冒烟FAQ库"}' \
  | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "  -> FAQ KB id=$FAQ_KB"
curl -s -X POST "$FAQ_API/api/v1/faq/knowledge-bases/$FAQ_KB/entries" -H "$H" -H 'Content-Type: application/json' \
  -d '{"question":"什么是 RAG？","answer":"检索增强生成，结合检索与 LLM。","keywords":["RAG","检索"]}' \
  | python3 -m json.tool | sed 's/^/  /'
# Verify D1: list returns PageResult {items,total,page,size}
curl -s "$FAQ_API/api/v1/faq/knowledge-bases/$FAQ_KB/entries?page=1&size=10" -H "$H" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'items' in d and 'total' in d, f'FAQ entries not PageResult: {d}';print(f'  -> list OK: total={d[\"total\"]} page={d[\"page\"]} size={d[\"size\"]}')"
# FAQ search
curl -s -X POST "$FAQ_API/api/v1/faq/search" -H "$H" -H 'Content-Type: application/json' \
  -d "{\"kb_id\":\"$FAQ_KB\",\"query\":\"RAG\",\"top_k\":3}" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);print(f'  -> FAQ search: {d[\"total\"]} hit(s)');[print(f'     - {r[\"question\"]} score={r[\"score\"]:.3f} ({r[\"match_type\"]})') for r in d['results'][:3]]"

# --- 8. API key create + list (verify D3 field names) ----------------------
echo "[8/9] API Key 创建 + 列表"
curl -s -X POST "$KB_API/api/v1/auth/api-keys" -H "$H" -H 'Content-Type: application/json' \
  -d '{"name":"smoke-key"}' \
  | python3 -c "import sys,json;d=json.load(sys.stdin);assert 'raw_key' in d and 'key_prefix' in d, f'POST api-keys missing raw_key/key_prefix: {d}';print(f'  -> created: prefix={d[\"key_prefix\"]} raw_key={d[\"raw_key\"][:14]}...')"
curl -s "$KB_API/api/v1/auth/api-keys" -H "$H" \
  | python3 -c "import sys,json;d=json.load(sys.stdin);assert all('key_prefix' in k for k in d), f'GET api-keys missing key_prefix: {d}';print(f'  -> list OK: {len(d)} key(s)')"

# --- 9. Settings (verify D-secret masking) ---------------------------------
echo "[9/9] 设置 (验证密钥掩码)"
curl -s "$KB_API/api/v1/settings" -H "$H" \
  | python3 -c "
import sys,json
d=json.load(sys.stdin)
for k,v in d.items():
    if v['is_secret'] and v['is_set']:
        assert v['value']=='', f'secret {k} leaked: {v}'
        print(f'  -> {k}: MASKED (is_set={v[\"is_set\"]})')
    else:
        print(f'  -> {k}: value={v[\"value\"]!r} is_set={v[\"is_set\"]}')
"

echo "SMOKE OK"
