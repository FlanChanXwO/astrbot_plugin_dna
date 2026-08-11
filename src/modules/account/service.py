"""账号登录、绑定和凭据查询 use case。

本模块只依赖 typed domain contract、SQLAlchemy repository 和框架无关响应 DTO。
真实网络由可注入 transport 实现；测试可以完全使用 fake transport 与隔离 SQLite。
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from ...entry.response import PlainTextResponse
from ...infrastructure.persistence import (
    AccountBindingRepository,
    AsyncDatabase,
    CredentialRepository,
)
from . import messages
from .contracts import (
    AccountActor,
    AccountTransport,
    AccountTransportError,
    LoginAttempt,
    LoginChannel,
    RoleInfo,
)

_UID_PATTERN = re.compile(r"^\d{13}$")


class _BindingLimitReached(Exception):
    """事务内发现新增角色会超过已有配置的绑定数量。"""


def _normalize_login_text(text: str) -> str:
    """沿用 legacy 登录命令的空白、引号和中文逗号清理规则。"""

    return text.strip().strip("\"'").strip().replace("，", ",")


def parse_login_attempt(text: str) -> LoginAttempt:
    """把命令参数解析成 token 或短信 typed request。

    legacy 行为把长度至少 40 的无逗号文本视为 token；其余合法形式是
    11 位大陆手机号加 4 位验证码。这里保留该判别边界，不把任意文本交给网络。
    """

    normalized = _normalize_login_text(text)
    if "," in normalized:
        parts = [part.strip().strip("\"'") for part in normalized.split(",")]
        if len(parts) == 2:
            try:
                return LoginAttempt.from_sms(parts[0], parts[1])
            except ValueError as exc:
                raise ValueError("登录参数格式错误") from exc
        raise ValueError("登录参数格式错误")

    if len(normalized) >= 40:
        try:
            return LoginAttempt.from_token(normalized)
        except ValueError as exc:
            raise ValueError("登录参数格式错误") from exc
    raise ValueError("登录参数格式错误")


def _valid_uid(uid: str) -> str:
    """校验 UID；13 位数字限制沿用 legacy DNABind 的 lenth_limit=13。"""

    normalized = uid.strip()
    if _UID_PATTERN.fullmatch(normalized) is None:
        raise ValueError("UID格式错误")
    return normalized


def _unique_roles(roles: Iterable[RoleInfo]) -> tuple[RoleInfo, ...]:
    """按 transport 顺序去除重复角色，保留第一个默认标记。"""

    unique: list[RoleInfo] = []
    seen: set[str] = set()
    for role in roles:
        uid = _valid_uid(role.uid)
        if uid in seen:
            continue
        seen.add(uid)
        unique.append(
            RoleInfo(
                uid=uid,
                name=role.name,
                is_default=role.is_default,
            )
        )
    return tuple(unique)


class AccountService:
    """账号相关 use case 的事务协调器。"""

    def __init__(
        self,
        database: AsyncDatabase,
        transport: AccountTransport,
        *,
        max_bind_count: int,
    ) -> None:
        if max_bind_count < 0:
            raise ValueError("max_bind_count 不能为负数")
        self.database = database
        self.transport = transport
        self.max_bind_count = max_bind_count

    async def begin_login(self, actor: AccountActor) -> PlainTextResponse:
        """创建登录页会话并立即返回地址。"""

        try:
            url = await self.transport.begin_login(actor)
        except AccountTransportError as exc:
            return PlainTextResponse(messages.transport_error(exc.kind))
        normalized_url = url.strip()
        if not normalized_url:
            return PlainTextResponse(messages.LOGIN_EMPTY_URL)
        return PlainTextResponse(messages.login_page(normalized_url))

    async def login(
        self,
        actor: AccountActor,
        attempt: LoginAttempt,
    ) -> PlainTextResponse:
        """认证并在单一事务中写入角色绑定及渠道凭据。"""

        try:
            result = await self.transport.authenticate(attempt)
        except AccountTransportError as exc:
            return PlainTextResponse(messages.transport_error(exc.kind))

        if result.status == "cancelled":
            return PlainTextResponse(messages.LOGIN_CANCELLED)
        if result.status != "success" or result.credentials is None:
            return PlainTextResponse(messages.LOGIN_FAILED)

        try:
            roles = _unique_roles(result.roles)
        except ValueError:
            return PlainTextResponse(messages.LOGIN_INVALID_ROLE)
        if not roles:
            return PlainTextResponse(messages.LOGIN_NO_ROLE)

        try:
            async with self.database.transaction() as session:
                bindings = await AccountBindingRepository.list(
                    session,
                    user_id=actor.user_id,
                    bot_id=actor.bot_id,
                )
                bound_uids = {binding.uid for binding in bindings}
                new_roles = [role for role in roles if role.uid not in bound_uids]
                if len(bindings) + len(new_roles) > self.max_bind_count:
                    raise _BindingLimitReached

                current = next(
                    (binding for binding in bindings if binding.is_active),
                    None,
                )
                for role in roles:
                    binding = await AccountBindingRepository.get(
                        session,
                        user_id=actor.user_id,
                        bot_id=actor.bot_id,
                        uid=role.uid,
                    )
                    if binding is None:
                        await AccountBindingRepository.add(
                            session,
                            user_id=actor.user_id,
                            bot_id=actor.bot_id,
                            uid=role.uid,
                            group_id=actor.group_id,
                            is_active=False,
                        )
                    if result.credentials.channel is LoginChannel.APP:
                        await CredentialRepository.save_app(
                            session,
                            user_id=actor.user_id,
                            bot_id=actor.bot_id,
                            uid=role.uid,
                            token=result.credentials.token,
                            device_code=result.credentials.dev_code,
                            d_num=result.credentials.d_num,
                            refresh_token=result.credentials.refresh_token,
                        )
                    else:
                        await CredentialRepository.save_web(
                            session,
                            user_id=actor.user_id,
                            bot_id=actor.bot_id,
                            uid=role.uid,
                            token=result.credentials.token,
                            device_code=result.credentials.dev_code,
                            d_num=result.credentials.d_num,
                            refresh_token=result.credentials.refresh_token,
                        )

                if current is None:
                    target = next(
                        (role for role in roles if role.is_default),
                        roles[0],
                    )
                    await AccountBindingRepository.set_active(
                        session,
                        user_id=actor.user_id,
                        bot_id=actor.bot_id,
                        uid=target.uid,
                    )
        except _BindingLimitReached:
            return PlainTextResponse(messages.LOGIN_BIND_LIMIT)

        return PlainTextResponse(
            messages.login_success(roles, result.credentials.channel),
        )

    async def bind_uid(
        self,
        actor: AccountActor,
        uid: str,
    ) -> PlainTextResponse:
        """新增一个 UID 绑定，首个绑定自动成为当前 UID。"""

        try:
            normalized_uid = _valid_uid(uid)
        except ValueError:
            return PlainTextResponse(messages.UID_FORMAT_ERROR)

        async with self.database.transaction() as session:
            bindings = await AccountBindingRepository.list(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
            if any(binding.uid == normalized_uid for binding in bindings):
                return PlainTextResponse(messages.UID_BIND_DUPLICATE)
            if len(bindings) >= self.max_bind_count:
                return PlainTextResponse(messages.UID_BIND_LIMIT)
            await AccountBindingRepository.add(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=normalized_uid,
                group_id=actor.group_id,
                is_active=not bindings,
            )
        return PlainTextResponse(messages.UID_BIND_SUCCESS)

    async def switch_uid(
        self,
        actor: AccountActor,
        uid: str,
    ) -> PlainTextResponse:
        """切换当前 UID。"""

        try:
            normalized_uid = _valid_uid(uid)
        except ValueError:
            return PlainTextResponse(messages.UID_FORMAT_ERROR)

        async with self.database.transaction() as session:
            switched = await AccountBindingRepository.set_active(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=normalized_uid,
            )
        if not switched:
            return PlainTextResponse(messages.UID_NOT_BOUND)
        return PlainTextResponse(messages.UID_SWITCH_SUCCESS)

    async def delete_uid(
        self,
        actor: AccountActor,
        uid: str,
    ) -> PlainTextResponse:
        """删除 UID 绑定及其 App/Web 凭据，并修复当前 UID。"""

        try:
            normalized_uid = _valid_uid(uid)
        except ValueError:
            return PlainTextResponse(messages.UID_FORMAT_ERROR)

        async with self.database.transaction() as session:
            deleted_binding = await AccountBindingRepository.delete(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=normalized_uid,
            )
            deleted_credential = await CredentialRepository.delete(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=normalized_uid,
            )
            if not deleted_binding and not deleted_credential:
                return PlainTextResponse(messages.UID_NOT_BOUND)

            remaining = await AccountBindingRepository.list(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
            if remaining and not any(binding.is_active for binding in remaining):
                await AccountBindingRepository.set_active(
                    session,
                    user_id=actor.user_id,
                    bot_id=actor.bot_id,
                    uid=remaining[0].uid,
                )
        return PlainTextResponse(messages.UID_DELETE_SUCCESS)

    async def delete_all(self, actor: AccountActor) -> PlainTextResponse:
        """删除当前作用域的全部 UID 绑定和凭据。"""

        async with self.database.transaction() as session:
            bindings = await AccountBindingRepository.delete_all(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
            credentials = await CredentialRepository.delete_all(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
        if not bindings and not credentials:
            return PlainTextResponse(messages.UID_EMPTY)
        return PlainTextResponse(messages.UID_DELETE_ALL_SUCCESS)

    async def logout(self, actor: AccountActor) -> PlainTextResponse:
        """退出当前 active UID 的登录，并保留其他绑定。"""

        async with self.database.transaction() as session:
            current = await AccountBindingRepository.current(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
            if current is None:
                return PlainTextResponse(messages.NOT_LOGGED_IN)
            credential = await CredentialRepository.get(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=current.uid,
            )
            if credential is None or not (
                credential.has_app_credentials or credential.has_web_credentials
            ):
                return PlainTextResponse(messages.NOT_LOGGED_IN)

            await AccountBindingRepository.delete(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=current.uid,
            )
            await CredentialRepository.delete(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
                uid=current.uid,
            )
            remaining = await AccountBindingRepository.list(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
            if remaining:
                await AccountBindingRepository.set_active(
                    session,
                    user_id=actor.user_id,
                    bot_id=actor.bot_id,
                    uid=remaining[0].uid,
                )
        return PlainTextResponse(messages.LOGOUT_SUCCESS)

    async def list_bindings(self, actor: AccountActor) -> PlainTextResponse:
        """列出当前作用域绑定的 UID；隐私遮罩由 Task 11 负责。"""

        async with self.database.session() as session:
            bindings = await AccountBindingRepository.list(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
        if not bindings:
            return PlainTextResponse(messages.UID_EMPTY)
        return PlainTextResponse(
            messages.binding_list(
                (binding.uid, binding.is_active) for binding in bindings
            ),
        )

    async def credentials(self, actor: AccountActor) -> PlainTextResponse:
        """查询凭据状态摘要，不返回任何原始敏感值。"""

        async with self.database.session() as session:
            records = await CredentialRepository.list(
                session,
                user_id=actor.user_id,
                bot_id=actor.bot_id,
            )
        if not records:
            return PlainTextResponse(messages.CREDENTIALS_EMPTY)
        return PlainTextResponse(
            messages.credential_summary(
                (
                    record.uid,
                    record.has_app_credentials,
                    record.has_web_credentials,
                )
                for record in records
            ),
        )


__all__ = ["AccountService", "parse_login_attempt"]
