"""v0.2 持久化模型。

这些模型是 rewrite 的新 schema，不与旧 SQLModel 模型共享 metadata，也不承担
旧数据库的数据迁移。凭据字段仍必须保存在本地私有数据库中，但模型的公开表示
只允许包含可定位记录所需的标识和状态。
"""

from __future__ import annotations

from datetime import date as DateValue
from typing import Any

from sqlalchemy import (
    Boolean,
    Date,
    Index,
    Integer,
    MetaData,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """所有新持久化模型共享的声明式基类。"""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class AccountBinding(Base):
    """用户、Bot 和 UID 的归一化绑定记录。"""

    __tablename__ = "account_bindings"
    __table_args__ = (
        Index("ix_account_bindings_lookup", "user_id", "bot_id"),
        UniqueConstraint(
            "user_id",
            "bot_id",
            "uid",
            name="uq_account_bindings_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    uid: Mapped[str] = mapped_column(Text, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )


class CredentialRecord(Base):
    """账号凭据记录。

    Cookie、refresh token、设备标识和 d_num 都属于敏感字段；任何日志、异常或 DTO
    都不得直接使用 ORM 默认字符串表示。本类提供显式脱敏快照供诊断使用。
    """

    __tablename__ = "credential_records"
    __table_args__ = (
        Index("ix_credential_records_lookup", "user_id", "bot_id"),
        UniqueConstraint(
            "user_id",
            "bot_id",
            "uid",
            name="uq_credential_records_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    uid: Mapped[str] = mapped_column(Text, nullable=False)

    app_cookie: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    app_device_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    app_d_num: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    app_refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    app_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )

    web_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    web_device_code: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    web_d_num: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    web_refresh_token: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )
    web_status: Mapped[str] = mapped_column(
        Text,
        nullable=False,
        default="",
        server_default=text("''"),
    )

    def __repr__(self) -> str:
        """仅返回非敏感字段，避免 ORM 对象被日志意外序列化时泄露凭据。"""
        return (
            "CredentialRecord("
            f"id={self.id!r}, user_id={self.user_id!r}, bot_id={self.bot_id!r}, "
            f"uid={self.uid!r}, app_status={self.app_status!r}, "
            f"web_status={self.web_status!r}, "
            f"has_app_credentials={self.has_app_credentials!r}, "
            f"has_web_credentials={self.has_web_credentials!r})"
        )

    @property
    def has_app_credentials(self) -> bool:
        """返回是否存在任一 App 凭据，不返回凭据内容。"""
        return any(
            (
                self.app_cookie,
                self.app_device_code,
                self.app_d_num,
                self.app_refresh_token,
            )
        )

    @property
    def has_web_credentials(self) -> bool:
        """返回是否存在任一 Web 凭据，不返回凭据内容。"""
        return any(
            (
                self.web_token,
                self.web_device_code,
                self.web_d_num,
                self.web_refresh_token,
            )
        )

    def redacted_snapshot(self) -> dict[str, Any]:
        """生成可用于日志或诊断的脱敏快照。"""
        return {
            "id": self.id,
            "user_id": self.user_id,
            "bot_id": self.bot_id,
            "uid": self.uid,
            "app_status": self.app_status,
            "web_status": self.web_status,
            "has_app_credentials": self.has_app_credentials,
            "has_web_credentials": self.has_web_credentials,
        }


class SignRecord(Base):
    """按 UID 和日期归档的签到状态。"""

    __tablename__ = "sign_records"
    __table_args__ = (
        Index("ix_sign_records_date", "date"),
        UniqueConstraint("uid", "date", name="uq_sign_records_uid_date"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    uid: Mapped[str] = mapped_column(Text, nullable=False)
    date: Mapped[DateValue] = mapped_column(Date, nullable=False)
    game_sign: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    bbs_sign: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    bbs_detail: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    bbs_like: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    bbs_share: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )
    bbs_reply: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        server_default=text("0"),
    )


class PrivacySetting(Base):
    """用户在 Bot 或群组作用域内的隐私设置。"""

    __tablename__ = "privacy_settings"
    __table_args__ = (
        Index("ix_privacy_settings_lookup", "user_id", "bot_id"),
        Index(
            "uq_privacy_settings_global_identity",
            "user_id",
            "bot_id",
            unique=True,
            sqlite_where=text("group_id IS NULL"),
        ),
        UniqueConstraint(
            "user_id",
            "bot_id",
            "group_id",
            name="uq_privacy_settings_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    group_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    allow_peek: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=True,
        server_default=text("1"),
    )
    uid_hidden: Mapped[bool] = mapped_column(
        Boolean,
        nullable=False,
        default=False,
        server_default=text("0"),
    )


class GroupPrivacySetting(Base):
    """群组级强制隐私设置。"""

    __tablename__ = "group_privacy_settings"
    __table_args__ = (
        UniqueConstraint("group_id", "bot_id", name="uq_group_privacy_settings_identity"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    group_id: Mapped[str] = mapped_column(Text, nullable=False)
    bot_id: Mapped[str] = mapped_column(Text, nullable=False)
    force_allow_peek: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    force_uid_hidden: Mapped[bool | None] = mapped_column(Boolean, nullable=True)


__all__ = [
    "AccountBinding",
    "Base",
    "CredentialRecord",
    "GroupPrivacySetting",
    "PrivacySetting",
    "SignRecord",
]
