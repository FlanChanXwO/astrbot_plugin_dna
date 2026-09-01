"""密函、公告列表/详情读取与通知订阅/推送 use case。"""

from __future__ import annotations

import inspect
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from ...entry.event import EventActor
from ...entry.response import ImageResponse, MultiImageResponse, PlainTextResponse
from ...infrastructure.cache import CacheManager
from ...infrastructure.http.concurrency import RequestConcurrencyGate
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import NoticesRenderer, RenderedNoticesImage
from ...infrastructure.rendering.errors import HtmlRenderError
from ...infrastructure.resources import ResourceSnapshotCoordinator
from ...infrastructure.subscriptions import SubscriptionStore
from ...infrastructure.utils.logger import logger
from ..privacy import PrivacyService
from . import messages
from .ann_delivery_state import AnnDeliveryStateStore
from .ann_state import AnnStateStore
from .contracts import (
    MhSnapshot,
    NoticeRequest,
    NoticesTransport,
    NoticesTransportError,
    validate_mh_snapshot,
)
from .mh_cache import (
    SHANGHAI,
    MhSnapshotCache,
    MhSnapshotEnvelope,
    snapshot_fingerprint,
)

NoticePayload = str | Path | tuple[Path, ...]
PushCallable = Callable[[str, NoticePayload], Awaitable[Any]]
ClockCallable = Callable[[], datetime]
_MH_TYPE_KEYS = ("角色", "武器", "魔之楔")


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
        ann_delivery_state: AnnDeliveryStateStore | None = None,
        *,
        secret_simple_image: bool = False,
        config_store: dict[str, Any] | None = None,
        sync_ann_group_cb: Callable[[str, bool], None] | None = None,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
        cache_manager: CacheManager | None = None,
        clock: ClockCallable | None = None,
        request_gate: RequestConcurrencyGate | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.subscriptions = subscriptions
        self.ann_state = ann_state
        self.ann_delivery_state = ann_delivery_state or (
            AnnDeliveryStateStore(ann_state.path.parent / "ann_delivery_state.json")
            if ann_state is not None
            else None
        )
        self.push = push
        self.secret_simple_image = secret_simple_image
        self.config_store = config_store
        self._sync_ann_group_cb = sync_ann_group_cb
        self.resource_snapshots = resource_snapshots
        self.mh_cache = (
            MhSnapshotCache(cache_manager) if cache_manager is not None else None
        )
        self._clock = clock
        self.request_gate = request_gate

    def _now(self) -> datetime:
        if self._clock is not None:
            value = self._clock()
        else:
            from ...utils import get_datetime

            value = get_datetime()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("密函时钟必须带时区")
        return value.astimezone(SHANGHAI)

    @staticmethod
    def _mh_gate_open(now: datetime) -> bool:
        window_start = MhSnapshotCache.window_start(now)
        return now >= window_start + timedelta(minutes=30)

    async def _verified_mh_snapshot(
        self,
        now: datetime,
        fetch: Callable[[], Awaitable[Any]],
    ) -> MhSnapshot:
        """读取或写入当前小时的已验证密函快照。"""

        window_start = MhSnapshotCache.window_start(now)
        if self.mh_cache is not None:
            cached = await self.mh_cache.get(window_start, now=now)
            if cached is not None:
                return cached.snapshot
        snapshot = validate_mh_snapshot(await fetch())
        if self.mh_cache is not None:
            envelope = MhSnapshotEnvelope(
                snapshot=snapshot,
                window_start=window_start,
                fetched_at=now,
                fingerprint=snapshot_fingerprint(snapshot),
            )
            await self.mh_cache.put(envelope)
        return snapshot

    def _renderer_context(self):
        if self.resource_snapshots is None:
            return nullcontext(self.renderer)
        return self.resource_snapshots.bind_renderer(
            self.renderer, "encyclopedia_resources"
        )

    async def _resolve_uid(
        self,
        request: NoticeRequest,
    ) -> tuple[str, str] | PlainTextResponse:
        resolution = await self.privacy.resolve_query(
            request.actor, request.target_user_id
        )
        if resolution.blocked:
            return PlainTextResponse(messages.NOTICES_PEEK_BLOCKED, need_at=True)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
            )
        if binding is None:
            return PlainTextResponse(messages.NOTICES_UID_INVALID, need_at=True)
        return target_user_id, binding.uid

    @staticmethod
    def _image_response(
        rendered: RenderedNoticesImage
        | list[RenderedNoticesImage]
        | tuple[RenderedNoticesImage, ...],
    ) -> ImageResponse | MultiImageResponse:
        """把单页或多页渲染结果转换为统一的临时图片响应。"""

        if isinstance(rendered, (list, tuple)):
            images = tuple(
                ImageResponse(
                    str(page.path),
                    temporary=True,
                    sidecar=getattr(page, "sidecar", None),
                    manifest=getattr(page, "manifest", None),
                )
                for page in rendered
            )
            return MultiImageResponse(images)
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            sidecar=getattr(rendered, "sidecar", None),
            manifest=getattr(rendered, "manifest", None),
        )

    async def mh(self, request: NoticeRequest):
        """读取并渲染当前小时段的密函数据。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            now = self._now()

            async def fetch() -> Any:
                return await self.transport.get_mh(
                    request.actor,
                    uid,
                    credential_user_id=target_user_id,
                )

            if self._mh_gate_open(now):
                snapshot = await self._verified_mh_snapshot(now, fetch)
            else:
                snapshot = validate_mh_snapshot(await fetch())
        except NoticesTransportError as error:
            logger.warning(
                "通知请求失败 operation=%s kind=%s resource=%s",
                "mh",
                error.kind.value,
                error.resource,
            )
            return PlainTextResponse(messages.MH_NOT_FOUND, need_at=True)
        except ValueError:
            logger.warning("通知数据解析失败 operation=%s", "mh")
            return PlainTextResponse(messages.MH_NOT_FOUND, need_at=True)
        with self._renderer_context() as renderer:
            rendered = await renderer.render_mh(
                snapshot,
                simple_image=self.secret_simple_image,
            )
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            sidecar=getattr(rendered, "sidecar", None),
            manifest=getattr(rendered, "manifest", None),
        )

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
            logger.warning(
                "通知请求失败 operation=%s kind=%s resource=%s",
                "ann_list",
                error.kind.value,
                error.resource,
            )
            return PlainTextResponse(messages.ANN_LIST_FAILED, need_at=True)
        if not snapshot.posts:
            return PlainTextResponse(messages.ANN_LIST_FAILED, need_at=True)

        if not index:
            try:
                with self._renderer_context() as renderer:
                    rendered = await renderer.render_ann_list(snapshot)
            except (HtmlRenderError, OSError, httpx.HTTPError, ValueError):
                return PlainTextResponse(messages.ANN_LIST_FAILED, need_at=True)
            return self._image_response(rendered)

        from .ann_utils import build_index_map, resolve_index

        post_map = build_index_map({"postId": post.post_id} for post in snapshot.posts)
        post_id = resolve_index(index, post_map)
        if post_id is None:
            return PlainTextResponse(messages.ANN_INDEX_INVALID, need_at=True)
        try:
            detail = await self.transport.get_ann_detail(post_id)
        except NoticesTransportError as error:
            logger.warning(
                "通知请求失败 operation=%s kind=%s resource=%s",
                "ann_detail",
                error.kind.value,
                error.resource,
            )
            return PlainTextResponse(messages.ANN_DETAIL_FAILED, need_at=True)
        try:
            with self._renderer_context() as renderer:
                rendered = await renderer.render_ann_detail(detail)
        except (HtmlRenderError, OSError, httpx.HTTPError, ValueError):
            return PlainTextResponse(messages.ANN_DETAIL_FAILED, need_at=True)
        return self._image_response(rendered)

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
            return PlainTextResponse(
                messages.mh_all_forbidden(request.matched_prefix), need_at=True
            )
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
                    if sub.unified_msg_origin == origin
                    and sub.uid == request.actor.user_id
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
                return PlainTextResponse(
                    messages.MH_SUBSCRIBED_TEMPLATE.format(names=",".join(keys)),
                    need_at=True,
                )
            existing = [item for item in target.extra_message.split(",") if item]
            if set(keys) <= set(existing):
                return PlainTextResponse(
                    messages.MH_DUPLICATE.format(name=mh_name), need_at=True
                )
            merged = sorted(set(existing) | set(keys))
            await self.subscriptions.update(
                messages.MH_SUBSCRIBE,
                origin,
                uid=request.actor.user_id,
                extra_message=",".join(merged),
            )
            return PlainTextResponse(
                f"{messages.MH_SUBSCRIBED_TEMPLATE.format(names=mh_name)}!当前订阅密函: {','.join(merged)}",
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
                    if sub.unified_msg_origin == origin
                    and sub.uid == request.actor.user_id
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
            remaining = [
                item
                for item in target.extra_message.split(",")
                if item and item not in keys
            ]
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
            lines.append(
                f"可以使用命令设置推送时间: {messages.COMMAND_PREFIX}订阅密函时间17:23"
            )
        return PlainTextResponse("\n".join(lines), need_at=True)

    async def set_mh_push_time(self, request: NoticeRequest):
        """设置密函推送时间窗口（user）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE, need_at=True)
        try:
            start = int(str(request.parameters.get("start", "")).strip())
            end = int(str(request.parameters.get("end", "")).strip())
        except ValueError:
            return PlainTextResponse(
                messages.mh_push_time_format(request.matched_prefix), need_at=True
            )
        if start < 0 or start > 23 or end < 0 or end > 23:
            return PlainTextResponse(
                messages.mh_push_time_format(request.matched_prefix), need_at=True
            )
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
        payload: NoticePayload,
        at_user_id: str | None = None,
    ) -> bool:
        if self.push is not None:
            try:
                sig = inspect.signature(self.push)
                if (
                    len(sig.parameters) >= 3
                    or "at_user_id" in sig.parameters
                    or any(
                        p.kind == inspect.Parameter.VAR_KEYWORD
                        for p in sig.parameters.values()
                    )
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
                    res = await res
                return res is not False
            except Exception:  # noqa: BLE001
                logger.warning("通知推送失败")
                return False
        return False

    @staticmethod
    def _mh_subscription_in_window(subscription: Any, current_hour: int) -> bool:
        """按订阅自身的普通或跨午夜小时窗口判断是否投递。"""

        extra_data = getattr(subscription, "extra_data", "")
        if not extra_data or ":" not in extra_data:
            return True
        try:
            start_text, end_text = extra_data.split(":", 1)
            start_hour, end_hour = int(start_text), int(end_text)
        except (TypeError, ValueError):
            return True
        if start_hour <= end_hour:
            return start_hour <= current_hour <= end_hour
        return current_hour >= start_hour or current_hour <= end_hour

    async def test_mh_push(self, request: NoticeRequest):
        """向当前会话发送一次密函测试推送（admin）。"""

        if self.push is None:
            return PlainTextResponse(messages.NOTICES_SERVICE_UNAVAILABLE)
        origin, error = await self._origin(request.actor)
        if error:
            return PlainTextResponse(error)
        if await self._invoke_push(origin, "密函测试推送"):
            return PlainTextResponse(messages.MH_TEST_SENT)
        return PlainTextResponse(messages.MH_TEST_FAILED)

    def _sync_ann_group(self, group_id: str | None, subscribed: bool) -> None:
        """保留旧调用点，但公告目标不再写入插件配置。

        ``subscriptions.json`` 才能完整保存平台、Bot 与会话 origin；旧配置仅供
        人工参考，不能由命令或启动流程改写、恢复。
        """

        return

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
        self._sync_ann_group(request.actor.group_id, True)
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
            self._sync_ann_group(request.actor.group_id, False)
            return PlainTextResponse(messages.ANN_UNSUBSCRIBED, need_at=True)
        return PlainTextResponse(messages.ANN_NOT_SUBSCRIBED, need_at=True)

    async def push_mh_now(self) -> int:
        """拉取当前密函并按订阅推送文本/图片；返回推送次数（计划任务）。"""

        if self.subscriptions is None or self.push is None:
            return 0
        now = self._now()
        if not self._mh_gate_open(now):
            logger.info("密函推送：当前小时尚未到 HH:30，跳过密函推送")
            return 0
        try:
            snapshot = await self._verified_mh_snapshot(
                now,
                self.transport.get_mh_any,
            )
        except NoticesTransportError as error:
            logger.warning(
                "通知请求失败 operation=%s kind=%s resource=%s",
                "push_mh",
                error.kind.value,
                error.resource,
            )
            return 0
        except ValueError:
            logger.warning("通知数据解析失败 operation=%s", "push_mh")
            return 0
        current_hour = now.hour

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
        subs_by_origin: dict[str, list[Any]] = {}
        for sub in text_subs:
            if not self._mh_subscription_in_window(sub, current_hour):
                continue
            subs_by_origin.setdefault(sub.unified_msg_origin, []).append(sub)

        for origin, group_subs in subs_by_origin.items():
            matched_keys_ordered: list[str] = []
            seen_keys: set[str] = set()
            at_users: list[str] = []
            seen_users: set[str] = set()

            for sub in group_subs:
                names = [item for item in sub.extra_message.split(",") if item]
                if not names:
                    continue
                matched = [key for key in names if key in available_names]
                if not matched:
                    continue

                for key in matched:
                    if key not in seen_keys:
                        seen_keys.add(key)
                        matched_keys_ordered.append(key)

                if sub.user_type == "group" or sub.group_id:
                    uid = str(sub.uid or sub.user_id)
                    if uid and uid not in seen_users:
                        seen_users.add(uid)
                        at_users.append(uid)

            if not matched_keys_ordered:
                continue

            lines = ["当前订阅密函已刷新:"]
            for key in matched_keys_ordered:
                type_name, _, mh_name = key.partition(":")
                lines.append(f"{type_name} : {mh_name or key}")

            at_target: str | list[str] | None = None
            if at_users:
                at_target = at_users if len(at_users) > 1 else at_users[0]

            if await self._invoke_push(origin, "\n".join(lines), at_user_id=at_target):
                pushed += 1

        # 2. 全量文本密函订阅 (MH_TEXT_SUBSCRIBE)
        all_text_subs = [
            sub
            for sub in await self.subscriptions.get(messages.MH_TEXT_SUBSCRIBE)
            if self._mh_subscription_in_window(sub, current_hour)
        ]
        if all_text_subs:
            text_lines = ["【密函已刷新】"]
            for type_name in ("角色", "武器", "魔之楔"):
                if by_type.get(type_name):
                    text_lines.append(f"\n-- {type_name} --")
                    text_lines.extend(
                        f"{i}. {name}"
                        for i, name in enumerate(by_type[type_name], start=1)
                    )
            full_text = "\n".join(text_lines)
            for sub in all_text_subs:
                if await self._invoke_push(
                    sub.unified_msg_origin, full_text, at_user_id=None
                ):
                    pushed += 1

        # 3. 图片密函订阅 (MH_PIC_SUBSCRIBE)
        pic_subs = [
            sub
            for sub in await self.subscriptions.get(messages.MH_PIC_SUBSCRIBE)
            if self._mh_subscription_in_window(sub, current_hour)
        ]
        if pic_subs:
            try:
                with self._renderer_context() as renderer:
                    rendered = await renderer.render_mh(
                        snapshot,
                        simple_image=self.secret_simple_image,
                    )
            except (HtmlRenderError, OSError, httpx.HTTPError, ValueError) as error:
                logger.warning(
                    "密函图片渲染失败 error_type=%s",
                    type(error).__name__,
                )
            else:
                for sub in pic_subs:
                    if await self._invoke_push(
                        sub.unified_msg_origin,
                        rendered.path,
                        at_user_id=None,
                    ):
                        pushed += 1

        return pushed

    async def poll_ann_now(self) -> int:
        """轮询公告并向群订阅者推送新公告图片；同一波次只执行一次。"""

        async def poll() -> int:
            return await self._poll_ann_now_once()

        if self.request_gate is None:
            return await poll()
        return await self.request_gate.run(poll, key=("ann-poll",))

    async def _poll_ann_now_once(self) -> int:
        """执行一轮公告轮询；由 ``poll_ann_now`` 负责 single-flight。"""

        if (
            self.subscriptions is None
            or self.push is None
            or self.ann_state is None
            or self.ann_delivery_state is None
        ):
            return 0
        try:
            snapshot = await self.transport.get_ann_list()
        except NoticesTransportError as error:
            logger.warning(
                "通知请求失败 operation=%s kind=%s resource=%s",
                "poll_ann_list",
                error.kind.value,
                error.resource,
            )
            return 0

        subs = await self.subscriptions.get(messages.ANN_SUBSCRIBE)
        observed_targets = tuple(
            dict.fromkeys(sub.unified_msg_origin for sub in subs if sub.enabled)
        )
        await self.ann_delivery_state.migrate_legacy_ids(
            await self.ann_state.known_ids(),
        )

        pushed = 0
        current_targets = set(observed_targets)
        for post in snapshot.posts:
            if not post.post_id.isdigit():
                continue
            pending_all = await self.ann_delivery_state.pending_targets(
                post.post_id,
                observed_targets,
            )
            pending = tuple(
                target for target in pending_all if target in current_targets
            )
            if not pending:
                # 旧版本只有公告 ID 去重；无当前待投递目标时同步兼容状态，
                # 让回滚不会把已完成或无人订阅的公告重新当成新公告。
                await self.ann_state.merge([int(post.post_id)])
                continue

            try:
                detail = await self.transport.get_ann_detail(post.post_id)
                with self._renderer_context() as renderer:
                    rendered = await renderer.render_ann_detail(detail)
                if isinstance(rendered, (list, tuple)):
                    if not rendered:
                        raise ValueError("公告详情渲染没有生成图片")
                    payload: NoticePayload = tuple(page.path for page in rendered)
                else:
                    payload = rendered.path
            except Exception as error:  # noqa: BLE001
                logger.warning(
                    "公告详情或渲染失败 post_id=%s error_type=%s",
                    post.post_id,
                    type(error).__name__,
                )
                continue

            all_delivered = True
            for target in pending:
                if await self._invoke_push(target, payload):
                    await self.ann_delivery_state.mark_delivered(post.post_id, target)
                    pushed += 1
                else:
                    all_delivered = False
            if all_delivered:
                # 只有当前观察到的目标全部成功后才更新旧 ID 列表；部分成功仍需
                # 保留旧文件的未完成语义，避免回滚版本过早跳过失败公告。
                await self.ann_state.merge([int(post.post_id)])

        return pushed


__all__ = ["NoticesService"]
