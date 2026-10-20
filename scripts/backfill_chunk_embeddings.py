"""文档库分段向量回填：为缺失/过期的叶子分段批量补 embedding。

背景：分段向量已持久化到 library_chunk_embeddings（入库时写入）；存量分段
与向量模型切换后的旧行需要本脚本回填（查询期自愈仅覆盖 ≤256 的小增量）。

本地（services/kb-api venv，含 kb_common + app 双包）：
    cd services/kb-api && uv run python ../../scripts/backfill_chunk_embeddings.py
容器内（远端部署）：
    docker exec kge-kb-api sh -c "cd /app/services/kb-api && \
        uv run python ../../scripts/backfill_chunk_embeddings.py"

用法：
    --library-id N   只回填指定文档库（缺省=全部 document 库）
    --batch-size N   每批向量数（默认 32，与检索链路同口径）
    --model NAME     覆盖模型名（缺省=当前生效 embedding 配置）
    --scope S        回填范围：vectors | tokens | both（默认 both；
                     tokens 为本地分词，无外部 API 依赖）
    --dry-run        只统计待回填数量，不调 embedding API

断点续跑：每批独立 commit；单批失败记日志跳过，重跑自动跳过已回填行。
"""
import argparse
import asyncio
import logging
import sys
from pathlib import Path

# 使 kb_common 与 app（kb-api）均可导入：脚本可从仓库任意位置用对应 venv 运行
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "services" / "kb-common"))
sys.path.insert(0, str(_REPO_ROOT / "services" / "kb-api"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [backfill] %(levelname)s %(message)s")


async def main():
    parser = argparse.ArgumentParser(description="文档库分段索引回填（向量 + 词项）")
    parser.add_argument("--library-id", type=int, default=None, help="只回填指定文档库")
    parser.add_argument("--batch-size", type=int, default=32, help="每批向量数（默认 32）")
    parser.add_argument("--model", default=None, help="覆盖模型名（缺省=当前生效配置）")
    parser.add_argument("--scope", choices=["vectors", "tokens", "both"], default="both",
                        help="回填范围（默认 both）")
    parser.add_argument("--dry-run", action="store_true", help="只统计待回填数量")
    args = parser.parse_args()

    from app.services.chunk_vectors import backfill
    try:
        stats = await backfill(library_id=args.library_id, batch_size=args.batch_size,
                               model=args.model, dry_run=args.dry_run, scope=args.scope)
    except ValueError as e:
        raise SystemExit(f"回填失败: {e}")

    failed_total = 0
    for lib_id, info in stats.items():
        parts = [f"库 {lib_id}（{info['name']}）"]
        for key, label in (('pending_vectors', '向量待回填'), ('pending_tokens', '词项待回填'),
                           ('backfilled_vectors', '向量回填'), ('backfilled_tokens', '词项回填'),
                           ('failed_vectors', '向量失败'), ('failed_tokens', '词项失败')):
            if key in info:
                parts.append(f"{label} {info[key]} 条")
                if key.startswith('failed'):
                    failed_total += info[key]
        print("，".join(parts))
    if failed_total:
        raise SystemExit(f"共 {failed_total} 条回填失败（见日志），请重跑本脚本续跑补齐")
    print("回填结束。")


if __name__ == "__main__":
    asyncio.run(main())
