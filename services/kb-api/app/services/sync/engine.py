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

from kb_common.config import get_settings
from kb_common.models import (
    SyncDocumentMapping, SyncFailure, SyncLog, SyncRun, SyncSource,
)

from .dingtalk_sync_client import DingTalkError
from .dify_sync_client import DifyError
from .export_service import (ExportError, ONLINE_TYPES, export_online_doc,
                             safe_name)
from .sync_database import SyncSessionLocal
from .sync_settings import make_dify_client, make_dingtalk_client

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
            dify = make_dify_client(db)
            try:
                self._progress(db, run, "开始遍历钉钉知识库目录树")
                nodes = dt.walk_tree(source.root_node_id, s.sync_max_depth,
                                     s.sync_max_results_per_page)
                run.total = len(nodes)
                db.commit()

                self._progress(db, run, f"发现 {len(nodes)} 个文档节点，准备 Dify 数据集")
                dataset_name = (source.dify_dataset_name or "").strip()
                if not dataset_name:
                    raise RuntimeError("同步源未选择 Dify 知识库")
                dataset = None
                try:
                    dataset = dify.find_dataset_by_name(dataset_name)
                except DifyError:
                    dataset = None
                if dataset is None and source.dify_dataset_id:
                    # 数据集在 Dify 侧改名后名称无法命中；回退使用已缓存的 dataset_id。
                    self._log(db, run.id, "WARNING",
                              f"按名称未找到 Dify 知识库 “{dataset_name}”，回退缓存 dataset_id: {source.dify_dataset_id}")
                    try:
                        dataset = dify.get_dataset(source.dify_dataset_id) or None
                    except DifyError:
                        dataset = None
                if not dataset:
                    raise RuntimeError(f"Dify 知识库不存在: {dataset_name}")
                dataset_id = dataset.get("id")
                if not dataset_id:
                    raise RuntimeError(f"Dify 数据集未返回 id: {dataset}")
                if source.dify_dataset_id != dataset_id:
                    source.dify_dataset_id = dataset_id
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
                base_dir = _local_storage_dir() / str(source.id)
                skip_exts = s.sync_skip_ext_list
                for node in nodes:
                    node_id = node["nodeId"]
                    name = node.get("name", node_id)
                    ext = Path(name).suffix.lower()
                    if ext in skip_exts:
                        stats["skipped"] += 1
                        self._log(db, run.id, "INFO", f"跳过（扩展名过滤）: {name}")
                        continue

                    mapping = mappings.get(node_id)
                    if mapping is not None and not mapping.enabled:
                        stats["skipped"] += 1
                        self._log(db, run.id, "INFO", f"跳过（预演中已关闭）: {name}")
                        continue
                    meta_hash = _meta_hash(node)
                    if (mapping and mapping.status == "synced"
                            and mapping.dify_document_id
                            and mapping.meta_hash and mapping.meta_hash == meta_hash):
                        stats["skipped"] += 1
                        continue

                    rel_dir = Path(node.get("relative_dir", "").strip("/"))
                    try:
                        self._progress(db, run, f"下载/导出文档: {name}")
                        local_file, content_hash = self._fetch(dt, node, name, base_dir, rel_dir)
                        changed = (mapping is None or mapping.status != "synced" or mapping.content_hash != content_hash
                                   or not mapping.dify_document_id)
                        # 导出文件名已带目标扩展名（xxx.docx/xxx.xlsx/xxx.pdf），
                        # 普通文件保持原名；Dify 靠扩展名识别格式
                        upload_name = local_file.name
                        if changed:
                            self._progress(db, run, f"上传至 Dify: {name}")
                            if mapping and mapping.dify_document_id:
                                result = dify.update_file(dataset_id, mapping.dify_document_id,
                                                          local_file, file_name=upload_name)
                                self._log(db, run.id, "INFO", f"更新 Dify 文档: {name}")
                            else:
                                result = dify.upload_file(dataset_id, local_file, file_name=upload_name)
                                self._log(db, run.id, "INFO", f"新建 Dify 文档: {name}")
                            doc_id = (result.get("document") or {}).get("id")
                            batch = result.get("batch", "")
                            if not doc_id:
                                raise DifyError("Dify 上传未返回文档 ID")
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
                            if s.sync_dify_wait_indexing:
                                if not batch:
                                    raise DifyError("Dify 上传未返回索引批次")
                                self._progress(db, run, f"等待 Dify 索引: {name}")
                                status = dify.wait_indexing(
                                    dataset_id, batch, s.sync_indexing_timeout_seconds,
                                    on_progress=lambda progress: self._progress(db, run, f"Dify 索引: {name} · {progress}"),
                                )
                                self._log(db, run.id, "INFO", f"索引状态: {name} -> {status}")
                            stats["updated" if was_update else "created"] += 1
                        else:
                            self._log(db, run.id, "INFO", f"内容未变化，跳过上传: {name}")

                        if mapping is None:
                            mapping = SyncDocumentMapping(source_id=source.id, node_id=node_id)
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
    def _delete_dify_doc(dify: DifyClient, dataset_id: str, mapping: SyncDocumentMapping) -> None:
        try:
            dify.delete_document(dataset_id, mapping.dify_document_id)
        except DifyError as exc:
            if exc.status not in (404,):
                raise

    def _fetch(self, dt: DingTalkClient, node: dict, name: str,
               base_dir: Path, rel_dir: Path) -> tuple[Path, str]:
        out_dir = base_dir / rel_dir
        out_dir.mkdir(parents=True, exist_ok=True)
        # 按类型分流：在线文档（adoc/axls/able/mind 等）按类型导出 Office/PDF；
        # 上传的普通文件（docx/xlsx/pdf/...）按原类型 OSS 原样下载。
        ext = (node.get("extension") or Path(name).suffix.lstrip(".")).lower()
        if ext in ONLINE_TYPES or node.get("category") == "ALIDOC":
            local_file = export_online_doc(node["nodeId"], name, out_dir,
                                           get_settings().sync_export_timeout_seconds)
            return local_file, _sha256(local_file.read_bytes())

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
    from .runtime import run_sync as supervised_run
    return supervised_run(source_id, trigger)
