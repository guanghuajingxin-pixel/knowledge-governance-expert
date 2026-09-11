"""在线文档（ALIDOC）与 AI 表格（able）导出：通过 dws CLI 子进程"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import httpx

from ..config import settings

FORMAT_SUFFIX = {"markdown": ".md", "docx": ".docx", "pdf": ".pdf"}
ABLE_SUFFIX = ".xlsx"


class ExportError(Exception):
    pass


def safe_name(name: str) -> str:
    cleaned = re.sub(r'[\\/:*?"<>|\r\n\t]', "_", name).strip().strip(".")
    return cleaned or "document"


def _run_dws(args: list[str], timeout: int) -> subprocess.CompletedProcess:
    cmd = [settings.dws_bin, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                              encoding="utf-8", errors="replace",
                              env={**os.environ, "DWS_CONFIG_DIR": settings.dws_config_dir})
    except FileNotFoundError as exc:
        raise ExportError(f"找不到 dws 命令（{settings.dws_bin}），请先安装并登录 dws CLI") from exc
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
            raise ExportError(f"查询 AI 表格导出任务失败：无法解析 dws 输出") from exc
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


def export_alidoc(dws_bin: str, node_id: str, name: str, output_dir: Path,
                  export_format: str = "markdown", timeout: int = 360) -> Path:
    """导出单个 ALIDOC 节点，返回输出文件路径。"""
    fmt = export_format if export_format in FORMAT_SUFFIX else "markdown"
    suffix = FORMAT_SUFFIX[fmt]
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{safe_name(name)}{suffix}"

    proc = _run_dws(["doc", "export", "--node", node_id, "--export-format", fmt,
                     "--output", str(output_file), "--format", "json", "--yes"], timeout)

    if proc.returncode == 0 and output_file.exists():
        return output_file
    raise ExportError(_proc_error(proc, "在线文档导出失败"))


def export_aitable(dws_bin: str, name: str, output_dir: Path,
                   timeout: int = 360) -> Path:
    """导出单个 AI 表格（.able）节点为 xlsx，返回输出文件路径。"""
    base_name = name[:-5] if name.lower().endswith(".able") else name
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"{safe_name(base_name)}{ABLE_SUFFIX}"

    # ① 按名称解析 baseId
    proc = _run_dws(["aitable", "+resolve-base", "--name", base_name,
                     "--format", "json", "--yes"], min(timeout, 120))
    if proc.returncode != 0:
        raise ExportError(_proc_error(proc, "解析 AI 表格失败"))
    try:
        resolved = json.loads(proc.stdout)
    except ValueError as exc:
        raise ExportError(f"解析 AI 表格失败：无法解析 dws 输出") from exc
    base_id = resolved.get("baseId")
    if not base_id:
        raise ExportError(f"解析 AI 表格失败：未找到 baseId，输出={proc.stdout[-300:]}")

    # ② 导出整个 Base 为 excel
    proc2 = _run_dws(["aitable", "export", "data", "--base-id", base_id,
                      "--scope", "all", "--export-format", "excel",
                      "--format", "json", "--yes", "--timeout-ms", "30000"],
                     min(timeout, 300))
    if proc2.returncode != 0:
        raise ExportError(_proc_error(proc2, "导出 AI 表格失败"))
    try:
        exported = json.loads(proc2.stdout)
    except ValueError as exc:
        raise ExportError(f"导出 AI 表格失败：无法解析 dws 输出") from exc
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


def check_dws(dws_bin: str) -> dict:
    try:
        proc = _run_dws(["--version"], 15)
        version = (proc.stdout or proc.stderr or "").strip().splitlines()
        return {"ok": proc.returncode == 0, "version": version[0] if version else "unknown"}
    except ExportError as exc:
        return {"ok": False, "version": str(exc)}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "version": str(exc)}