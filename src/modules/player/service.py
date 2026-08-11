"""角色概览、详情/伤害和原图 use case。"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

from ...entry.response import ImageResponse, PlainTextResponse
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import OriginalImageCache, PlayerRenderer
from ..privacy import PrivacyService
from . import messages
from .contracts import (
    DamageCalculation,
    PlayerCommandRequest,
    PlayerFailureKind,
    PlayerTransport,
    PlayerTransportError,
    RoleItem,
    RoleOverview,
    WeaponDetail,
    WeaponItem,
)

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


class PlayerService:
    """玩家读取的事务/隐私/transport/渲染协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: PlayerTransport,
        privacy: PrivacyService,
        renderer: PlayerRenderer,
        original_images: OriginalImageCache,
        *,
        show_unowned_roles: bool = True,
        role_original_image: bool = True,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.original_images = original_images
        self.show_unowned_roles = show_unowned_roles
        self.role_original_image = role_original_image
        self.last_original_image: Path | None = None

    async def _resolve_uid(self, request: PlayerCommandRequest) -> tuple[str, str] | PlainTextResponse:
        """解析目标用户和当前绑定 UID，先应用隐私策略再读取账号。"""

        resolution = await self.privacy.resolve_query(request.actor, request.target_user_id)
        if resolution.blocked:
            return PlainTextResponse(messages.PLAYER_PEEK_BLOCKED)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
                bot_id=request.actor.bot_id,
            )
        if binding is None:
            return PlainTextResponse(messages.PLAYER_UID_INVALID)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: PlayerTransportError) -> PlainTextResponse:
        """映射安全错误类别；不向用户返回 detail。"""

        if error.kind is PlayerFailureKind.NOT_FOUND:
            return PlainTextResponse(f"{error.resource}未找到，请检查是否正确")
        if error.kind is PlayerFailureKind.NOT_UNLOCKED:
            return PlainTextResponse(f"{error.resource}暂未拥有，无法查看")
        return PlainTextResponse(messages.transport_error(error.kind.value))

    async def role_overview(self, request: PlayerCommandRequest):
        """读取并渲染角色/武器总览。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            overview = await self.transport.get_overview(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except PlayerTransportError as error:
            return self._transport_response(error)
        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            request.actor.bot_id,
            request.actor.group_id,
        )
        rendered = self.renderer.render_overview(
            overview,
            uid=uid,
            uid_hidden=uid_hidden,
            show_unowned=self.show_unowned_roles,
        )
        return ImageResponse(str(rendered.path), temporary=True)

    @staticmethod
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
            (item for item in overview.role_chars if normalized and normalized in item.name),
            None,
        )

    @staticmethod
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

    @classmethod
    def _select_weapons(
        cls,
        overview: RoleOverview,
        names: tuple[str, ...],
    ) -> tuple[tuple[str, WeaponItem], ...] | PlainTextResponse:
        if len(names) > 2:
            return PlainTextResponse(messages.PLAYER_WEAPON_CONFLICT)
        selected: list[tuple[str, WeaponItem]] = []
        slots: set[str] = set()
        for input_name in names:
            found = cls._find_weapon(overview.close_weapons, overview.ranged_weapons, input_name)
            if found is None:
                return PlainTextResponse(messages.PLAYER_WEAPON_NOT_FOUND)
            slot, weapon = found
            if slot in slots:
                return PlainTextResponse(messages.PLAYER_WEAPON_CONFLICT)
            if not weapon.unlocked:
                return PlainTextResponse(messages.PLAYER_WEAPON_NOT_UNLOCKED)
            if weapon.weapon_eid is None:
                return PlainTextResponse(messages.PLAYER_WEAPON_DETAIL_NOT_FOUND)
            slots.add(slot)
            selected.append(found)
        return tuple(selected)

    async def role_detail(self, request: PlayerCommandRequest):
        """读取角色详情、选定武器和伤害结果后生成一张完整详情图。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            overview = await self.transport.get_overview(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except PlayerTransportError as error:
            return self._transport_response(error)

        char_name = str(request.parameters.get("char_name", "")).strip()
        role = self._find_role(overview, char_name)
        if role is None:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_FOUND)
        if not role.unlocked or role.char_eid is None:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_UNLOCKED)

        names: list[str] = []
        for key in ("weapon_name_1", "weapon_name_2"):
            value = request.parameters.get(key)
            if value is not None and str(value).strip():
                names.append(str(value))
        selected = self._select_weapons(overview, tuple(names))
        if isinstance(selected, PlainTextResponse):
            return selected

        try:
            role_detail = await self.transport.get_role_detail(
                request.actor,
                uid,
                role.char_id,
                role.char_eid,
                credential_user_id=target_user_id,
            )
        except PlayerTransportError as error:
            return self._transport_response(error)

        weapon_sections: list[tuple[str, WeaponDetail]] = []
        if role_detail.con_weapon_id is not None and role_detail.con_weapon_eid is not None:
            try:
                con_weapon = await self.transport.get_weapon_detail(
                    request.actor,
                    uid,
                    role_detail.con_weapon_id,
                    role_detail.con_weapon_eid,
                    credential_user_id=target_user_id,
                )
            except PlayerTransportError as error:
                return self._transport_response(error)
            weapon_sections.append(("同律武器", con_weapon))

        for slot, weapon in selected:
            assert weapon.weapon_eid is not None
            try:
                weapon_detail = await self.transport.get_weapon_detail(
                    request.actor,
                    uid,
                    weapon.weapon_id,
                    weapon.weapon_eid,
                    credential_user_id=target_user_id,
                )
            except PlayerTransportError as error:
                return self._transport_response(error)
            weapon_sections.append((slot, weapon_detail))

        try:
            damage = await self.transport.calculate_damage(
                request.actor,
                uid,
                role_detail,
                next((detail for label, detail in weapon_sections if label == "同律武器"), None),
                next((detail for label, detail in weapon_sections if label == "近战武器"), None),
                next((detail for label, detail in weapon_sections if label == "远程武器"), None),
                credential_user_id=target_user_id,
            )
        except PlayerTransportError as error:
            damage = DamageCalculation.failure(messages.transport_error(error.kind.value))

        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            request.actor.bot_id,
            request.actor.group_id,
        )
        rendered = self.renderer.render_detail(
            role_detail,
            weapon_sections,
            damage,
            uid=uid,
            uid_hidden=uid_hidden,
        )
        self.last_original_image = rendered.original_image_path
        return ImageResponse(str(rendered.path), temporary=True)

    async def original_image(self, request: PlayerCommandRequest):
        """按引用消息 ID返回明确登记的原始面板图。"""

        if not self.role_original_image:
            return PlainTextResponse(messages.PLAYER_ORIGINAL_DISABLED)
        if request.reply_id is None:
            return PlainTextResponse(messages.PLAYER_ORIGINAL_REPLY_REQUIRED)
        image_path = self.original_images.get(request.reply_id)
        if image_path is None:
            return PlainTextResponse(messages.PLAYER_ORIGINAL_NOT_FOUND)
        return ImageResponse(str(image_path))

    def remember_original_image(
        self,
        message_ids: Iterable[str],
        image_path: Path | None = None,
    ) -> None:
        """在平台发送回调拿到消息 ID 后登记最近详情图对应的原图。"""

        self.original_images.remember(
            message_ids,
            self.last_original_image if image_path is None else image_path,
        )


__all__ = ["PlayerService"]
