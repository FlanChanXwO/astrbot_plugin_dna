"""密函、公告列表与详情读取 use case。"""

from __future__ import annotations

from ...entry.response import ImageResponse, PlainTextResponse
from ...infrastructure.persistence import AccountBindingRepository, AsyncDatabase
from ...infrastructure.rendering import NoticesRenderer
from ..privacy import PrivacyService
from . import messages
from .contracts import (
    NoticeRequest,
    NoticesTransport,
    NoticesTransportError,
)

_ANN_LIST_LIMIT = 20


class NoticesService:
    """通知读取的隐私、账号、transport 和渲染协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: NoticesTransport,
        privacy: PrivacyService,
        renderer: NoticesRenderer,
    ) -> None:
        self.database = database
        self.transport = transport
        self.privacy = privacy
        self.renderer = renderer

    async def _resolve_uid(
        self,
        request: NoticeRequest,
    ) -> tuple[str, str] | PlainTextResponse:
        resolution = await self.privacy.resolve_query(request.actor, request.target_user_id)
        if resolution.blocked:
            return PlainTextResponse(messages.NOTICES_PEEK_BLOCKED)
        target_user_id = resolution.resolved_user_id
        async with self.database.session() as session:
            binding = await AccountBindingRepository.current(
                session,
                user_id=target_user_id,
                bot_id=request.actor.bot_id,
            )
        if binding is None:
            return PlainTextResponse(messages.NOTICES_UID_INVALID)
        return target_user_id, binding.uid

    @staticmethod
    def _transport_response(error: NoticesTransportError) -> PlainTextResponse:
        return PlainTextResponse(messages.transport_error(error.kind))

    async def mh(self, request: NoticeRequest):
        """读取并渲染当前小时段的密函数据。"""

        resolved = await self._resolve_uid(request)
        if isinstance(resolved, PlainTextResponse):
            return resolved
        target_user_id, uid = resolved
        try:
            snapshot = await self.transport.get_mh(
                request.actor,
                uid,
                credential_user_id=target_user_id,
            )
        except NoticesTransportError as error:
            return self._transport_response(error)
        if not snapshot.sections:
            return PlainTextResponse(messages.MH_NOT_FOUND)
        rendered = self.renderer.render_mh(snapshot)
        return ImageResponse(str(rendered.path), temporary=True)

    async def mh_list(self, _request: NoticeRequest):
        """返回全部密函委托名称。"""

        from dnaby.utils.api.mh_map import get_mh_list

        return PlainTextResponse("\n".join(get_mh_list()))

    async def ann(self, request: NoticeRequest):
        """读取公告列表；带序号时读取对应公告详情。"""

        index = str(request.parameters.get("index") or "").strip()
        try:
            snapshot = await self.transport.get_ann_list()
        except NoticesTransportError as error:
            return self._transport_response(error)
        if not snapshot.posts:
            return PlainTextResponse(messages.ANN_LIST_FAILED)

        if not index:
            rendered = self.renderer.render_ann_list(snapshot)
            return ImageResponse(str(rendered.path), temporary=True)

        from dnaby.dna_ann.utils import build_index_map, resolve_index

        post_map = build_index_map(
            {"postId": post.post_id} for post in snapshot.posts[: _ANN_LIST_LIMIT]
        )
        post_id = resolve_index(index, post_map)
        if post_id is None:
            return PlainTextResponse(messages.ANN_INDEX_INVALID)
        try:
            detail = await self.transport.get_ann_detail(post_id)
        except NoticesTransportError as error:
            return self._transport_response(error)
        rendered = self.renderer.render_ann_detail(detail)
        return ImageResponse(str(rendered.path), temporary=True)


__all__ = ["NoticesService"]
