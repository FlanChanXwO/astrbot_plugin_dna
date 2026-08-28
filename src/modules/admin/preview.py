"""管理员玩家预览 service。

该模块只依赖 rewrite 自己的 typed contract、repository 和渲染器。管理员请求已经
明确提供目标 ``user_id + uid``，因此这里不经过普通命令的 PrivacyService；渲染结果
在 service 内读取为 base64 DTO，绝不把 renderer 的本地临时路径交给 Web 层。
"""

from __future__ import annotations

import base64
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal, Protocol

from ...entry.event import EventActor
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import RenderedPlayerImage
from ...infrastructure.rendering.errors import HtmlRenderError
from ..player.contracts import (
    DamageCalculation,
    PlayerFailureKind,
    PlayerTransport,
    PlayerTransportError,
    RoleDetail,
    RoleItem,
    RoleOverview,
    WeaponDetail,
    WeaponItem,
)
from .contracts import AdminApiResponse, AdminError, AdminErrorCode

_MASTER_ALIASES = {
    "主角": "女主-光",
    "女主": "女主-光",
    "女主光": "女主-光",
    "男主": "男主-光",
    "男主光": "男主-光",
    "女主暗": "女主-暗",
    "男主暗": "男主-暗",
    "主角女": "女主-光",
    "主角男": "男主-光",
    "主角（女）": "女主-光",
    "主角（男）": "男主-光",
}


class AdminPreviewRenderer(Protocol):
    """管理员预览需要的最小渲染器协议。"""

    async def render_overview(
        self,
        overview: RoleOverview,
        *,
        uid: str,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
        uid_hidden: bool = False,
        show_unowned: bool = True,
    ) -> RenderedPlayerImage:
        """生成与普通基本信息卡相同的总览图。"""
        ...

    async def render_detail(
        self,
        detail: RoleDetail,
        weapons: list[tuple[str, WeaponDetail]] | None = None,
        damage_calc: DamageCalculation | None = None,
        *,
        uid: str,
        uid_hidden: bool = False,
        overview: RoleOverview | None = None,
        actor: EventActor | None = None,
        target_user_id: str | None = None,
    ) -> RenderedPlayerImage:
        """生成与普通角色详情/伤害卡相同的详情图。"""
        ...


@dataclass(frozen=True, slots=True)
class AdminPreviewRequest:
    """管理员预览请求；身份键来自服务端已认证的管理请求。"""

    actor: EventActor
    user_id: str
    uid: str
    char_name: str | None = None
    weapon_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        user_id = self.user_id.strip()
        uid = self.uid.strip()
        if not user_id or not uid:
            raise ValueError("预览请求缺少 user_id 或 uid")
        object.__setattr__(self, "user_id", user_id)
        object.__setattr__(self, "uid", uid)

        char_name = self.char_name
        if char_name is not None:
            char_name = char_name.strip()
            object.__setattr__(self, "char_name", char_name or None)
        weapon_names = tuple(name.strip() for name in self.weapon_names)
        object.__setattr__(self, "weapon_names", weapon_names)


@dataclass(frozen=True, slots=True)
class AdminPreviewImage:
    """可由认证 API 消费的图片 DTO，不包含任何本地路径。"""

    user_id: str
    uid: str
    view: Literal["overview", "detail"]
    data_base64: str = field(repr=False)
    content_type: str = "image/png"
    width: int = 0
    height: int = 0

    @property
    def data(self) -> str:
        """返回 API 使用的 base64 图片数据。"""

        return self.data_base64

    @property
    def image_base64(self) -> str:
        """``data_base64`` 的语义别名。"""

        return self.data_base64

    def to_dict(self) -> dict[str, object]:
        """显式导出图片数据；这里不会生成或暴露 renderer 路径。"""

        return {
            "user_id": self.user_id,
            "uid": self.uid,
            "view": self.view,
            "data": self.data_base64,
            "content_type": self.content_type,
            "width": self.width,
            "height": self.height,
        }

    def __repr__(self) -> str:
        """日志表示只保留图片元数据，不输出完整 base64 内容。"""

        return (
            "AdminPreviewImage("
            f"user_id={self.user_id!r}, uid={self.uid!r}, view={self.view!r}, "
            f"content_type={self.content_type!r}, width={self.width!r}, "
            f"height={self.height!r})"
        )


def _failure(
    code: AdminErrorCode,
    message: str,
) -> AdminApiResponse[AdminPreviewImage]:
    return AdminApiResponse.failure(AdminError(code, message))


def _find_role(overview: RoleOverview, input_name: str) -> RoleItem | None:
    normalized = input_name.strip()
    target_name = _MASTER_ALIASES.get(normalized, normalized)
    exact = next(
        (item for item in overview.role_chars if item.name == target_name),
        None,
    )
    if exact is not None:
        return exact
    return next(
        (
            item
            for item in overview.role_chars
            if normalized and normalized in item.name
        ),
        None,
    )


def _find_weapon(
    close_weapons: Iterable[WeaponItem],
    ranged_weapons: Iterable[WeaponItem],
    input_name: str,
) -> tuple[str, WeaponItem] | None:
    normalized = input_name.strip()
    for slot, weapons in (("近战武器", close_weapons), ("远程武器", ranged_weapons)):
        for weapon in weapons:
            if normalized == weapon.name or (normalized and normalized in weapon.name):
                return slot, weapon
    return None


def _select_weapons(
    overview: RoleOverview,
    names: tuple[str, ...],
) -> tuple[tuple[str, WeaponItem], ...] | AdminError:
    """复用普通详情命令的两槽位选择规则，并映射为安全 admin 错误。"""

    names = tuple(name for name in names if name)
    if len(names) > 2:
        return AdminError(AdminErrorCode.VALIDATION, "最多选择两把武器")
    selected: list[tuple[str, WeaponItem]] = []
    slots: set[str] = set()
    for input_name in names:
        found = _find_weapon(
            overview.close_weapons,
            overview.ranged_weapons,
            input_name,
        )
        if found is None:
            return AdminError(AdminErrorCode.NOT_FOUND, "所选武器不存在")
        slot, weapon = found
        if slot in slots:
            return AdminError(AdminErrorCode.CONFLICT, "同一武器类型只能选择一把")
        if not weapon.unlocked:
            return AdminError(AdminErrorCode.CONFLICT, "所选武器尚未解锁")
        if weapon.weapon_eid is None:
            return AdminError(AdminErrorCode.NOT_FOUND, "所选武器详情不存在")
        slots.add(slot)
        selected.append(found)
    return tuple(selected)


class AdminPreviewService:
    """按全局账号身份生成不受隐私设置影响的玩家预览。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: PlayerTransport,
        renderer: AdminPreviewRenderer,
    ) -> None:
        self.database = database
        self.transport = transport
        self.renderer = renderer

    async def _binding_exists(self, request: AdminPreviewRequest) -> bool:
        async with self.database.session() as session:
            binding = await AccountBindingRepository.get(
                session,
                user_id=request.user_id,
                uid=request.uid,
            )
        return binding is not None

    @staticmethod
    def _transport_error(error: PlayerTransportError) -> AdminError:
        if error.kind is PlayerFailureKind.NOT_FOUND:
            return AdminError(AdminErrorCode.NOT_FOUND, "预览数据不存在")
        if error.kind is PlayerFailureKind.NOT_UNLOCKED:
            return AdminError(AdminErrorCode.CONFLICT, "预览目标尚未解锁")
        return AdminError(AdminErrorCode.UPSTREAM, "上游玩家数据读取失败")

    @staticmethod
    def _render_error() -> AdminError:
        return AdminError(AdminErrorCode.INTERNAL, "玩家预览渲染失败")

    @staticmethod
    def _image_response(
        rendered: RenderedPlayerImage,
        *,
        user_id: str,
        uid: str,
        view: Literal["overview", "detail"],
    ) -> AdminApiResponse[AdminPreviewImage]:
        try:
            payload = rendered.path.read_bytes()
        except OSError:
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "玩家预览图片读取失败"),
            )
        if not payload:
            return AdminApiResponse.failure(
                AdminError(AdminErrorCode.INTERNAL, "玩家预览图片为空"),
            )
        return AdminApiResponse.success(
            AdminPreviewImage(
                user_id=user_id,
                uid=uid,
                view=view,
                data_base64=base64.b64encode(payload).decode("ascii"),
                width=rendered.width,
                height=rendered.height,
            ),
        )

    async def preview_overview(
        self,
        request: AdminPreviewRequest,
    ) -> AdminApiResponse[AdminPreviewImage]:
        """生成完整 UID 的基本信息卡。"""

        if not await self._binding_exists(request):
            return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")
        try:
            overview = await self.transport.get_overview(
                request.actor,
                request.uid,
                credential_user_id=request.user_id,
            )
            rendered = await self.renderer.render_overview(
                overview,
                uid=request.uid,
                actor=request.actor,
                target_user_id=request.user_id,
                uid_hidden=False,
                show_unowned=True,
            )
        except PlayerTransportError as error:
            return AdminApiResponse.failure(self._transport_error(error))
        except (HtmlRenderError, OSError, ValueError):
            return AdminApiResponse.failure(self._render_error())
        return self._image_response(
            rendered,
            user_id=request.user_id,
            uid=request.uid,
            view="overview",
        )

    async def preview_detail(
        self,
        request: AdminPreviewRequest,
    ) -> AdminApiResponse[AdminPreviewImage]:
        """从总览选择角色/可选武器，生成完整详情与伤害卡。"""

        if request.char_name is None:
            return _failure(AdminErrorCode.VALIDATION, "角色名不能为空")
        if not await self._binding_exists(request):
            return _failure(AdminErrorCode.NOT_FOUND, "账号绑定不存在")

        try:
            overview = await self.transport.get_overview(
                request.actor,
                request.uid,
                credential_user_id=request.user_id,
            )
            role = _find_role(overview, request.char_name)
            if role is None:
                return _failure(AdminErrorCode.NOT_FOUND, "所选角色不存在")
            if not role.unlocked or role.char_eid is None:
                return _failure(AdminErrorCode.CONFLICT, "所选角色尚未解锁")

            selected = _select_weapons(overview, request.weapon_names)
            if isinstance(selected, AdminError):
                return AdminApiResponse.failure(selected)

            role_detail = await self.transport.get_role_detail(
                request.actor,
                request.uid,
                role.char_id,
                role.char_eid,
                credential_user_id=request.user_id,
            )

            weapon_sections: list[tuple[str, WeaponDetail]] = []
            if (
                role_detail.con_weapon_id is not None
                and role_detail.con_weapon_eid is not None
            ):
                con_weapon = await self.transport.get_weapon_detail(
                    request.actor,
                    request.uid,
                    role_detail.con_weapon_id,
                    role_detail.con_weapon_eid,
                    credential_user_id=request.user_id,
                )
                weapon_sections.append(("同律武器", con_weapon))

            for slot, weapon in selected:
                if weapon.weapon_eid is None:
                    return _failure(AdminErrorCode.NOT_FOUND, "所选武器详情不存在")
                weapon_detail = await self.transport.get_weapon_detail(
                    request.actor,
                    request.uid,
                    weapon.weapon_id,
                    weapon.weapon_eid,
                    credential_user_id=request.user_id,
                )
                weapon_sections.append((slot, weapon_detail))

            try:
                damage = await self.transport.calculate_damage(
                    request.actor,
                    request.uid,
                    role_detail,
                    next(
                        (
                            detail
                            for label, detail in weapon_sections
                            if label == "同律武器"
                        ),
                        None,
                    ),
                    next(
                        (
                            detail
                            for label, detail in weapon_sections
                            if label == "近战武器"
                        ),
                        None,
                    ),
                    next(
                        (
                            detail
                            for label, detail in weapon_sections
                            if label == "远程武器"
                        ),
                        None,
                    ),
                    credential_user_id=request.user_id,
                )
            except PlayerTransportError as error:
                return AdminApiResponse.failure(self._transport_error(error))
            if damage.data is None:
                return _failure(AdminErrorCode.UPSTREAM, "上游伤害计算失败")

            rendered = await self.renderer.render_detail(
                role_detail,
                weapon_sections,
                damage,
                uid=request.uid,
                uid_hidden=False,
                overview=overview,
                actor=request.actor,
                target_user_id=request.user_id,
            )
        except PlayerTransportError as error:
            return AdminApiResponse.failure(self._transport_error(error))
        except (HtmlRenderError, OSError, ValueError):
            return AdminApiResponse.failure(self._render_error())
        return self._image_response(
            rendered,
            user_id=request.user_id,
            uid=request.uid,
            view="detail",
        )


__all__ = [
    "AdminPreviewImage",
    "AdminPreviewRenderer",
    "AdminPreviewRequest",
    "AdminPreviewService",
]
