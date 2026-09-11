"""在线文档（ALIDOC）与 AI 表格（able）导出：通过 dws CLI 子进程。

迁移自 DingDingKonwledgePipeline，dws_bin / dws_config_dir 改从平台配置读取。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

from kb_common.config import get_settings

FORMAT_SUFFIX = {"markdown": ".md", "docx": ".docx", "pdf": ".pdf"}
ABLE_SUFFIX = ".xlsx"
XLSX_SUFFIX = ".xlsx"

# 钉钉在线文档类型 → Office 目标格式（「是什么类型就转成 Office 的什么类型」）
ONLINE_DOC_TARGET = {"adoc": "docx", "axls": "xlsx", "able": "xlsx"}
# Office 无法表达的在线类型（脑图/白板等）→ 转 PDF 再同步
ONLINE_PDF_TYPES = {"mind", "mindnote", "board", "whiteboard"}
# 全部需要走导出流程的在线类型
ONLINE_TYPES = set(ONLINE_DOC_TARGET) | ONLINE_PDF_TYPES


class ExportError(Exception):
    pass


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().strip(".")
    return cleaned or "document"


def _dws_env() -> dict:
    s = get_settings()
    config_dir = s.dws_config_dir or ""
    env = dict(os.environ)
    if config_dir:
        env["DWS_CONFIG_DIR"] = config_dir
    return env


def _run_dws(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    s = get_settings()
    cmd = [s.dws_bin, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace", env=_dws_env())
    except FileNotFoundError as exc:
        raise ExportError(f"找不到 dws 命令（{s.dws_bin}），请先安装并登录 dws CLI") from exc
    except subprocess.TimeoutExpired as exc:
        raise ExportError(f"dws 命令超时（>{timeout}s）") from exc


def _proc_error(proc: subprocess.CompletedProcess, action: str) -> str:
    detail = (proc.stdout or "").strip()[-500:] or (proc.stderr or "").strip()[-500:]
    return f"{action}: dws 退出码 {proc.returncode}: {detail}"


def _poll_aitable_download(base_id: str, task_id: str, timeout: int) -> str:
    """轮询导出任务，直到返回 downloadUrl。"""
    deadline = time.monotonic() + timeout
    while True:
        proc = _run_dws(["aitable", "export", "data", "--base-id", base_id,
                         "--task-id", task_id, "--format", "json",
                         "--timeout-ms", "30000", "--yes"], min(timeout, 120))
        if proc.returncode != 0:
            raise ExportError(_proc_error(proc, "查询 AI 表格导出任务失败"))
        try:
            exported = json.loads(proc.stdout)
        except ValueError as exc:
            raise ExportError("查询 AI 表格导出任务失败：无法解析 dws 输出") from exc
        data = exported.get("data", exported)
        download_url = data.get("downloadUrl")
        if download_url:
            return download_url
        status = str(data.get("status", "")).lower()
        if status in ("failed", "error", "cancelled", "canceled"):
            raise ExportError(f"导出 AI 表格任务失败：{proc.stdout[-300:]}")
        if time.monotonic() >= deadline:
            raise ExportError("等待 AI 表格导出下载地址超时")
        time.sleep(3)


def _strip_online_ext(name: str) -> str:
    """去掉在线文档自带的类型后缀（.adoc/.axls/.able/.mind 等），避免导出后双扩展名。"""
    stem = safe_name(name)
    for ext in ONLINE_TYPES:
        if stem.lower().endswith("." + ext):
            return stem[: -len(ext) - 1]
    return stem


def export_alidoc(node_id: str, name: str, output_dir: Path,
                  export_format: str = "docx", timeout: int = 360) -> Path:
    """导出单个 ALIDOC 节点，返回输出文件路径。dws_bin 从配置读取。"""
    fmt = export_format if export_format in FORMAT_SUFFIX else "docx"
    suffix = FORMAT_SUFFIX[fmt]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{_strip_online_ext(name)}{suffix}"

    proc = _run_dws(["doc", "export", "--node", node_id, "--export-format", fmt,
                     "--output", str(output_file), "--format", "json", "--yes"], timeout)

    if proc.returncode == 0 and output_file.exists():
        return output_file
    raise ExportError(_proc_error(proc, "在线文档导出失败"))


def export_axls(node_id: str, name: str, output_dir: Path, timeout: int = 360) -> Path:
    """导出钉钉在线电子表格（axls）为 Office xlsx，返回输出文件路径。"""
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{_strip_online_ext(name)}{XLSX_SUFFIX}"

    proc = _run_dws(["sheet", "export", "--node", node_id,
                     "--output", str(output_file), "--format", "json", "--yes"], timeout)

    if proc.returncode == 0 and output_file.exists():
        return output_file
    raise ExportError(_proc_error(proc, "在线表格导出失败"))


def online_ext_of(name: str) -> str:
    """从节点名推断在线文档类型（钉钉在线文档名自带 .adoc/.axls/.able 等后缀）。"""
    stem = safe_name(name)
    for ext in ONLINE_TYPES:
        if stem.lower().endswith("." + ext):
            return ext
    return ""


def export_online_doc(node_id: str, name: str, output_dir: Path, timeout: int = 360) -> Path:
    """在线文档统一分流导出：
    - adoc（在线文档）→ docx；axls（在线表格）→ xlsx；able（AI 表格）→ xlsx
    - mind/board 等 Office 不支持的类型 → pdf
    返回导出文件路径；上传的普通文件不走这里（直接 OSS 原样下载）。
    """
    ext = online_ext_of(name)
    if ext == "axls":
        return export_axls(node_id, name, output_dir, timeout)
    if ext == "able":
        return export_aitable(name, output_dir, timeout, node_id=node_id)
    if ext in ONLINE_PDF_TYPES:
        return export_alidoc(node_id, name, output_dir, "pdf", timeout)
    # adoc 及其余在线文字文档 → docx
    return export_alidoc(node_id, name, output_dir, "docx", timeout)


def _resolve_aitable_base(base_name: str, timeout: int) -> str:
    """按名称解析 AI 表格 baseId（同名歧义/未找到时抛 ExportError）。"""
    proc = _run_dws(["aitable", "+resolve-base", "--name", base_name,
                     "--format", "json", "--yes"], min(timeout, 120))
    if proc.returncode != 0:
        raise ExportError(_proc_error(proc, "解析 AI 表格失败"))
    try:
        resolved = json.loads(proc.stdout)
    except ValueError as exc:
        raise ExportError("解析 AI 表格失败：无法解析 dws 输出") from exc
    base_id = resolved.get("baseId")
    if not base_id:
        raise ExportError(f"解析 AI 表格失败：未找到 baseId，输出={proc.stdout[-300:]}")
    return base_id


def export_aitable(name: str, output_dir: Path, timeout: int = 360,
                   node_id: str = "") -> Path:
    """导出单个 AI 表格（.able）节点为 xlsx，返回输出文件路径。

    AI 表格节点的 nodeId 即 aitable baseId：优先直接导出；
    直接导出失败时回退按名称 resolve（避免同名歧义/无效 ID）。
    """
    base_name = name[:-5] if name.lower().endswith(".able") else name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{safe_name(base_name)}{ABLE_SUFFIX}"

    # ① 确定 baseId：nodeId 直接用作 baseId，失败再按名称解析
    base_id = node_id
    if not base_id:
        base_id = _resolve_aitable_base(base_name, timeout)

    # ② 导出整个 Base 为 excel
    proc2 = _run_dws(["aitable", "export", "data", "--base-id", base_id,
                      "--scope", "all", "--export-format", "excel",
                      "--format", "json", "--yes", "--timeout-ms", "30000"],
                     min(timeout, 300))
    if proc2.returncode != 0 and node_id:
        # nodeId 直接导出失败：回退按名称解析后重试一次
        base_id = _resolve_aitable_base(base_name, timeout)
        proc2 = _run_dws(["aitable", "export", "data", "--base-id", base_id,
                          "--scope", "all", "--export-format", "excel",
                          "--format", "json", "--yes", "--timeout-ms", "30000"],
                         min(timeout, 300))
    if proc2.returncode != 0:
        raise ExportError(_proc_error(proc2, "导出 AI 表格失败"))
    try:
        exported = json.loads(proc2.stdout)
    except ValueError as exc:
        raise ExportError("导出 AI 表格失败：无法解析 dws 输出") from exc
    data = exported.get("data", exported)
    download_url = data.get("downloadUrl")
    if not download_url:
        task_id = data.get("taskId")
        if not task_id:
            raise ExportError(f"导出 AI 表格失败：未返回下载地址，输出={proc2.stdout[-300:]}")
        download_url = _poll_aitable_download(base_id, task_id, timeout)

    # ③ 下载导出文件
    try:
        with httpx.Client(timeout=300, follow_redirects=True) as client:
            resp = client.get(download_url)
            resp.raise_for_status()
            output_file.write_bytes(resp.content)
    except httpx.HTTPError as exc:
        raise ExportError(f"下载 AI 表格导出文件失败: {exc}") from exc

    if output_file.exists() and output_file.stat().st_size > 0:
        return output_file
    raise ExportError("下载 AI 表格导出文件失败：文件为空")


def check_dws() -> dict:
    """检查 dws CLI 是否可用。"""
    try:
        proc = _run_dws(["--version"], 15)
        version = (proc.stdout or proc.stderr or "").strip().splitlines()
        return {"ok": proc.returncode == 0, "version": version[0] if version else "unknown"}
    except ExportError as exc:
        return {"ok": False, "version": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "version": str(exc)}
