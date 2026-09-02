"""密函与公告的 legacy 纯 API 适配器。

只在 transport 边界读取 rewrite 凭据并组装 legacy ``DNAUser`` 值对象；业务层
收到的始终是 typed notices contracts。密函复用 legacy ``get_default_role_for_tool``
响应中的 ``instanceInfo``；公告列表/详情无账号凭据（公共 BBS），HTML 清洗与时间
解析复用 ``dnaby/dna_ann/utils`` 的纯逻辑。没有凭据或外部 API 结构异常时返回
安全的 ``NoticesTransportError``，不把原始响应或 secret 带进日志/响应。
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from astrbot.api import logger

from ...entry.event import SCHEDULED_ACTOR_BOT_ID, EventActor
from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from ...modules.notices.contracts import (
    AnnBlock,
    AnnDetail,
    AnnPost,
    AnnSnapshot,
    MhInstance,
    MhSection,
    MhSnapshot,
    NoticesFailureKind,
    NoticesTransportError,
    validate_mh_snapshot,
)
from .concurrency import RequestConcurrencyGate, gated_transport_method


def _error_kind(response: Any) -> NoticesFailureKind:
    code = getattr(response, "code", None)
    if code == -999:
        return NoticesFailureKind.NETWORK
    if isinstance(code, int) and code >= 400:
        return NoticesFailureKind.STATUS
    return NoticesFailureKind.SERVER


def _response_data(response: Any, *, resource: str) -> Any:
    """检查 legacy response 成功标志并隐藏 msg/data 原文。"""

    if not getattr(response, "is_success", False):
        raise NoticesTransportError(
            _error_kind(response),
            resource=resource,
            detail=f"api response code={getattr(response, 'code', None)!r}",
        )
    data = getattr(response, "data", None)
    if data is None:
        raise NoticesTransportError(
            NoticesFailureKind.SERVER,
            resource=resource,
            detail="successful response has no data",
        )
    return data


class DnaApiNoticesTransport:
    """密函与公告读取的 legacy 纯 API 适配器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        request_gate: RequestConcurrencyGate | None = None,
    ) -> None:
        self.database = database
        self.request_gate = request_gate

    async def _legacy_user(
        self,
        actor: EventActor,
        uid: str,
        credential_user_id: str,
    ) -> Any:
        async with self.database.session() as session:
            record = await CredentialRepository.get(
                session,
                user_id=credential_user_id,
                uid=uid,
            )
        if record is None:
            raise NoticesTransportError(
                NoticesFailureKind.CREDENTIAL,
                resource="账号凭据",
                detail="credential record is missing",
            )
        try:
            from ...utils.database.models import DNAUser

            return DNAUser(
                user_id=credential_user_id,
                bot_id=actor.bot_id,
                uid=uid,
                cookie=record.app_cookie,
                dev_code=record.app_device_code,
                d_num=record.app_d_num,
                refresh_token=record.app_refresh_token,
                status=record.app_status,
            )
        except (AttributeError, TypeError, ValueError) as error:
            raise NoticesTransportError(
                NoticesFailureKind.SERVER,
                resource="账号凭据",
                detail=f"legacy credential value construction failed: {type(error).__name__}",
            ) from None

    @staticmethod
    def _mh_snapshot(data: Any) -> MhSnapshot:
        from ...utils.api.mh_map import get_mh_type_name
        from ...utils.api.model import DNAMHRes

        payload = DNAMHRes.model_validate(data)
        sections = []
        for info in payload.instanceInfo:
            if not info.mh_type:
                continue
            sections.append(
                MhSection(
                    mh_type=info.mh_type,
                    type_name=get_mh_type_name(info.mh_type),
                    instances=tuple(
                        MhInstance(instance_id=item.id, name=item.name)
                        for item in info.instances
                    ),
                ),
            )
        return validate_mh_snapshot(MhSnapshot(sections=tuple(sections)))

    @staticmethod
    def _ann_snapshot(posts: list[dict[str, Any]]) -> AnnSnapshot:
        from ...modules.notices.ann_utils import pick_preview, pick_subject, pick_time

        entries = []
        for post in posts:
            if not isinstance(post, dict):
                continue
            post_id = str(post.get("postId", ""))
            if not post_id:
                continue
            entries.append(
                AnnPost(
                    post_id=post_id,
                    title=pick_subject(post),
                    time=pick_time(post),
                    preview=pick_preview(post),
                ),
            )
        return AnnSnapshot(posts=tuple(entries))

    @staticmethod
    def _ann_detail(data: dict[str, Any], post_id: str) -> AnnDetail:
        from ...modules.notices.ann_utils import extract_blocks, pick_subject, pick_time

        content = data.get("postContent")
        if not isinstance(content, list) or not content:
            raise ValueError("公告详情缺少有效正文")
        parsed = []
        for kind, value in extract_blocks(content):
            if kind == "text":
                parsed.append(AnnBlock(kind="text", text=value))
            else:
                parsed.append(AnnBlock(kind="image", image_url=value))
        if not parsed:
            raise ValueError("公告详情正文没有有效内容块")
        return AnnDetail(
            post_id=post_id,
            title=pick_subject(data),
            blocks=tuple(parsed),
            time=pick_time(data),
        )

    @gated_transport_method
    async def get_mh(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> MhSnapshot:
        try:
            from ...utils import dna_api

            response = await dna_api.get_default_role_for_tool(
                await self._legacy_user(actor, uid, credential_user_id),
            )
            return self._mh_snapshot(_response_data(response, resource="密函数据"))
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(
                NoticesFailureKind.NETWORK, resource="密函数据"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(
                NoticesFailureKind.SERVER, resource="密函数据"
            ) from None

    @gated_transport_method
    async def get_mh_any(self) -> MhSnapshot:
        """用任意可用账号凭据读取密函（计划任务推送用，当单个凭据失效时自动轮询下一个有效凭据）。"""

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list_all(session)
            records = []
            for binding in bindings:
                record = await CredentialRepository.get(
                    session,
                    user_id=binding.user_id,
                    uid=binding.uid,
                )
                if record is not None and record.app_status != "无效":
                    records.append((binding, record))
        if not records:
            raise NoticesTransportError(
                NoticesFailureKind.CREDENTIAL,
                resource="密函数据",
                detail="no usable credential for scheduled push",
            )

        from ...utils import dna_api

        last_error: NoticesTransportError | None = None
        for binding, record in records:
            try:
                user = await self._legacy_user(
                    EventActor(
                        binding.user_id,
                        SCHEDULED_ACTOR_BOT_ID,
                        binding.group_id,
                    ),
                    binding.uid,
                    binding.user_id,
                )
                response = await dna_api.get_default_role_for_tool(user)
                return self._mh_snapshot(_response_data(response, resource="密函数据"))
            except NoticesTransportError as error:
                last_error = error
                continue
            except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
                last_error = NoticesTransportError(
                    NoticesFailureKind.NETWORK, resource="密函数据"
                )
                continue
            except (AttributeError, KeyError, TypeError, ValueError):
                last_error = NoticesTransportError(
                    NoticesFailureKind.SERVER, resource="密函数据"
                )
                continue

        if last_error is not None:
            raise last_error
        raise NoticesTransportError(
            NoticesFailureKind.SERVER,
            resource="密函数据",
            detail="failed to fetch secret letters from any available credential",
        )

    @gated_transport_method
    async def get_ann_list(self) -> AnnSnapshot:
        try:
            from ...utils import dna_api

            page_index = 1
            page_size = 20
            posts: list[dict[str, Any]] = []
            seen_post_ids: set[str] = set()
            seen_pages: set[tuple[str, ...]] = set()
            while True:
                response = await dna_api.get_ann_list_page(
                    page_index=page_index,
                    page_size=page_size,
                )
                data = _response_data(response, resource="公告列表")
                if not isinstance(data, dict):
                    raise NoticesTransportError(
                        NoticesFailureKind.SERVER,
                        resource="公告列表",
                        detail="successful response has no dict data",
                    )
                page_posts = data.get("postList")
                if not isinstance(page_posts, list):
                    raise NoticesTransportError(
                        NoticesFailureKind.SERVER,
                        resource="公告列表",
                        detail="successful response has no postList array",
                    )
                if not page_posts:
                    break
                if not all(isinstance(post, dict) for post in page_posts):
                    raise NoticesTransportError(
                        NoticesFailureKind.SERVER,
                        resource="公告列表",
                        detail="postList contains an invalid item",
                    )
                page_signature = tuple(
                    str(post.get("postId", "")) for post in page_posts
                )
                if page_signature in seen_pages:
                    # 公告接口在没有更多数据时可能继续返回最后一个满页，
                    # 即使响应里的 hasNext 仍为 1。重复页不再视为服务端失败，
                    # 只保留已经收集的唯一公告并结束翻页。
                    logger.warning(
                        "公告分页返回重复页，结束翻页 page=%s collected=%s",
                        page_index,
                        len(posts),
                    )
                    break
                seen_pages.add(page_signature)
                for post in page_posts:
                    post_id = str(post.get("postId", ""))
                    if post_id and post_id not in seen_post_ids:
                        seen_post_ids.add(post_id)
                        posts.append(post)
                if len(page_posts) < page_size:
                    break
                page_index += 1
            return self._ann_snapshot(posts)
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(
                NoticesFailureKind.NETWORK, resource="公告列表"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(
                NoticesFailureKind.SERVER, resource="公告列表"
            ) from None

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        try:
            from ...utils import dna_api

            async def fetch_detail() -> Any:
                return await dna_api.get_post_detail(post_id)

            request_gate = getattr(self, "request_gate", None)
            if request_gate is None:
                response = await fetch_detail()
            else:
                response = await request_gate.run(
                    fetch_detail, key=("ann-detail", post_id)
                )
            data = _response_data(response, resource="公告详情")
            if not isinstance(data, dict):
                raise NoticesTransportError(
                    NoticesFailureKind.SERVER,
                    resource="公告详情",
                    detail="successful response has no dict data",
                )
            detail = data.get("postDetail")
            if not isinstance(detail, dict):
                raise NoticesTransportError(
                    NoticesFailureKind.SERVER,
                    resource="公告详情",
                    detail="successful response has no postDetail object",
                )
            return self._ann_detail(detail, post_id)
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(
                NoticesFailureKind.NETWORK, resource="公告详情"
            ) from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(
                NoticesFailureKind.SERVER, resource="公告详情"
            ) from None


__all__ = ["DnaApiNoticesTransport"]
