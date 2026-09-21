from passlib.context import CryptContext
from jose import jwt
from datetime import datetime, timedelta, timezone
from kb_common.config import get_settings

_pwd = CryptContext(schemes=["bcrypt"])

def hash_password(p: str) -> str: return _pwd.hash(p)
def verify_password(p: str, h: str) -> bool: return _pwd.verify(p, h)

def create_jwt(user_id: str, role: str, *, dt_unionid: str | None = None,
               must_change_password: bool = False) -> str:
    s = get_settings()
    payload = {"sub": user_id, "role": role,
               "exp": datetime.now(timezone.utc) + timedelta(minutes=s.jwt_ttl_minutes)}
    # dtu=钉钉 unionId（按登录用户维度调钉钉 API 用）；mcp=需强制改密（前端守卫兜底）
    if dt_unionid:
        payload["dtu"] = dt_unionid
    if must_change_password:
        payload["mcp"] = True
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algo)

def decode_jwt(token: str) -> dict:
    return jwt.decode(token, get_settings().jwt_secret, algorithms=[get_settings().jwt_algo])
