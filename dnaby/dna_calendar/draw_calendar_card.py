from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from zoneinfo import ZoneInfo

from PIL import Image
from pydantic import BaseModel

from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    font_data_uri,
    image_data_uri,
    pil_image_data_uri,
)
from ..utils.dna_api import dna_api
from ..utils.fonts.dna_fonts import FONT_ORIGIN_PATH
from ..utils.image import download_pic_from_url
from ..utils.image_utils import crop_center_img
from ..utils.resource.RESOURCE_PATH import CALENDAR_PATH
from ..utils.session import EventContext

TEXT_PATH = Path(__file__).parent / "texture2d"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
_RENDERER = HtmlRenderer()


class TimeType(str, Enum):
    MOLING = "moling"
    MIHAN = "mihan"
    ZHOUBEN = "zhouben"


START_TIME = {
    TimeType.MOLING: {
        "start_time": datetime(2026, 1, 3, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 86400 * 3,
    },
    TimeType.MIHAN: {
        "start_time": datetime(2026, 1, 3, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 3600,
    },
    TimeType.ZHOUBEN: {
        "start_time": datetime(2025, 12, 29, 5, 0, tzinfo=SHANGHAI_TZ),
        "date_range": 86400 * 7,
    },
}


def get_time(now: datetime, time_type: TimeType):
    if now.tzinfo is None:
        now = now.replace(tzinfo=SHANGHAI_TZ)
    else:
        now = now.astimezone(SHANGHAI_TZ)
    start_time = START_TIME[time_type]["start_time"]
    date_range = START_TIME[time_type]["date_range"]
    date_range_td = timedelta(seconds=date_range)
    elapsed_time = (now - start_time).total_seconds()
    period_index = int(elapsed_time // date_range)
    period_start = start_time + period_index * date_range_td
    period_end = period_start + date_range_td
    return {
        "start_time": period_start,
        "end_time": period_end,
        "start_date_str": period_start.strftime("%Y-%m-%d %H:%M"),
        "end_date_str": period_end.strftime("%Y-%m-%d %H:%M"),
    }


class CalendarContent(BaseModel):
    title: str
    pic: str
    start_time: str | int
    end_time: str | int


def _calendar_background(height: int) -> Image.Image:
    """按旧 PIL 的中心裁剪规则生成最终画布背景。"""

    with Image.open(TEXT_PATH / "bg.jpg") as opened:
        return crop_center_img(opened.convert("RGBA"), 1200, height)


async def _load_banner(height: int) -> str:
    """按旧 PIL 合成顺序预合成 banner，避免 T2I 对透明 JPEG 的底色差异。"""

    banner_bg = Image.open(TEXT_PATH / "banner_bg.webp").convert("RGBA").resize((1200, 675))
    banner_mask = Image.open(TEXT_PATH / "banner_mask.png").getchannel("A")
    banner_bg = crop_center_img(banner_bg, banner_mask.width, banner_mask.height)
    # legacy 在日历背景上以 mask 粘贴 banner；在插件侧完成这一步，
    # 模板只接收最终不透明素材，避免渲染服务以黑色处理透明像素。
    background = _calendar_background(height).crop((0, 150, 1200, 750))
    banner = Image.alpha_composite(background, Image.merge("RGBA", (*banner_bg.split()[:3], banner_mask)))
    frame = Image.open(TEXT_PATH / "banner_frame.png").convert("RGBA")
    banner.alpha_composite(frame)
    return pil_image_data_uri(banner)


def _event_dates(cont: CalendarContent) -> list[str]:
    date_range: list[str] = []
    if isinstance(cont.start_time, str) and cont.start_time:
        date_range.append(cont.start_time)
    if isinstance(cont.end_time, str) and cont.end_time:
        date_range.append(cont.end_time)
    if isinstance(cont.start_time, int) and cont.start_time > 0:
        date_range.append(datetime.fromtimestamp(cont.start_time, tz=SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M"))
    if isinstance(cont.end_time, int) and cont.end_time > 0:
        date_range.append(datetime.fromtimestamp(cont.end_time, tz=SHANGHAI_TZ).strftime("%Y-%m-%d %H:%M"))
    return date_range


def _event_payload(cont: CalendarContent, now: datetime) -> dict[str, object]:
    date_range = _event_dates(cont)
    payload: dict[str, object] = {
        "date_range": " ~ ".join(date_range),
        "icon": None,
        "left": "",
        "left_color": "white",
        "progress": 0,
        "progress_color": "gold",
        "status": "",
        "title": cont.title,
    }
    if len(date_range) < 2:
        return payload

    start_time = datetime.strptime(date_range[0], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    end_time = datetime.strptime(date_range[1], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    status, left, color = get_date_range(date_range, now)
    if status == "已结束":
        progress = 1.0
    else:
        total_duration = (end_time - start_time).total_seconds()
        progress = (now - start_time).total_seconds() / total_duration if total_duration > 0 else 0
    payload.update(
        {
            "date_range": f"{start_time:%m.%d %H:%M} ~ {end_time:%m.%d %H:%M}",
            "left": left,
            "left_color": color,
            "progress": max(0.0, min(progress, 1.0)),
            "progress_color": "white" if status == "已结束" else ("gold" if color == "white" else color),
            "status": status,
        }
    )
    return payload


async def _event_image(cont: CalendarContent) -> str | None:
    if not cont.pic:
        return None
    if "http" in cont.pic:
        image = await download_pic_from_url(CALENDAR_PATH, cont.pic, size=(100, 100))
        return pil_image_data_uri(image)
    return image_data_uri(TEXT_PATH / cont.pic)


async def draw_calendar_img(ctx: EventContext):
    activity_res = await dna_api.get_activity_info()
    activity_list = activity_res.data.get("activities", []) if activity_res.is_success and isinstance(activity_res.data, dict) else []

    wiki_list = []
    wiki_home = await dna_api.get_calendar_info()
    if wiki_home:
        jumu = next(filter(lambda x: x["sectionType"] == 3 and x.get("activityUps") is not None, wiki_home), None)
        old_activity_list = next(filter(lambda x: x["sectionType"] == 3 and x.get("activities") is not None, wiki_home), None)
        if jumu:
            wiki_list.append(jumu)
        if old_activity_list:
            wiki_list.append(old_activity_list)

    if not activity_list and not wiki_list:
        return "获取日历失败"

    now = datetime.now(tz=SHANGHAI_TZ)
    content = [
        CalendarContent(title="魔灵", pic="moling.png", start_time=get_time(now, TimeType.MOLING)["start_date_str"], end_time=get_time(now, TimeType.MOLING)["end_date_str"]),
        CalendarContent(title="周本", pic="zhouben.png", start_time=get_time(now, TimeType.ZHOUBEN)["start_date_str"], end_time=get_time(now, TimeType.ZHOUBEN)["end_date_str"]),
    ]
    if wiki_list:
        for item in wiki_list:
            for activity_up in item.get("activityUps", []):
                start_time, end_time = activity_up.get("createTime"), activity_up.get("endTime")
                content.extend(
                    CalendarContent(
                        title=activity_up.get("name") or entry["name"],
                        pic=entry["pic"],
                        start_time=int(start_time / 1000) if start_time else "",
                        end_time=int(end_time / 1000) if end_time else "",
                    )
                    for entry in activity_up["contents"]
                )
            for activity in item.get("activities", []):
                content.append(
                    CalendarContent(
                        title=activity["name"],
                        pic=activity["pic"],
                        start_time=int(activity["createTime"] / 1000) if activity["createTime"] else "",
                        end_time=int(activity["endTime"] / 1000) if activity["endTime"] else "",
                    )
                )
    for activity in activity_list:
        if activity.get("cycleDay", -1) != -1 or "委托密函轮换" in activity["name"]:
            continue
        start_time, end_time = activity.get("startTime"), activity.get("endTime")
        content.append(
            CalendarContent(
                title=activity["name"],
                pic=activity.get("icon", ""),
                start_time=int(start_time / 1000) if start_time else "",
                end_time=int(end_time / 1000) if end_time else "",
            )
        )

    events = []
    for item in content:
        event = _event_payload(item, now)
        event["icon"] = await _event_image(item)
        events.append(event)

    height = 880 + 170 * ((len(events) + 1) // 2)
    background = _calendar_background(height)

    return await _RENDERER.render(
        "cards/calendar.html.j2",
        {
            "background": pil_image_data_uri(background.convert("RGB"), image_format="JPEG"),
            "banner": await _load_banner(height),
            "events": events,
            "event_background": image_data_uri(TEXT_PATH / "event_bg.png"),
            "bar": image_data_uri(TEXT_PATH / "bar.png"),
            "time_icon": image_data_uri(TEXT_PATH / "time_icon.png"),
            "footer_image": image_data_uri(Path(__file__).parents[1] / "utils" / "texture2d" / "footer.png"),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "footer_text": "DNAUID",
            "height": height,
            "width": 1200,
        },
        RenderSpec(width=1200, height=height, full_page=False, image_format="jpeg"),
    )


def get_left_time_str(remaining_time):
    remaining_days = remaining_time.days
    remaining_hours, remaining_minutes = divmod(remaining_time.seconds, 3600)
    remaining_minutes, _ = divmod(remaining_minutes, 60)
    return f"还剩{remaining_days}天{remaining_hours}小时{remaining_minutes}分钟"


def get_date_range(dateRange, now):
    start_time = datetime.strptime(dateRange[0], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    end_time = datetime.strptime(dateRange[1], "%Y-%m-%d %H:%M").replace(tzinfo=SHANGHAI_TZ)
    now = now.replace(tzinfo=SHANGHAI_TZ) if now.tzinfo is None else now.astimezone(SHANGHAI_TZ)
    if start_time <= now <= end_time:
        remaining_time = end_time - now
        return "进行中", get_left_time_str(remaining_time), "red" if remaining_time.days < 1 else "white"
    if now > end_time:
        return "已结束", "", "white"
    return "未开始", "", "white"
