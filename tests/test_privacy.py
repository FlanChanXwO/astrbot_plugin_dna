"""Task 11/12 隐私设置、群组强制策略和查询解析的隔离测试。"""

import asyncio
from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.entry.event import EventActor
from src.infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    PrivacySetting,
    PrivacySettingRepository,
)
from src.modules.privacy.service import PrivacyService


@pytest_asyncio.fixture
async def database(tmp_path) -> AsyncIterator[AsyncDatabase]:
    """为每条隐私测试提供隔离新 SQLite。"""
    database = AsyncDatabase(tmp_path / "dnaby.sqlite3")
    await database.create_schema_for_tests()
    try:
        yield database
    finally:
        await database.dispose()


def _actor(group_id: str | None = "group-1") -> EventActor:
    return EventActor(user_id="user-1", bot_id="bot-1", group_id=group_id)


@pytest.mark.asyncio
async def test_personal_privacy_defaults_and_group_force_precedence(database):
    """个人默认值可修改；群强制值优先，并能在取消后恢复个人设置。"""
    service = PrivacyService(database)

    assert await service.is_peek_allowed("user-1", "bot-1", "group-1") is True
    assert await service.is_uid_hidden("user-1", "bot-1", "group-1") is False

    personal_peek = await service.set_personal_peek(_actor(), False)
    personal_uid = await service.set_personal_uid_hidden(_actor(), True)
    assert personal_peek.text == "已禁止他人查看你的游戏信息~"
    assert personal_uid.text == "已隐藏你的UID，其他人将无法查看~"
    assert await service.is_peek_allowed("user-1", "bot-1", "group-1") is False
    assert await service.is_uid_hidden("user-1", "bot-1", "group-1") is True

    await service.set_group_peek(_actor(), True)
    await service.set_group_uid_hidden(_actor(), False)
    assert await service.is_peek_allowed("user-1", "bot-1", "group-1") is True
    assert await service.is_uid_hidden("user-1", "bot-1", "group-1") is False

    await service.cancel_group_peek(_actor())
    await service.cancel_group_uid_hidden(_actor())
    assert await service.is_peek_allowed("user-1", "bot-1", "group-1") is False
    assert await service.is_uid_hidden("user-1", "bot-1", "group-1") is True


@pytest.mark.asyncio
async def test_personal_write_is_rejected_by_group_force_without_mutating_record(database):
    """群强制设置存在时，个人修改返回可见原因且不产生个人写入。"""
    service = PrivacyService(database)
    await service.set_group_peek(_actor(), True)

    response = await service.set_personal_peek(_actor(), False)

    assert response.text == "当前群已开启全体允许被查看，无法修改个人设置"
    async with database.session() as session:
        from src.infrastructure.persistence import PrivacySettingRepository

        assert (
            await PrivacySettingRepository.get(
                session,
                user_id="user-1",
                bot_id="bot-1",
                group_id=None,
            )
            is None
        )


@pytest.mark.asyncio
async def test_target_admin_setting_requires_group_mention_and_binding(database):
    """指定管理员操作按群聊、@目标和目标绑定三层边界拒绝越权输入。"""
    service = PrivacyService(database)

    assert (
        await service.set_target_peek(_actor(None), "target-1", True)
    ).text == "请在群聊中使用此命令"
    assert (
        await service.set_target_peek(_actor(), None, True)
    ).text == "请@要允许被查看的玩家"
    assert (
        await service.set_target_peek(_actor(), "target-1", True)
    ).text == "该用户未绑定UID"

    async with database.transaction() as session:
        await AccountBindingRepository.add(
            session,
            user_id="target-1",
            bot_id="bot-1",
            uid="1234567890123",
            group_id="group-1",
        )

    response = await service.set_target_peek(_actor(), "target-1", False)
    assert response.text == "已禁止该用户被他人查看游戏信息~"
    assert await service.is_peek_allowed("target-1", "bot-1", "group-1") is False


@pytest.mark.asyncio
async def test_query_resolution_preserves_self_query_and_group_override(database):
    """查询他人时按配置、群强制和目标个人设置解析，查询自己始终放行。"""
    service = PrivacyService(database, allow_mention_query=False)
    actor = _actor()

    disabled = await service.resolve_query(actor, "target-1")
    assert disabled.resolved_user_id == "user-1"
    assert disabled.blocked is True

    self_query = await service.resolve_query(actor, "user-1")
    assert self_query.resolved_user_id == "user-1"
    assert self_query.blocked is False

    service.allow_mention_query = True
    await service.set_personal_peek(
        EventActor(user_id="target-1", bot_id="bot-1"),
        False,
    )
    blocked = await service.resolve_query(actor, "target-1")
    assert blocked.resolved_user_id == "user-1"
    assert blocked.blocked is True

    await service.set_group_peek(actor, True)
    allowed = await service.resolve_query(actor, "target-1")
    assert allowed.resolved_user_id == "target-1"
    assert allowed.blocked is False


@pytest.mark.asyncio
async def test_uid_and_peek_group_settings_are_scoped_by_bot_and_group(database):
    """群强制设置不会串到另一个 Bot 或群组。"""
    service = PrivacyService(database)
    await service.set_group_peek(_actor(), False)
    await service.set_group_uid_hidden(_actor(), True)

    assert await service.is_peek_allowed("user-1", "bot-1", "group-1") is False
    assert await service.is_uid_hidden("user-1", "bot-1", "group-1") is True
    assert await service.is_peek_allowed("user-1", "bot-1", "group-2") is True
    assert await service.is_uid_hidden("user-1", "bot-1", "group-2") is False
    assert await service.is_peek_allowed("user-1", "bot-2", "group-1") is True


@pytest.mark.asyncio
async def test_concurrent_personal_upserts_keep_one_global_record(database):
    """并发个人写入不得因 SQLite NULL 唯一性产生重复全局记录。"""
    service = PrivacyService(database)
    actor = _actor()

    responses = await asyncio.gather(
        *(service.set_personal_peek(actor, index % 2 == 0) for index in range(16)),
    )

    assert all(response.text in {
        "已允许他人查看你的游戏信息~",
        "已禁止他人查看你的游戏信息~",
    } for response in responses)
    async with database.session() as session:
        records = list(
            (
                await session.scalars(
                    select(PrivacySetting).where(
                        PrivacySetting.user_id == "user-1",
                        PrivacySetting.bot_id == "bot-1",
                        PrivacySetting.group_id.is_(None),
                    ),
                )
            ).all()
        )
    assert len(records) == 1


@pytest.mark.asyncio
async def test_global_privacy_identity_is_unique_in_sqlite(database):
    """数据库约束也要阻止绕过 repository 的重复全局隐私记录。"""
    async with database.transaction() as session:
        await PrivacySettingRepository.add(
            session,
            user_id="user-1",
            bot_id="bot-1",
            group_id=None,
        )

    with pytest.raises(IntegrityError):
        async with database.transaction() as session:
            await PrivacySettingRepository.add(
                session,
                user_id="user-1",
                bot_id="bot-1",
                group_id=None,
            )
