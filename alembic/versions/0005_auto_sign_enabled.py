"""为每个用户 UID 绑定增加独立的自动签到开关。"""

import sqlalchemy as sa

from alembic import op

revision = "0005_auto_sign_enabled"
down_revision = "0004_app_credentials_only"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """默认开启已有绑定，保持升级前的自动签到行为。"""

    with op.batch_alter_table("account_bindings", recreate="always") as batch:
        batch.add_column(
            sa.Column(
                "auto_sign_enabled",
                sa.Boolean(),
                server_default=sa.text("1"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    """回退只移除开关字段，不修改绑定记录。"""

    with op.batch_alter_table("account_bindings", recreate="always") as batch:
        batch.drop_column("auto_sign_enabled")
