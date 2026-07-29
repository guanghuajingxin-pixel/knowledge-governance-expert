"""Seed the initial super_admin user. Idempotent-ish: will fail on duplicate username.

Run from services/kb-common so the venv + kb_common import resolve:
    cd services/kb-common && uv run python ../../scripts/seed_admin.py
"""
import asyncio
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
    async with SessionLocal() as s:
        admin = User(
            username="admin",
            password_hash=hash_password("admin123"),
            role="super_admin",
            email="admin@kb.local",
        )
        s.add(admin)
        await s.commit()
    print("admin / admin123 created")


if __name__ == "__main__":
    asyncio.run(main())
