from __future__ import annotations

import json

import pytest

from src.infrastructure.i18n.catalog import (
    I18nCatalogError,
    I18nKeyError,
    I18nTemplateError,
    TipCatalog,
)
from src.modules.checkin import messages as checkin_messages
from src.modules.encyclopedia import messages as encyclopedia_messages
from src.modules.notices import messages as notices_messages
from src.modules.player import messages as player_messages


def test_tip_catalog_reads_nested_template(tmp_path):
    path = tmp_path / "tip.json"
    path.write_text(
        json.dumps(
            {"account": {"login_page": "登录地址：{url}"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    catalog = TipCatalog(path)

    assert catalog.get("account.login_page", url="https://example.test/login") == (
        "登录地址：https://example.test/login"
    )


@pytest.mark.parametrize(
    ("payload", "error", "message"),
    [
        (None, I18nCatalogError, "文案文件不存在"),
        ("{", I18nCatalogError, "JSON 损坏"),
        ("[]", I18nCatalogError, "根节点必须是对象"),
        ('{"account": {"login_page": 1}}', I18nCatalogError, "叶子节点必须是字符串"),
        ('{"account": {"login_page": ""}}', I18nCatalogError, "叶子节点不能为空"),
        (
            '{"account": {"login_page": "登录地址：{url"}}',
            I18nTemplateError,
            "模板格式错误",
        ),
    ],
)
def test_tip_catalog_rejects_invalid_catalog(tmp_path, payload, error, message):
    path = tmp_path / "tip.json"
    if payload is None:
        with pytest.raises(error, match=message):
            TipCatalog(path)
        return
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(error, match=message):
        TipCatalog(path)


def test_tip_catalog_reports_missing_key_and_template_parameter(tmp_path):
    path = tmp_path / "tip.json"
    path.write_text(
        '{"account": {"login_page": "登录地址：{url}", "uid": "UID：{uid}"}}',
        encoding="utf-8",
    )
    catalog = TipCatalog(path)

    with pytest.raises(I18nKeyError, match="account.missing"):
        catalog.get("account.missing")
    with pytest.raises(I18nTemplateError, match="account.uid.*uid"):
        catalog.get("account.uid")


def test_account_not_bound_tips_are_actionable_and_target_aware() -> None:
    assert encyclopedia_messages.account_not_bound() == "当前未绑定账号，请先登录"
    assert (
        encyclopedia_messages.account_not_bound(target=True)
        == "目标用户尚未绑定账号，无法查询"
    )
    assert player_messages.account_not_bound() == "当前未绑定账号，请先登录"
    assert (
        player_messages.account_not_bound(target=True)
        == "目标用户尚未绑定账号，无法查询"
    )
    assert checkin_messages.account_not_bound() == "当前未绑定账号，请先登录"
    assert (
        checkin_messages.account_not_bound(target=True)
        == "目标用户尚未绑定账号，无法查询"
    )
    assert notices_messages.account_not_bound() == "当前未绑定账号，请先登录"
    assert (
        notices_messages.account_not_bound(target=True)
        == "目标用户尚未绑定账号，无法查询"
    )


def test_credential_tips_are_actionable_and_target_aware() -> None:
    self_tip = "登录已失效，请重新登录"
    target_tip = "账号凭据无效，请重新登录"

    assert encyclopedia_messages.transport_error("credential") == self_tip
    assert (
        encyclopedia_messages.transport_error("credential", target=True) == target_tip
    )
    assert player_messages.transport_error("credential") == self_tip
    assert player_messages.transport_error("credential", target=True) == target_tip
    assert (
        checkin_messages.transport_error(checkin_messages.CheckinFailureKind.CREDENTIAL)
        == self_tip
    )
    assert (
        checkin_messages.transport_error(
            checkin_messages.CheckinFailureKind.CREDENTIAL, target=True
        )
        == target_tip
    )
    assert notices_messages.transport_error("credential") == self_tip
    assert notices_messages.transport_error("credential", target=True) == target_tip


def test_common_service_tip_has_no_duplicated_service_word() -> None:
    tip = encyclopedia_messages.transport_error("server")

    assert tip == "服务暂不可用，请稍后重试"
    assert tip.count("服务") == 1


def test_damage_messages_are_catalog_backed() -> None:
    assert player_messages.damage_config_missing("菲娜") == "官方 H5 缺少菲娜的伤害配置"
    assert player_messages.damage_not_open("菲娜") == "官方 H5 暂未开放菲娜的伤害计算"
    assert (
        player_messages.damage_role_level_unsupported("菲娜", 75)
        == "角色「菲娜」Lv.75 不在官网计算档位中"
    )
    assert (
        player_messages.damage_weapon_level_unsupported("近战武器", "武器甲", 25)
        == "近战武器「武器甲」Lv.25 不在官网计算档位中"
    )
