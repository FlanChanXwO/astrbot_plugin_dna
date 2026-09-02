from __future__ import annotations

import secrets
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..database.models import DNAUser


class LoginChannel(StrEnum):
    APP = "app"


class DNACapability(StrEnum):
    ROLE_CARD = "role_card"
    ACCOUNT_QUERY = "account_query"
    ACCOUNT_ACTION = "account_action"
    DAMAGE_CALCULATION = "damage_calculation"


_CAPABILITY_CHANNELS = {
    DNACapability.ROLE_CARD: (LoginChannel.APP,),
    DNACapability.ACCOUNT_QUERY: (LoginChannel.APP,),
    DNACapability.ACCOUNT_ACTION: (LoginChannel.APP,),
    DNACapability.DAMAGE_CALCULATION: (LoginChannel.APP,),
}


@dataclass(frozen=True, slots=True, kw_only=True)
class LoginCredentials:
    channel: LoginChannel
    token: str
    dev_code: str
    d_num: str = ""
    refresh_token: str = ""

    def __post_init__(self) -> None:
        token = self.token.strip()
        dev_code = self.dev_code.strip()
        if token == "":
            raise ValueError("token 不能为空")
        if dev_code == "":
            raise ValueError("devCode 不能为空")
        object.__setattr__(self, "token", token)
        object.__setattr__(self, "dev_code", dev_code)


def get_channel_credentials(
    dna_user: DNAUser,
    channel: LoginChannel,
) -> LoginCredentials | None:
    if channel is not LoginChannel.APP:
        return None
    if dna_user.cookie == "" or dna_user.dev_code == "" or dna_user.status == "无效":
        return None
    return LoginCredentials(
        channel=channel,
        token=dna_user.cookie,
        dev_code=dna_user.dev_code,
        d_num=dna_user.d_num,
        refresh_token=dna_user.refresh_token,
    )


def get_capability_credentials(
    dna_user: DNAUser,
    capability: DNACapability,
) -> LoginCredentials | None:
    for channel in _CAPABILITY_CHANNELS[capability]:
        credentials = get_channel_credentials(dna_user, channel)
        if credentials is not None:
            return credentials
    return None


def create_device_code(channel: LoginChannel) -> str:
    return "2" + secrets.token_hex(16)
