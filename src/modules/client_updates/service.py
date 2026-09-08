"""客户端更新 Source 查询、轮询与订阅编排。"""

from __future__ import annotations

import json
from collections.abc import Sequence
from datetime import datetime, timezone

from ...entry.response import CommandResponse, MultiTextResponse, PlainTextResponse
from ...infrastructure.subscriptions import Subscription, SubscriptionStore
from ...infrastructure.utils.logger import logger
from . import messages
from .contracts import (
    ClientSourceObservation,
    ClientSourceVersion,
    ClientUpdateChange,
    ClientUpdateRequest,
    ClientUpdateStructureError,
    ClientUpdateTransport,
    ClientUpdateTransportError,
)
from .registry import (
    CLIENT_UPDATE_REGISTRY,
    DEFAULT_CLIENT_UPDATE_TARGET_IDS,
    ClientUpdateRegistry,
)
from .routing import pending_targets_for_change
from .state import ClientUpdateBaseline, ClientUpdateStateStore


class ClientUpdateRollbackError(ValueError):
    """可靠 order key 表明 Source 版本倒退。"""

    def __init__(self, previous_revision_id: str, current_revision_id: str) -> None:
        self.previous_revision_id = previous_revision_id
        self.current_revision_id = current_revision_id
        super().__init__("client update version moved backwards")


class ClientUpdatePatchSizeError(ValueError):
    """完整历史变化缺少可用更新大小时抛出的领域错误。"""


class ClientUpdateService:
    """按 Source 去重读取，并把结果展开为配置 Target。"""

    def __init__(
        self,
        state: ClientUpdateStateStore,
        *,
        transport: ClientUpdateTransport | None = None,
        subscriptions: SubscriptionStore | None = None,
        target_ids: Sequence[str] | None = None,
        registry: ClientUpdateRegistry = CLIENT_UPDATE_REGISTRY,
    ) -> None:
        if not isinstance(registry, ClientUpdateRegistry):
            raise TypeError("registry 必须是 ClientUpdateRegistry")
        self.state = state
        self.transport = transport
        self.subscriptions = subscriptions
        self.registry = registry
        self.target_ids = registry.normalize_target_ids(
            DEFAULT_CLIENT_UPDATE_TARGET_IDS if target_ids is None else target_ids
        )
        self._target_ids_by_source = registry.group_target_ids_by_source(self.target_ids)

    async def poll_now(self) -> tuple[ClientUpdateChange, ...]:
        """每个 Source 读取一次，并原子保存基线与首次 pending 事件。"""

        if self.transport is None:
            raise RuntimeError("client update transport unavailable")

        changes: list[ClientUpdateChange] = []
        for source_id, target_ids in self._target_ids_by_source.items():
            baseline = await self.state.get_baseline(source_id)
            try:
                observation = await self.transport.get_observation(
                    source_id,
                    baseline=baseline.version if baseline is not None else None,
                )
                _validate_observation(observation, source_id)
                change = _change_from_observation(baseline, observation, target_ids)
                observed_at = datetime.now(timezone.utc)
                if baseline is None:
                    await self.state.save_baseline(
                        ClientUpdateBaseline(
                            version=observation.current,
                            observed_at=observed_at,
                        )
                    )
                    continue
                if change is None:
                    await self.state.save_baseline(
                        ClientUpdateBaseline(
                            version=observation.current,
                            observed_at=observed_at,
                            last_change=baseline.last_change,
                        )
                    )
                    continue

                subscriptions = self.subscriptions
                pending_targets = (
                    pending_targets_for_change(
                        change,
                        await subscriptions.get(
                            messages.CLIENT_UPDATE_SUBSCRIPTION_TYPE
                        ),
                    )
                    if subscriptions is not None
                    else ()
                )
                await self.state.save_baseline_with_pending_event(
                    ClientUpdateBaseline(
                        version=observation.current,
                        observed_at=observed_at,
                        last_change=change,
                    ),
                    change,
                    pending_targets,
                )
            except ClientUpdateTransportError as error:
                _log_transport_failure("poll", source_id, error)
                continue
            except (
                ClientUpdatePatchSizeError,
                ClientUpdateRollbackError,
                ClientUpdateStructureError,
                TypeError,
                ValueError,
            ) as error:
                _log_source_failure("poll", source_id, type(error).__name__)
                continue
            changes.append(change)
        return tuple(changes)

    async def query(self, request: ClientUpdateRequest) -> CommandResponse:
        """查询配置 Target；读取 baseline 仅用于比较，绝不修改 state。"""

        if request.actor is None:
            return PlainTextResponse(messages.CLIENT_UPDATE_CONTEXT_UNAVAILABLE)
        if self.transport is None:
            return PlainTextResponse(messages.CLIENT_UPDATE_SERVICE_UNAVAILABLE)

        result: list[str] = []
        for source_id, target_ids in self._target_ids_by_source.items():
            baseline = await self.state.get_baseline(source_id)
            try:
                observation = await self.transport.get_observation(
                    source_id,
                    baseline=baseline.version if baseline is not None else None,
                )
                _validate_observation(observation, source_id)
                target_names = self._target_names(target_ids)
                if baseline is None:
                    result.append(
                        messages.format_current(observation.current, target_names)
                    )
                    continue
                change = _change_from_observation(baseline, observation, target_ids)
                if change is None:
                    result.append(
                        messages.format_no_change(observation.current, target_names)
                    )
                    continue
                result.append(messages.format_change(change, target_names))
            except ClientUpdateTransportError as error:
                _log_transport_failure("query", source_id, error)
            except (
                ClientUpdatePatchSizeError,
                ClientUpdateRollbackError,
                ClientUpdateStructureError,
                TypeError,
                ValueError,
            ) as error:
                _log_source_failure("query", source_id, type(error).__name__)

        if not result:
            return PlainTextResponse(messages.CLIENT_UPDATE_UNAVAILABLE)
        if len(result) == 1:
            return PlainTextResponse(result[0])
        return MultiTextResponse(tuple(result))

    async def subscribe(self, request: ClientUpdateRequest) -> PlainTextResponse:
        """创建或更新群订阅，并尝试建立缺失 Source 基线。"""

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
            extra_data=_serialize_platforms(request),
            provenance="chat_command",
        )
        failed_sources = await self._initialize_missing_baselines()
        if existing is not None:
            return PlainTextResponse(
                messages.CLIENT_UPDATE_ALREADY_SUBSCRIBED,
                need_at=True,
            )
        if failed_sources:
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

    async def _initialize_missing_baselines(self) -> tuple[str, ...]:
        """每个尚无基线的配置 Source 最多尝试一次首次读取。"""

        if self.transport is None:
            return tuple(self._target_ids_by_source)
        failed: list[str] = []
        for source_id in self._target_ids_by_source:
            if await self.state.get_baseline(source_id) is not None:
                continue
            try:
                observation = await self.transport.get_observation(source_id)
                _validate_observation(observation, source_id)
                await self.state.save_baseline(
                    ClientUpdateBaseline(
                        version=observation.current,
                        observed_at=datetime.now(timezone.utc),
                    )
                )
            except ClientUpdateTransportError as error:
                _log_transport_failure("subscribe_baseline", source_id, error)
                failed.append(source_id)
            except (ClientUpdateStructureError, TypeError, ValueError) as error:
                _log_source_failure(
                    "subscribe_baseline", source_id, type(error).__name__
                )
                failed.append(source_id)
        return tuple(failed)

    def _target_names(self, target_ids: Sequence[str]) -> tuple[str, ...]:
        return tuple(
            self.registry.resolve_target(target_id).display_name
            for target_id in target_ids
        )


def _change_from_observation(
    baseline: ClientUpdateBaseline | None,
    observation: ClientSourceObservation,
    target_ids: tuple[str, ...],
) -> ClientUpdateChange | None:
    if baseline is None:
        return None
    previous = baseline.version
    current = observation.current
    if current.revision_id == previous.revision_id:
        return None
    if _is_rollback(previous, current):
        raise ClientUpdateRollbackError(previous.revision_id, current.revision_id)
    if observation.history_complete and observation.added_size_bytes is None:
        raise ClientUpdatePatchSizeError("complete history must include update size")
    if not observation.history_complete and observation.added_size_bytes is not None:
        raise ClientUpdateStructureError("history gap cannot include update size")
    return ClientUpdateChange(
        previous=previous,
        current=current,
        history_complete=observation.history_complete,
        added_size_bytes=observation.added_size_bytes,
        target_ids=target_ids,
    )


def _is_rollback(previous: ClientSourceVersion, current: ClientSourceVersion) -> bool:
    if previous.order_key is None or current.order_key is None:
        return False
    try:
        return current.order_key < previous.order_key
    except TypeError as error:
        raise ClientUpdateStructureError("Source order_key types do not match") from error


def _validate_observation(
    observation: ClientSourceObservation,
    source_id: str,
) -> None:
    if not isinstance(observation, ClientSourceObservation):
        raise ClientUpdateStructureError("transport 返回了无效 observation")
    if observation.current.source_id != source_id:
        raise ClientUpdateStructureError("observation 与请求 Source 不一致")


def _serialize_platforms(request: ClientUpdateRequest) -> str:
    """T10 清理前保留旧订阅写入形状，避免在本 task 混入命令迁移。"""

    return json.dumps(
        {"platforms": [platform.value for platform in request.platforms]},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _log_transport_failure(
    operation: str,
    source_id: str,
    error: ClientUpdateTransportError,
) -> None:
    logger.warning(
        "客户端更新请求失败 operation=%s source=%s kind=%s resource=%s",
        operation,
        source_id,
        error.kind.value,
        error.resource,
    )


def _log_source_failure(operation: str, source_id: str, category: str) -> None:
    logger.warning(
        "客户端更新结果不可用 operation=%s source=%s category=%s",
        operation,
        source_id,
        category,
    )


__all__ = [
    "ClientUpdatePatchSizeError",
    "ClientUpdateRollbackError",
    "ClientUpdateService",
]
