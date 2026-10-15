"""统一东 8 区：存量 naive timestamp 从 UTC 基准平移到北京时间基准。

背景：此前业务容器/PostgreSQL 均为 UTC，func.now()/datetime.utcnow() 写入的
naive 时间实为 UTC，前端直接展示比北京时间早 8 小时。本次容器统一注入
TZ/PGTZ=Asia/Shanghai 且代码 utcnow→now，存量数据需一次性 +8 小时对齐。

范围：public schema 下全部 timestamp without time zone 列（68 列，均为
UTC 基准——系统从未以本地基准写过 naive 时间）。JSON 列内的时间串、
钉钉原始 modifiedTimestamp 等不受影响。
"""
from alembic import op

revision = "0060_utc_to_shanghai"
down_revision = "0059_sync_source_import_once"
branch_labels = None
depends_on = None

# 只迁移业务表；alembic_version 等无时间列，information_schema 过滤天然排除。
# 计划任务/批次相关的表在批量进程并发写入窗口内可能混入少量新基准时间，
# 由发布流程保证迁移在容器切换后立即执行，窗口内写入量可忽略。
_EXCLUDED_TABLES = {"alembic_version"}


def upgrade():
    op.execute(f"""
    DO $$
    DECLARE r record;
    BEGIN
        FOR r IN
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'timestamp without time zone'
              AND table_name NOT IN ({','.join(f"'{t}'" for t in _EXCLUDED_TABLES)})
        LOOP
            EXECUTE format(
                'UPDATE %I SET %I = %I + INTERVAL ''8 hours''',
                r.table_name, r.column_name, r.column_name);
        END LOOP;
    END $$;
    """)


def downgrade():
    op.execute(f"""
    DO $$
    DECLARE r record;
    BEGIN
        FOR r IN
            SELECT table_name, column_name
            FROM information_schema.columns
            WHERE table_schema = 'public'
              AND data_type = 'timestamp without time zone'
              AND table_name NOT IN ({','.join(f"'{t}'" for t in _EXCLUDED_TABLES)})
        LOOP
            EXECUTE format(
                'UPDATE %I SET %I = %I - INTERVAL ''8 hours''',
                r.table_name, r.column_name, r.column_name);
        END LOOP;
    END $$;
    """)
