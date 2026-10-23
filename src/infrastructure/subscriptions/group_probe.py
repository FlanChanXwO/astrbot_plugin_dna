"""Query platform membership before retiring unreachable group subscriptions."""

from __future__ import annotations

import inspect
from collections.abc import Mapping
from typing import Any


async def probe_group_membership(
    context: Any, platform_id: str, group_id: str
) -> bool | None:
    """True: accessible; False: confirmed absent; None: cannot verify."""

    get_platform = getattr(context, "get_platform_inst", None)
    if not callable(get_platform):
        return None
    platform = get_platform(platform_id)
    if platform is None:
        return None
    meta = getattr(platform, "meta", None)
    name = getattr(meta() if callable(meta) else meta, "name", None)

    if name == "aiocqhttp":
        client = getattr(platform, "bot", None)
        call_action = getattr(client, "call_action", None)
        if not callable(call_action):
            return None
        try:
            response = call_action("get_group_list")
            if inspect.isawaitable(response):
                response = await response
        except Exception:  # noqa: BLE001 - Probe failure means unknown membership.
            return None
        if isinstance(response, Mapping):
            if response.get("status") not in (None, "ok"):
                return None
            response = response.get("data")
        if not isinstance(response, list) or any(
            not isinstance(item, Mapping) or "group_id" not in item for item in response
        ):
            return None
        return any(str(item["group_id"]) == group_id for item in response)

    if name == "telegram" and group_id.lstrip("-").isdigit():
        client = getattr(platform, "client", None)
        if not callable(getattr(client, "get_me", None)) or not callable(
            getattr(client, "get_chat_member", None)
        ):
            return None
        try:
            bot = await client.get_me()
            member = await client.get_chat_member(chat_id=int(group_id), user_id=bot.id)
        except Exception as error:  # noqa: BLE001 - Distinguish known platform errors.
            # Telegram differentiates absent chats/membership from network errors.
            reason = str(error).casefold()
            if type(error).__name__ in ("Forbidden", "BadRequest") and any(
                text in reason
                for text in (
                    "chat not found",
                    "bot was kicked",
                    "bot is not a member",
                    "user not found",
                )
            ):
                return False
            return None
        status = str(getattr(member, "status", "")).lower()
        if status in ("left", "kicked", "banned"):
            return False
        if status == "restricted":
            return bool(getattr(member, "is_member", False))
        return True if status in ("creator", "administrator", "member") else None

    return None
