from minio import Minio
from kb_common.config import get_settings
_s = get_settings()
minio = Minio(_s.minio_endpoint, access_key=_s.minio_access_key,
              secret_key=_s.minio_secret_key, secure=False)
RAW = "raw-docs"; PARSED = "parsed-docs"
for b in (RAW, PARSED):
    if not minio.bucket_exists(b): minio.make_bucket(b)
