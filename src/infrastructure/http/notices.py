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

from ...entry.event import EventActor
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
)


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

    def __init__(self, database: AsyncDatabase) -> None:
        self.database = database

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
                bot_id=actor.bot_id,
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
                web_token=record.web_token,
                web_dev_code=record.web_device_code,
                web_d_num=record.web_d_num,
                web_refresh_token=record.web_refresh_token,
                web_status=record.web_status,
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
        return MhSnapshot(sections=tuple(sections))

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
        from ...modules.notices.ann_utils import extract_blocks, pick_subject

        content = data.get("postContent", [])
        parsed = []
        for kind, value in extract_blocks(content):
            if kind == "text":
                parsed.append(AnnBlock(kind="text", text=value))
            else:
                parsed.append(AnnBlock(kind="image", image_url=value))
        return AnnDetail(
            post_id=post_id,
            title=pick_subject(data),
            blocks=tuple(parsed),
        )

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
            raise NoticesTransportError(NoticesFailureKind.NETWORK, resource="密函数据") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(NoticesFailureKind.SERVER, resource="密函数据") from None

    async def get_mh_any(self) -> MhSnapshot:
        """用任意可用账号凭据读取密函（计划任务推送用，区别于读取命令的调用者账号）。"""

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list_all(session)
            records = []
            for binding in bindings:
                record = await CredentialRepository.get(
                    session,
                    user_id=binding.user_id,
                    bot_id=binding.bot_id,
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
        binding, record = records[0]
        try:
            from ...utils import dna_api

            user = await self._legacy_user(
                EventActor(binding.user_id, binding.bot_id, None),
                binding.uid,
                binding.user_id,
            )
            response = await dna_api.get_default_role_for_tool(user)
            return self._mh_snapshot(_response_data(response, resource="密函数据"))
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(NoticesFailureKind.NETWORK, resource="密函数据") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(NoticesFailureKind.SERVER, resource="密函数据") from None

    async def get_ann_list(self) -> AnnSnapshot:
        try:
            from ...utils import dna_api

            posts = await dna_api.get_ann_list(is_cache=True) or []
            return self._ann_snapshot(posts)
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(NoticesFailureKind.NETWORK, resource="公告列表") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(NoticesFailureKind.SERVER, resource="公告列表") from None

    async def get_ann_detail(self, post_id: str) -> AnnDetail:
        try:
            from ...utils import dna_api

            response = await dna_api.get_post_detail(post_id)
            data = _response_data(response, resource="公告详情")
            if not isinstance(data, dict):
                raise NoticesTransportError(
                    NoticesFailureKind.SERVER,
                    resource="公告详情",
                    detail="successful response has no dict data",
                )
            return self._ann_detail(data, post_id)
        except NoticesTransportError:
            raise
        except (aiohttp.ClientError, OSError, asyncio.TimeoutError):
            raise NoticesTransportError(NoticesFailureKind.NETWORK, resource="公告详情") from None
        except (AttributeError, KeyError, TypeError, ValueError):
            raise NoticesTransportError(NoticesFailureKind.SERVER, resource="公告详情") from None


__all__ = ["DnaApiNoticesTransport"]
