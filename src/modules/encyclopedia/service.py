"""便签、周报、日历和资料读取 use case。"""

from __future__ import annotations

from datetime import datetime

from ...entry.response import ChainResponse, ImageResponse, PlainTextResponse
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import EncyclopediaRenderer
from ...infrastructure.resources import EncyclopediaResourceStore
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
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer
        self.resources = resources
        self.guide_providers = guide_providers

    async def _resolve_uid(
        self,
        request: EncyclopediaRequest,
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
                bot_id=request.actor.bot_id,
            )
        if binding is None:
            return PlainTextResponse(messages.UID_INVALID)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: EncyclopediaTransportError) -> PlainTextResponse:
        """映射安全错误类别；不向用户返回 detail。"""

        if error.kind is EncyclopediaFailureKind.NOT_FOUND:
            return PlainTextResponse(messages.not_found(error.resource))
        return PlainTextResponse(messages.transport_error(error.kind.value))

    async def stamina(self, request: EncyclopediaRequest):
        """读取并渲染当前用户或被允许查询用户的便签。"""

        resolved = await self._resolve_uid(request)
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
            return self._transport_response(error)
        rendered = self.renderer.render_stamina(snapshot)
        return ImageResponse(str(rendered.path), temporary=True)

    async def weekly_report(self, request: EncyclopediaRequest):
        """读取并渲染本周/上周周报。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        week_type = request.parameters.get("week_type", 1)
        if week_type not in (1, 2):
            return PlainTextResponse("周报类型无效")
        try:
            report = await self.transport.get_weekly_report(
                request.actor,
                uid,
                int(week_type),
                credential_user_id=target_user_id,
            )
        except EncyclopediaTransportError as error:
            return self._transport_response(error)
        rendered = self.renderer.render_weekly_report(report)
        return ImageResponse(str(rendered.path), temporary=True)

    async def calendar(self, request: EncyclopediaRequest):
        """读取并渲染活动日历。"""

        try:
            snapshot = await self.transport.get_calendar(request.actor)
        except EncyclopediaTransportError as error:
            return self._transport_response(error)
        rendered = self.renderer.render_calendar(snapshot)
        return ImageResponse(str(rendered.path), temporary=True)

    async def wiki(self, request: EncyclopediaRequest):
        """按角色、武器、魔灵别名读取本地图鉴素材。"""

        name = str(request.parameters.get("name", "")).strip()
        asset = self.resources.wiki_asset(name)
        if asset is None:
            return PlainTextResponse(messages.not_found(f"【{name}】图鉴"))
        _kind, path = asset
        return ImageResponse(str(path))

    async def guide(self, request: EncyclopediaRequest):
        """按配置作者读取攻略图片，保留作者文本和图片顺序。"""

        name = str(request.parameters.get("char_name", "")).strip()
        assets = self.resources.guides_for(name, self.guide_providers)
        if not assets:
            return PlainTextResponse(messages.not_found(f"角色【{name}】攻略"))
        if "all" not in self.guide_providers and len(assets) == 1:
            return ImageResponse(str(assets[0].path))
        components: list[PlainTextResponse | ImageResponse] = []
        previous_provider: str | None = None
        for asset in assets:
            # legacy 按作者目录读取图片，作者文案只在每个作者组的首张图前出现。
            if asset.provider != previous_provider:
                components.append(PlainTextResponse(f"攻略作者：{asset.provider}"))
                previous_provider = asset.provider
            components.append(ImageResponse(str(asset.path)))
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
                            messages.code_entry(
                                entry.code,
                                self._format_expiry(entry.expires_at),
                            ),
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
                PlainTextResponse(f"有效期至：{self._format_expiry(expiry)}"),
            )
        return ChainResponse(tuple(components))

    async def alias_list(self, request: EncyclopediaRequest):
        """读取角色或武器的别名列表；写操作不在 Task 14 注册。"""

        alias_type = str(request.parameters.get("alias_type") or "角色")
        name = str(request.parameters.get("name", "")).strip()
        if alias_type == "武器":
            canonical = self.resources.aliases.resolve_weapon(name)
            aliases = self.resources.aliases.weapon_alias_list(name)
            if canonical is None or aliases is None:
                return PlainTextResponse(f"武器【{name}】不存在，请检查名称")
            return PlainTextResponse(
                f"武器【{canonical}】别名列表：\n" + "\n".join(aliases),
            )
        aliases = self.resources.aliases.char_alias_list(name)
        if aliases is None:
            return PlainTextResponse(f"角色【{name}】不存在，请检查名称")
        return PlainTextResponse(
            f"角色【{name}】别名列表：\n" + "\n".join(aliases),
        )

    async def alias_all_list(self, request: EncyclopediaRequest):
        """读取全部角色或武器 canonical name。"""

        if request.text == "武器列表":
            return PlainTextResponse("武器列表：\n" + "\n".join(self.resources.aliases.all_weapons()))
        return PlainTextResponse("角色列表：\n" + "\n".join(self.resources.aliases.all_chars()))


__all__ = ["EncyclopediaService"]
