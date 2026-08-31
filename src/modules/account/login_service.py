"""legacy 登录 service 的 App 兼容层。

rewrite 的命令入口使用 src.modules.account.service；本模块只保留旧
login_router 和历史调用方需要的薄适配，不再创建、读取或保存 Web 凭据。
"""

from __future__ import annotations

from dataclasses import dataclass

from ...utils import dna_api
from ...utils.api.auth import LoginChannel, LoginCredentials, create_device_code
from ...utils.api.model import DNALoginRes, DNARoleListRes
from ...utils.constants.constants import DNA_GAME_ID
from ...utils.database.models import DNABind, DNAUser
from ...utils.session import EventContext, Sender
from ...utils.utils import mask_uid_in_text

complete_error_msg = "您尚未注册二重螺旋账号，请先在【皎皎角】进行角色绑定"
role_error_msg = "未找到二重螺旋角色，请在皎皎角注册账号后重新登录"


@dataclass(frozen=True, slots=True, kw_only=True)
class _RoleToBind:
    uid: str
    name: str | None
    is_default: bool


def _normalize_optional(value: str | None) -> str:
    return "" if value is None else value


def _credential_values(credentials: LoginCredentials) -> dict[str, str]:
    """把 App 凭据映射到 legacy 内存模型。"""

    if credentials.channel is not LoginChannel.APP:
        raise ValueError("legacy 兼容层只支持 App 凭据")
    return {
        "cookie": credentials.token,
        "status": "",
        "dev_code": credentials.dev_code,
        "d_num": credentials.d_num,
        "refresh_token": credentials.refresh_token,
    }


class DNALoginService:
    """保留旧调用签名、但仅执行 App 登录的适配器。"""

    def __init__(self, sender: Sender, ctx: EventContext) -> None:
        self.sender = sender
        self.ctx = ctx

    async def login(
        self,
        *,
        channel: LoginChannel = LoginChannel.APP,
        mobile: str,
        code: str,
        dev_code: str | None = None,
    ) -> str:
        if channel is not LoginChannel.APP:
            return "当前仅支持 App 登录"
        dev_code = dev_code or create_device_code(LoginChannel.APP)
        result = await dna_api.login_app(mobile, code, dev_code)
        if not result.is_success:
            return result.throw_msg()

        login_response = DNALoginRes.model_validate(result.data)
        if login_response.isComplete == 0:
            return complete_error_msg

        credentials = LoginCredentials(
            channel=LoginChannel.APP,
            token=login_response.token.strip(),
            dev_code=dev_code,
            refresh_token=login_response.refreshToken,
            d_num=_normalize_optional(login_response.dNum),
        )
        return await self.login_with_credentials(credentials)

    async def dna_login_by_token(
        self,
        token: str,
        dev_code: str | None = None,
        refresh_token: str | None = "",
        d_num: str | None = "",
    ) -> str:
        normalized_token = token.strip()
        if not normalized_token:
            return "token不能为空"
        credentials = LoginCredentials(
            channel=LoginChannel.APP,
            token=normalized_token,
            dev_code=dev_code or create_device_code(LoginChannel.APP),
            refresh_token=_normalize_optional(refresh_token),
            d_num=_normalize_optional(d_num),
        )
        return await self.login_with_credentials(credentials)

    async def login_with_credentials(self, credentials: LoginCredentials) -> str:
        if credentials.channel is not LoginChannel.APP:
            return "当前仅支持 App 登录"
        roles_to_bind = await self._get_roles(credentials)
        if isinstance(roles_to_bind, str):
            return roles_to_bind
        return await self._complete_login(credentials, roles_to_bind)

    async def _complete_login(
        self,
        credentials: LoginCredentials,
        roles_to_bind: list[_RoleToBind],
    ) -> str:
        if not roles_to_bind:
            return complete_error_msg

        role_ids_msg: list[dict[str, str]] = []
        for role in roles_to_bind:
            await self._save_credentials(role.uid, credentials)
            await self._bind_uid(role)
            role_ids_msg.append(
                {"name": role.name or "未命名角色", "uid": role.uid}
            )
            if role.is_default:
                role_ids_msg.insert(0, role_ids_msg.pop())

        message = ["登录成功, 已为您绑定以下角色:"]
        message.extend(f"- 名字: {role['name']}" for role in role_ids_msg)
        return "\n".join(message)

    async def _get_roles(
        self,
        credentials: LoginCredentials,
    ) -> list[_RoleToBind] | str:
        if credentials.channel is not LoginChannel.APP:
            return "当前仅支持 App 登录"
        role_list_response = await dna_api.get_app_role_list(
            credentials.token,
            credentials.dev_code,
        )
        if not role_list_response.is_success:
            return role_list_response.throw_msg()
        if not role_list_response.data:
            return role_error_msg

        role_list = DNARoleListRes.model_validate(role_list_response.data)
        roles_to_bind: list[_RoleToBind] = []
        for role in role_list.roles:
            if role.gameId != DNA_GAME_ID:
                continue
            for show_vo in role.showVoList:
                roles_to_bind.append(
                    _RoleToBind(
                        uid=show_vo.roleId,
                        name=show_vo.roleName,
                        is_default=show_vo.isDefault == 1,
                    )
                )
        return roles_to_bind

    async def _save_credentials(
        self,
        uid: str,
        credentials: LoginCredentials,
    ) -> None:
        values = _credential_values(credentials)
        user = await DNAUser.select_dna_user(uid, self.ctx.user_id, self.ctx.bot_id)
        if user is None:
            await DNAUser.insert_data(
                user_id=self.ctx.user_id,
                bot_id=self.ctx.bot_id,
                uid=uid,
                **values,
            )
            return
        await DNAUser.update_data_by_data(
            select_data={
                "user_id": self.ctx.user_id,
                "bot_id": self.ctx.bot_id,
                "uid": uid,
            },
            update_data=values,
        )

    async def _bind_uid(self, role: _RoleToBind) -> None:
        result = await DNABind.insert_uid(
            self.ctx.user_id,
            self.ctx.bot_id,
            role.uid,
            self.ctx.group_id,
            lenth_limit=13,
        )
        if result == 0 or (result == -2 and role.is_default):
            await DNABind.switch_uid_by_game(
                self.ctx.user_id,
                self.ctx.bot_id,
                role.uid,
            )

    async def get_cookie(self) -> str:
        from ...utils.utils import is_uid_hidden

        hidden = await is_uid_hidden(
            self.ctx.user_id,
            self.ctx.bot_id,
            self.ctx.group_id,
        )
        dna_users = await DNAUser.select_dna_users(
            self.ctx.user_id,
            self.ctx.bot_id,
        )
        if not dna_users:
            return "当前并未登录"

        message: list[str] = []
        seen_tokens: set[str] = set()
        for raw_user in dna_users:
            if raw_user.cookie == "" or raw_user.cookie in seen_tokens:
                continue
            dna_user = await dna_api.check_cookie(raw_user)
            if dna_user is None or dna_user.cookie in seen_tokens:
                continue
            seen_tokens.add(dna_user.cookie)
            message.extend(
                (
                    f"二重螺旋UID: {dna_user.uid}",
                    "App token:",
                    dna_user.cookie,
                    "--------------------------------",
                )
            )

        if not message:
            return "未找到可用的二重螺旋 token"
        result = "\n".join(message)
        return mask_uid_in_text(result) if hidden else result


__all__ = ["DNALoginService"]
