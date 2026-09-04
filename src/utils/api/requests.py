import asyncio
import hashlib
import json
import random
from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, TypeVar
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import aiohttp
from astrbot.api import logger

from ...infrastructure.http.app import (
    AppTransport,
    AppTransportError,
    AppTransportFailureKind,
)
from ..constants.constants import DNA_GAME_ID
from ..database.models import DNAUser
from ..utils import timed_async_cache
from .api import (
    ACTIVITY_LIST_URL,
    ANN_LIST_URL,
    BBS_SIGN_URL,
    CALENDAR_LIST_URL,
    DAMAGE_CALCULATE_URL,
    DAMAGE_CONFIG_URL,
    DAMAGE_ENVIRONMENT_URL,
    DAMAGE_WEAPON_URL,
    GAME_SIGN_URL,
    GET_POST_DETAIL_URL,
    GET_POST_LIST_URL,
    GET_RSA_PUBLIC_KEY_URL,
    GET_SMS_CODE_URL,
    GET_TASK_PROCESS_URL,
    HAVE_SIGN_IN_URL,
    ITEM_WEEKLY_REPORT_URL,
    LIKE_POST_URL,
    LOGIN_LOG_URL,
    LOGIN_URL,
    MAIN_URL,
    REFRESH_TOKEN_URL,
    REPLY_POST_URL,
    ROLE_DETAIL_URL,
    ROLE_FOR_TOOL_URL,
    ROLE_LIST_URL,
    SHARE_POST_URL,
    SHORT_NOTE_URL,
    SIGN_CALENDAR_URL,
    WEAPON_DETAIL_URL,
    WIKI_DETAIL_URL,
    WIKI_HOME_LIST_URL,
    WIKI_LIST_URL,
)
from .auth import (
    DNACapability,
    get_capability_credentials,
)
from .damage_model import (
    BuildConfigData,
    CharacterCalculateData,
    CharacterCalculateRequest,
    EnvironmentCalculateData,
    EnvironmentCalculateRequest,
    WeaponCalculateData,
    WeaponCalculateRequest,
)
from .dnum import check_decrypt_dnum
from .request_util import (
    DNAApiResp,
    get_base_header,
    get_damage_header,
)
from .sign import get_dev_code, get_signed_headers_and_body

_DamageDataT = TypeVar("_DamageDataT")
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")

_RSA_PUBLIC_KEY_FALLBACK = (
    "MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDGpdbezK+eknQZQzPOjp8mr/dP+"
    "QHwk8CRkQh6C6qFnfLH3tiyl0pnt3dePuFDnM1PUXGhCkQ157ePJCQgkDU2+mimDmXh0oLFn9zuWSp+"
    "U8uLSLX3t3PpJ8TmNCROfUDWvzdbnShqg7JfDmnrOJz49qd234W84nrfTHbzdqeigQIDAQAB"
)


def _cache_origin(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme and parsed.netloc:
        return f"{parsed.scheme.lower()}://{parsed.netloc.lower()}"
    return url.strip().lower()


def _secret_digest(value: str | None) -> str:
    """仅把凭据的不可逆摘要放入进程缓存键，避免缓存键携带明文。"""

    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _rsa_cache_key(_self: "DNAApi") -> str:
    return _cache_origin(GET_RSA_PUBLIC_KEY_URL)


def _cache_rsa_result(value: object, *_args, **_kwargs) -> bool:
    return isinstance(value, str) and value != _RSA_PUBLIC_KEY_FALLBACK


def _login_log_cache_key(
    _self: "DNAApi",
    token: str,
    dev_code: str | None = None,
) -> str:
    return ":".join(
        (
            _cache_origin(LOGIN_LOG_URL),
            _secret_digest(token),
            _secret_digest(dev_code),
        ),
    )


def _post_list_cache_key(_self: "DNAApi", dna_user: DNAUser) -> str:
    credentials = get_capability_credentials(dna_user, DNACapability.ACCOUNT_QUERY)
    return ":".join(
        (
            _cache_origin(GET_POST_LIST_URL),
            _secret_digest(str(getattr(dna_user, "user_id", ""))),
            _secret_digest(str(getattr(dna_user, "bot_id", ""))),
            _secret_digest(str(getattr(dna_user, "uid", ""))),
            _secret_digest(credentials.token if credentials else None),
            _secret_digest(credentials.dev_code if credentials else None),
        ),
    )


class DNAApi:
    """legacy DNAApi facade backed by the unified App transport."""

    def __init__(self, *, app_transport: AppTransport | None = None) -> None:
        self.app_transport = app_transport or AppTransport(api_base_url=MAIN_URL)

    def configure_network(
        self,
        *,
        api_base_url: str = "",
        proxy_url: str = "",
        websocket_continue_seconds: int | None = None,
        websocket_wait_seconds: int | None = None,
    ) -> None:
        """把 typed network 配置同步到 REST 与官方业务 WS 两个出口。"""

        self.app_transport.set_network(
            api_base_url=api_base_url,
            proxy_url=proxy_url,
        )
        from .ws_manager import configure_ws_manager

        configure_ws_manager(
            proxy_url=proxy_url,
            continue_seconds=websocket_continue_seconds,
            wait_seconds=websocket_wait_seconds,
        )

    async def get_dna_user(self, uid: str, user_id: str, bot_id: str) -> DNAUser | None:
        dna_user = await DNAUser.select_dna_user(uid, user_id, bot_id)
        if dna_user is None:
            return None
        return await self._prepare_dna_user(dna_user)

    async def get_random_dna_user(self) -> DNAUser | None:
        dna_users = await DNAUser.get_all_card_users()
        if not dna_users:
            return None
        random.shuffle(dna_users)
        for dna_user in dna_users[:3]:
            available_user = await self._prepare_dna_user(dna_user)
            if available_user is not None:
                return available_user
        return None

    async def _prepare_dna_user(
        self,
        dna_user: DNAUser,
    ) -> DNAUser | None:
        app_credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if app_credentials is not None:
            checked_user = await self.check_cookie(dna_user)
            if checked_user is not None:
                return checked_user

        return None

    async def check_cookie(self, dna_user: DNAUser) -> DNAUser | None:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return None

        dr = check_decrypt_dnum(credentials.d_num)
        logger.debug(f"[DNA登录] 检查 App 凭据 uid={dna_user.uid} dr={dr}")
        # if dr > 0:
        #     return dna_user

        if dr == 0 and credentials.refresh_token != "":
            res = await self.refresh_token(
                credentials.token,
                credentials.refresh_token,
                credentials.dev_code,
            )
            if res.success and res.data and isinstance(res.data, dict):
                dna_user.cookie = res.data["token"]
                dna_user.d_num = res.data["dNum"]
                dna_user.status = ""
                await DNAUser.update_data_by_data(
                    select_data={
                        "user_id": dna_user.user_id,
                        "bot_id": dna_user.bot_id,
                        "uid": dna_user.uid,
                    },
                    update_data={
                        "status": "",
                        "cookie": dna_user.cookie,
                        "d_num": dna_user.d_num,
                    },
                )
                return dna_user

        login_log = await self.login_log(
            credentials.token,
            credentials.dev_code,
        )
        if not login_log.success:
            await DNAUser.mark_cookie_invalid(
                dna_user.uid,
                credentials.token,
                "无效",
            )
            dna_user.status = "无效"
            return None

        return dna_user

    @timed_async_cache(
        86400,
        lambda x: x and len(x) > 0,
        key_builder=_rsa_cache_key,
        cache_if=_cache_rsa_result,
    )
    async def get_rsa_public_key(self) -> str:
        dev_code = get_dev_code()
        headers = await get_base_header(dev_code=dev_code)
        res = await self._dna_request(
            url=GET_RSA_PUBLIC_KEY_URL, method="POST", header=headers
        )

        rsa_pub = _RSA_PUBLIC_KEY_FALLBACK

        if res.is_success and isinstance(res.data, dict):
            key = res.data.get("key")
            if key and isinstance(key, str):
                rsa_pub = key

        return rsa_pub

    async def get_app_sms_code(
        self,
        mobile: str | int,
        v_json: str,
        dev_code: str,
    ) -> DNAApiResp[Any]:
        payload = {"mobile": mobile, "vJson": v_json, "isCaptcha": 1}
        headers = await get_base_header(dev_code)
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=GET_SMS_CODE_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(
            GET_SMS_CODE_URL,
            "POST",
            headers,
            data=payload,
        )

    async def login_app(
        self,
        mobile: str | int,
        code: str,
        dev_code: str,
    ) -> DNAApiResp[Any]:
        headers = await get_base_header(dev_code)
        payload = {
            "code": code,
            "gameList": DNA_GAME_ID,
            "loginType": 1,
            "mobile": mobile,
        }
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=LOGIN_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(LOGIN_URL, "POST", headers, data=payload)

    async def refresh_token(self, token: str, refresh_token: str, dev_code: str):
        headers = await get_base_header(dev_code=dev_code, token=token)
        payload = {"refreshToken": refresh_token}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=REFRESH_TOKEN_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(REFRESH_TOKEN_URL, "POST", headers, data=payload)

    @timed_async_cache(
        3600,
        lambda x: x and x.success,
        key_builder=_login_log_cache_key,
    )
    async def login_log(self, token: str, dev_code: str | None = None):
        headers = await get_base_header(dev_code=dev_code, token=token)
        res = await self._dna_request(LOGIN_LOG_URL, "POST", headers)
        await asyncio.sleep(1 + random.uniform(0, 0.5))
        return res

    async def get_app_role_list(
        self,
        token: str,
        dev_code: str,
    ) -> DNAApiResp[Any]:
        headers = await get_base_header(dev_code=dev_code, token=token)
        payload = {}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=ROLE_LIST_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(ROLE_LIST_URL, "POST", headers, data=payload)

    async def get_mh(self):
        dna_user = await self.get_random_dna_user()
        if not dna_user:
            return DNAApiResp[Any].err("获取DNA用户失败")

        return await self.get_default_role_for_tool(dna_user)

    async def get_default_role_for_tool(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ROLE_CARD,
        )
        if credentials is None:
            return DNAApiResp[Any].err("当前账号没有可用的角色卡片凭据")
        header = await get_base_header(
            credentials.dev_code,
            token=credentials.token,
        )
        payload = {"type": 1}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=ROLE_FOR_TOOL_URL,
            header=header,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(ROLE_FOR_TOOL_URL, "POST", headers, data=payload)

    async def _damage_request(
        self,
        dna_user: DNAUser,
        url: str,
        response_model: type[DNAApiResp[_DamageDataT]],
        payload: dict[str, Any] | None = None,
    ) -> DNAApiResp[_DamageDataT]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.DAMAGE_CALCULATION,
        )
        if credentials is None:
            return response_model.err("伤害计算需要 App 登录")

        response = await self._dna_request(
            url,
            "POST",
            get_damage_header(credentials.token),
            json_data=payload,
        )
        return response_model.model_validate(response.model_dump())

    async def get_damage_config(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[BuildConfigData]:
        return await self._damage_request(
            dna_user,
            DAMAGE_CONFIG_URL,
            DNAApiResp[BuildConfigData],
        )

    async def calculate_damage(
        self,
        dna_user: DNAUser,
        request: CharacterCalculateRequest,
    ) -> DNAApiResp[CharacterCalculateData]:
        payload = request.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        return await self._damage_request(
            dna_user,
            DAMAGE_CALCULATE_URL,
            DNAApiResp[CharacterCalculateData],
            payload,
        )

    async def calculate_weapon(
        self,
        dna_user: DNAUser,
        request: WeaponCalculateRequest,
    ) -> DNAApiResp[WeaponCalculateData]:
        payload = request.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        return await self._damage_request(
            dna_user,
            DAMAGE_WEAPON_URL,
            DNAApiResp[WeaponCalculateData],
            payload,
        )

    async def calculate_environment(
        self,
        dna_user: DNAUser,
        request: EnvironmentCalculateRequest,
    ) -> DNAApiResp[EnvironmentCalculateData]:
        payload = request.model_dump(
            mode="json",
            by_alias=True,
            exclude_none=True,
        )
        return await self._damage_request(
            dna_user,
            DAMAGE_ENVIRONMENT_URL,
            DNAApiResp[EnvironmentCalculateData],
            payload,
        )

    async def get_role_detail(
        self,
        dna_user: DNAUser,
        char_id: str,
        char_eid: str,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ROLE_CARD,
        )
        if credentials is None:
            return DNAApiResp[Any].err("当前账号没有可用的角色卡片凭据")

        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data: dict[str, str | int] = {
            "charId": char_id,
            "charEid": char_eid,
            "type": 1,
        }
        return await self._dna_request(ROLE_DETAIL_URL, "POST", headers, data=data)

    async def get_weapon_detail(
        self,
        dna_user: DNAUser,
        weapon_id: int,
        weapon_eid: str,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ROLE_CARD,
        )
        if credentials is None:
            return DNAApiResp[Any].err("当前账号没有可用的角色卡片凭据")

        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data: dict[str, str | int] = {
            "weaponId": weapon_id,
            "weaponEid": weapon_eid,
            "type": 1,
        }
        return await self._dna_request(WEAPON_DETAIL_URL, "POST", headers, data=data)

    async def get_short_note_info(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        payload = {}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=SHORT_NOTE_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(SHORT_NOTE_URL, "POST", headers)

    async def get_item_weekly_report(
        self,
        dna_user: DNAUser,
        week_type: int = 1,
    ) -> DNAApiResp[Any]:
        """获取周报（资源获取统计）

        Args:
            week_type: 1=本周, 2=上周
        """
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {"weekType": week_type}
        return await self._dna_request(
            ITEM_WEEKLY_REPORT_URL, "POST", headers, data=data
        )

    async def have_sign_in(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {"gameId": DNA_GAME_ID}
        return await self._dna_request(HAVE_SIGN_IN_URL, "POST", headers, data=data)

    async def sign_calendar(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {"gameId": DNA_GAME_ID}
        return await self._dna_request(SIGN_CALENDAR_URL, "POST", headers, data=data)

    async def game_sign(
        self,
        dna_user: DNAUser,
        day_award_id: int,
        period: int,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_ACTION,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            credentials.dev_code,
            token=credentials.token,
        )
        payload = {"dayAwardId": day_award_id, "periodId": period, "signinType": 1}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=GAME_SIGN_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(GAME_SIGN_URL, "POST", headers, data=payload)

    async def bbs_sign(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_ACTION,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        payload = {"gameId": DNA_GAME_ID}
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=BBS_SIGN_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(BBS_SIGN_URL, "POST", headers, data=payload)

    async def get_task_process(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        """获取任务进度"""
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {"gameId": DNA_GAME_ID}
        try:
            return await self._dna_request(
                GET_TASK_PROCESS_URL, "POST", headers, data=data
            )
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_task_process", e)
            return DNAApiResp[Any].err("请求皎皎角服务失败")

    @timed_async_cache(
        3600,
        lambda x: x and isinstance(x, DNAApiResp) and x.is_success,
        key_builder=_post_list_cache_key,
    )
    async def get_post_list(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        """获取帖子列表"""
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_QUERY,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {
            "forumId": 46,  # 全部
            "gameId": DNA_GAME_ID,
            "pageIndex": 1,
            "pageSize": 20,
            "searchType": 1,  # 1:最新 2:热门
            "timeType": 0,
        }
        try:
            return await self._dna_request(
                GET_POST_LIST_URL, "POST", headers, data=data
            )
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_post_list", e)
            return DNAApiResp[Any].err("请求皎皎角服务失败")

    async def get_post_detail(
        self,
        post_id: str,
        dna_user: DNAUser | None = None,
    ) -> DNAApiResp[Any]:
        """获取帖子详情"""
        if dna_user is None:
            header = await get_base_header()
        else:
            credentials = get_capability_credentials(
                dna_user,
                DNACapability.ACCOUNT_QUERY,
            )
            if credentials is None:
                return DNAApiResp[Any].err("该功能需要 App 登录")
            header = await get_base_header(
                dev_code=credentials.dev_code,
                token=credentials.token,
            )
        data = {"postId": post_id}
        try:
            return await self._dna_request(
                GET_POST_DETAIL_URL, "POST", header, data=data
            )
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_post_detail", e)
            return DNAApiResp[Any].err("请求皎皎角服务失败")

    async def do_like(
        self,
        dna_user: DNAUser,
        post: dict[str, Any],
    ) -> DNAApiResp[Any]:
        """点赞帖子"""
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_ACTION,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        headers = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )

        payload = {
            "forumId": post.get("gameForumId"),
            "gameId": DNA_GAME_ID,
            "likeType": "1",
            "operateType": "1",
            "postCommentId": "",
            "postCommentReplyId": "",
            "postId": post.get("postId"),
            "postType": post.get("postType"),
            "toUserId": post.get("userId"),
        }
        rsa_pub = await self.get_rsa_public_key()
        headers, payload = get_signed_headers_and_body(
            url=LIKE_POST_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        try:
            return await self._dna_request(LIKE_POST_URL, "POST", headers, data=payload)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("do_like", e)
            return DNAApiResp[Any].err("请求皎皎角服务失败")

    async def do_share(
        self,
        dna_user: DNAUser,
    ) -> DNAApiResp[Any]:
        """分享帖子任务"""
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_ACTION,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        header = await get_base_header(
            dev_code=credentials.dev_code,
            token=credentials.token,
        )
        data = {"gameId": DNA_GAME_ID}
        try:
            return await self._dna_request(SHARE_POST_URL, "POST", header, data=data)
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("do_share", e)
            return DNAApiResp[Any].err("请求皎皎角服务失败")

    async def do_reply(
        self,
        dna_user: DNAUser,
        post: dict[str, Any],
        content: str,
    ) -> DNAApiResp[Any]:
        """回复帖子"""
        credentials = get_capability_credentials(
            dna_user,
            DNACapability.ACCOUNT_ACTION,
        )
        if credentials is None:
            return DNAApiResp[Any].err("该功能需要 App 登录")
        content_json = json.dumps([{"content": content, "contentType": "1"}])
        header = await get_base_header(
            credentials.dev_code,
            token=credentials.token,
        )
        rsa_pub = await self.get_rsa_public_key()
        payload = {
            "postId": post.get("postId"),
            "forumId": post.get("gameForumId", 47),
            "postType": "1",
            "content": content_json,
            "toUserId": post.get("userId"),
        }
        headers, payload = get_signed_headers_and_body(
            url=REPLY_POST_URL,
            header=header,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(REPLY_POST_URL, "POST", headers, data=payload)

    async def get_ann_list_page(self, *, page_index: int = 1, page_size: int = 20):
        """读取公告列表的一页；调用方负责根据服务端结果继续翻页。"""

        if page_index < 1 or page_size < 1:
            raise ValueError("公告分页参数必须为正数")
        headers = await get_base_header(dev_code=get_dev_code())
        data = {
            "otherUserId": "709542994134436647",
            "searchType": 1,
            "type": 2,
            "pageIndex": page_index,
            "pageSize": page_size,
        }
        return await self._dna_request(ANN_LIST_URL, "POST", headers, data=data)

    async def get_ann_list(self, is_cache: bool = False):
        """兼容 legacy 调用形状，但不再读取或写入进程级公告缓存。"""

        del is_cache
        res = await self.get_ann_list_page()
        if res.is_success and isinstance(res.data, dict):
            return res.data.get("postList", [])
        return []

    async def get_calendar_info(self):
        headers = await get_base_header(
            is_h5=True, is_need_origin=True, is_need_refer=True
        )
        data = {}
        res = await self._dna_request(CALENDAR_LIST_URL, "POST", headers, data=data)
        if res.is_success and isinstance(res.data, dict):
            return res.data.get("vos", [])
        return []

    async def get_wiki_home_list(self):
        headers = await get_base_header(
            is_h5=True, is_need_origin=True, is_need_refer=True
        )
        data = {}
        try:
            res = await self._dna_request(
                WIKI_HOME_LIST_URL, "POST", headers, data=data
            )
            if res.is_success and isinstance(res.data, dict):
                return res.data
            return None
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_wiki_home_list", e)
            return None

    async def get_wiki_list(
        self,
        wiki_type: int = 1,
        page_num: int = 1,
        page_size: int = 20,
        filter_ids: str | None = None,
    ):
        """获取图鉴列表

        Args:
            wiki_type: 图鉴类型，1=角色图鉴, 2=武器图鉴, 3=魔之楔图鉴, 4=魔灵图鉴, etc.
            page_num: 页码
            page_size: 每页数量
            filter_ids: 筛选条件ID，多个用逗号分隔
        """
        headers = await get_base_header(
            is_h5=True, is_need_origin=True, is_need_refer=True
        )
        data: dict[str, Any] = {
            "pageNum": page_num,
            "pageSize": page_size,
            "id": wiki_type,  # 使用 categorize ID 而非 WikiType 枚举值
        }
        if filter_ids:
            data["filterIds"] = filter_ids
        try:
            res = await self._dna_request(WIKI_LIST_URL, "POST", headers, data=data)
            return res
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_wiki_list", e)
            return DNAApiResp[Any].err("请求皎皎角Wiki服务失败")

    async def get_wiki_detail(self, wiki_id: str):
        """获取图鉴详情

        Args:
            wiki_id: 图鉴的wikiId
        """
        headers = await get_base_header(
            is_h5=True, is_need_origin=True, is_need_refer=True
        )
        data = {"id": wiki_id}
        try:
            res = await self._dna_request(WIKI_DETAIL_URL, "POST", headers, data=data)
            return res
        except (
            aiohttp.ClientError,
            asyncio.TimeoutError,
            OSError,
            TypeError,
            ValueError,
        ) as e:
            logger.exception("get_wiki_detail", e)
            return DNAApiResp[Any].err("请求皎皎角Wiki详情失败")

    async def get_activity_info(self):
        now = datetime.now(tz=SHANGHAI_TZ)
        headers = await get_base_header(dev_code=get_dev_code())
        rsa_pub = await self.get_rsa_public_key()
        payload = {
            "curTime": now.strftime("%Y-%m-%d %H:%M:%S"),  # 当前时间
            "endTime": "2026-04-05 23:59:59",
            "startTime": "2025-12-01 00:00:00",
        }
        headers, payload = get_signed_headers_and_body(
            url=ACTIVITY_LIST_URL,
            header=headers,
            data=payload,
            rsa_public_key=rsa_pub,
        )
        return await self._dna_request(ACTIVITY_LIST_URL, "POST", headers, data=payload)

    async def _dna_request(
        self,
        url: str,
        method: Literal["GET", "POST"] = "GET",
        header: Mapping[str, str] | None = None,
        params: dict[str, Any] | None = None,
        json_data: dict[str, Any] | None = None,
        data: str | dict[str, Any] | None = None,
    ) -> DNAApiResp[str | dict[str, Any] | list[Any]]:
        """通过统一 App transport 发送一次请求，不隐式重试或吞掉失败。"""

        if header is None:
            header = await get_base_header()

        raw_res = await self.app_transport.request_json(
            method,
            url,
            headers=header,
            params=params,
            json=json_data,
            data=data,
        )
        if isinstance(raw_res, dict):
            raw_data = raw_res.get("data")
            if isinstance(raw_data, str):
                try:
                    raw_res["data"] = json.loads(raw_data)
                except json.JSONDecodeError as error:
                    logger.debug("[DNA] data 字段不是 JSON: %s", type(error).__name__)

            logger.debug(
                "[DNA] App response url=%s code=%s success=%s",
                url,
                raw_res.get("code"),
                raw_res.get("success"),
            )
        else:
            logger.debug(
                "[DNA] App response url=%s type=%s", url, type(raw_res).__name__
            )

        try:
            return DNAApiResp[Any].model_validate(raw_res)
        except (TypeError, ValueError) as error:
            raise AppTransportError(
                AppTransportFailureKind.SERVER,
                method=method,
                url=url,
                detail=f"response contract failed: {type(error).__name__}",
            ) from None
