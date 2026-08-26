"""密函、公告列表/详情读取与通知订阅/推送 use case。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...entry.event import EventActor
from ...entry.response import ImageResponse, PlainTextResponse
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import NoticesRenderer
from ...infrastructure.subscriptions import SubscriptionStore
from ..privacy import PrivacyService
from . import messages
from .ann_state import AnnStateStore
from .contracts import (
    NoticeRequest,
    NoticesTransport,
    NoticesTransportError,
)

PushCallable = Callable[[str, str | Path], Awaitable[Any]]
_MH_TYPE_KEYS = ("角色", "武器", "魔之楔")
_ANN_LIST_LIMIT = 20


def _mh_keys(mh_name: str, mh_type: str | None) -> list[str]:
    if mh_type:
        return [f"{mh_type}:{mh_name}"]
    return [f"{kind}:{mh_name}" for kind in _MH_TYPE_KEYS]


class NoticesService:
    """通知读取、订阅管理与推送的协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: NoticesTransport,
        privacy: PrivacyService,
        renderer: NoticesRenderer,
        subscriptions: SubscriptionStore | None = None,
        ann_state: AnnStateStore | None = None,
        push: PushCallable | None = None,
        *,
        secret_simple_image: bool = False,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.subscriptions = subscriptions
        self.ann_state = ann_state
        self.push = push
        self.secret_simple_image = secret_simple_image

    async def _resolve_uid(
        self,
        request: NoticeRequest,
    ) -> tuple[str, str] | PlainTextResponse:
        resolution = await self.privacy.resolve_query(request.actor, request.target_user_id)
        if resolution.blocked:
            return PlainTextResponse(messages.NOTICES_PEEK_BLOCKED, need_at=True)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
                bot_id=request.actor.bot_id,
            )
        if binding is None:
            return PlainTextResponse(messages.NOTICES_UID_INVALID, need_at=True)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: NoticesTransportError) -> PlainTextResponse:
        return PlainTextResponse(messages.transport_error(error.kind), need_at=True)

    async def mh(self, request: NoticeRequest):
        """读取并渲染当前小时段的密函数据。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            snapshot = await self.transport.get_mh(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except NoticesTransportError as error:
            return self._transport_response(error)
        if not snapshot.sections:
            return PlainTextResponse(messages.MH_NOT_FOUND, need_at=True)
        rendered = await self.renderer.render_mh(
            snapshot,
            simple_image=self.secret_simple_image,
        )
        return ImageResponse(str(rendered.path), temporary=True)

    async def mh_list(self, _request: NoticeRequest):
        """返回全部密函委托名称。"""

        from ...utils.api.mh_map import get_mh_list

        return PlainTextResponse("\n".join(get_mh_list()))

    async def ann(self, request: NoticeRequest):
        """读取公告列表；带序号时读取对应公告详情。"""

        index = str(request.parameters.get("index") or "").strip()
        try:
            snapshot = await self.transport.get_ann_list()
        except NoticesTransportError as error:
            return self._transport_response(error)
        if not snapshot.posts:
            return PlainTextResponse(messages.ANN_LIST_FAILED, need_at=True)

        if not index:
            rendered = await self.renderer.render_ann_list(snapshot)
            return ImageResponse(str(rendered.path), temporary=True)

        from .ann_utils import build_index_map, resolve_index

        post_map = build_index_map(
            {"postId": post.post_id} for post in snapshot.posts[: _ANN_LIST_LIMIT]
        )
        post_id = resolve_index(index, post_map)
        if post_id is None:
            return PlainTextResponse(messages.ANN_INDEX_INVALID, need_at=True)
        try:
            detail = await self.transport.get_ann_detail(post_id)
        except NoticesTransportError as error:
            return self._transport_response(error)
        rendered = await self.renderer.render_ann_detail(detail)
        return ImageResponse(str(rendered.path), temporary=True)


    @staticmethod
    async def _origin(actor: EventActor) -> tuple[str, str]:
        origin = actor.unified_msg_origin if actor is not None else None
        if not origin:
            return "", messages.NOTICES_CONTEXT_UNAVAILABLE
        return origin, ""

    async def subscribe_mh(self, request: NoticeRequest):
        """按名称订阅密函委托（user，按会话作用域）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        mh_name = str(request.parameters.get("mh_name", "")).strip()
        mh_type = str(request.parameters.get("mh_type") or "").strip() or None
        if not mh_name:
            return PlainTextResponse(messages.MH_NOT_FOUND, need_at=True)
        if mh_name == "全部":
            return PlainTextResponse(messages.MH_ALL_FORBIDDEN, need_at=True)
        keys = _mh_keys(mh_name, mh_type)

        try:
            target = next(
                (
                    sub
                    for sub in await self.subscriptions.get(
                        messages.MH_SUBSCRIBE,
                        user_id=request.actor.user_id,
                        bot_id=request.actor.bot_id,
                    )
                    if sub.unified_msg_origin == origin and sub.uid == request.actor.user_id
                ),
                None,
            )
            if target is None or not target.extra_message:
                await self.subscriptions.add(
                    messages.MH_SUBSCRIBE,
                    origin=origin,
                    user_id=request.actor.user_id,
                    bot_id=request.actor.bot_id,
                    group_id=request.actor.group_id or "",
                    user_type="group" if request.actor.group_id else "direct",
                    uid=request.actor.user_id,
                    extra_message=",".join(keys),
                )
                return PlainTextResponse(messages.MH_SUBSCRIBED_TEMPLATE.format(names=",".join(keys)), need_at=True)
            existing = [item for item in target.extra_message.split(",") if item]
            if set(keys) <= set(existing):
                return PlainTextResponse(messages.MH_DUPLICATE.format(name=mh_name), need_at=True)
            merged = sorted(set(existing) | set(keys))
            await self.subscriptions.update(
                messages.MH_SUBSCRIBE,
                origin,
                uid=request.actor.user_id,
                extra_message=",".join(merged),
            )
            return PlainTextResponse(
                f"{messages.MH_SUBSCRIBED_TEMPLATE.format(names=mh_name)}!当前订阅密函: {",".join(merged)}",
                need_at=True,
            )
        except RuntimeError:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)

    async def unsubscribe_mh(self, request: NoticeRequest):
        """按名称取消订阅密函委托；全部 时删除当前会话的订阅（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        mh_name = str(request.parameters.get("mh_name", "")).strip()
        mh_type = str(request.parameters.get("mh_type") or "").strip() or None
        try:
            target = next(
                (
                    sub
                    for sub in await self.subscriptions.get(
                        messages.MH_SUBSCRIBE,
                        user_id=request.actor.user_id,
                        bot_id=request.actor.bot_id,
                    )
                    if sub.unified_msg_origin == origin and sub.uid == request.actor.user_id
                ),
                None,
            )
            if target is None or not target.extra_message:
                return PlainTextResponse(messages.MH_NOT_SUBSCRIBED, need_at=True)
            if mh_name == "全部":
                await self.subscriptions.delete(
                    messages.MH_SUBSCRIBE,
                    origin,
                    uid=request.actor.user_id,
                )
                return PlainTextResponse(messages.MH_UNSUBSCRIBED_ALL, need_at=True)
            keys = _mh_keys(mh_name, mh_type)
            remaining = [item for item in target.extra_message.split(",") if item and item not in keys]
            if not remaining:
                await self.subscriptions.delete(
                    messages.MH_SUBSCRIBE,
                    origin,
                    uid=request.actor.user_id,
                )
                return PlainTextResponse(
                    f"{messages.MH_UNSUBSCRIBED.format(name=mh_name)}!当前订阅密函: ",
                    need_at=True,
                )
            await self.subscriptions.update(
                messages.MH_SUBSCRIBE,
                origin,
                uid=request.actor.user_id,
                extra_message=",".join(remaining),
            )
            return PlainTextResponse(
                f"{messages.MH_UNSUBSCRIBED.format(name=mh_name)}!当前订阅密函: {','.join(remaining)}",
                need_at=True,
            )
        except RuntimeError:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)

    async def mh_subscriptions(self, request: NoticeRequest):
        """查看当前会话的密函订阅与推送时间（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        target = next(
            (
                sub
                for sub in await self.subscriptions.get(
                    messages.MH_SUBSCRIBE,
                    user_id=request.actor.user_id,
                    bot_id=request.actor.bot_id,
                )
                if sub.unified_msg_origin == origin and sub.uid == request.actor.user_id
            ),
            None,
        )
        if target is None or not target.extra_message:
            return PlainTextResponse(messages.MH_NOT_SUBSCRIBED, need_at=True)
        lines = [messages.MH_CURRENT.format(names=target.extra_message)]
        if target.extra_data and ":" in target.extra_data:
            start, end = target.extra_data.split(":", 1)
            lines.append(messages.MH_PUSH_TIME_SET.format(start=start, end=end))
        else:
            lines.append(messages.MH_PUSH_TIME_UNLIMITED)
            lines.append(f"可以使用命令设置推送时间: {messages.COMMAND_PREFIX}订阅密函时间17:23")
        return PlainTextResponse("\n".join(lines), need_at=True)

    async def set_mh_push_time(self, request: NoticeRequest):
        """设置密函推送时间窗口（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        try:
            start = int(str(request.parameters.get("start", "")).strip())
            end = int(str(request.parameters.get("end", "")).strip())
        except ValueError:
            return PlainTextResponse(messages.MH_PUSH_TIME_FORMAT, need_at=True)
        if start < 0 or start > 23 or end < 0 or end > 23:
            return PlainTextResponse(messages.MH_PUSH_TIME_FORMAT, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        updated = await self.subscriptions.update(
            messages.MH_SUBSCRIBE,
            origin,
            uid=request.actor.user_id,
            extra_data=f"{start}:{end}",
        )
        if not updated:
            return PlainTextResponse(messages.MH_NOT_SUBSCRIBED, need_at=True)
        return await self.mh_subscriptions(request)

    async def toggle_mh_pic(self, request: NoticeRequest):
        """订阅/取消订阅密函图片推送（admin，会话作用域）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        cancelling = "取消" in request.text
        if cancelling:
            if not await self.subscriptions.delete(messages.MH_PIC_SUBSCRIBE, origin):
                return PlainTextResponse(messages.MH_PIC_NOT_SUBSCRIBED, need_at=True)
            return PlainTextResponse(messages.MH_PIC_UNSUBSCRIBED, need_at=True)
        await self.subscriptions.add(
            messages.MH_PIC_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id or "",
        )
        return PlainTextResponse(messages.MH_PIC_SUBSCRIBED, need_at=True)

    async def toggle_mh_text(self, request: NoticeRequest):
        """订阅/取消订阅密函文本推送（admin，会话作用域）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        cancelling = "取消" in request.text
        if cancelling:
            if not await self.subscriptions.delete(messages.MH_TEXT_SUBSCRIBE, origin):
                return PlainTextResponse(messages.MH_TEXT_NOT_SUBSCRIBED, need_at=True)
            return PlainTextResponse(messages.MH_TEXT_UNSUBSCRIBED, need_at=True)
        await self.subscriptions.add(
            messages.MH_TEXT_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id or "",
        )
        return PlainTextResponse(messages.MH_TEXT_SUBSCRIBED, need_at=True)

    async def _invoke_push(
        self,
        origin: str,
        payload: str | Path,
        at_user_id: str | None = None,
    ) -> bool:
        if self.push is not None:
            try:
                sig = inspect.signature(self.push)
                if (
                    len(sig.parameters) >= 3
                    or "at_user_id" in sig.parameters
                    or any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                ):
                    res = self.push(origin, payload, at_user_id=at_user_id)
                elif at_user_id:
                    try:
                        res = self.push(origin, payload, at_user_id)
                    except TypeError:
                        res = self.push(origin, payload)
                else:
                    res = self.push(origin, payload)

                if inspect.isawaitable(res):
                    await res
                return True
            except Exception as error:  # noqa: BLE001
                from astrbot.api import logger

                logger.warning(f"[dnaby][push] 发送给 {origin} 失败: {error}")
                return False
        return False

    async def test_mh_push(self, request: NoticeRequest):
        """向当前会话发送一次密函测试推送（owner）。"""

        if self.push is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        await self._invoke_push(origin, "密函测试推送")
        return PlainTextResponse(messages.MH_TEST_SENT)

    async def subscribe_ann(self, request: NoticeRequest):
        """订阅公告推送（admin，仅群聊）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        if not request.actor.group_id:
            return PlainTextResponse(messages.ANN_GROUP_ONLY, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        subs = await self.subscriptions.get(
            messages.ANN_SUBSCRIBE,
            group_id=request.actor.group_id,
        )
        if any(sub.group_id == request.actor.group_id for sub in subs):
            return PlainTextResponse(messages.ANN_ALREADY_SUBSCRIBED, need_at=True)
        await self.subscriptions.add(
            messages.ANN_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id,
            user_type="group",
        )
        return PlainTextResponse(messages.ANN_SUBSCRIBED, need_at=True)

    async def unsubscribe_ann(self, request: NoticeRequest):
        """取消订阅公告推送（admin，仅群聊）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        if not request.actor.group_id:
            return PlainTextResponse(messages.ANN_GROUP_UNSUB_ONLY, need_at=True)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error, need_at=True)
        if await self.subscriptions.delete(messages.ANN_SUBSCRIBE, origin):
            return PlainTextResponse(messages.ANN_UNSUBSCRIBED, need_at=True)
        return PlainTextResponse(messages.ANN_NOT_SUBSCRIBED, need_at=True)

    async def push_mh_now(self) -> int:
        """拉取当前密函并按订阅推送文本/图片；返回推送次数（计划任务）。"""

        if self.subscriptions is None or self.push is None:
            return 0
        try:
            snapshot = await self.transport.get_mh_any()
        except NoticesTransportError:
            from astrbot.api import logger

            logger.warning("[dnaby][push_mh] 获取密函数据失败，跳过本次定时推送")
            return 0

        if not snapshot.sections:
            return 0

        from ...utils import get_datetime

        current_hour = get_datetime().hour

        available_names: set[str] = set()
        by_type: dict[str, list[str]] = {}
        for section in snapshot.sections:
            type_name = section.type_name
            instance_names = [item.name for item in section.instances]
            by_type[type_name] = instance_names
            for full_name in instance_names:
                base_name = full_name.split("/")[0]
                available_names.add(base_name)
                available_names.add(full_name)
                available_names.add(f"{type_name}:{base_name}")
                available_names.add(f"{type_name}:{full_name}")

        pushed = 0

        # 1. 个人/群聊按名称订阅 (MH_SUBSCRIBE)
        text_subs = await self.subscriptions.get(messages.MH_SUBSCRIBE)
        for sub in text_subs:
            # 检查时间段限制: "17:23" -> start 17, end 23
            if sub.extra_data and ":" in sub.extra_data:
                try:
                    s_str, e_str = sub.extra_data.split(":", 1)
                    start_h, end_h = int(s_str), int(e_str)
                    if start_h <= end_h:
                        if current_hour < start_h or current_hour > end_h:
                            continue
                    else:
                        if current_hour < start_h and current_hour > end_h:
                            continue
                except (ValueError, TypeError):
                    pass

            names = [item for item in sub.extra_message.split(",") if item]
            if not names:
                continue

            matched = [key for key in names if key in available_names]
            if not matched:
                continue

            lines = ["当前订阅密函已刷新:"]
            for key in matched:
                type_name, _, mh_name = key.partition(":")
                lines.append(f"{type_name} : {mh_name or key}")
            at_target = (sub.uid or sub.user_id) if (sub.user_type == "group" or sub.group_id) else None
            if await self._invoke_push(sub.unified_msg_origin, "\n".join(lines), at_user_id=at_target):
                pushed += 1

        # 2. 全量文本密函订阅 (MH_TEXT_SUBSCRIBE)
        all_text_subs = await self.subscriptions.get(messages.MH_TEXT_SUBSCRIBE)
        if all_text_subs:
            text_lines = ["【密函已刷新】"]
            for type_name in ("角色", "武器", "魔之楔"):
                if by_type.get(type_name):
                    text_lines.append(f"\n-- {type_name} --")
                    text_lines.extend(f"{i}. {name}" for i, name in enumerate(by_type[type_name], start=1))
            full_text = "\n".join(text_lines)
            for sub in all_text_subs:
                at_target = (sub.uid or sub.user_id) if (sub.user_type == "group" or sub.group_id) else None
                if await self._invoke_push(sub.unified_msg_origin, full_text, at_user_id=at_target):
                    pushed += 1

        # 3. 图片密函订阅 (MH_PIC_SUBSCRIBE)
        pic_subs = await self.subscriptions.get(messages.MH_PIC_SUBSCRIBE)
        if pic_subs:
            rendered = await self.renderer.render_mh(
                snapshot,
                simple_image=self.secret_simple_image,
            )
            for sub in pic_subs:
                at_target = (sub.uid or sub.user_id) if (sub.user_type == "group" or sub.group_id) else None
                if await self._invoke_push(sub.unified_msg_origin, rendered.path, at_user_id=at_target):
                    pushed += 1

        return pushed

    async def poll_ann_now(self) -> int:
        """轮询公告并向群订阅者推送新公告图片；返回推送条数（计划任务）。"""

        if self.subscriptions is None or self.push is None or self.ann_state is None:
            return 0
        try:
            snapshot = await self.transport.get_ann_list()
        except NoticesTransportError:
            return 0

        fresh_ids = [int(post.post_id) for post in snapshot.posts if post.post_id.isdigit()]
        pending = await self.ann_state.merge(fresh_ids)
        if not pending:
            return 0

        subs = await self.subscriptions.get(messages.ANN_SUBSCRIBE)
        if not subs:
            return 0

        pushed = 0
        title_by_id = {post.post_id: post.title for post in snapshot.posts}

        for post_id in pending:
            payload: Path | str
            try:
                detail = await self.transport.get_ann_detail(str(post_id))
                rendered = await self.renderer.render_ann_detail(detail)
                payload = rendered.path
            except Exception:  # noqa: BLE001
                title = title_by_id.get(str(post_id), str(post_id))
                payload = f"【最新二重螺旋公告】\n{title}"

            for sub in subs:
                if await self._invoke_push(sub.unified_msg_origin, payload):
                    pushed += 1

        return pushed


__all__ = ["NoticesService"]
