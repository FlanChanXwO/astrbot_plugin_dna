"""物理删除凭据表中的 Web 字段，保留 App-only 数据。"""

import sqlalchemy as sa

from alembic import op

revision = "0004_app_credentials_only"
down_revision = "0003_global_identity"
branch_labels = None
depends_on = None

_WEB_COLUMNS = (
    "web_token",
    "web_device_code",
    "web_d_num",
    "web_refresh_token",
    "web_status",
)


def upgrade() -> None:
    """删除 Web 凭据列；SQLite 通过重建表保留其他数据和约束。"""

    with op.batch_alter_table("credential_records", recreate="always") as batch:
        for column_name in _WEB_COLUMNS:
            batch.drop_column(column_name)


def downgrade() -> None:
    """仅创建空 Web 列，不尝试恢复已删除的凭据数据。"""

    with op.batch_alter_table("credential_records", recreate="always") as batch:
        for column_name in _WEB_COLUMNS:
            batch.add_column(
                sa.Column(
                    column_name,
                    sa.Text(),
                    server_default=sa.text("''"),
                    nullable=False,
                ),
            )
