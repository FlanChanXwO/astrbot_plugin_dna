from src.modules.notices.refresh_text import format_refresh_text


def test_format_refresh_text_compacts_same_type_to_one_line() -> None:
    assert format_refresh_text(
        ["魔之楔:扼守", "魔之楔:探险", "魔之楔:驱离"]
    ) == "密函订阅已刷新：魔之楔「扼守、探险、驱离」"


def test_format_refresh_text_keeps_multiple_types_compact() -> None:
    assert format_refresh_text(
        ["角色:贝蕾妮卡", "角色:赛琪", "魔之楔:扼守"]
    ) == "密函订阅已刷新：角色「贝蕾妮卡、赛琪」；魔之楔「扼守」"
