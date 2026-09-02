"""角色概览、基础详情和玩家缓存 use case。"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterable
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone

from ...entry.response import ChainResponse, ImageResponse, PlainTextResponse
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import PlayerRenderer
from ...infrastructure.resources import ResourceSnapshotCoordinator
from ...infrastructure.utils.logger import logger
from ..privacy import PrivacyService
from . import messages
from .cache import PlayerCache
from .contracts import (
    DamageCalculation,
    PlayerCommandRequest,
    PlayerFailureKind,
    PlayerTransport,
    PlayerTransportError,
    RoleDetail,
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


@dataclass(frozen=True, slots=True)
class _OverviewState:
    overview: RoleOverview
    digest: str
    stale: bool = False


@dataclass(frozen=True, slots=True)
class _RoleDetailBundle:
    role_detail: RoleDetail
    weapon_sections: tuple[tuple[str, WeaponDetail], ...]
    damage: DamageCalculation | None = None

    @property
    def cacheable(self) -> bool:
        """基础角色和武器详情完整即可缓存；详情不再依赖伤害接口。"""

        return True


@dataclass(frozen=True, slots=True)
class _DetailState:
    bundle: _RoleDetailBundle
    digest: str | None
    stale: bool = False


class PlayerService:
    """玩家读取的事务/隐私/transport/渲染协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: PlayerTransport,
        privacy: PrivacyService,
        renderer: PlayerRenderer,
        *,
        show_unowned_roles: bool = True,
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
        cache: PlayerCache | None = None,
        refresh_send_card: bool = True,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.show_unowned_roles = show_unowned_roles
        self.resource_snapshots = resource_snapshots
        self.cache = cache
        self.refresh_send_card = refresh_send_card
        self.clock = clock or (lambda: datetime.now(timezone.utc))
        self._overview_locks: dict[tuple[str, str], asyncio.Lock] = {}

    def _overview_lock(self, target_user_id: str, uid: str) -> asyncio.Lock:
        """串行化同一身份的概览回填，避免旧请求覆盖显式刷新结果。"""

        key = (target_user_id, uid)
        return self._overview_locks.setdefault(key, asyncio.Lock())

    def _renderer_context(self):
        if self.resource_snapshots is None:
            return nullcontext(self.renderer)
        return self.resource_snapshots.bind_renderer(self.renderer, "player_resources")

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
            )
        if binding is None:
            return PlainTextResponse(messages.PLAYER_UID_INVALID)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: PlayerTransportError) -> PlainTextResponse:
        """映射安全错误类别；不向用户返回 detail。"""

        logger.warning(
            "玩家请求失败 kind=%s resource=%s",
            error.kind.value,
            error.resource,
        )

        if error.kind is PlayerFailureKind.NOT_FOUND:
            return PlainTextResponse(f"{error.resource}未找到，请检查是否正确")
        if error.kind is PlayerFailureKind.NOT_UNLOCKED:
            return PlainTextResponse(f"{error.resource}暂未拥有，无法查看")
        return PlainTextResponse(messages.transport_error(error.kind.value))

    def _now(self) -> datetime:
        return self.clock()

    def _resource_version(self) -> str:
        """组合 generation 身份，使动态素材变更自然形成新的卡片 key。"""

        if self.resource_snapshots is None:
            return "legacy"
        snapshot = self.resource_snapshots.current_snapshot
        if snapshot is None:
            return "legacy"
        return "|".join(
            str(value)
            for value in (
                snapshot.commit_sha,
                snapshot.content_sha256,
                snapshot.resource_version,
            )
        )

    @staticmethod
    def _value_digest(value: object) -> str:
        return PlayerCache.content_digest(PlayerCache.encode_json(value))

    async def _fetch_overview(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
    ) -> RoleOverview:
        return await self.transport.get_overview(
            request.actor,
            uid,
            credential_user_id=target_user_id,
        )

    async def _load_overview(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        *,
        now: datetime,
    ) -> _OverviewState | PlainTextResponse:
        if self.cache is None:
            try:
                overview = await self._fetch_overview(request, target_user_id, uid)
            except PlayerTransportError as error:
                return self._transport_response(error)
            return _OverviewState(overview, self._value_digest(overview))

        async with self._overview_lock(target_user_id, uid):
            return await self._load_overview_cached(
                request,
                target_user_id,
                uid,
                now=now,
            )

    async def _load_overview_cached(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        *,
        now: datetime,
    ) -> _OverviewState | PlainTextResponse:
        assert self.cache is not None
        key = self.cache.overview_data_key(target_user_id, uid)
        lookup = await self.cache.get_data(key, now=now)
        cached_entry = lookup.entry
        cached_overview: RoleOverview | None = None
        if cached_entry is not None:
            try:
                cached_overview = RoleOverview.model_validate(
                    self.cache.decode_json(cached_entry.content),
                )
            except (KeyError, TypeError, ValueError):
                cached_overview = None
        if cached_overview is not None and lookup.status == "fresh":
            assert cached_entry is not None
            return _OverviewState(
                cached_overview,
                cached_entry.metadata.content_sha256,
            )
        if cached_overview is not None and lookup.status == "stale":
            assert cached_entry is not None
            try:
                overview = await self._fetch_overview(request, target_user_id, uid)
            except PlayerTransportError as error:
                logger.warning(
                    "玩家请求失败 kind=%s resource=%s cache=%s",
                    error.kind.value,
                    error.resource,
                    "stale",
                )
                return _OverviewState(
                    cached_overview,
                    cached_entry.metadata.content_sha256,
                    stale=True,
                )
            metadata = await self.cache.put_data(
                key,
                overview,
                tags=(
                    "player_data",
                    "overview",
                    self.cache.identity_tag(target_user_id, uid),
                ),
                now=now,
            )
            return _OverviewState(overview, metadata.content_sha256)

        try:
            overview = await self._fetch_overview(request, target_user_id, uid)
        except PlayerTransportError as error:
            return self._transport_response(error)
        metadata = await self.cache.put_data(
            key,
            overview,
            tags=(
                "player_data",
                "overview",
                self.cache.identity_tag(target_user_id, uid),
            ),
            now=now,
        )
        return _OverviewState(overview, metadata.content_sha256)

    async def _cached_card(
        self,
        key: str,
        *,
        now: datetime,
        fresh_only: bool,
    ) -> tuple[str, ImageResponse] | None:
        if self.cache is None:
            return None
        lookup = await self.cache.get_card(key, now=now)
        if lookup.entry is None or (fresh_only and lookup.status != "fresh"):
            return None
        return lookup.status, await self.cache.card_response(key, now=now)

    @staticmethod
    def _response_from_rendered(rendered) -> ImageResponse:
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            original_image_path=getattr(rendered, "original_image_path", None),
            incomplete=bool(getattr(rendered, "incomplete", False)),
            sidecar=getattr(rendered, "sidecar", None),
            manifest=getattr(rendered, "manifest", None),
        )

    async def _render_overview(
        self,
        overview: RoleOverview,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        uid_hidden: bool,
    ) -> ImageResponse:
        with self._renderer_context() as renderer:
            rendered_res = renderer.render_overview(
                overview,
                actor=request.actor,
                target_user_id=target_user_id,
                uid=uid,
                uid_hidden=uid_hidden,
                show_unowned=self.show_unowned_roles,
            )
            rendered = (
                await rendered_res
                if asyncio.iscoroutine(rendered_res)
                else rendered_res
            )
        return self._response_from_rendered(rendered)

    async def _store_card(
        self,
        key: str,
        response: ImageResponse,
        *,
        tags: tuple[str, ...],
        resource_version: str,
        now: datetime,
    ) -> None:
        if self.cache is None or response.incomplete:
            return
        await self.cache.put_card(
            key,
            self.cache.read_rendered_card(response.image),
            resource_version=resource_version,
            tags=tags,
            now=now,
        )

    @staticmethod
    def _stale_response(image: ImageResponse) -> ChainResponse:
        return ChainResponse((PlainTextResponse(messages.PLAYER_CACHE_STALE), image))

    async def role_overview(self, request: PlayerCommandRequest):
        """读取并渲染角色/武器总览。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        now = self._now()
        state = await self._load_overview(
            request,
            target_user_id,
            uid,
            now=now,
        )
        if isinstance(state, PlainTextResponse):
            return state
        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            group_id=request.actor.group_id,
        )
        resource_version = self._resource_version()
        if self.cache is not None:
            card_key = self.cache.overview_card_key(
                target_user_id,
                uid,
                state.digest,
                resource_version,
                uid_hidden,
                self.show_unowned_roles,
            )
            if state.stale:
                cached = await self._cached_card(card_key, now=now, fresh_only=False)
                if cached is not None:
                    return self._stale_response(cached[1])
                response = await self._render_overview(
                    state.overview,
                    request,
                    target_user_id,
                    uid,
                    uid_hidden,
                )
                return self._stale_response(response)
            cached = await self._cached_card(card_key, now=now, fresh_only=True)
            if cached is not None:
                return cached[1]
        response = await self._render_overview(
            state.overview,
            request,
            target_user_id,
            uid,
            uid_hidden,
        )
        if self.cache is not None and not state.stale:
            assert card_key is not None
            await self._store_card(
                card_key,
                response,
                tags=self.cache.overview_card_tags(
                    target_user_id,
                    uid,
                    state.digest,
                    resource_version,
                ),
                resource_version=resource_version,
                now=now,
            )
        return response

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

    @staticmethod
    def _detail_payload(bundle: _RoleDetailBundle) -> dict[str, object]:
        return {
            "role_detail": bundle.role_detail.model_dump(mode="json", by_alias=True),
            "weapon_sections": [
                {
                    "label": label,
                    "detail": detail.model_dump(mode="json", by_alias=True),
                }
                for label, detail in bundle.weapon_sections
            ],
            # 保留旧缓存中显式伤害结果的解析兼容；新卡片路径固定不写入伤害。
            "damage": (
                None
                if bundle.damage is None
                else {
                    "data": (
                        None
                        if bundle.damage.data is None
                        else bundle.damage.data.model_dump(mode="json", by_alias=True)
                    ),
                    "message": bundle.damage.message,
                }
            ),
        }

    @staticmethod
    def _detail_from_payload(raw: dict[str, object]) -> _RoleDetailBundle:
        role_raw = raw.get("role_detail")
        sections_raw = raw.get("weapon_sections")
        damage_raw = raw.get("damage")
        if (
            not isinstance(role_raw, dict)
            or not isinstance(sections_raw, list)
            or (damage_raw is not None and not isinstance(damage_raw, dict))
        ):
            raise TypeError("角色详情缓存结构无效")
        sections: list[tuple[str, WeaponDetail]] = []
        for section in sections_raw:
            if not isinstance(section, dict):
                raise TypeError("角色详情缓存武器结构无效")
            label = section.get("label")
            detail_raw = section.get("detail")
            if not isinstance(label, str) or not isinstance(detail_raw, dict):
                raise TypeError("角色详情缓存武器结构无效")
            sections.append((label, WeaponDetail.model_validate(detail_raw)))
        # 旧缓存可能仍带有伤害结果，但正常详情路径必须忽略它，避免升级后
        # 继续渲染已废弃的伤害区块；伤害 DTO/renderer 仍由显式调用方复用。
        damage = None
        return _RoleDetailBundle(
            role_detail=RoleDetail.model_validate(role_raw),
            weapon_sections=tuple(sections),
            damage=damage,
        )

    async def _fetch_detail_bundle(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        role: RoleItem,
        selected: tuple[tuple[str, WeaponItem], ...],
    ) -> _RoleDetailBundle:
        assert role.char_eid is not None
        role_detail = await self.transport.get_role_detail(
            request.actor,
            uid,
            role.char_id,
            role.char_eid,
            credential_user_id=target_user_id,
        )

        weapon_sections: list[tuple[str, WeaponDetail]] = []
        if role_detail.con_weapon_id is not None and role_detail.con_weapon_eid is not None:
            con_weapon = await self.transport.get_weapon_detail(
                request.actor,
                uid,
                role_detail.con_weapon_id,
                role_detail.con_weapon_eid,
                credential_user_id=target_user_id,
            )
            weapon_sections.append(("同律武器", con_weapon))

        for slot, weapon in selected:
            assert weapon.weapon_eid is not None
            weapon_detail = await self.transport.get_weapon_detail(
                request.actor,
                uid,
                weapon.weapon_id,
                weapon.weapon_eid,
                credential_user_id=target_user_id,
            )
            weapon_sections.append((slot, weapon_detail))

        return _RoleDetailBundle(
            role_detail=role_detail,
            weapon_sections=tuple(weapon_sections),
        )

    async def _load_detail(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        role: RoleItem,
        selected: tuple[tuple[str, WeaponItem], ...],
        overview_digest: str,
        *,
        now: datetime,
    ) -> _DetailState | PlainTextResponse:
        selected_names = tuple(weapon.name for _, weapon in selected)
        if self.cache is None:
            try:
                bundle = await self._fetch_detail_bundle(
                    request,
                    target_user_id,
                    uid,
                    role,
                    selected,
                )
            except PlayerTransportError as error:
                return self._transport_response(error)
            return _DetailState(bundle, self._value_digest(self._detail_payload(bundle)))

        key = self.cache.detail_data_key(
            target_user_id,
            uid,
            role.char_id,
            selected_names,
            overview_digest,
        )
        lookup = await self.cache.get_data(key, now=now)
        cached_entry = lookup.entry
        cached_bundle: _RoleDetailBundle | None = None
        if cached_entry is not None:
            try:
                cached_bundle = self._detail_from_payload(
                    self.cache.decode_json(cached_entry.content),
                )
            except (KeyError, TypeError, ValueError):
                cached_bundle = None
        if cached_bundle is not None and lookup.status == "fresh":
            assert cached_entry is not None
            return _DetailState(
                cached_bundle,
                cached_entry.metadata.content_sha256,
            )
        if cached_bundle is not None and lookup.status == "stale":
            assert cached_entry is not None
            try:
                bundle = await self._fetch_detail_bundle(
                    request,
                    target_user_id,
                    uid,
                    role,
                    selected,
                )
            except PlayerTransportError as error:
                logger.warning(
                    "玩家请求失败 kind=%s resource=%s cache=%s",
                    error.kind.value,
                    error.resource,
                    "stale",
                )
                return _DetailState(
                    cached_bundle,
                    cached_entry.metadata.content_sha256,
                    stale=True,
                )
            if not bundle.cacheable:
                return _DetailState(
                    cached_bundle,
                    cached_entry.metadata.content_sha256,
                    stale=True,
                )
            metadata = await self.cache.put_data(
                key,
                self._detail_payload(bundle),
                tags=self.cache.detail_data_tags(
                    target_user_id,
                    uid,
                    role.char_id,
                    overview_digest,
                ),
                now=now,
            )
            digest = metadata.content_sha256
            return _DetailState(bundle, digest)

        try:
            bundle = await self._fetch_detail_bundle(
                request,
                target_user_id,
                uid,
                role,
                selected,
            )
        except PlayerTransportError as error:
            return self._transport_response(error)
        if not bundle.cacheable:
            return _DetailState(bundle, None)
        metadata = await self.cache.put_data(
            key,
            self._detail_payload(bundle),
            tags=self.cache.detail_data_tags(
                target_user_id,
                uid,
                role.char_id,
                overview_digest,
            ),
            now=now,
        )
        return _DetailState(bundle, metadata.content_sha256)

    async def _render_detail(
        self,
        bundle: _RoleDetailBundle,
        overview: RoleOverview,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        uid_hidden: bool,
    ) -> ImageResponse:
        with self._renderer_context() as renderer:
            rendered_res = renderer.render_detail(
                bundle.role_detail,
                list(bundle.weapon_sections),
                bundle.damage,
                uid=uid,
                uid_hidden=uid_hidden,
                overview=overview,
                actor=request.actor,
                target_user_id=target_user_id,
            )
            rendered = (
                await rendered_res
                if asyncio.iscoroutine(rendered_res)
                else rendered_res
            )
        return self._response_from_rendered(rendered)

    async def _role_detail_from_overview(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        uid: str,
        overview_state: _OverviewState,
        *,
        now: datetime,
        send_card: bool = True,
    ):
        """在已取得概览后读取、缓存并渲染一个角色详情。"""

        overview = overview_state.overview

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
        detail_state = await self._load_detail(
            request,
            target_user_id,
            uid,
            role,
            selected,
            overview_state.digest,
            now=now,
        )
        if isinstance(detail_state, PlainTextResponse):
            return detail_state

        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            group_id=request.actor.group_id,
        )
        resource_version = self._resource_version()
        detail_digest = detail_state.digest
        stale = overview_state.stale or detail_state.stale
        card_key: str | None = None
        if self.cache is not None and detail_digest is not None:
            selected_names = tuple(weapon.name for _, weapon in selected)
            card_key = self.cache.detail_card_key(
                target_user_id,
                uid,
                role.char_id,
                selected_names,
                overview_state.digest,
                detail_digest,
                resource_version,
                uid_hidden,
            )
            if send_card and not stale and detail_state.bundle.cacheable:
                cached = await self._cached_card(card_key, now=now, fresh_only=True)
                if cached is not None:
                    return cached[1]
            if stale:
                cached = await self._cached_card(card_key, now=now, fresh_only=False)
                if cached is not None:
                    return self._stale_response(cached[1])

        response = await self._render_detail(
            detail_state.bundle,
            overview,
            request,
            target_user_id,
            uid,
            uid_hidden,
        )
        if (
            self.cache is not None
            and card_key is not None
            and detail_digest is not None
            and not stale
            and detail_state.bundle.cacheable
        ):
            await self._store_card(
                card_key,
                response,
                tags=self.cache.detail_card_tags(
                    target_user_id,
                    uid,
                    role.char_id,
                    detail_digest,
                    resource_version,
                ),
                resource_version=resource_version,
                now=now,
            )
        if stale:
            return self._stale_response(response)
        if not send_card:
            return PlainTextResponse(messages.PLAYER_CACHE_REFRESHED)
        return response

    async def role_detail(self, request: PlayerCommandRequest):
        """读取角色详情和选定武器后生成一张基础详情图。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        now = self._now()
        overview_state = await self._load_overview(
            request,
            target_user_id,
            uid,
            now=now,
        )
        if isinstance(overview_state, PlainTextResponse):
            return overview_state
        return await self._role_detail_from_overview(
            request,
            target_user_id,
            uid,
            overview_state,
            now=now,
        )

    async def _refresh_overview(
        self,
        request: PlayerCommandRequest,
        target_user_id: str,
        refresh_uid: str,
        *,
        now: datetime,
    ) -> tuple[RoleOverview, str] | PlainTextResponse:
        try:
            overview = await self._fetch_overview(
                request,
                target_user_id,
                refresh_uid,
            )
        except PlayerTransportError as error:
            return self._transport_response(error)

        char_name = str(request.parameters.get("char_name", "")).strip()
        role = self._find_role(overview, char_name)
        if role is None:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_FOUND)
        if not role.unlocked or role.char_eid is None:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_UNLOCKED)

        if self.cache is not None:
            await self.cache.invalidate_role(target_user_id, refresh_uid, role.char_id)
            overview_metadata = await self.cache.put_data(
                self.cache.overview_data_key(target_user_id, refresh_uid),
                overview,
                tags=(
                    "player_data",
                    "overview",
                    self.cache.identity_tag(target_user_id, refresh_uid),
                ),
                now=now,
            )
            overview_digest = overview_metadata.content_sha256
        else:
            overview_digest = self._value_digest(overview)
        return overview, overview_digest

    async def refresh_role(
        self,
        request: PlayerCommandRequest,
        *,
        uid: str | None = None,
    ):
        """强制刷新指定角色，并按配置决定是否返回新卡片。"""

        if uid is not None:
            target_user_id = request.actor.user_id
            refresh_uid = str(uid).strip()
            if not refresh_uid:
                return PlainTextResponse(messages.PLAYER_UID_INVALID)
        else:
            if request.target_user_id not in (None, request.actor.user_id):
                return PlainTextResponse(messages.PLAYER_REFRESH_SELF_ONLY)
            resolved = await self._resolve_uid(request)
            if isinstance(resolved, PlainTextResponse):
                return resolved
            target_user_id, refresh_uid = resolved

        now = self._now()
        if self.cache is not None:
            async with self._overview_lock(target_user_id, refresh_uid):
                refreshed = await self._refresh_overview(
                    request,
                    target_user_id,
                    refresh_uid,
                    now=now,
                )
        else:
            refreshed = await self._refresh_overview(
                request,
                target_user_id,
                refresh_uid,
                now=now,
            )

        if isinstance(refreshed, PlainTextResponse):
            return refreshed
        overview, overview_digest = refreshed

        return await self._role_detail_from_overview(
            request,
            target_user_id,
            refresh_uid,
            _OverviewState(overview, overview_digest),
            now=now,
            send_card=self.refresh_send_card,
        )

    async def refresh_all_roles(self, request: PlayerCommandRequest):
        """刷新当前 UID 的概览和全部已解锁角色详情，只返回汇总。"""

        if request.target_user_id not in (None, request.actor.user_id):
            return PlainTextResponse(messages.PLAYER_REFRESH_SELF_ONLY)
        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, refresh_uid = resolved
        now = self._now()
        async with self._overview_lock(target_user_id, refresh_uid):
            try:
                overview = await self._fetch_overview(
                    request,
                    target_user_id,
                    refresh_uid,
                )
            except PlayerTransportError as error:
                return self._transport_response(error)

            if self.cache is not None:
                await self.cache.invalidate_identity(target_user_id, refresh_uid)
                overview_metadata = await self.cache.put_data(
                    self.cache.overview_data_key(target_user_id, refresh_uid),
                    overview,
                    tags=(
                        "player_data",
                        "overview",
                        self.cache.identity_tag(target_user_id, refresh_uid),
                    ),
                    now=now,
                )
                overview_digest = overview_metadata.content_sha256
            else:
                overview_digest = self._value_digest(overview)

            succeeded = 0
            failed_names: list[str] = []
            for role in overview.role_chars:
                if not role.unlocked or role.char_eid is None:
                    continue
                try:
                    bundle = await self._fetch_detail_bundle(
                        request,
                        target_user_id,
                        refresh_uid,
                        role,
                        (),
                    )
                    if self.cache is not None and bundle.cacheable:
                        await self.cache.put_data(
                            self.cache.detail_data_key(
                                target_user_id,
                                refresh_uid,
                                role.char_id,
                                (),
                                overview_digest,
                            ),
                            self._detail_payload(bundle),
                            tags=self.cache.detail_data_tags(
                                target_user_id,
                                refresh_uid,
                                role.char_id,
                                overview_digest,
                            ),
                            now=now,
                        )
                    succeeded += 1
                except PlayerTransportError as error:
                    failed_names.append(role.name)
                    logger.warning(
                        "角色批量刷新失败 kind=%s resource=%s role=%s",
                        error.kind.value,
                        error.resource,
                        role.name,
                    )
                except Exception as error:  # noqa: BLE001 - 每个角色必须隔离未预期异常
                    failed_names.append(role.name)
                    logger.exception(
                        "角色批量刷新出现未预期异常 kind=%s role=%s",
                        type(error).__name__,
                        role.name,
                    )

        response = PlainTextResponse(
            messages.PLAYER_ALL_REFRESHED.format(
                success=succeeded,
                failed=len(failed_names),
            ),
        )
        if failed_names:
            response = PlainTextResponse(
                response.text + "\n失败角色：" + "、".join(failed_names),
            )
        return response

    async def clear_role_cache(self, request: PlayerCommandRequest):
        """清理当前 UID 指定角色的详情数据和卡片，保留概览缓存。"""

        if request.target_user_id not in (None, request.actor.user_id):
            return PlainTextResponse(messages.PLAYER_REFRESH_SELF_ONLY)
        if self.cache is None:
            return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
        char_name = str(request.parameters.get("char_name", "")).strip()
        if not char_name:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_FOUND)
        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        overview_state = await self._load_overview(
            request,
            target_user_id,
            uid,
            now=self._now(),
        )
        if isinstance(overview_state, PlainTextResponse):
            return overview_state
        role = self._find_role(overview_state.overview, char_name)
        if role is None:
            return PlainTextResponse(messages.PLAYER_ROLE_NOT_FOUND)
        await self.cache.invalidate_role_only(target_user_id, uid, role.char_id)
        return PlainTextResponse(messages.PLAYER_ROLE_CACHE_CLEARED.format(name=char_name))

    async def clear_all_cache(self) -> PlainTextResponse:
        """清理全部玩家数据和卡片缓存，保留其它业务缓存。"""

        if self.cache is None:
            return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
        await self.cache.invalidate_all()
        return PlainTextResponse(messages.PLAYER_CACHE_CLEARED)

    async def clear_all_role_cache(self, request: PlayerCommandRequest) -> PlainTextResponse:
        """清理当前用户当前 UID 的全部角色数据和卡片缓存。"""

        if request.target_user_id not in (None, request.actor.user_id):
            return PlainTextResponse(messages.PLAYER_REFRESH_SELF_ONLY)
        if self.cache is None:
            return PlainTextResponse(messages.PLAYER_SERVICE_UNAVAILABLE)
        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        await self.cache.invalidate_identity(target_user_id, uid)
        return PlainTextResponse(messages.PLAYER_ALL_ROLE_CACHE_CLEARED)

    async def original_image(self, _request: PlayerCommandRequest):
        """明确报告当前公开 AstrBot 结果边界不支持原图引用。"""

        return PlainTextResponse(messages.PLAYER_ORIGINAL_UNSUPPORTED)


__all__ = ["PlayerService"]
