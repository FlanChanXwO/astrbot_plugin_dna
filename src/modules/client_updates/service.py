"""客户端更新观察与版本变化检测领域逻辑。

本模块只编排已归一化的版本快照、补丁大小和状态 store，不接触 HTTP、AstrBot
事件或消息投递。手动查询和定时轮询都可以复用 ``observe`` 之外的更高层 use
case；本轮先固化成功观察的基线与变化语义。
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime

from .contracts import ClientUpdateChange, ClientVersionSnapshot
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
    """保存成功观察并生成不可重复的客户端版本变化。"""

    def __init__(self, state: ClientUpdateStateStore) -> None:
        self.state = state

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

        if not isinstance(current, ClientVersionSnapshot):
            raise TypeError("current 必须是 ClientVersionSnapshot")

        baseline = await self.state.get_baseline(current.region, current.platform)
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

        normalized_sizes = _normalize_patch_sizes(patch_sizes)
        added_size_bytes = _sum_new_patch_sizes(
            previous.patch_version,
            current.patch_version,
            normalized_sizes,
        )
        change = ClientUpdateChange(
            previous=previous,
            current=current,
            added_size_bytes=added_size_bytes,
            region=current.region,
            platform=current.platform,
        )
        await self.state.save_baseline(
            ClientUpdateBaseline(
                snapshot=current,
                observed_at=observed_at,
                last_change=change,
            )
        )
        return change


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
