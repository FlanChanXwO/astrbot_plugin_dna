"""建立 rewrite/v0.1 的五张新业务表。

Revision ID: 0001_initial
Revises:
"""

import sqlalchemy as sa

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """从空库创建 normalized schema，不读取或改写旧 dnaby.db。"""
    op.create_table(
        "account_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_account_bindings"),
        sa.UniqueConstraint(
            "user_id",
            "bot_id",
            "uid",
            name="uq_account_bindings_identity",
        ),
    )
    op.create_index(
        "ix_account_bindings_lookup",
        "account_bindings",
        ["user_id", "bot_id"],
    )

    op.create_table(
        "credential_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column(
            "app_cookie", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "app_device_code", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("app_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "app_refresh_token", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "app_status", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("web_token", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_device_code", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column("web_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_refresh_token", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.Column(
            "web_status", sa.Text(), server_default=sa.text("''"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_credential_records"),
        sa.UniqueConstraint(
            "user_id",
            "bot_id",
            "uid",
            name="uq_credential_records_identity",
        ),
    )
    op.create_index(
        "ix_credential_records_lookup",
        "credential_records",
        ["user_id", "bot_id"],
    )

    op.create_table(
        "sign_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "game_sign", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bbs_sign", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bbs_detail", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bbs_like", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bbs_share", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.Column(
            "bbs_reply", sa.Integer(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_sign_records"),
        sa.UniqueConstraint("uid", "date", name="uq_sign_records_uid_date"),
    )
    op.create_index("ix_sign_records_date", "sign_records", ["date"])

    op.create_table(
        "privacy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column(
            "allow_peek", sa.Boolean(), server_default=sa.text("1"), nullable=False
        ),
        sa.Column(
            "uid_hidden", sa.Boolean(), server_default=sa.text("0"), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name="pk_privacy_settings"),
        sa.UniqueConstraint(
            "user_id",
            "bot_id",
            "group_id",
            name="uq_privacy_settings_identity",
        ),
    )
    op.create_index(
        "ix_privacy_settings_lookup",
        "privacy_settings",
        ["user_id", "bot_id"],
    )

    op.create_table(
        "group_privacy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("force_allow_peek", sa.Boolean(), nullable=True),
        sa.Column("force_uid_hidden", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_group_privacy_settings"),
        sa.UniqueConstraint(
            "group_id",
            "bot_id",
            name="uq_group_privacy_settings_identity",
        ),
    )


def downgrade() -> None:
    """按依赖相反顺序删除初始 schema。"""
    op.drop_table("group_privacy_settings")
    op.drop_index("ix_privacy_settings_lookup", table_name="privacy_settings")
    op.drop_table("privacy_settings")
    op.drop_index("ix_sign_records_date", table_name="sign_records")
    op.drop_table("sign_records")
    op.drop_index("ix_credential_records_lookup", table_name="credential_records")
    op.drop_table("credential_records")
    op.drop_index("ix_account_bindings_lookup", table_name="account_bindings")
    op.drop_table("account_bindings")
