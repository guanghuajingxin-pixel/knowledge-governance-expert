"""Seed a local development super_admin using an explicitly supplied strong secret.

Run from services/kb-common so the venv + kb_common import resolve:
    KGE_BOOTSTRAP_ADMIN_PASSWORD='...' uv run python ../../scripts/seed_admin.py

Production using Keycloak should provision the first administrator in Keycloak instead.
"""
import asyncio
import os
import sys
from pathlib import Path

# Make kb_common importable. When run as `python ../../scripts/seed_admin.py`
# from services/kb-common, sys.path[0] is scripts/, not the cwd - so we
# explicitly add the kb-common package dir.
_REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_REPO_ROOT / "services" / "kb-common"))

from kb_common.database import SessionLocal
from kb_common.models import User
from kb_common.security import hash_password


async def main():
    from kb_common.config import get_settings
    if get_settings().auth_provider != "local":
        raise SystemExit("Refusing to seed a local account while AUTH_PROVIDER is not local")
    username = os.environ.get("KGE_BOOTSTRAP_ADMIN_USERNAME", "admin").strip()
    password = os.environ.get("KGE_BOOTSTRAP_ADMIN_PASSWORD", "")
    if not username or len(username) > 100:
        raise SystemExit("KGE_BOOTSTRAP_ADMIN_USERNAME must be 1-100 characters")
    if (len(password) < 16 or len(password) > 64 or len(password.encode("utf-8")) > 72
            or not any(c.islower() for c in password)
            or not any(c.isupper() for c in password)
            or not any(c.isdigit() for c in password)):
        raise SystemExit("Set KGE_BOOTSTRAP_ADMIN_PASSWORD to a 16-64 character password with upper, lower, and numeric characters")
    async with SessionLocal() as s:
        admin = User(
            username=username,
            password_hash=hash_password(password),
            role="super_admin",
            email=None,
        )
        s.add(admin)
        await s.commit()
    print(f"Local super_admin {username!r} created; the password was not printed.")


if __name__ == "__main__":
    asyncio.run(main())
