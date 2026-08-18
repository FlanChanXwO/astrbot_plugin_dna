"""公告与日历时间处理的时区边界测试。"""

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

SHANGHAI = ZoneInfo("Asia/Shanghai")


def test_announcement_timestamp_is_rendered_in_shanghai_time():
    from src.modules.notices.ann_utils import format_post_time

    timestamp = int(datetime(2026, 1, 3, 5, tzinfo=timezone.utc).timestamp())

    assert format_post_time(timestamp) == "2026-01-03 13:00"


def test_calendar_period_accepts_timezone_aware_now():
    from src.infrastructure.rendering.encyclopedia import TimeType, get_time

    result = get_time(datetime(2026, 1, 3, 6, tzinfo=SHANGHAI), TimeType.MOLING)

    assert result["start_date_str"] == "2026-01-03 05:00"
    assert result["start_time"].tzinfo == SHANGHAI


def test_calendar_activity_range_accepts_timezone_aware_now():
    from src.infrastructure.rendering.encyclopedia import get_date_range

    result = get_date_range(
        ["2026-01-03 05:00", "2026-01-03 07:00"],
        datetime(2026, 1, 3, 6, tzinfo=SHANGHAI),
    )

    assert result[0] == "进行中"
