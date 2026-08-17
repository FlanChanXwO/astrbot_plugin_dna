from __future__ import annotations

import subprocess
import unicodedata
from pathlib import Path

from astrbot.api import logger
from PIL import Image, ImageDraw, ImageFont

from ..rendering import (
    HtmlRenderer,
    RenderSpec,
    font_data_uri,
    image_data_uri,
    pil_image_data_uri,
)
from ..utils.fonts.dna_fonts import EMOJI_ORIGIN_PATH, FONT_ORIGIN_PATH


def _get_git_logs() -> list[str]:
    try:
        process = subprocess.Popen(
            ["git", "log", "--pretty=format:%s", "-40"],
            cwd=str(Path(__file__).parents[2]),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout, stderr = process.communicate()
        if process.returncode != 0:
            logger.warning(f"Git log failed: {stderr.decode('utf-8', errors='ignore')}")
            return []
        commits = stdout.decode("utf-8", errors="ignore").split("\n")

        filtered_commits = []
        for commit in commits:
            if commit:
                emojis, _ = _extract_leading_emojis(commit)
                if emojis:
                    filtered_commits.append(commit)
                    if len(filtered_commits) >= 18:
                        break
        return filtered_commits
    except (OSError, subprocess.SubprocessError, UnicodeError) as exc:
        logger.warning(f"Get logs failed: {exc}")
        return []


def _extract_leading_emojis(message: str) -> tuple[list[str], str]:
    """提取消息开头连续的 emoji，并返回剩余文本。"""

    emojis = []
    index = 0
    while index < len(message):
        char = message[index]
        if char == "\ufe0f":
            index += 1
            continue
        if unicodedata.category(char) in ("So", "Sk"):
            emojis.append(char)
            index += 2 if index + 1 < len(message) and message[index + 1] == "\ufe0f" else 1
        else:
            break
    return emojis, message[index:].lstrip()


_CACHED_LOGS: list[str] | None = None


def _get_cached_logs() -> list[str]:
    """首次查看更新记录时才执行 git log，避免导入插件时污染日志。"""

    global _CACHED_LOGS
    if _CACHED_LOGS is None:
        _CACHED_LOGS = _get_git_logs()
    return _CACHED_LOGS


TEXT_PATH = Path(__file__).parent / "texture2d"
BACKGROUND_PATH = Path(__file__).parents[1] / "utils" / "texture2d" / "bg.jpg"
CARD_W = 950
_RENDERER = HtmlRenderer()


def _build_log_payload(logs: list[str]) -> list[dict[str, str]]:
    payload: list[dict[str, str]] = []
    for raw_log in logs:
        emojis, text = _extract_leading_emojis(raw_log)
        if not emojis:
            continue
        if ")" in text:
            text = text.split(")")[0] + ")"
        payload.append({"emojis": "".join(emojis[:4]), "text": text.replace("`", "")})
    return payload


def _render_emoji_sprite(emoji: str, target_size: int = 48) -> Image.Image:
    """沿用 legacy 的 NotoColorEmoji 栅格化，避免浏览器系统 emoji 发生漂移。"""

    font = ImageFont.truetype(str(EMOJI_ORIGIN_PATH), size=109)
    probe = ImageDraw.Draw(Image.new("RGBA", (218, 218), (0, 0, 0, 0)))
    bbox = probe.textbbox((0, 0), emoji, font=font, anchor="lt")
    width = max(1, int(bbox[2] - bbox[0]))
    height = max(1, int(bbox[3] - bbox[1]))
    sprite = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    ImageDraw.Draw(sprite).text((-bbox[0], -bbox[1]), emoji, font=font, embedded_color=True)
    if width > height:
        size = (target_size, max(1, int(height * target_size / width)))
    else:
        size = (max(1, int(width * target_size / height)), target_size)
    return sprite.resize(size, Image.Resampling.LANCZOS)


def _emoji_images(logs: list[dict[str, str]]) -> list[str]:
    return [pil_image_data_uri(_render_emoji_sprite(log["emojis"])) for log in logs]


async def draw_update_log_img(logs: list[str] | None = None) -> bytes | str:
    """以 HTML/T2I 渲染更新记录，保留无日志时的旧错误文案。"""

    if logs is None:
        logs = _get_cached_logs()
    if not logs:
        return "获取失败"

    payload = _build_log_payload(logs)
    return await _RENDERER.render(
        "cards/update_log.html.j2",
        {
            "background": image_data_uri(BACKGROUND_PATH),
            "font": font_data_uri(FONT_ORIGIN_PATH),
            "logs": payload,
            "emoji_images": _emoji_images(payload),
            "title_image": image_data_uri(TEXT_PATH / "log_title.png"),
            "width": CARD_W,
        },
        RenderSpec(width=CARD_W, full_page=True, image_format="jpeg"),
    )
