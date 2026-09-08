"""密函与公告读取领域的 typed 合约。

本模块只描述密函分节、公告列表与详情所需的数据，不接触 AstrBot event、旧
``Sender`` 或数据库 ORM。camelCase 映射、HTML 清洗和 legacy 值对象组装都在
infrastructure 边界完成，service 只消费这些校验过的快照并保持错误可见。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from ...entry.event import EventActor


class NoticesFailureKind(StrEnum):
    """通知读取 transport 的可观察失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    SERVER = "server"
    CREDENTIAL = "credential"
    NOT_FOUND = "not_found"


class NoticesTransportError(Exception):
    """不会把服务端原文、URL 或凭据带到用户响应的通知读取错误。"""

    def __init__(
        self,
        kind: NoticesFailureKind | str,
        *,
        resource: str = "通知数据",
        detail: str = "",
    ) -> None:
        self.kind = NoticesFailureKind(kind)
        self.resource = resource
        self.detail = detail
        super().__init__(f"notices transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """异常 repr 只保留类别和安全资源名，避免 detail 泄露。"""

        return f"NoticesTransportError(kind={self.kind.value!r}, resource={self.resource!r})"


@dataclass(frozen=True, slots=True)
class MhInstance:
    """一条密函委托实例。"""

    instance_id: int
    name: str


@dataclass(frozen=True, slots=True)
class MhSection:
    """一个密函类型（角色/武器/魔之楔）下的全部委托。"""

    mh_type: str
    type_name: str
    instances: tuple[MhInstance, ...] = ()


@dataclass(frozen=True, slots=True)
class MhSnapshot:
    """当前小时段密函数据的 typed 快照。"""

    sections: tuple[MhSection, ...] = ()


def validate_mh_snapshot(snapshot: MhSnapshot) -> MhSnapshot:
    """校验可用于缓存或自动推送的完整密函快照。

    实时查询仍可把空快照映射为“未找到”，但缓存和自动推送必须拒绝空分区、
    空名称或非整数实例 ID，避免把结构异常误记为当前小时的成功结果。
    """

    if not isinstance(snapshot, MhSnapshot) or not snapshot.sections:
        raise ValueError("密函快照缺少有效分区")
    for section in snapshot.sections:
        if (
            not isinstance(section, MhSection)
            or not section.instances
            or not isinstance(section.mh_type, str)
            or not isinstance(section.type_name, str)
            or not section.mh_type.strip()
            or not section.type_name.strip()
        ):
            raise ValueError("密函快照分区结构不完整")
        for instance in section.instances:
            if (
                not isinstance(instance, MhInstance)
                or type(instance.instance_id) is not int
                or not isinstance(instance.name, str)
            ):
                raise ValueError("密函实例结构不完整")
            if not instance.name.strip():
                raise ValueError("密函实例名称为空")
    return snapshot


@dataclass(frozen=True, slots=True)
class AnnPost:
    """公告列表中的一项。"""

    post_id: str
    title: str
    time: str = ""
    preview: str = ""


@dataclass(frozen=True, slots=True)
class AnnSnapshot:
    """公告列表快照。"""

    posts: tuple[AnnPost, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnBlock:
    """公告详情中的一个文本或图片块。"""

    kind: str  # "text" | "image"
    text: str = ""
    image_url: str = ""


@dataclass(frozen=True, slots=True)
class AnnDetail:
    """一篇公告的标题和内容块。"""

    post_id: str
    title: str
    blocks: tuple[AnnBlock, ...] = ()
    time: str = ""


@dataclass(frozen=True, slots=True)
class NoticeRequest:
    """通知命令的框架无关输入。"""

    actor: EventActor
    target_user_id: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    text: str = ""
    matched_prefix: str = "kk"


class NoticesTransport(Protocol):
    """通知读取 use case 所需的最小 transport。"""

    async def get_mh(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> MhSnapshot:
        """读取当前小时段的密函数据。"""
        ...

    async def get_mh_any(self) -> MhSnapshot:
        """使用任意可用账号凭据读取公共密函。"""
        ...

    async def get_ann_list(self) -> AnnSnapshot:
        """读取公告列表。"""
        ...

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        """读取一篇公告详情。"""
        ...


__all__ = [
    "AnnBlock",
    "AnnDetail",
    "AnnPost",
    "AnnSnapshot",
    "MhInstance",
    "MhSection",
    "MhSnapshot",
    "NoticeRequest",
    "NoticesFailureKind",
    "NoticesTransport",
    "NoticesTransportError",
    "validate_mh_snapshot",
]
