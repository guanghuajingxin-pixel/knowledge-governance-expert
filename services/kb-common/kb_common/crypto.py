"""业务系统推送凭证 SecretKey 的对称加密存储（Fernet）。

密钥派生自 JWT_SECRET：sha256(b"kb-business-credential:" + jwt_secret)。
注意：JWT_SECRET 轮换会使存量 cipher 无法解密，需为各业务系统重新颁发密钥。
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from kb_common.config import get_settings

_fernet: Fernet | None = None


def _client() -> Fernet:
    global _fernet
    if _fernet is None:
        secret = (get_settings().jwt_secret or "").encode("utf-8")
        key = base64.urlsafe_b64encode(hashlib.sha256(b"kb-business-credential:" + secret).digest())
        _fernet = Fernet(key)
    return _fernet


def encrypt_secret(plaintext: str) -> str:
    return _client().encrypt(plaintext.encode("utf-8")).decode("ascii")


def decrypt_secret(cipher: str) -> str:
    try:
        return _client().decrypt(cipher.encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise ValueError("密钥解密失败（服务端密钥可能已轮换，请重新颁发）") from exc
