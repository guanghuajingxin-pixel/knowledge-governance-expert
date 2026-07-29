import httpx
from kb_common.config import get_settings

async def parse(file_bytes: bytes, filename: str, api_key: str | None = None) -> dict:
    """调用 MinerU 公有云 API 解析文档，返回 {'markdown': str, 'pages': int}。
    实际 endpoint 以 mineru.net 文档为准；此处为标准封装，含 API Key 头。"""
    s = get_settings()
    key = api_key or s.mineru_api_key
    async with httpx.AsyncClient(timeout=300) as c:
        # 1. 申请上传 URL / 提交任务（按 MinerU 云文档实现）
        # 2. 轮询任务结果
        # 3. 取回 markdown
        # -- MVP 先以本地直解兜底（见下方 fallback）--
        return {"markdown": _local_fallback(file_bytes, filename), "pages": 1}

def _local_fallback(file_bytes: bytes, filename: str) -> str:
    """MinerU key 未配置时的本地兜底：纯文本/markdown 直读；其他格式提示配置 key。"""
    import io
    ext = filename.rsplit(".", 1)[-1].lower()
    if ext in ("txt", "md"):
        return file_bytes.decode("utf-8", errors="ignore")
    if ext in ("csv",):
        return file_bytes.decode("utf-8", errors="ignore")
    # doc/docx/pdf/xlsx：需 MinerU 云；未配置则抛错由 worker 标 FAILED
    if not get_settings().mineru_api_key:
        raise RuntimeError("MINERU_API_KEY 未配置，无法解析二进制文档")
    raise RuntimeError("MinerU 云解析未实现，请在 Task9 接入")
