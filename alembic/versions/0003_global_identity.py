"""将账号、凭据和隐私数据改为跨 Bot 的全局身份。

本 revision 有意丢弃旧四张身份/隐私表中的全部行：旧表以 ``bot_id`` 为身份组成部分，
无法在不引入隐式合并规则的情况下安全转换为全局语义。``sign_records`` 是独立的
UID/日期历史表，因此原样保留。

Downgrade 只能恢复旧 schema 的空表结构，不能恢复升级时丢弃的数据；真实回滚必须
使用迁移前的数据库备份。

Revision ID: 0003_global_identity
Revises: 0002_privacy_global_identity
"""

import sqlalchemy as sa

from alembic import op

revision = "0003_global_identity"
down_revision = "0002_privacy_global_identity"
branch_labels = None
depends_on = None


def _drop_identity_tables() -> None:
    """删除需要改变 identity 语义的四张表，不触碰签到历史。"""

    op.drop_table("group_privacy_settings")
    op.drop_table("privacy_settings")
    op.drop_table("credential_records")
    op.drop_table("account_bindings")


def _create_global_identity_tables() -> None:
    """创建不含 bot_id 的全局身份/隐私表。"""

    op.create_table(
        "account_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_account_bindings"),
        sa.UniqueConstraint(
            "user_id",
            "uid",
            name="uq_account_bindings_identity",
        ),
    )
    op.create_index(
        "ix_account_bindings_lookup",
        "account_bindings",
        ["user_id"],
    )
    op.create_index(
        "uq_account_bindings_active_user",
        "account_bindings",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("is_active = 1"),
    )

    op.create_table(
        "credential_records",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("app_cookie", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "app_device_code",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("app_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "app_refresh_token",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("app_status", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("web_token", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_device_code",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("web_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_refresh_token",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("web_status", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_credential_records"),
        sa.UniqueConstraint(
            "user_id",
            "uid",
            name="uq_credential_records_identity",
        ),
    )
    op.create_index(
        "ix_credential_records_lookup",
        "credential_records",
        ["user_id"],
    )

    op.create_table(
        "privacy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("allow_peek", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("uid_hidden", sa.Boolean(), server_default=sa.text("0"), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_privacy_settings"),
        sa.UniqueConstraint(
            "user_id",
            "group_id",
            name="uq_privacy_settings_identity",
        ),
    )
    op.create_index(
        "ix_privacy_settings_lookup",
        "privacy_settings",
        ["user_id"],
    )
    op.create_index(
        "uq_privacy_settings_global_identity",
        "privacy_settings",
        ["user_id"],
        unique=True,
        sqlite_where=sa.text("group_id IS NULL"),
    )

    op.create_table(
        "group_privacy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("group_id", sa.Text(), nullable=False),
        sa.Column("force_allow_peek", sa.Boolean(), nullable=True),
        sa.Column("force_uid_hidden", sa.Boolean(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_group_privacy_settings"),
        sa.UniqueConstraint(
            "group_id",
            name="uq_group_privacy_settings_identity",
        ),
    )


def _create_legacy_identity_tables() -> None:
    """downgrade 时恢复 0002 的旧空表结构，不伪造数据恢复。"""

    op.create_table(
        "account_bindings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("uid", sa.Text(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("1"), nullable=False),
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
        sa.Column("app_cookie", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "app_device_code",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("app_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "app_refresh_token",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("app_status", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("web_token", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_device_code",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("web_d_num", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column(
            "web_refresh_token",
            sa.Text(),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column("web_status", sa.Text(), server_default=sa.text("''"), nullable=False),
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
        "privacy_settings",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("bot_id", sa.Text(), nullable=False),
        sa.Column("group_id", sa.Text(), nullable=True),
        sa.Column("allow_peek", sa.Boolean(), server_default=sa.text("1"), nullable=False),
        sa.Column("uid_hidden", sa.Boolean(), server_default=sa.text("0"), nullable=False),
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
    op.create_index(
        "uq_privacy_settings_global_identity",
        "privacy_settings",
        ["user_id", "bot_id"],
        unique=True,
        sqlite_where=sa.text("group_id IS NULL"),
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


def upgrade() -> None:
    """重建四张身份/隐私表，保留独立的 sign_records。"""

    _drop_identity_tables()
    _create_global_identity_tables()


def downgrade() -> None:
    """恢复 0002 的旧空 schema；升级丢弃的数据不能由此恢复。"""

    _drop_identity_tables()
    _create_legacy_identity_tables()
