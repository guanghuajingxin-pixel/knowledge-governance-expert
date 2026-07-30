async def parse(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """解析文档为 {'markdown': str, 'pages': int}。

    MinerU 云解析暂未实现（MVP 仅支持 txt/md/csv 本地解析）；即便配置了
    MINERU_API_KEY，PDF/DOCX/XLSX 等二进制格式仍会抛错。api_key 参数保留以
    备未来接入云解析，当前未使用。"""
    return {"markdown": _local_fallback(file_bytes, filename), "pages": 1}


def _local_fallback(file_bytes: bytes, filename: str) -> str:
    """本地兜底：txt/md/csv 直读；其他格式暂不支持（MinerU 云解析未实现）。"""
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "md", "csv"):
        return file_bytes.decode("utf-8", errors="ignore")
    # doc/docx/pdf/xlsx/pptx/html 等：MinerU 云解析暂未实现（MVP 仅支持 txt/md/csv）
    raise RuntimeError("MinerU 云解析暂未实现（MVP 仅支持 txt/md/csv 本地解析）")
