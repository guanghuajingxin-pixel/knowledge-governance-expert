"""同步引擎：钉钉目录树 → 下载/导出 → Dify 上传（增量）。

迁移自 DingDingKonwledgePipeline，改造点：
- 配置改从 kb_common.config.get_settings() 读取
- DB Session 改用同步版 SyncSessionLocal（psycopg），引擎整体仍同步、跑在后台线程
- 日志改用 stdlib logging（平台约定，不依赖 loguru）
- DocumentMapping 模型改名为 SyncDocumentMapping（与平台命名一致）
"""
from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from kb_common.clients import minio_client
from kb_common.clients.dify_document import dataset_runtime
from kb_common.config import get_settings
from kb_common.models import (
    SyncDocumentMapping, SyncFailure, SyncLog, SyncRun, SyncSource,
)

from .dingtalk_sync_client import DingTalkClient, DingTalkError
from .dify_sync_client import DifyClient, DifyError
from .dify_pipeline_vars import resolve_pipeline_inputs
from .export_service import ExportError, safe_name
from .source_files import fetch_source_file, source_file_name, skip_reason
from .sync_database import SyncSessionLocal
from .sync_settings import make_backend, make_dify_client, make_dingtalk_client

logger = logging.getLogger(__name__)



def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _meta_hash(node: dict) -> str:
    """节点元数据指纹；无时间戳时返回空串表示强制处理。"""
    ts_keys = ("updatedAt", "updateTime", "modifiedAt", "modifiedTime")
    stamps = {k: node.get(k) for k in ts_keys if node.get(k)}
    if not stamps:
        return ""
    base = {"name": node.get("name", ""), "category": node.get("category", "")}
    raw = json.dumps({**base, **stamps}, sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


def _local_storage_dir() -> Path:
    s = get_settings()
    base = s.sync_local_storage_dir
    if not base:
        # 默认 services/kb-api/data/sync_downloads
        base = str(Path(__file__).resolve().parents[3] / "data" / "sync_downloads")
    return Path(base)


class SyncEngine:
    def __init__(self, source: SyncSource):
        self.source = source

    # ---------- 日志 ----------
    @staticmethod
    def _log(db, run_id: int | None, level: str, message: str) -> None:
        db.add(SyncLog(run_id=run_id, level=level, message=message))
        logger.info("[%s] %s", run_id, message)
        db.commit()

    # ---------- 主流程 ----------
    def run(self, trigger: str = "manual", run_id: int | None = None) -> dict:
        return self._run_unlocked(trigger, run_id)

    def _run_unlocked(self, trigger: str, run_id: int | None = None) -> dict:
        db = SyncSessionLocal()
        run: SyncRun | None = None
        try:
            source = db.get(SyncSource, self.source.id)
            if source is None:
                raise RuntimeError(f"同步源 {self.source.id} 不存在")
            if not source.enabled:
                return {"status": "skipped", "message": "同步源已停用"}
            self.source = source

            if run_id is None:
                run = SyncRun(source_id=source.id, trigger=trigger, status="running")
                db.add(run)
                db.commit()
                run_id = run.id
            else:
                run = db.get(SyncRun, run_id)
                if run is None or run.status != "running":
                    raise RuntimeError("同步任务已结束或不存在")

            stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "failed": 0}

            s = get_settings()
            dt = make_dingtalk_client(db)
            backend = make_backend(source, db)
            is_dify = (source.backend_type or "dify") == "dify"
            try:
                self._progress(db, run, "开始遍历钉钉知识库目录树")
                # 真实同步不用缓存：必须看到钉钉侧最新增删，缓存仅供预演快速回显
                nodes = dt.walk_tree(source.root_node_id, s.sync_max_depth,
                                     s.sync_max_results_per_page, use_cache=False)
                run.total = len(nodes)
                db.commit()

                self._progress(db, run, f"发现 {len(nodes)} 个文档节点，准备目标数据集")
                dataset = backend.resolve_dataset(source.dify_dataset_id, source.dify_dataset_name)
                dataset_id = dataset["id"]
                dataset_name = dataset.get("name") or source.dify_dataset_name
                # 知识流水线（rag_pipeline）是 Dify 专属；RAGFlow 一律按普通库处理
                runtime_mode = dataset_runtime(dataset) if is_dify else "general"
                if runtime_mode == "rag_pipeline":
                    self._log(db, run.id, "INFO",
                              f"目标为知识流水线数据集 “{dataset_name}”，走 pipeline/run 同步通道")
                # 流水线 input form 变量值（分段参数）：sync_sources.pipeline_inputs 存 JSON 字符串。
                # 不同流水线变量不同（max_chunk_length / parent_mode / child_length 等），
                # 缺失必填变量 Dify 会报 500 "xxx is required in input form"。
                pipeline_inputs: dict = {}
                raw_inputs = (getattr(source, "pipeline_inputs", "") or "").strip()
                if raw_inputs:
                    try:
                        parsed = json.loads(raw_inputs)
                        if not isinstance(parsed, dict):
                            raise ValueError("expected JSON object")
                        pipeline_inputs = parsed
                    except (ValueError, TypeError) as exc:
                        raise DifyError("同步源流水线参数不是合法 JSON 对象，请编辑任务修正") from exc
                if runtime_mode == "rag_pipeline":
                    pipeline_inputs = resolve_pipeline_inputs(
                        dataset_id, backend.local_file_node_id(dataset_id), pipeline_inputs)
                    self._log(db, run.id, "INFO",
                              f"流水线分段参数：{json.dumps(pipeline_inputs, ensure_ascii=False)}")
                source.dify_dataset_id = dataset_id
                source.dify_dataset_name = dataset_name
                db.commit()

                remote = {n["nodeId"]: n for n in nodes if n.get("nodeId")}
                mappings = {m.node_id: m for m in
                            db.query(SyncDocumentMapping).filter_by(source_id=source.id).all()}

                # ① 删除：钉钉侧已不存在且策略为 sync
                for node_id, mapping in list(mappings.items()):
                    if node_id in remote:
                        continue
                    if source.delete_policy == "sync":
                        try:
                            if mapping.dify_document_id:
                                self._delete_dify_doc(backend, dataset_id, mapping)
                            db.delete(mapping)
                            stats["deleted"] += 1
                            self._log(db, run.id, "INFO", f"删除已同步文档: {mapping.name}")
                        except Exception as exc:  # noqa: BLE001
                            self._record_failure(db, run, source.id, mapping.node_id,
                                                 mapping.name, f"删除失败: {exc}")
                            stats["failed"] += 1
                    else:
                        self._log(db, run.id, "INFO",
                                  f"钉钉侧已删除但策略为 keep，保留 Dify 文档: {mapping.name}")
                db.commit()

                # ② 新增/更新
                base_dir = _local_storage_dir() / str(source.id)
                for node in nodes:
                    node_id = node["nodeId"]
                    name = node.get("name", node_id)
                    reason = skip_reason(node, s, runtime_mode)
                    if reason:
                        stats["skipped"] += 1
                        self._log(db, run.id, "INFO", f"跳过: {name} · {reason}")
                        continue

                    mapping = mappings.get(node_id)
                    if mapping is not None and not mapping.enabled:
                        stats["skipped"] += 1
                        self._log(db, run.id, "INFO", f"跳过（预演中已关闭）: {name}")
                        continue
                    meta_hash = _meta_hash(node)

                    rel_dir = Path(node.get("relative_dir", "").strip("/"))
                    try:
                        self._progress(db, run, f"下载/导出文档: {name}")
                        local_file, content_hash = self._fetch(dt, node, name, base_dir, rel_dir)
                        # 用户口径：预演开关打开的文档一律老实同步，不做内容 hash 跳过；
                        # 已同步过的走更新，未同步过的新建。
                        # 源文档直传：下载文件保留源扩展名（缺失时按 OSS 文件名/节点 extension 补齐），
                        # 在线文档带导出目标扩展名（xxx.docx/xxx.xlsx/xxx.pdf）；
                        # 上传名恒为本地源文件名，不做任何格式转换，引擎靠扩展名识别格式
                        upload_name = local_file.name
                        self._progress(db, run, f"上传至目标知识库: {name}")
                        if runtime_mode == "rag_pipeline":
                            # Dify 流水线数据集：pipeline/run 阻塞执行，完成即返回；
                            # 更新场景先索引新文档，成功后才替换旧文档。
                            pipeline_timeout = float(s.sync_indexing_timeout_seconds)
                            if mapping and mapping.dify_document_id:
                                result = backend.update_file_via_pipeline(
                                    dataset_id, mapping.dify_document_id, local_file,
                                    file_name=upload_name, timeout=pipeline_timeout,
                                    inputs=pipeline_inputs)
                                self._log(db, run.id, "INFO", f"更新文档（知识流水线）: {name}")
                            else:
                                result = backend.upload_file_via_pipeline(
                                    dataset_id, local_file, file_name=upload_name,
                                    timeout=pipeline_timeout, inputs=pipeline_inputs)
                                self._log(db, run.id, "INFO", f"新建文档（知识流水线）: {name}")
                        elif mapping and mapping.dify_document_id:
                            result = backend.update_file(dataset_id, mapping.dify_document_id,
                                                         local_file, file_name=upload_name)
                            self._log(db, run.id, "INFO", f"更新文档: {name}")
                        else:
                            result = backend.upload_file(dataset_id, local_file, file_name=upload_name)
                            self._log(db, run.id, "INFO", f"新建文档: {name}")
                        doc_id = (result.get("document") or {}).get("id")
                        batch = result.get("batch", "")
                        if not doc_id:
                            raise DifyError("目标知识库上传未返回文档 ID")
                        was_update = bool(mapping and mapping.dify_document_id)
                        if mapping is None:
                            mapping = SyncDocumentMapping(source_id=source.id, node_id=node_id,
                                                          name=name, category=node.get("category", ""))
                            db.add(mapping)
                        # 上传成功即保存远端 ID；索引失败重试时更新同一文档，避免重复创建。
                        mapping.dify_document_id = doc_id
                        mapping.dify_batch = batch
                        mapping.content_hash = content_hash
                        mapping.status = "indexing"
                        db.commit()
                        if s.sync_dify_wait_indexing and batch and result["document"].get("indexing_status") != "completed":
                            self._progress(db, run, f"等待索引: {name}")
                            status = backend.wait_indexing(
                                dataset_id, batch, s.sync_indexing_timeout_seconds,
                                on_progress=lambda progress: self._progress(db, run, f"索引: {name} · {progress}"),
                            )
                            self._log(db, run.id, "INFO", f"索引状态: {name} -> {status}")
                        stats["updated" if was_update else "created"] += 1

                        mapping.parent_node_id = self._parent_of(node, source.root_node_id)
                        mapping.name = name
                        mapping.relative_path = str(rel_dir / safe_name(name))
                        mapping.category = node.get("category", "")
                        mapping.meta_hash = meta_hash
                        mapping.content_hash = content_hash
                        mapping.local_path = str(local_file)
                        mapping.dify_document_id = doc_id
                        mapping.dify_batch = batch
                        mapping.status = "synced"
                        mapping.error = ""
                        mapping.last_synced_at = datetime.utcnow()
                    except (DingTalkError, ExportError, DifyError, OSError) as exc:
                        self._record_failure(db, run, source.id, node_id, name, str(exc))
                        stats["failed"] += 1
                        if mapping is not None:
                            mapping.status = "error"
                            mapping.error = str(exc)
                        else:
                            m = SyncDocumentMapping(source_id=source.id, node_id=node_id, name=name,
                                                   category=node.get("category", ""), status="error",
                                                   error=str(exc))
                            db.add(m)
                    except Exception as exc:  # noqa: BLE001
                        self._record_failure(db, run, source.id, node_id, name, f"未知错误: {exc}")
                        stats["failed"] += 1
                    run.created_count = stats["created"]
                    run.updated_count = stats["updated"]
                    run.deleted_count = stats["deleted"]
                    run.failed_count = stats["failed"]
                    if mapping is not None and mapping.status == "synced":
                        db.query(SyncFailure).filter_by(source_id=source.id, node_id=node_id).delete()
                    db.commit()

                run.created_count = stats["created"]
                run.updated_count = stats["updated"]
                run.deleted_count = stats["deleted"]
                run.failed_count = stats["failed"]
                run.finished_at = datetime.utcnow()
                if stats["failed"] == 0:
                    run.status = "success"
                elif stats["created"] + stats["updated"] + stats["deleted"] + stats["skipped"] == 0:
                    run.status = "failed"
                else:
                    run.status = "partial"
                run.message = (f"total={run.total} skipped={stats['skipped']} created={stats['created']} "
                               f"updated={stats['updated']} deleted={stats['deleted']} "
                               f"failed={stats['failed']}")
                db.commit()
                return self._summary(run)
            finally:
                dt.close()
                backend.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("同步失败")
            db.rollback()
            if run_id is not None:
                from .runtime import finish_interrupted
                finish_interrupted(run_id, f"异常终止: {exc}")
            return {"run_id": run_id, "status": "failed", "message": str(exc)}
        finally:
            db.close()

    def _progress(self, db, run: SyncRun, message: str) -> None:
        run.message = message
        self._log(db, run.id, "INFO", message)

    # ---------- 辅助 ----------
    @staticmethod
    def _parent_of(node: dict, root_node_id: str) -> str:
        return node.get("parent_node_id", root_node_id)

    @staticmethod
    def _delete_dify_doc(backend, dataset_id: str, mapping: SyncDocumentMapping) -> None:
        try:
            backend.delete_document(dataset_id, mapping.dify_document_id)
        except DifyError as exc:
            if exc.status not in (404,):
                raise

    def _fetch(self, dt: DingTalkClient, node: dict, name: str,
               base_dir: Path, rel_dir: Path) -> tuple[Path, str]:
        out_dir = base_dir / safe_name(node["nodeId"]) / Path(*(safe_name(part) for part in rel_dir.parts))
        local_file = fetch_source_file(dt, {**node, "name": name}, out_dir)
        self._store_source_object(node["nodeId"], local_file)
        return local_file, _sha256(local_file.read_bytes())

    _source_file_name = staticmethod(source_file_name)

    def _store_source_object(self, node_id: str, local_file: Path) -> None:
        """源文档备份到对象存储（raw-docs/dingtalk-sync/{node_id}/{filename}）。

        需求口径：源文档下载到对象存储后，再以源文档上传 Dify（不经过转换引擎）。
        备份失败仅 WARNING，不阻断同步主流程。
        """
        import mimetypes

        key = f"dingtalk-sync/{node_id}/{local_file.name}"
        try:
            minio_client.upload_bytes(
                minio_client.RAW, key, local_file.read_bytes(),
                mimetypes.guess_type(local_file.name)[0] or "application/octet-stream")
        except Exception as exc:  # noqa: BLE001
            logger.warning("源文档存对象存储失败 %s: %s", key, exc)

    def _record_failure(self, db, run: SyncRun, source_id: int, node_id: str | None,
                        name: str, error: str) -> None:
        db.add(SyncFailure(run_id=run.id, source_id=source_id, node_id=node_id,
                           name=name, error=error))
        self._log(db, run.id, "ERROR", f"失败 [{name}]: {error}")

    @staticmethod
    def _summary(run: SyncRun) -> dict:
        return {
            "run_id": run.id,
            "status": run.status,
            "total": run.total,
            "created": run.created_count,
            "updated": run.updated_count,
            "deleted": run.deleted_count,
            "failed": run.failed_count,
            "message": run.message,
        }


def run_sync(source_id: int, trigger: str = "manual") -> dict:
    from .runtime import run_sync as supervised_run
    return supervised_run(source_id, trigger)
