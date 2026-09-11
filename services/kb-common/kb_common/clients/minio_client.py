import io
from datetime import timedelta
from minio import Minio
from kb_common.config import get_settings
_s = get_settings()
minio = Minio(_s.minio_endpoint, access_key=_s.minio_access_key,
              secret_key=_s.minio_secret_key, secure=False)
RAW = "raw-docs"; PARSED = "parsed-docs"
for b in (RAW, PARSED):
    if not minio.bucket_exists(b): minio.make_bucket(b)


def upload_bytes(bucket: str, key: str, data: bytes, content_type: str = "application/octet-stream") -> str:
    """上传字节到 Minio，返回对象 key。"""
    minio.put_object(bucket, key, io.BytesIO(data), len(data), content_type=content_type)
    return key


def presigned_url(bucket: str, key: str, expires: timedelta = timedelta(hours=24)) -> str:
    """生成预签名下载 URL。"""
    return minio.presigned_get_object(bucket, key, expires=expires)
