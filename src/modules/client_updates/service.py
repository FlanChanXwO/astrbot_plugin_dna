"""客户端更新查询、订阅与版本变化检测领域逻辑。

本模块只编排已归一化的版本快照、补丁大小、状态 store 和订阅 store，不接触
AstrBot event、HTTP 请求或消息投递。手动查询保持只读；订阅首次执行时只为
尚未建立基线的平台尝试建立基线。
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone

from ...entry.response import PlainTextResponse
from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from ...infrastructure.utils.logger import logger
from . import messages
from .channels import (
    CLIENT_UPDATE_CHANNELS,
    ClientUpdateChannel,
    default_channel_id_for_platform,
    normalize_client_update_channel_ids,
    resolve_client_update_channel,
    select_enabled_channels,
)
from .contracts import (
    ClientPlatform,
    ClientRegion,
    ClientUpdateChange,
    ClientUpdateObservation,
    ClientUpdateRequest,
    ClientUpdateStructureError,
    ClientUpdateTransport,
    ClientUpdateTransportError,
    ClientVersionSnapshot,
)
from .routing import pending_targets_for_change
from .state import ClientUpdateBaseline, ClientUpdateStateStore


class ClientUpdateRollbackError(ValueError):
    """当前快照低于最近成功基线时抛出的服务端状态异常。"""

    def __init__(self, previous_patch_version: int, current_patch_version: int) -> None:
        self.previous_patch_version = previous_patch_version
        self.current_patch_version = current_patch_version
        super().__init__("client update version moved backwards")


class ClientUpdatePatchSizeError(ValueError):
    """变化区间缺少补丁大小或补丁大小结构非法。"""


class ClientUpdateService:
    """保存成功观察、查询当前版本并管理群级客户端更新订阅。"""

    def __init__(
        self,
        state: ClientUpdateStateStore,
        *,
        transport: ClientUpdateTransport | None = None,
        subscriptions: SubscriptionStore | None = None,
        channels: Sequence[str] | None = None,
    ) -> None:
        self.state = state
        self.transport = transport
        self.subscriptions = subscriptions
        self._channel_mode = channels is not None
        self.channels = (
            tuple(CLIENT_UPDATE_CHANNELS)
            if channels is None
            else normalize_client_update_channel_ids(channels)
        )
        # 未传 channels 时保留旧 platform transport seam；bootstrap 传入配置后
        # 才切换到固定 channel ID，避免破坏已有自定义 transport。
        self._poll_targets: tuple[ClientPlatform | str, ...] = (
            (ClientPlatform.PC, ClientPlatform.ANDROID)
            if channels is None
            else self.channels
        )

    def _targets_for_platforms(
        self,
        platforms: tuple[ClientPlatform, ...],
    ) -> tuple[ClientPlatform | str, ...]:
        if not self._channel_mode:
            return platforms
        return tuple(
            channel_id
            for platform in platforms
            for channel_id in select_enabled_channels(
                self.channels,
                platform=platform,
            )
        )

    async def observe(
        self,
        current: ClientVersionSnapshot,
        *,
        observed_at: datetime,
        patch_sizes: Mapping[int, int],
    ) -> ClientUpdateChange | None:
        """观察一个平台快照并返回新变化；首次或未变化观察返回 ``None``。

        ``patch_sizes`` 使用补丁版本号到字节数的映射。只有
        ``previous.patch_version < patch_version <= current.patch_version`` 的
        补丁参与汇总；变化确认成功后才会写入新的基线。
        """

        return await self._observe(
            current,
            observed_at=observed_at,
            patch_sizes=patch_sizes,
            stage_pending=False,
        )

    async def _observe(
        self,
        current: ClientVersionSnapshot,
        *,
        observed_at: datetime,
        patch_sizes: Mapping[int, int],
        stage_pending: bool,
    ) -> ClientUpdateChange | None:
        """执行观察；定时轮询可要求基线和 pending 事件一次落盘。"""

        if not isinstance(current, ClientVersionSnapshot):
            raise TypeError("current 必须是 ClientVersionSnapshot")

        baseline = await self.state.get_baseline(
            current.region,
            current.channel_id or current.platform,
        )
        if baseline is None:
            await self.state.save_baseline(
                ClientUpdateBaseline(snapshot=current, observed_at=observed_at)
            )
            return None

        previous = baseline.snapshot
        if current.patch_version < previous.patch_version:
            raise ClientUpdateRollbackError(
                previous.patch_version,
                current.patch_version,
            )

        if current.patch_version == previous.patch_version:
            await self.state.save_baseline(
                ClientUpdateBaseline(
                    snapshot=current,
                    observed_at=observed_at,
                    last_change=baseline.last_change,
                )
            )
            return None

        change = _change_from_baseline(
            baseline,
            current,
            patch_sizes,
        )
        new_baseline = ClientUpdateBaseline(
            snapshot=current,
            observed_at=observed_at,
            last_change=change,
        )
        if not stage_pending:
            await self.state.save_baseline(new_baseline)
            return change

        subscriptions = self.subscriptions
        targets = (
            pending_targets_for_change(
                change,
                await subscriptions.get(messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE),
            )
            if subscriptions is not None
            else ()
        )
        await self.state.save_baseline_with_pending_event(
            new_baseline,
            change,
            targets,
        )
        return change

    async def poll_now(self) -> tuple[ClientUpdateChange, ...]:
        """轮询已启用渠道并维护成功观察基线，返回本轮确认的变化。"""

        if self.transport is None:
            raise RuntimeError("client update transport unavailable")

        changes: list[ClientUpdateChange] = []
        for target in self._poll_targets:
            baseline = await self.state.get_baseline(
                _target_region(target),
                target,
            )
            try:
                observation = await self.transport.get_observation(
                    target,
                    previous_patch_version=(
                        baseline.snapshot.patch_version
                        if baseline is not None
                        else None
                    ),
                )
                _validate_observation(observation, target)
                change = await self._observe(
                    observation.snapshot,
                    observed_at=datetime.now(timezone.utc),
                    patch_sizes=observation.patch_sizes,
                    stage_pending=True,
                )
            except ClientUpdateTransportError as error:
                _log_transport_failure("poll", target, error)
                continue
            except (
                ClientUpdatePatchSizeError,
                ClientUpdateRollbackError,
                ClientUpdateStructureError,
            ) as error:
                _log_query_failure(target, type(error).__name__)
                continue
            if change is not None:
                changes.append(change)
        return tuple(changes)

    async def query(self, request: ClientUpdateRequest) -> PlainTextResponse:
        """查询所选平台的当前版本；不会推进或覆盖定时观察基线。"""

        if request.actor is None:
            return PlainTextResponse(messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE)
        if self.transport is None:
            return PlainTextResponse(messages.CLIENT_UPDATE_SERVICE_UNAVAILABLE)

        result: list[str] = []
        for target in self._targets_for_platforms(request.platforms):
            baseline = await self.state.get_baseline(
                _target_region(target),
                target,
            )
            try:
                observation = await self.transport.get_observation(
                    target,
                    previous_patch_version=(
                        baseline.snapshot.patch_version
                        if baseline is not None
                        else None
                    ),
                )
                _validate_observation(observation, target)
                if baseline is None:
                    result.append(messages.format_current(observation.snapshot))
                    continue
                if (
                    observation.snapshot.patch_version
                    == baseline.snapshot.patch_version
                ):
                    result.append(messages.format_no_change(observation.snapshot))
                    continue
                change = _change_from_baseline(
                    baseline,
                    observation.snapshot,
                    observation.patch_sizes,
                )
            except ClientUpdateTransportError as error:
                _log_transport_failure("query", target, error)
                continue
            except (
                ClientUpdatePatchSizeError,
                ClientUpdateRollbackError,
                ClientUpdateStructureError,
            ) as error:
                _log_query_failure(target, type(error).__name__)
                continue
            result.append(messages.format_change(change))

        if not result:
            return PlainTextResponse(messages.CLIENT_UPDATE_UNAVAILABLE)
        return PlainTextResponse("\n\n".join(result))

    async def subscribe(self, request: ClientUpdateRequest) -> PlainTextResponse:
        """创建或更新当前群的客户端更新订阅，并尝试建立缺失基线。"""

        actor = request.actor
        if actor is None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE,
                need_at=True,
            )
        if not actor.group_id:
            return PlainTextResponse(messages.CLIENT_UPDATE_GROUP_ONLY, need_at=True)
        if not actor.unified_msg_origin:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE,
                need_at=True,
            )
        if self.subscriptions is None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_SERVICE_UNAVAILABLE,
                need_at=True,
            )

        existing = await self._subscription_for_origin(actor.unified_msg_origin)
        await self.subscriptions.add(
            messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
            origin=actor.unified_msg_origin,
            user_id=actor.user_id,
            group_id=actor.group_id,
            bot_id=actor.bot_id,
            user_type="group",
            uid="",
            extra_data=_serialize_platforms(request.platforms),
            provenance="chat_command",
        )

        failed_platforms = await self._initialize_missing_baselines(request.platforms)
        if existing is not None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_ALREADY_SUBSCRIBED,
                need_at=True,
            )
        if failed_platforms:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_SUBSCRIBED_RETRY,
                need_at=True,
            )
        return PlainTextResponse(messages.CLIENT_UPDATE_SUBSCRIBED, need_at=True)

    async def unsubscribe(self, request: ClientUpdateRequest) -> PlainTextResponse:
        """取消当前群的客户端更新订阅。"""

        actor = request.actor
        if actor is None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE,
                need_at=True,
            )
        if not actor.group_id:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_GROUP_UNSUB_ONLY,
                need_at=True,
            )
        if not actor.unified_msg_origin:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE,
                need_at=True,
            )
        if self.subscriptions is None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_SERVICE_UNAVAILABLE,
                need_at=True,
            )

        deleted = await self.subscriptions.delete(
            messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE,
            actor.unified_msg_origin,
            uid="",
        )
        # 取消后即刻移除所有历史 pending，重新订阅不能补发旧事件。
        await self.state.remove_target(actor.unified_msg_origin, uid="")
        if not deleted:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_NOT_SUBSCRIBED,
                need_at=True,
            )
        return PlainTextResponse(messages.CLIENT_UPDATE_UNSUBSCRIBED, need_at=True)

    async def _subscription_for_origin(self, origin: str) -> Subscription | None:
        subscriptions = self.subscriptions
        if subscriptions is None:
            return None
        stored = await subscriptions.get(messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE)
        return next(
            (
                subscription
                for subscription in stored
                if subscription.unified_msg_origin == origin and subscription.uid == ""
            ),
            None,
        )

    async def _initialize_missing_baselines(
        self,
        platforms: tuple[ClientPlatform, ...],
    ) -> tuple[ClientPlatform | str, ...]:
        """只为没有基线的平台或渠道建立首个成功观察。"""

        targets = self._targets_for_platforms(platforms)
        if self.transport is None:
            return targets

        failed: list[ClientPlatform | str] = []
        for target in targets:
            baseline = await self.state.get_baseline(
                _target_region(target),
                target,
            )
            if baseline is not None:
                continue
            try:
                observation = await self.transport.get_observation(target)
                _validate_observation(observation, target)
                await self.state.save_baseline(
                    ClientUpdateBaseline(
                        snapshot=observation.snapshot,
                        observed_at=datetime.now(timezone.utc),
                    )
                )
            except ClientUpdateTransportError as error:
                _log_transport_failure("subscribe_baseline", target, error)
                failed.append(target)
            except (ClientUpdateStructureError, ValueError) as error:
                _log_query_failure(target, type(error).__name__)
                failed.append(target)
        return tuple(failed)


def _change_from_baseline(
    baseline: ClientUpdateBaseline,
    current: ClientVersionSnapshot,
    patch_sizes: Mapping[int, int],
) -> ClientUpdateChange:
    previous = baseline.snapshot
    if current.patch_version < previous.patch_version:
        raise ClientUpdateRollbackError(
            previous.patch_version,
            current.patch_version,
        )
    if current.patch_version == previous.patch_version:
        raise ValueError("未变化快照不应创建 ClientUpdateChange")
    normalized_sizes = _normalize_patch_sizes(patch_sizes)
    return ClientUpdateChange(
        previous=previous,
        current=current,
        added_size_bytes=_sum_new_patch_sizes(
            previous.patch_version,
            current.patch_version,
            normalized_sizes,
        ),
        region=current.region,
        platform=current.platform,
    )


def _validate_observation(
    observation: ClientUpdateObservation,
    target: ClientPlatform | str,
) -> None:
    if not isinstance(observation, ClientUpdateObservation):
        raise ClientUpdateStructureError("transport 返回了无效 observation")

    expected_platform = _target_platform(target)
    if (
        observation.snapshot.region is not _target_region(target)
        or observation.snapshot.platform is not expected_platform
    ):
        raise ClientUpdateStructureError("observation 的区服或平台与请求不一致")

    if _is_explicit_channel_target(target):
        channel = _target_channel(target)
        if observation.snapshot.channel_id != channel.channel_id:
            raise ClientUpdateStructureError("observation 的渠道与请求不一致")


def _target_platform(target: ClientPlatform | str) -> ClientPlatform:
    try:
        return ClientPlatform(target)
    except (TypeError, ValueError):
        return _target_channel(target).platform


def _target_region(target: ClientPlatform | str) -> ClientRegion:
    if not _is_explicit_channel_target(target):
        return ClientRegion.CN
    return _target_channel(target).region


def _target_channel(target: ClientPlatform | str) -> ClientUpdateChannel:
    try:
        platform = ClientPlatform(target)
    except (TypeError, ValueError):
        return resolve_client_update_channel(target)
    return resolve_client_update_channel(default_channel_id_for_platform(platform))


def _is_explicit_channel_target(target: ClientPlatform | str) -> bool:
    if isinstance(target, ClientPlatform):
        return False
    try:
        ClientPlatform(target)
    except (TypeError, ValueError):
        return True
    return False


def _target_label(target: ClientPlatform | str) -> str:
    if _is_explicit_channel_target(target):
        return _target_channel(target).channel_id
    return _target_platform(target).value


def _serialize_platforms(platforms: tuple[ClientPlatform, ...]) -> str:
    return json.dumps(
        {"platforms": [platform.value for platform in platforms]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _log_transport_failure(
    operation: str,
    target: ClientPlatform | str,
    error: ClientUpdateTransportError,
) -> None:
    """只记录可观测的安全摘要，不把 transport detail 带入日志。"""

    logger.warning(
        "客户端更新请求失败 operation=%s target=%s kind=%s resource=%s",
        operation,
        _target_label(target),
        error.kind.value,
        error.resource,
    )


def _log_query_failure(target: ClientPlatform | str, category: str) -> None:
    logger.warning(
        "客户端更新结果不可用 target=%s category=%s",
        _target_label(target),
        category,
    )


def _normalize_patch_sizes(patch_sizes: Mapping[int, int]) -> dict[int, int]:
    if not isinstance(patch_sizes, Mapping):
        raise TypeError("patch_sizes 必须是补丁版本到字节数的映射")
    normalized: dict[int, int] = {}
    for patch_version, size_bytes in patch_sizes.items():
        if type(patch_version) is not int or patch_version < 0:
            raise ClientUpdatePatchSizeError("patch_sizes 的补丁版本号必须是非负整数")
        if type(size_bytes) is not int or size_bytes < 0:
            raise ClientUpdatePatchSizeError("patch_sizes 的大小必须是非负整数")
        normalized[patch_version] = size_bytes
    return normalized


def _sum_new_patch_sizes(
    previous_patch_version: int,
    current_patch_version: int,
    patch_sizes: Mapping[int, int],
) -> int:
    total = 0
    for patch_version in range(previous_patch_version + 1, current_patch_version + 1):
        try:
            total += patch_sizes[patch_version]
        except KeyError as error:
            raise ClientUpdatePatchSizeError(
                f"missing patch size for version {patch_version}"
            ) from error
    return total


__all__ = [
    "ClientUpdatePatchSizeError",
    "ClientUpdateRollbackError",
    "ClientUpdateService",
]
