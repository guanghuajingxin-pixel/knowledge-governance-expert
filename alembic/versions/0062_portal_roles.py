"""Portal roles + per-user menu permission overrides; widen users.role for custom codes."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "0062_portal_roles"
down_revision = "0061_wiki_library"
branch_labels = None
depends_on = None

SYSTEM_ROLES = [
    ("super_admin", "超级管理员", "系统内置角色，拥有全部能力"),
    ("admin", "管理员", "系统内置角色，可管理知识库与系统配置"),
    ("editor", "编辑者", "系统内置角色，可维护知识库"),
    ("viewer", "查看者", "系统内置角色，可检索问答"),
]


def upgrade():
    op.create_table("portal_roles",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column("menu_permissions", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    # 与 ORM 对齐：unique=True + index=True 渲染为唯一索引（而非约束+普通索引）
    op.create_index("ix_portal_roles_code", "portal_roles", ["code"], unique=True)

    op.create_table("portal_user_menu_overrides",
        sa.Column("user_id", sa.String(36), primary_key=True),
        sa.Column("menu_permissions", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )

    # users.role 放宽到 50 以容纳自定义角色 code
    op.alter_column("users", "role",
                     existing_type=sa.String(20), type_=sa.String(50))

    # 种子 4 个系统角色：menu_permissions NULL = 未配置（全部菜单）
    roles_tbl = sa.table("portal_roles",
        sa.column("id", UUID(as_uuid=True)),
        sa.column("code", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.Text),
        sa.column("is_system", sa.Boolean),
        sa.column("menu_permissions", sa.JSON),
    )
    import uuid as _uuid
    op.bulk_insert(roles_tbl, [
        {"id": _uuid.uuid4(), "code": code, "name": name,
         "description": desc, "is_system": True, "menu_permissions": None}
        for code, name, desc in SYSTEM_ROLES
    ])


def downgrade():
    # 收窄列前把自定义角色回落到 viewer，避免超长值截断报错
    op.execute(
        "UPDATE users SET role='viewer' WHERE role NOT IN "
        "('super_admin','admin','editor','viewer')")
    op.alter_column("users", "role",
                     existing_type=sa.String(50), type_=sa.String(20))
    op.drop_table("portal_user_menu_overrides")
    op.drop_index("ix_portal_roles_code", table_name="portal_roles")
    op.drop_table("portal_roles")
