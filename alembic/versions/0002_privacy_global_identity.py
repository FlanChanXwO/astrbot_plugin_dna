"""约束 SQLite 全局隐私设置的一人一行语义。"""

import sqlalchemy as sa

from alembic import op

revision = "0002_privacy_global_identity"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """把可空 group_id 的全局作用域纳入唯一性约束。"""
    op.create_index(
        "uq_privacy_settings_global_identity",
        "privacy_settings",
        ["user_id", "bot_id"],
        unique=True,
        sqlite_where=sa.text("group_id IS NULL"),
    )


def downgrade() -> None:
    """移除本轮新增的 SQLite 全局作用域唯一索引。"""
    op.drop_index(
        "uq_privacy_settings_global_identity",
        table_name="privacy_settings",
    )
