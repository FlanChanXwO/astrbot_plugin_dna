"""密函、公告列表/详情读取与通知订阅/推送 use case。"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from ...entry.response import ImageResponse, PlainTextResponse
from ...entry.event import EventActor
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
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.subscriptions = subscriptions
        self.ann_state = ann_state
        self.push = push

    async def _resolve_uid(
        self,
        request: NoticeRequest,
    ) -> tuple[str, str] | PlainTextResponse:
        resolution = await self.privacy.resolve_query(request.actor, request.target_user_id)
        if resolution.blocked:
            return PlainTextResponse(messages.NOTICES_PEEK_BLOCKED)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
                bot_id=request.actor.bot_id,
            )
        if binding is None:
            return PlainTextResponse(messages.NOTICES_UID_INVALID)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: NoticesTransportError) -> PlainTextResponse:
        return PlainTextResponse(messages.transport_error(error.kind))

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
            return PlainTextResponse(messages.MH_NOT_FOUND)
        rendered = self.renderer.render_mh(snapshot)
        return ImageResponse(str(rendered.path), temporary=True)

    async def mh_list(self, _request: NoticeRequest):
        """返回全部密函委托名称。"""

        from dnaby.utils.api.mh_map import get_mh_list

        return PlainTextResponse("\n".join(get_mh_list()))

    async def ann(self, request: NoticeRequest):
        """读取公告列表；带序号时读取对应公告详情。"""

        index = str(request.parameters.get("index") or "").strip()
        try:
            snapshot = await self.transport.get_ann_list()
        except NoticesTransportError as error:
            return self._transport_response(error)
        if not snapshot.posts:
            return PlainTextResponse(messages.ANN_LIST_FAILED)

        if not index:
            rendered = self.renderer.render_ann_list(snapshot)
            return ImageResponse(str(rendered.path), temporary=True)

        from dnaby.dna_ann.utils import build_index_map, resolve_index

        post_map = build_index_map(
            {"postId": post.post_id} for post in snapshot.posts[: _ANN_LIST_LIMIT]
        )
        post_id = resolve_index(index, post_map)
        if post_id is None:
            return PlainTextResponse(messages.ANN_INDEX_INVALID)
        try:
            detail = await self.transport.get_ann_detail(post_id)
        except NoticesTransportError as error:
            return self._transport_response(error)
        rendered = self.renderer.render_ann_detail(detail)
        return ImageResponse(str(rendered.path), temporary=True)


    @staticmethod
    async def _origin(actor: EventActor) -> tuple[str, str]:
        origin = actor.unified_msg_origin if actor is not None else None
        if not origin:
            return "", messages.NOTICES_CONTEXT_UNAVAILABLE
        return origin, ""

    async def subscribe_mh(self, request: NoticeRequest):
        """按名称订阅密函委托（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        mh_name = str(request.parameters.get("mh_name", "")).strip()
        mh_type = str(request.parameters.get("mh_type") or "").strip() or None
        if not mh_name:
            return PlainTextResponse(messages.MH_NOT_FOUND)
        if mh_name == "全部":
            return PlainTextResponse(messages.MH_ALL_FORBIDDEN)
        keys = _mh_keys(mh_name, mh_type)

        try:
            subs = await self.subscriptions.get(
                messages.MH_SUBSCRIBE,
                user_id=request.actor.user_id,
                bot_id=request.actor.bot_id,
            )
            target = next((sub for sub in subs if sub.uid == request.actor.user_id), None)
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
                return PlainTextResponse(messages.MH_SUBSCRIBED_TEMPLATE.format(names=",".join(keys)))
            existing = [item for item in target.extra_message.split(",") if item]
            if set(keys) <= set(existing):
                return PlainTextResponse(messages.MH_DUPLICATE.format(name=mh_name))
            merged = sorted(set(existing) | set(keys))
            await self.subscriptions.update(
                messages.MH_SUBSCRIBE,
                origin,
                extra_message=",".join(merged),
            )
            return PlainTextResponse(
                f"{messages.MH_SUBSCRIBED_TEMPLATE.format(names=mh_name)}!当前订阅密函: {','.join(merged)}",
            )
        except RuntimeError:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)

    async def unsubscribe_mh(self, request: NoticeRequest):
        """按名称取消订阅密函委托；全部 时删除整条订阅（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        mh_name = str(request.parameters.get("mh_name", "")).strip()
        mh_type = str(request.parameters.get("mh_type") or "").strip() or None
        try:
            subs = await self.subscriptions.get(
                messages.MH_SUBSCRIBE,
                user_id=request.actor.user_id,
                bot_id=request.actor.bot_id,
            )
            target = next((sub for sub in subs if sub.uid == request.actor.user_id), None)
            if target is None or not target.extra_message:
                return PlainTextResponse(messages.MH_NOT_SUBSCRIBED)
            if mh_name == "全部":
                await self.subscriptions.delete(messages.MH_SUBSCRIBE, origin)
                return PlainTextResponse(messages.MH_UNSUBSCRIBED_ALL)
            keys = _mh_keys(mh_name, mh_type)
            remaining = [item for item in target.extra_message.split(",") if item and item not in keys]
            await self.subscriptions.update(
                messages.MH_SUBSCRIBE,
                origin,
                extra_message=",".join(remaining),
            )
            return PlainTextResponse(
                f"{messages.MH_UNSUBSCRIBED.format(name=mh_name)}!当前订阅密函: {','.join(remaining)}",
            )
        except RuntimeError:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)

    async def mh_subscriptions(self, request: NoticeRequest):
        """查看当前密函订阅与推送时间（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        subs = await self.subscriptions.get(
            messages.MH_SUBSCRIBE,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
        )
        target = next((sub for sub in subs if sub.uid == request.actor.user_id), None)
        if target is None or not target.extra_message:
            return PlainTextResponse(messages.MH_NOT_SUBSCRIBED)
        lines = [messages.MH_CURRENT.format(names=target.extra_message)]
        if target.extra_data and ":" in target.extra_data:
            start, end = target.extra_data.split(":", 1)
            lines.append(messages.MH_PUSH_TIME_SET.format(start=start, end=end))
        else:
            lines.append(messages.MH_PUSH_TIME_UNLIMITED)
            lines.append("可以使用命令设置推送时间: 订阅密函时间17:23")
        return PlainTextResponse("\n".join(lines))

    async def set_mh_push_time(self, request: NoticeRequest):
        """设置密函推送时间窗口（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        try:
            start = int(str(request.parameters.get("start", "")).strip())
            end = int(str(request.parameters.get("end", "")).strip())
        except ValueError:
            return PlainTextResponse(messages.MH_PUSH_TIME_FORMAT)
        if start < 0 or start > 23 or end < 0 or end > 23:
            return PlainTextResponse(messages.MH_PUSH_TIME_FORMAT)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        updated = await self.subscriptions.update(
            messages.MH_SUBSCRIBE,
            origin,
            extra_data=f"{start}:{end}",
        )
        if not updated:
            return PlainTextResponse(messages.MH_NOT_SUBSCRIBED)
        return await self.mh_subscriptions(request)

    async def toggle_mh_pic(self, request: NoticeRequest):
        """订阅/取消订阅密函图片推送（admin，会话作用域）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        cancelling = "取消" in request.text
        if cancelling:
            if not await self.subscriptions.delete(messages.MH_PIC_SUBSCRIBE, origin):
                return PlainTextResponse(messages.MH_PIC_NOT_SUBSCRIBED)
            return PlainTextResponse(messages.MH_PIC_UNSUBSCRIBED)
        await self.subscriptions.add(
            messages.MH_PIC_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id or "",
        )
        return PlainTextResponse(messages.MH_PIC_SUBSCRIBED)

    async def toggle_mh_text(self, request: NoticeRequest):
        """订阅/取消订阅密函文本推送（admin，会话作用域）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        cancelling = "取消" in request.text
        if cancelling:
            if not await self.subscriptions.delete(messages.MH_TEXT_SUBSCRIBE, origin):
                return PlainTextResponse(messages.MH_TEXT_NOT_SUBSCRIBED)
            return PlainTextResponse(messages.MH_TEXT_UNSUBSCRIBED)
        await self.subscriptions.add(
            messages.MH_TEXT_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id or "",
        )
        return PlainTextResponse(messages.MH_TEXT_SUBSCRIBED)

    async def test_mh_push(self, request: NoticeRequest):
        """向当前会话发送一次密函测试推送（owner）。"""

        if self.push is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        await self.push(origin, "密函测试推送")
        return PlainTextResponse(messages.MH_TEST_SENT)

    async def subscribe_ann(self, request: NoticeRequest):
        """订阅公告推送（admin，仅群聊）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        if not request.actor.group_id:
            return PlainTextResponse(messages.ANN_GROUP_ONLY)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        subs = await self.subscriptions.get(
            messages.ANN_SUBSCRIBE,
            group_id=request.actor.group_id,
        )
        if any(sub.group_id == request.actor.group_id for sub in subs):
            return PlainTextResponse(messages.ANN_ALREADY_SUBSCRIBED)
        await self.subscriptions.add(
            messages.ANN_SUBSCRIBE,
            origin=origin,
            user_id=request.actor.user_id,
            bot_id=request.actor.bot_id,
            group_id=request.actor.group_id,
            user_type="group",
        )
        return PlainTextResponse(messages.ANN_SUBSCRIBED)

    async def unsubscribe_ann(self, request: NoticeRequest):
        """取消订阅公告推送（admin，仅群聊）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        if not request.actor.group_id:
            return PlainTextResponse(messages.ANN_GROUP_ONLY)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        if await self.subscriptions.delete(messages.ANN_SUBSCRIBE, origin):
            return PlainTextResponse(messages.ANN_UNSUBSCRIBED)
        return PlainTextResponse(messages.ANN_NOT_SUBSCRIBED)

    async def push_mh_now(self) -> int:
        """拉取当前密函并按订阅推送文本/图片；返回推送次数（计划任务）。"""

        if self.subscriptions is None or self.push is None:
            return 0
        snapshot = await self.transport.get_mh_any()
        if not snapshot.sections:
            return 0
        pushed = 0
        text_subs = await self.subscriptions.get(messages.MH_SUBSCRIBE)
        for sub in text_subs:
            names = [item for item in sub.extra_message.split(",") if item]
            if not names:
                continue
            lines = ["当前订阅密函已刷新:"]
            for key in names:
                type_name, _, mh_name = key.partition(":")
                lines.append(f"{type_name} : {mh_name or key}")
            await self.push(sub.unified_msg_origin, "\n".join(lines))
            pushed += 1
        pic_subs = await self.subscriptions.get(messages.MH_PIC_SUBSCRIBE)
        for sub in pic_subs:
            rendered = self.renderer.render_mh(snapshot)
            await self.push(sub.unified_msg_origin, rendered.path)
            pushed += 1
        return pushed

    async def poll_ann_now(self) -> int:
        """轮询公告并向群订阅者推送新公告；返回推送条数（计划任务）。"""

        if self.subscriptions is None or self.push is None or self.ann_state is None:
            return 0
        snapshot = await self.transport.get_ann_list()
        fresh_ids = [int(post.post_id) for post in snapshot.posts if post.post_id.isdigit()]
        pending = await self.ann_state.merge(fresh_ids)
        if not pending:
            return 0
        title_by_id = {post.post_id: post.title for post in snapshot.posts}
        pushed = 0
        subs = await self.subscriptions.get(messages.ANN_SUBSCRIBE)
        for sub in subs:
            lines = ["最新公告:"]
            lines.extend(f"#{idx} {title_by_id.get(str(post_id), post_id)}" for idx, post_id in enumerate(pending, start=1))
            await self.push(sub.unified_msg_origin, "\n".join(lines))
            pushed += 1
        return pushed


__all__ = ["NoticesService"]
