"""游戏/社区签到、日历和批量签到 use case。

服务层只消费 typed contracts 与框架无关请求/响应；真实写操作只通过注入的
``CheckinTransport`` 执行，测试用 fake transport 覆盖成功、取消、网络/状态码/
服务端错误和重复签到，不向用户暴露上游原文或凭据。
"""

from __future__ import annotations

import asyncio
import random
from collections.abc import Awaitable, Callable
from contextlib import nullcontext
from datetime import date, datetime
from zoneinfo import ZoneInfo

from ...entry.event import SCHEDULED_ACTOR_BOT_ID, EventActor
from ...entry.response import ImageResponse, PlainTextResponse
from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    SignRecordRepository,
)
from ...infrastructure.rendering import CheckinRenderer
from ...infrastructure.resources import ResourceSnapshotCoordinator
from ...infrastructure.subscriptions import SubscriptionStore
from ...infrastructure.utils.logger import logger
from ..privacy import PrivacyService
from . import messages
from .contracts import (
    CheckinCalendarData,
    CheckinCommandRequest,
    CheckinOutcome,
    CheckinSnapshot,
    CheckinSummary,
    CheckinTransport,
    CheckinTransportError,
    CommunityPost,
    SignStatus,
)

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")
GAME_SIGN_TARGET = 1
BBS_SIGN_TARGET = 1
ERROR_TIMES = 3


class CheckinService:
    """签到的隐私、账号、transport、持久化和渲染协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: CheckinTransport,
        privacy: PrivacyService,
        renderer: CheckinRenderer,
        *,
        community_tasks: tuple[str, ...] = ("bbs_sign", "bbs_detail", "bbs_like", "bbs_share", "bbs_reply"),
        concurrency: int = 1,
        interval_range: tuple[int, int] = (0, 0),
        subscriptions: SubscriptionStore | None = None,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.community_tasks = community_tasks
        self.concurrency = max(1, concurrency)
        self.interval_range = interval_range
        self.subscriptions = subscriptions
        self.resource_snapshots = resource_snapshots

    def _renderer_context(self):
        if self.resource_snapshots is None:
            return nullcontext(self.renderer)
        return self.resource_snapshots.bind_renderer(self.renderer, "encyclopedia_resources")

    @staticmethod
    def _transport_response(error: CheckinTransportError) -> PlainTextResponse:
        """记录安全错误类别并映射为稳定的用户文案。"""

        logger.warning(
            "签到请求失败 kind=%s resource=%s",
            error.kind.value,
            error.resource,
        )
        return PlainTextResponse(messages.transport_error(error.kind))

    async def _resolve_uid(
        self,
        request: CheckinCommandRequest,
    ) -> tuple[str, str] | PlainTextResponse:
        resolution = await self.privacy.resolve_query(request.actor, request.target_user_id)
        if resolution.blocked:
            return PlainTextResponse(messages.CHECKIN_PEEK_BLOCKED)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
            )
        if binding is None:
            return PlainTextResponse(messages.CHECKIN_UID_INVALID)
        return target_user_id, binding.uid

    async def _load_snapshot(self, uid: str) -> CheckinSnapshot:
        today = datetime.now(tz=SHANGHAI_TZ).date()
        async with self.database.session() as session:
            record = await SignRecordRepository.get(
                session,
                uid=uid,
                record_date=today,
            )
        if record is None:
            return CheckinSnapshot(uid=uid, record_date=today)
        return CheckinSnapshot(
            uid=uid,
            record_date=today,
            game_sign=record.game_sign,
            bbs_sign=record.bbs_sign,
            bbs_detail=record.bbs_detail,
            bbs_like=record.bbs_like,
            bbs_share=record.bbs_share,
            bbs_reply=record.bbs_reply,
        )

    async def _save_snapshot(self, snapshot: CheckinSnapshot) -> None:
        async with self.database.transaction() as session:
            await SignRecordRepository.save(
                session,
                uid=snapshot.uid,
                record_date=snapshot.record_date,
                game_sign=snapshot.game_sign,
                bbs_sign=snapshot.bbs_sign,
                bbs_detail=snapshot.bbs_detail,
                bbs_like=snapshot.bbs_like,
                bbs_share=snapshot.bbs_share,
                bbs_reply=snapshot.bbs_reply,
            )

    def _game_complete(self, snapshot: CheckinSnapshot) -> bool:
        return snapshot.game_sign >= GAME_SIGN_TARGET

    def _community_complete(self, snapshot: CheckinSnapshot) -> bool:
        for mark_name in self.community_tasks:
            count = getattr(snapshot, mark_name, 0)
            if count < messages.community_target(mark_name):
                return False
        return True

    async def _run_game(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
        snapshot: CheckinSnapshot,
    ) -> SignStatus:
        if self._game_complete(snapshot):
            return SignStatus.SKIP
        calendar = await self.transport.get_sign_calendar(
            actor,
            uid,
            credential_user_id=credential_user_id,
        )
        if calendar.today_signed:
            snapshot.game_sign = GAME_SIGN_TARGET
            return SignStatus.SKIP
        if (
            calendar.signin_time is None
            or not calendar.day_awards
            or calendar.signin_time >= len(calendar.day_awards)
        ):
            # 后端返回不完整日历或索引越界时不伪造成功。
            return SignStatus.FAILED
        award = calendar.day_awards[calendar.signin_time]
        status = await self.transport.game_sign(
            actor,
            uid,
            award,
            credential_user_id=credential_user_id,
        )
        if status is SignStatus.DONE:
            snapshot.game_sign = GAME_SIGN_TARGET
        return status

    async def _post_iteration(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
        *,
        count: int,
        target: int,
        posts: tuple[CommunityPost, ...],
        operation: Callable[..., Awaitable[bool]],
        error_message: str,
    ) -> tuple[int, str]:
        """按 legacy 语义遍历帖子完成浏览/点赞/回复；连续失败不静默吞掉。"""
        if count >= target:
            return count, ""
        posts = tuple(posts)
        shuffled = list(posts)
        random.shuffle(shuffled)
        error_times = 0
        for post in shuffled:
            ok = await operation(
                actor,
                uid,
                post,
                credential_user_id=credential_user_id,
            )
            if ok:
                count += 1
            else:
                error_times += 1
                if error_times >= ERROR_TIMES:
                    return count, error_message
            if count >= target:
                break
        return count, ""

    async def _run_community(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
        snapshot: CheckinSnapshot,
    ) -> tuple[SignStatus, tuple[str, ...], str]:
        """执行启用的社区任务，返回稳定状态、逐任务文案和可见错误。"""
        if self._community_complete(snapshot):
            return SignStatus.SKIP, (), ""
        task_process = await self.transport.get_task_process(
            actor,
            uid,
            credential_user_id=credential_user_id,
        )
        lines: list[str] = []
        error = ""
        posts: tuple[CommunityPost, ...] | None = None

        tasks = tuple(
            task for task in task_process.daily_tasks if task.mark_name in self.community_tasks
        )
        if not tasks:
            return SignStatus.FAILED, (), messages.CHECKIN_TASKS_EMPTY

        for task in tasks:
            mark_name = task.mark_name
            assert mark_name is not None
            label = messages.community_label(mark_name)
            target = messages.community_target(mark_name)
            count = getattr(snapshot, mark_name)
            if task.complete_times >= task.times:
                setattr(snapshot, mark_name, max(count, task.times))
                lines.append(f"{label}: {messages.sign_status(SignStatus.DONE)}")
                continue
            if count >= target:
                lines.append(f"{label}: {messages.sign_status(SignStatus.SKIP)}")
                continue

            if mark_name == "bbs_sign":
                status = await self.transport.bbs_sign(
                    actor,
                    uid,
                    credential_user_id=credential_user_id,
                )
                if status is SignStatus.DONE:
                    snapshot.bbs_sign = BBS_SIGN_TARGET
                lines.append(f"{label}: {messages.sign_status(status)}")
                continue

            if mark_name == "bbs_share":
                ok = await self.transport.do_share(
                    actor,
                    uid,
                    credential_user_id=credential_user_id,
                )
                if ok:
                    snapshot.bbs_share = target
                    lines.append(f"{label}: {messages.sign_status(SignStatus.DONE)}")
                else:
                    lines.append(f"{label}: {messages.sign_status(SignStatus.FAILED)}")
                continue

            # detail/like/reply 需要帖子列表
            if posts is None:
                posts = await self.transport.get_post_list(
                    actor,
                    uid,
                    credential_user_id=credential_user_id,
                )
            if not posts:
                error = messages.CHECKIN_POSTS_EMPTY
                lines.append(f"{label}: {messages.sign_status(SignStatus.FAILED)}")
                continue

            operation = {
                "bbs_detail": self.transport.get_post_detail,
                "bbs_like": self.transport.do_like,
                "bbs_reply": self.transport.do_reply,
            }[mark_name]
            error_message = {
                "bbs_detail": messages.CHECKIN_DETAIL_FAILED,
                "bbs_like": messages.CHECKIN_LIKE_FAILED,
                "bbs_reply": messages.CHECKIN_REPLY_FAILED,
            }[mark_name]
            new_count, op_error = await self._post_iteration(
                actor,
                uid,
                credential_user_id,
                count=count,
                target=target,
                posts=posts,
                operation=operation,
                error_message=error_message,
            )
            setattr(snapshot, mark_name, new_count)
            if op_error:
                error = op_error
                lines.append(f"{label}: {messages.sign_status(SignStatus.FAILED)}")
            elif new_count >= target:
                lines.append(f"{label}: {messages.sign_status(SignStatus.DONE)}")
            else:
                lines.append(f"{label}: {messages.sign_status(SignStatus.FAILED)}")

        completed = self._community_complete(snapshot)
        if error:
            return SignStatus.FAILED, tuple(lines), error
        if completed:
            return SignStatus.DONE, tuple(lines), ""
        return SignStatus.FAILED, tuple(lines), ""

    async def _sign_one(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
    ) -> CheckinOutcome:
        snapshot = await self._load_snapshot(uid)
        if self._game_complete(snapshot) and self._community_complete(snapshot):
            return CheckinOutcome(
                SignStatus.SKIP,
                SignStatus.SKIP,
                (messages.CHECKIN_ALREADY,),
                "",
            )

        game_status = await self._run_game(actor, uid, credential_user_id, snapshot)
        bbs_status, community_lines, error = await self._run_community(
            actor,
            uid,
            credential_user_id,
            snapshot,
        )
        await self._save_snapshot(snapshot)

        lines: list[str] = []
        lines.append(f"签到状态: {messages.sign_status(game_status)}")
        lines.append("社区任务:")
        lines.extend(community_lines)
        if error:
            lines.append(f"错误信息: {error}")
        lines.append("-----------------------------")
        return CheckinOutcome(
            game_status=game_status,
            bbs_status=bbs_status,
            detail_lines=tuple(lines),
            error=error,
        )

    async def manual_sign(self, request: CheckinCommandRequest):
        """为当前用户或被允许查询用户执行一次签到。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            outcome = await self._sign_one(request.actor, uid, target_user_id)
        except CheckinTransportError as error:
            return self._transport_response(error)
        return PlainTextResponse("\n".join(outcome.detail_lines))

    async def sign_calendar(self, request: CheckinCommandRequest):
        """读取并渲染当前用户或被允许查询用户的签到日历。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            calendar = await self.transport.get_sign_calendar(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
            tasks = await self.transport.get_task_process(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
            total_days = await self.transport.have_sign_in(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
            role = await self.transport.get_role_overview(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except CheckinTransportError as error:
            return self._transport_response(error)
        data = CheckinCalendarData(
            calendar=calendar,
            tasks=tasks,
            total_sign_in_days=total_days,
            role_overview=role,
            snapshot=await self._load_snapshot(uid),
        )
        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            group_id=request.actor.group_id,
        )
        with self._renderer_context() as renderer:
            rendered = await renderer.render_calendar(
                data,
                actor=request.actor,
                target_user_id=target_user_id,
                uid_hidden=uid_hidden,
            )
        return ImageResponse(str(rendered.path), temporary=True)

    async def _run_all_signs(
        self,
        *,
        respect_auto_sign: bool = False,
        enable_all_users: bool = False,
    ) -> CheckinSummary:
        """为目标绑定执行签到并按并发/间隔聚合结果。

        手动“全部签到”显式忽略开关；计划任务默认尊重每个用户 UID 的设置，
        ``enable_all_users`` 是配置要求的管理员强制模式。
        """

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list_all(session)
        if respect_auto_sign and not enable_all_users:
            bindings = [binding for binding in bindings if binding.auto_sign_enabled]
        if not bindings:
            return CheckinSummary()

        success = 0
        failed = 0
        game_success = 0
        bbs_success = 0
        semaphore = asyncio.Semaphore(self.concurrency)

        async def process(binding) -> CheckinOutcome:
            async with semaphore:
                return await self._sign_one(
                    # 计划任务没有入站事件；此 sentinel 仅供 legacy DNAUser
                    # 构造和请求上下文使用，绝不写入全局身份表。
                    EventActor(
                        binding.user_id,
                        SCHEDULED_ACTOR_BOT_ID,
                        binding.group_id,
                    ),
                    binding.uid,
                    binding.user_id,
                )

        tasks = [process(binding) for binding in bindings]
        for i in range(0, len(tasks), self.concurrency):
            batch = tasks[i : i + self.concurrency]
            results = await asyncio.gather(*batch, return_exceptions=True)
            for result in results:
                if not isinstance(result, CheckinOutcome):
                    failed += 1
                    continue
                if result.success:
                    success += 1
                else:
                    failed += 1
                if result.game_status in (SignStatus.DONE, SignStatus.SKIP):
                    game_success += 1
                if result.bbs_status in (SignStatus.DONE, SignStatus.SKIP):
                    bbs_success += 1
            if self.interval_range[1] > 0:
                await asyncio.sleep(random.uniform(*self.interval_range))

        return CheckinSummary(
            success=success,
            failed=failed,
            game_success=game_success,
            bbs_success=bbs_success,
        )

    async def sign_all(self, request: CheckinCommandRequest):
        """为所有已绑定账号执行签到并按并发/间隔聚合结果。"""

        summary = await self._run_all_signs()
        if summary.success == 0 and summary.failed == 0:
            return PlainTextResponse(messages.CHECKIN_NO_USERS)
        lines = [
            messages.CHECKIN_ALL_STARTED,
            messages.CHECKIN_ALL_DONE,
            f"今日成功签到 {summary.success} 个账号，失败 {summary.failed} 个账号",
        ]
        return PlainTextResponse("\n".join(lines))

    async def auto_sign_all(self, *, enable_all_users: bool = False) -> str:
        """供计划任务调用的全账号自动签到，返回可推送摘要。"""

        summary = await self._run_all_signs(
            respect_auto_sign=True,
            enable_all_users=enable_all_users,
        )
        if summary.success == 0 and summary.failed == 0:
            return f"[二重螺旋]自动任务\n{messages.CHECKIN_NO_USERS}"
        return (
            f"[二重螺旋]自动任务\n"
            f"今日成功游戏签到 {summary.game_success} 个账号\n"
            f"今日社区签到 {summary.bbs_success} 个账号"
        )

    async def set_auto_sign(
        self,
        request: CheckinCommandRequest,
        *,
        enabled: bool,
    ) -> PlainTextResponse:
        """按当前用户当前 UID 保存自动签到开关。"""

        if request.target_user_id not in (None, request.actor.user_id):
            return PlainTextResponse(messages.CHECKIN_UID_INVALID)
        async with self.database.transaction() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=request.actor.user_id,
            )
            if binding is None:
                return PlainTextResponse(messages.CHECKIN_UID_INVALID)
            changed = await AccountBindingRepository.set_auto_sign_enabled(
                session,
                user_id=request.actor.user_id,
                uid=binding.uid,
                enabled=enabled,
            )
        if not changed:
            return PlainTextResponse(messages.CHECKIN_UID_INVALID)
        return PlainTextResponse(
            messages.CHECKIN_AUTO_ENABLED if enabled else messages.CHECKIN_AUTO_DISABLED,
        )

    async def subscribe_sign_result(self, request: CheckinCommandRequest):
        """订阅/取消订阅签到结果推送（admin）。"""

        if self.subscriptions is None:
            return PlainTextResponse(messages.CHECKIN_SERVICE_UNAVAILABLE)
        origin = request.actor.unified_msg_origin if request.actor is not None else None
        if not origin:
            return PlainTextResponse(messages.SIGN_RESULT_ORIGIN_MISSING)
        try:
            if "取消" in request.text:
                await self.subscriptions.delete(messages.SIGN_RESULT_SUBSCRIBE, origin)
                return PlainTextResponse(messages.SIGN_RESULT_UNSUBSCRIBED)
            await self.subscriptions.add(
                messages.SIGN_RESULT_SUBSCRIBE,
                origin=origin,
                user_id=request.actor.user_id,
                group_id=request.actor.group_id or "",
                bot_id=request.actor.bot_id,
                user_type="group" if request.actor.group_id else "direct",
            )
        except RuntimeError:
            # 订阅文件损坏时转为用户可见错误，不让 handler 崩溃。
            return PlainTextResponse(messages.SIGN_RESULT_STORE_UNAVAILABLE)
        return PlainTextResponse(messages.SIGN_RESULT_SUBSCRIBED)

    async def clear_sign_records_before(self, record_date: date) -> int:
        """清理指定日期之前的签到记录，返回删除条数。"""

        async with self.database.transaction() as session:
            return await SignRecordRepository.delete_before(session, record_date)


__all__ = ["CheckinService"]
