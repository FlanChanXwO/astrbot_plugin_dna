"""数据库公开接口回归测试。"""

import asyncio
from pathlib import Path

import pytest
from dnaby.utils.database import base as database_base
from dnaby.utils.database.models import (
    NO_CHANGE,
    DNABind,
    DNAGroupPrivacy,
    DNAPrivacy,
    DNASign,
    DNAUser,
)


def _run(awaitable):
    """在未安装 pytest-asyncio 时运行项目的 async 数据库接口。"""
    return asyncio.run(awaitable)


@pytest.fixture
def initialized_db(tmp_path: Path):
    """为每个测试建立独立 SQLite 文件，并清理引擎全局状态。"""
    if database_base._engine is not None:
        _run(database_base.close_db())
    database_base._engine = None
    database_base._sessionmaker = None

    db_path = tmp_path / "dnaby.db"
    database_base.init_db(db_path)
    try:
        _run(database_base.create_db_and_tables())
        yield db_path
    finally:
        if database_base._engine is not None:
            _run(database_base.close_db())
        database_base._engine = None
        database_base._sessionmaker = None
        for suffix in ("", "-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)


def test_init_db_and_create_db_and_tables(initialized_db: Path):
    """初始化并建表后，临时 SQLite 文件应已创建。"""
    assert initialized_db.is_file()


def test_dnabind_supports_multiple_uid_lifecycle(initialized_db: Path):
    """DNABind 支持多 UID、去重、切换以及逐个删除。"""
    user_id = "user-1"
    bot_id = "bot-1"

    assert _run(DNABind.insert_uid(user_id, bot_id, "1001", group_id="group-1", lenth_limit=4)) == 0
    assert _run(DNABind.get_uid_list_by_game(user_id, bot_id)) == ["1001"]
    assert _run(DNABind.get_uid_by_game(user_id, bot_id)) == "1001"

    assert _run(DNABind.insert_uid(user_id, bot_id, "1002", lenth_limit=4)) == 0
    assert _run(DNABind.get_uid_list_by_game(user_id, bot_id)) == ["1001", "1002"]
    assert _run(DNABind.insert_uid(user_id, bot_id, "1001", lenth_limit=4)) == -2

    assert _run(DNABind.switch_uid_by_game(user_id, bot_id, "1002")) == 0
    assert _run(DNABind.get_uid_list_by_game(user_id, bot_id)) == ["1002", "1001"]
    assert _run(DNABind.switch_uid_by_game(user_id, bot_id, "9999")) == -1

    assert _run(DNABind.delete_uid(user_id, bot_id, "1001")) == 0
    assert _run(DNABind.get_uid_list_by_game(user_id, bot_id)) == ["1002"]
    assert _run(DNABind.delete_uid(user_id, bot_id, "9999")) == -1

    assert _run(DNABind.delete_uid(user_id, bot_id, "1002")) == 0
    assert _run(DNABind.get_uid_list_by_game(user_id, bot_id)) == []
    assert _run(DNABind.select_data(user_id, bot_id)) is None


def test_dnauser_crud_and_cookie_queries(initialized_db: Path):
    """DNAUser 可插入、查询、按 UID 更新，并按 Cookie 查询与删除。"""
    user_id = "user-1"
    bot_id = "bot-1"
    uid = "1001"

    assert (
        _run(
            DNAUser.insert_data(
                user_id,
                bot_id,
                uid=uid,
                cookie="cookie-a",
                dev_code="device-a",
                d_num="d-num-a",
            )
        )
        == 0
    )

    record = _run(DNAUser.select_data(user_id, bot_id))
    assert record is not None
    assert record.uid == uid
    assert record.cookie == "cookie-a"
    assert record.dev_code == "device-a"
    assert _run(DNAUser.select_cookie(uid, user_id, bot_id)) == "cookie-a"
    assert _run(DNAUser.select_data_by_cookie("cookie-a")).uid == uid
    assert _run(DNAUser.select_data_by_cookie_and_uid("cookie-a", uid)).uid == uid

    assert _run(DNAUser.update_data_by_uid(uid, bot_id, cookie="cookie-b", status="有效")) == 0
    updated = _run(DNAUser.select_data_by_cookie_and_uid("cookie-b", uid))
    assert updated is not None
    assert updated.status == "有效"
    assert _run(DNAUser.select_data_list(user_id=user_id, bot_id=bot_id, status="有效")) == [updated]
    assert _run(DNAUser.update_data_by_uid("9999", bot_id, status="无效")) == -1

    assert _run(DNAUser.delete_cookie(user_id, bot_id, uid)) == 1
    assert _run(DNAUser.select_data_by_cookie("cookie-b")) is None


def test_remaining_model_tables_support_public_operations(initialized_db: Path):
    """签到与两类隐私表的公开操作可用，确保五张表都能正常建表。"""
    sign = DNASign.build("2001")
    sign.game_sign = 1
    inserted_sign = _run(DNASign.upsert_dna_sign(sign))
    assert inserted_sign is not None
    assert _run(DNASign.get_sign_data("2001", sign.date)).game_sign == 1

    changed_sign = DNASign(uid="2001", date=sign.date, game_sign=2)
    _run(DNASign.upsert_dna_sign(changed_sign))
    assert _run(DNASign.get_sign_data("2001", sign.date)).game_sign == 2
    assert _run(DNASign.get_all_sign_data_by_date(sign.date))
    _run(DNASign.clear_sign_record(sign.date))
    assert _run(DNASign.get_sign_data("2001", sign.date)) is None

    privacy = _run(
        DNAPrivacy.set_privacy_setting(
            "user-1",
            "bot-1",
            allow_peek=False,
            uid_hidden=True,
        )
    )
    assert privacy.allow_peek is False
    assert privacy.uid_hidden is True
    _run(DNAPrivacy.set_privacy_setting("user-1", "bot-1", allow_peek=True))
    stored_privacy = _run(DNAPrivacy.get_privacy_setting("user-1", "bot-1"))
    assert stored_privacy is not None
    assert stored_privacy.allow_peek is True
    assert stored_privacy.uid_hidden is True
    assert _run(DNAPrivacy.is_uid_hidden("user-1", "bot-1")) is True

    group_privacy = _run(
        DNAGroupPrivacy.set_group_force_privacy(
            "group-1",
            "bot-1",
            force_allow_peek=True,
            force_uid_hidden=False,
        )
    )
    assert group_privacy.group_id == "group-1"
    assert _run(DNAGroupPrivacy.get_group_privacy("group-1", "bot-1")) is not None
    assert _run(DNAGroupPrivacy.check_group_force_privacy("group-1", "bot-1")) is True
    assert _run(DNAGroupPrivacy.check_uid_hidden("group-1", "bot-1")) is False

    _run(
        DNAGroupPrivacy.set_group_force_privacy(
            "group-1",
            "bot-1",
            force_allow_peek=None,
            force_uid_hidden=NO_CHANGE,
        )
    )
    assert _run(DNAGroupPrivacy.check_group_force_privacy("group-1", "bot-1")) is None
    assert _run(DNAGroupPrivacy.check_uid_hidden("group-1", "bot-1")) is False
