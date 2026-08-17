"""Task 14 legacy API/model 到 typed encyclopedia contract 的边界测试。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from src.infrastructure.http.encyclopedia import DnaApiEncyclopediaTransport


SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_legacy_short_note_payload_maps_without_dropping_draft_fields() -> None:
    snapshot = DnaApiEncyclopediaTransport._short_note(
        {
            "rougeLikeRewardCount": 2,
            "rougeLikeRewardTotal": 5,
            "currentTaskProgress": 3,
            "maxDailyTaskProgress": 6,
            "hardBossRewardCount": 4,
            "hardBossRewardTotal": 8,
            "dungeonReward": 1,
            "dungeonRewardTotal": 3,
            "draftInfo": {
                "draftDoingNum": 1,
                "draftMaxNum": 2,
                "draftDoingInfo": [
                    {
                        "draftCompleteNum": 0,
                        "draftDoingNum": 3,
                        "startTime": "2026-08-11 08:00:00",
                        "endTime": "2026-08-11 12:00:00",
                        "productId": 10,
                        "productName": "测试矿石",
                    },
                ],
            },
        },
    )

    assert snapshot.current_task_progress == 3
    assert snapshot.drafts[0].product_name == "测试矿石"
    assert snapshot.drafts[0].end_at is not None
    assert snapshot.drafts[0].draft_doing_num == 3
    assert snapshot.draft_doing_num == 1
    assert snapshot.draft_max_num == 2


def test_legacy_weekly_payload_maps_all_categories_and_items() -> None:
    report = DnaApiEncyclopediaTransport._weekly(
        {
            "categories": [
                {
                    "categoryName": "资源分类",
                    "isBase": False,
                    "type": 1,
                    "items": [
                        {
                            "icon": "weekly://1",
                            "itemId": 1,
                            "itemName": "完整资源",
                            "quality": 5,
                            "totalNum": "123",
                        },
                    ],
                },
            ],
            "startDate": "20260803",
            "endDate": "20260809",
            "weekType": 2,
        },
        {"roleInfo": {"roleShow": {
            "roleChars": [],
            "langRangeWeapons": [],
            "closeWeapons": [],
            "level": 55,
            "params": [{"paramKey": "额外统计", "paramValue": "完整"}],
            "roleId": "role-1",
            "roleName": "资料玩家",
            "roleAchv": {"total": 21},
        }}},
    )

    assert report.week_type == 2
    assert report.categories[0].items[0].item_name == "完整资源"
    assert report.role_overview is not None
    assert report.role_overview.role_name == "资料玩家"


def test_code_provider_maps_all_valid_entries_with_their_own_expiry() -> None:
    """provider 的逐码截止时间必须进入 typed transport 输出。"""

    snapshot = DnaApiEncyclopediaTransport._codes(
        {
            "data": [
                {"code": "CODE-A", "end_at": 1787241599},
                {"code": "CODE-B", "end_at": 1787327999},
                {"code": "EXPIRED", "end_at": 1787068799},
            ],
        },
        now=datetime(2026, 8, 20, 0, 0, tzinfo=SHANGHAI),
    )

    assert snapshot.codes == ("CODE-A", "CODE-B")
    assert [(entry.code, entry.expires_at) for entry in snapshot.entries] == [
        ("CODE-A", datetime(2026, 8, 20, 23, 59, 59, tzinfo=SHANGHAI)),
        ("CODE-B", datetime(2026, 8, 21, 23, 59, 59, tzinfo=SHANGHAI)),
    ]


def test_calendar_payloads_merge_legacy_and_new_events_without_rotations() -> None:
    """日历 transport 保留新旧事件，并排除 legacy 明确过滤的轮换活动。"""

    snapshot = DnaApiEncyclopediaTransport._calendar_from_payloads(
        {
            "activities": [
                {
                    "name": "新活动",
                    "icon": "new.png",
                    "startTime": 1787155200000,
                    "endTime": 1787241600000,
                    "cycleDay": -1,
                },
                {
                    "name": "委托密函轮换",
                    "icon": "rotation.png",
                    "startTime": 1787155200000,
                    "endTime": 1787241600000,
                    "cycleDay": -1,
                },
                {
                    "name": "周期活动",
                    "icon": "cycle.png",
                    "startTime": 1787155200000,
                    "endTime": 1787241600000,
                    "cycleDay": 7,
                },
            ],
        },
        [
            {
                "sectionType": 3,
                "activityUps": [
                    {
                        "name": "旧 UP",
                        "createTime": 1787155200000,
                        "endTime": 1787241600000,
                        "contents": [{"pic": "up.png"}],
                    },
                ],
                "activities": [
                    {
                        "name": "旧活动",
                        "pic": "legacy.png",
                        "createTime": 1787155200000,
                        "endTime": 1787241600000,
                    },
                ],
            },
        ],
    )

    events = {event.title: event for event in snapshot.events}
    assert {"魔灵", "周本", "旧 UP", "旧活动", "新活动"} <= events.keys()
    assert "委托密函轮换" not in events
    assert "周期活动" not in events
    assert events["旧 UP"].start_at is not None
    assert events["新活动"].end_at is not None


def test_base_calendar_events_do_not_import_legacy_renderer(monkeypatch) -> None:
    """轮换时间计算是纯逻辑，资料 transport 不应触发旧渲染器的导入副作用。"""

    import builtins

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "dnaby.dna_calendar.draw_calendar_card":
            raise AssertionError("资料 transport 不应导入 legacy 日历渲染器")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)

    events = DnaApiEncyclopediaTransport._base_calendar_events(
        datetime(2026, 8, 20, 12, 0, tzinfo=SHANGHAI),
    )

    assert [event.title for event in events] == ["魔灵", "周本"]
    assert all(event.start_at is not None and event.end_at is not None for event in events)
