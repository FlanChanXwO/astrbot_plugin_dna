"""便签、周报、日历和资料读取 use case。"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager, nullcontext
from datetime import datetime
from pathlib import Path

from ...entry.response import (
    ChainResponse,
    ImageResponse,
    PlainTextResponse,
    write_temporary_image,
)
from ...infrastructure.data_layout import RuntimeDataLayout
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import EncyclopediaRenderer
from ...infrastructure.resources import (
    EncyclopediaResourceStore,
    ResourceSnapshotCoordinator,
)
from ...infrastructure.utils.logger import logger
from ..privacy import PrivacyService
from . import messages
from .contracts import (
    EncyclopediaFailureKind,
    EncyclopediaRequest,
    EncyclopediaTransport,
    EncyclopediaTransportError,
)


class EncyclopediaService:
    """资料读取的隐私、账号、transport、资源和渲染协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: EncyclopediaTransport,
        privacy: PrivacyService,
        renderer: EncyclopediaRenderer,
        resources: EncyclopediaResourceStore,
        *,
        guide_providers: tuple[str, ...] = ("all",),
        resource_snapshots: ResourceSnapshotCoordinator | None = None,
        rendered_root: str | Path | None = None,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.resources = resources
        self.guide_providers = guide_providers
        self.resource_snapshots = resource_snapshots
        self.rendered_root = (
            Path(rendered_root).expanduser().absolute()
            if rendered_root is not None
            else RuntimeDataLayout.from_data_dir(
                self.database.path.parent
            ).cache_rendered_dir
        )

    def _renderer_context(self):
        if self.resource_snapshots is None:
            return nullcontext(self.renderer)
        return self.resource_snapshots.bind_renderer(
            self.renderer, "encyclopedia_resources"
        )

    @contextmanager
    def _resource_context(self) -> Iterator[EncyclopediaResourceStore]:
        if self.resource_snapshots is None:
            yield self.resources
            return
        with self.resource_snapshots.bind_resource(
            "encyclopedia_resources"
        ) as resources:
            yield resources

    def _copy_resource_image(self, path: Path) -> ImageResponse:
        return write_temporary_image(
            self.rendered_root,
            path.read_bytes(),
            prefix="dnaby-resource-",
            suffix=path.suffix or ".bin",
        )

    async def _resolve_uid(
        self,
        request: EncyclopediaRequest,
        *,
        operation: str,
    ) -> tuple[str, str] | PlainTextResponse:
        """先应用隐私策略，再按最终目标读取绑定 UID。"""

        resolution = await self.privacy.resolve_query(
            request.actor,
            request.target_user_id,
        )
        if resolution.blocked:
            return PlainTextResponse(messages.PEEK_BLOCKED)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
            )
        if binding is None:
            target = target_user_id != request.actor.user_id
            logger.warning(
                "账号绑定缺失 operation=%s scope=%s reason=local_binding_missing",
                operation,
                "target" if target else "self",
            )
            return PlainTextResponse(messages.account_not_bound(target=target))
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(
        error: EncyclopediaTransportError,
        *,
        target: bool = False,
    ) -> PlainTextResponse:
        """映射安全错误类别；不向用户返回 detail。"""

        logger.warning(
            "资料请求失败 kind=%s resource=%s",
            error.kind.value,
            error.resource,
        )

        if error.kind is EncyclopediaFailureKind.NOT_FOUND:
            return PlainTextResponse(messages.not_found(error.resource))
        return PlainTextResponse(
            messages.transport_error(error.kind.value, target=target)
        )

    async def stamina(self, request: EncyclopediaRequest):
        """读取并渲染当前用户或被允许查询用户的便签。"""

        resolved = await self._resolve_uid(request, operation="stamina")
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            snapshot = await self.transport.get_short_note(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except EncyclopediaTransportError as error:
            return self._transport_response(
                error, target=target_user_id != request.actor.user_id
            )
        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            group_id=request.actor.group_id,
        )
        with self._renderer_context() as renderer:
            rendered = await renderer.render_stamina(
                snapshot,
                actor=request.actor,
                target_user_id=target_user_id,
                uid=uid,
                uid_hidden=uid_hidden,
            )
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            sidecar=rendered.sidecar,
            manifest=rendered.manifest,
        )

    async def weekly_report(self, request: EncyclopediaRequest):
        """读取并渲染本周/上周周报。"""

        resolved = await self._resolve_uid(request, operation="weekly_report")
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        week_type = request.parameters.get("week_type", 1)
        if week_type not in (1, 2):
            return PlainTextResponse(messages.weekly_type_invalid())
        try:
            report = await self.transport.get_weekly_report(
                request.actor,
                uid,
                int(week_type),
                credential_user_id=target_user_id,
            )
        except EncyclopediaTransportError as error:
            return self._transport_response(
                error, target=target_user_id != request.actor.user_id
            )
        uid_hidden = await self.privacy.is_uid_hidden(
            target_user_id,
            group_id=request.actor.group_id,
        )
        with self._renderer_context() as renderer:
            rendered = await renderer.render_weekly_report(
                report,
                actor=request.actor,
                target_user_id=target_user_id,
                uid=uid,
                uid_hidden=uid_hidden,
            )
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            sidecar=rendered.sidecar,
            manifest=rendered.manifest,
        )

    async def calendar(self, request: EncyclopediaRequest):
        """读取并渲染活动日历。"""

        try:
            snapshot = await self.transport.get_calendar(request.actor)
        except EncyclopediaTransportError as error:
            return self._transport_response(error)
        with self._renderer_context() as renderer:
            rendered = await renderer.render_calendar(
                snapshot,
                actor=request.actor,
            )
        return ImageResponse(
            str(rendered.path),
            temporary=True,
            sidecar=rendered.sidecar,
            manifest=rendered.manifest,
        )

    async def wiki(self, request: EncyclopediaRequest):
        """按角色、武器、魔灵别名读取本地图鉴素材。"""

        name = str(request.parameters.get("name", "")).strip()
        with self._resource_context() as resources:
            asset = resources.wiki_asset(name)
            if asset is None:
                return PlainTextResponse(messages.not_found(f"【{name}】图鉴"))
            _kind, path = asset
            if (
                self.resource_snapshots is not None
                and self.resource_snapshots.current_snapshot is not None
            ):
                return self._copy_resource_image(path)
            return ImageResponse(str(path))

    async def guide(self, request: EncyclopediaRequest):
        """按配置作者读取攻略图片，保留作者文本和图片顺序。"""

        name = str(request.parameters.get("char_name", "")).strip()
        with self._resource_context() as resources:
            assets = resources.guides_for(name, self.guide_providers)
            if not assets:
                return PlainTextResponse(messages.not_found(f"角色【{name}】攻略"))
            active_generation = (
                self.resource_snapshots is not None
                and self.resource_snapshots.current_snapshot is not None
            )
            if "all" not in self.guide_providers and len(assets) == 1:
                if active_generation:
                    return self._copy_resource_image(assets[0].path)
                return ImageResponse(str(assets[0].path))
            components: list[PlainTextResponse | ImageResponse] = []
            previous_provider: str | None = None
            for asset in assets:
                # legacy 按作者目录读取图片，作者文案只在每个作者组的首张图前出现。
                if asset.provider != previous_provider:
                    components.append(
                        PlainTextResponse(messages.guide_author(asset.provider))
                    )
                    previous_provider = asset.provider
                image = (
                    self._copy_resource_image(asset.path)
                    if active_generation
                    else ImageResponse(str(asset.path))
                )
                components.append(image)
            return ChainResponse(components)

    @staticmethod
    def _format_expiry(value: datetime | None) -> str:
        if value is None:
            return ""
        return value.strftime("%Y-%m-%d %H:%M:%S")

    async def codes(self, request: EncyclopediaRequest):
        """读取兑换码，并以框架无关消息链保留旧输出顺序。"""

        try:
            snapshot = await self.transport.get_codes(request.actor)
        except EncyclopediaTransportError as error:
            return self._transport_response(error)
        if snapshot.entries:
            return ChainResponse(
                (
                    PlainTextResponse(messages.CODE_TITLE),
                    *(
                        PlainTextResponse(
                            messages.code_entry(entry),
                        )
                        for entry in snapshot.entries
                    ),
                ),
            )
        if not snapshot.codes:
            return PlainTextResponse(messages.CODE_EMPTY)
        components: list[PlainTextResponse] = [PlainTextResponse(messages.CODE_TITLE)]
        components.extend(PlainTextResponse(code) for code in snapshot.codes)
        expiry = snapshot.expires_at
        if snapshot.entries:
            expiry = snapshot.entries[0].expires_at
        if expiry is not None:
            components.append(
                PlainTextResponse(messages.code_expiry(self._format_expiry(expiry))),
            )
        return ChainResponse(tuple(components))

    async def alias_list(self, request: EncyclopediaRequest):
        """读取角色或武器的别名列表；写操作不在 Task 14 注册。"""

        alias_type = str(request.parameters.get("alias_type") or "角色")
        name = str(request.parameters.get("name", "")).strip()
        with self._resource_context() as resources:
            if alias_type == "武器":
                canonical = resources.aliases.resolve_weapon(name)
                aliases = resources.aliases.weapon_alias_list(name)
                if canonical is None or aliases is None:
                    return PlainTextResponse(messages.alias_weapon_not_found(name))
                return PlainTextResponse(
                    messages.alias_weapon_list(canonical, "\n".join(aliases)),
                )
            aliases = resources.aliases.char_alias_list(name)
            if aliases is None:
                return PlainTextResponse(messages.alias_char_not_found(name))
            return PlainTextResponse(
                messages.alias_char_list(name, "\n".join(aliases)),
            )

    async def alias_all_list(self, request: EncyclopediaRequest):
        """读取全部角色或武器 canonical name。"""

        with self._resource_context() as resources:
            if request.text == "武器列表":
                return PlainTextResponse(
                    messages.alias_all_list(
                        "武器", "\n".join(resources.aliases.all_weapons())
                    )
                )
            return PlainTextResponse(
                messages.alias_all_list(
                    "角色", "\n".join(resources.aliases.all_chars())
                )
            )


__all__ = ["EncyclopediaService"]
