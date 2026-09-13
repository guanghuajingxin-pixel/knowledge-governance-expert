"""Shared upload limits for Dify document uploads."""
from pathlib import PurePath
from kb_common.config import get_settings

MAX_UPLOAD_BYTES = 15 * 1024 * 1024
UPLOAD_EXTENSIONS = {"pdf", "docx", "doc", "pptx", "ppt", "xls", "xlsx", "csv", "txt", "md", "markdown", "mdx", "html", "htm", "vtt", "properties", "eml", "msg", "xml", "epub"}

# Dify 内置 ETL（ETL_TYPE=Dify，默认）支持的文档扩展名，与
# dify/api/constants/__init__.py 的 _DEFAULT_DOCUMENT_EXTENSION_BASE 对齐。
# 超出此集合的格式（pptx/ppt/doc/eml/msg/xml/epub）只有 Dify 配置
# ETL_TYPE=Unstructured 后才支持；内置 ETL 下 create-by-file 会抛
# UnsupportedFileTypeError（对外表现为空 message 的 invalid_param）。
# 目录级批量同步必须在上传前按此集合过滤，避免整批失败。
DIFY_BUILTIN_ETL_EXTENSIONS = {
    "txt", "markdown", "md", "mdx", "pdf", "html", "htm",
    "xlsx", "xls", "docx", "csv", "vtt", "properties",
}

# Dify 配置 ETL_TYPE=Unstructured 时的支持集合，与
# dify/api/constants/__init__.py 的 _UNSTRUCTURED_DOCUMENT_EXTENSION_BASE 对齐。
# 比内置 ETL 多出 doc/pptx/eml/msg/xml/epub（解析走 Unstructured API 服务）。
DIFY_UNSTRUCTURED_ETL_EXTENSIONS = {
    "txt", "markdown", "md", "mdx", "pdf", "html", "htm",
    "xlsx", "xls", "vtt", "properties", "doc", "docx", "csv",
    "eml", "msg", "pptx", "xml", "epub",
}


def supported_dify_extensions(etl_type: str = "dify") -> set[str]:
    """按 Dify 的 ETL_TYPE 返回文档扩展名白名单（大小写不敏感）。"""
    if (etl_type or "").strip().lower() == "unstructured":
        return DIFY_UNSTRUCTURED_ETL_EXTENSIONS
    return DIFY_BUILTIN_ETL_EXTENSIONS


def max_upload_bytes() -> int:
    return get_settings().dify_upload_max_mb * 1024 * 1024


def prepare_document(filename: str, content: bytes) -> tuple[str, bytes]:
    """校验并原样返回源文档字节；不做任何本地转换（源文档直传 Dify）。

    需求口径：源文档经钉钉下载接口存对象存储后，以源文档上传，
    禁止在本地转换（MinerU / 文本抽取）后再上传。
    """
    extension = PurePath(filename).suffix.lower().lstrip(".")
    if extension not in UPLOAD_EXTENSIONS:
        raise ValueError("不支持此文件格式，请使用 PDF、Word、PowerPoint、Excel、CSV、TXT、Markdown 或 HTML。")
    if not content:
        raise ValueError("文件为空，请选择有内容的文档。")
    limit = max_upload_bytes()
    if len(content) > limit:
        raise ValueError(f"文件超过当前配置的 {limit // (1024 * 1024)} MB 上限，请在系统配置中与 Dify 上传上限保持一致。")
    return filename, content
