"""同步引擎：钉钉目录树 → 下载/导出 → Dify 上传（增量）"""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path

from loguru import logger

from ..config import settings
from ..database import SessionLocal
from ..models import DocumentMapping, SyncFailure, SyncLog, SyncRun, SyncSource
from .dify_client import DifyClient, DifyError
from .dingtalk_client import DingTalkClient, DingTalkError
from .export_service import ExportError, export_alidoc, export_aitable, safe_name

_run_lock = threading.Lock()


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


class SyncEngine:
    def __init__(self, source: SyncSource):
        self.source = source

    # ---------- 日志 ----------
    @staticmethod
    def _log(db, run_id: int | None, level: str, message: str) -> None:
        db.add(SyncLog(run_id=run_id, level=level, message=message))
        logger.info(f"[run={run_id}] {message}")

    # ---------- 主流程 ----------
    def run(self, trigger: str = "manual") -> dict:
        with _run_lock:
            return self._run_unlocked(trigger)

    def _run_unlocked(self, trigger: str) -> dict:
        db = SessionLocal()
        run: SyncRun | None = None
        try:
            source = db.get(SyncSource, self.source.id)
            if source is None:
                raise RuntimeError(f"同步源 {self.source.id} 不存在")
            self.source = source

            run = SyncRun(source_id=source.id, trigger=trigger, status="running")
            db.add(run)
            db.commit()
            db.refresh(run)

            stats = {"created": 0, "updated": 0, "deleted": 0, "skipped": 0, "failed": 0}

            dt = DingTalkClient(settings.dingtalk_app_key, settings.dingtalk_app_secret,
                                settings.dingtalk_operator_id)
            dify = DifyClient(settings.dify_base_url, settings.dify_dataset_api_key)
            try:
                self._log(db, run.id, "INFO", "开始遍历钉钉知识库目录树")
                nodes = dt.walk_tree(source.root_node_id, settings.max_depth,
                                     settings.max_results_per_page)
                run.total = len(nodes)
                db.commit()

                self._log(db, run.id, "INFO", f"发现 {len(nodes)} 个文档节点，准备 Dify 数据集")
                dataset_name = (source.dify_dataset_name or "").strip() \
                    or (source.start_dir or "").strip() or (source.name or "").strip() or "钉钉知识库"
                dataset = dify.find_or_create_dataset(
                    dataset_name,
                    permission=settings.dify_default_permission,
                )
                dataset_id = dataset.get("id")
                if not dataset_id:
                    raise RuntimeError(f"Dify 数据集未返回 id: {dataset}")
                if source.dify_dataset_id != dataset_id:
                    source.dify_dataset_id = dataset_id
                    db.commit()

                remote = {n["nodeId"]: n for n in nodes if n.get("nodeId")}
                mappings = {m.node_id: m for m in
                            db.query(DocumentMapping).filter_by(source_id=source.id).all()}

                # ① 删除：钉钉侧已不存在且策略为 sync
                for node_id, mapping in mappings.items():
                    if node_id in remote:
                        continue
                    if source.delete_policy == "sync":
                        try:
                            if mapping.dify_document_id:
                                self._delete_dify_doc(dify, dataset_id, mapping)
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
                base_dir = Path(settings.local_storage_dir) / str(source.id)
                skip_exts = settings.skip_ext_list
                for node in nodes:
                    node_id = node["nodeId"]
                    name = node.get("name", node_id)
                    ext = Path(name).suffix.lower()
                    if ext in skip_exts:
                        stats["skipped"] += 1
                        self._log(db, run.id, "INFO", f"跳过（扩展名过滤）: {name}")
                        continue

                    mapping = mappings.get(node_id)
                    meta_hash = _meta_hash(node)
                    if (mapping and mapping.status == "synced"
                            and mapping.dify_document_id
                            and mapping.meta_hash and mapping.meta_hash == meta_hash):
                        stats["skipped"] += 1
                        continue

                    rel_dir = Path(node.get("relative_dir", "").strip("/"))
                    try:
                        local_file, content_hash = self._fetch(dt, node, name, base_dir, rel_dir)
                        changed = (mapping is None or mapping.content_hash != content_hash
                                   or not mapping.dify_document_id)
                        upload_name = safe_name(name).removesuffix(".able") + ".xlsx" if name.lower().endswith(".able") else safe_name(name)
                        if changed:
                            if mapping and mapping.dify_document_id:
                                result = dify.update_file(dataset_id, mapping.dify_document_id,
                                                          local_file, file_name=upload_name)
                                stats['updated'] += 1
                                self._log(db, run.id, "INFO", f"更新 Dify 文档: {name}")
                            else:
                                result = dify.upload_file(dataset_id, local_file, file_name=upload_name)
                                stats['created'] += 1
                                self._log(db, run.id, "INFO", f"新建 Dify 文档: {name}")
                            doc_id = (result.get("document") or {}).get("id")
                            batch = result.get("batch", "")
                            if settings.dify_wait_indexing and batch:
                                status = dify.wait_indexing(dataset_id, batch)
                                self._log(db, run.id, "INFO", f"索引状态: {name} -> {status}")
                        else:
                            self._log(db, run.id, "INFO", f"内容未变化，跳过上传: {name}")

                        if mapping is None:
                            mapping = DocumentMapping(source_id=source.id, node_id=node_id)
                            db.add(mapping)
                        mapping.parent_node_id = self._parent_of(node, source.root_node_id)
                        mapping.name = name
                        mapping.relative_path = str(rel_dir / safe_name(name))
                        mapping.category = node.get("category", "")
                        mapping.meta_hash = meta_hash
                        mapping.content_hash = content_hash
                        mapping.local_path = str(local_file)
                        if changed:
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
                            m = DocumentMapping(source_id=source.id, node_id=node_id, name=name,
                                                category=node.get("category", ""), status="error",
                                                error=str(exc))
                            db.add(m)
                    except Exception as exc:  # noqa: BLE001
                        self._record_failure(db, run, source.id, node_id, name, f"未知错误: {exc}")
                        stats["failed"] += 1
                    db.commit()

                run.created_count = stats["created"]
                run.updated_count = stats["updated"]
                run.deleted_count = stats["deleted"]
                run.failed_count = stats["failed"]
                run.finished_at = datetime.utcnow()
                if stats["failed"] == 0:
                    run.status = "success"
                elif run.total == 0:
                    run.status = "failed"
                else:
                    run.status = "partial"
                run.message = (f"total={run.total} created={stats['created']} "
                               f"updated={stats['updated']} deleted={stats['deleted']} "
                               f"failed={stats['failed']}")
                db.commit()
                return self._summary(run)
            finally:
                dt.close()
                dify.close()
        except Exception as exc:  # noqa: BLE001
            logger.exception("同步失败")
            if run is not None:
                run.status = "failed"
                run.finished_at = datetime.utcnow()
                run.message = f"异常终止: {exc}"
                db.commit()
            return {"run_id": run.id if run else None, "status": "failed", "message": str(exc)}
        finally:
            db.close()

    # ---------- 辅助 ----------
    @staticmethod
    def _parent_of(node: dict, root_node_id: str) -> str:
        return node.get("parent_node_id", root_node_id)

    @staticmethod
    def _delete_dify_doc(dify: DifyClient, dataset_id: str, mapping: DocumentMapping) -> None:
        try:
            dify.delete_document(dataset_id, mapping.dify_document_id)
        except DifyError as exc:
            if exc.status not in (404,):
                raise

    def _fetch(self, dt: DingTalkClient, node: dict, name: str,
               base_dir: Path, rel_dir: Path) -> tuple[Path, str]:
        out_dir = base_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        if name.lower().endswith(".able"):
            local_file = export_aitable(settings.dws_bin, name, out_dir)
            content_hash = _sha256(local_file.read_bytes())
            return local_file, content_hash
        if node.get("category") == "ALIDOC":
            local_file = export_alidoc(settings.dws_bin, node["nodeId"], name, out_dir,
                                       settings.export_format)
            content_hash = _sha256(local_file.read_bytes())
            return local_file, content_hash

        content, _filename = dt.download_document(node["nodeId"])
        local_file = out_dir / safe_name(name)
        local_file.write_bytes(content)
        return local_file, _sha256(content)

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
    """对外入口：加载 source 并执行同步。"""
    db = SessionLocal()
    try:
        source = db.get(SyncSource, source_id)
        if source is None:
            return {"status": "failed", "message": f"同步源 {source_id} 不存在"}
        return SyncEngine(source).run(trigger)
    finally:
        db.close()
