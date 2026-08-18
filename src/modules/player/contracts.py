"""玩家查询领域的 typed 合约。

本模块只描述角色查询、详情和伤害计算所需的数据，不接触 AstrBot event、旧
``Sender`` 或数据库 ORM。外部 API 的 snake/camel case 映射在 transport 边界
完成，渲染器只消费这些已经校验过的快照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field

from ...entry.event import EventActor


class _PlayerModel(BaseModel):
    """玩家 API 数据的共同校验策略。"""

    model_config = ConfigDict(extra="ignore", populate_by_name=True)


class PlayerFailureKind(StrEnum):
    """玩家读取 transport 的可观察失败类别。"""

    NETWORK = "network"
    STATUS = "status"
    SERVER = "server"
    NOT_FOUND = "not_found"
    NOT_UNLOCKED = "not_unlocked"


class PlayerTransportError(Exception):
    """不会把服务端原文、URL 或凭据带到用户响应的读取错误。"""

    def __init__(
        self,
        kind: PlayerFailureKind,
        *,
        resource: str = "玩家数据",
        detail: str = "",
    ) -> None:
        self.kind = PlayerFailureKind(kind)
        self.resource = resource
        self.detail = detail
        super().__init__(f"player transport {self.kind.value} failure")

    def __repr__(self) -> str:
        """异常 repr 只保留类别，避免日志意外包含 detail。"""

        return f"PlayerTransportError(kind={self.kind.value!r}, resource={self.resource!r})"


class RoleItem(_PlayerModel):
    """角色展柜中的一项。"""

    char_id: int = Field(validation_alias="charId", serialization_alias="charId")
    char_eid: str | None = Field(default=None, validation_alias="charEid", serialization_alias="charEid")
    element_icon: str = Field(default="", validation_alias="elementIcon", serialization_alias="elementIcon")
    icon: str = ""
    level: int = 0
    name: str
    grade_level: int = Field(default=0, validation_alias="gradeLevel", serialization_alias="gradeLevel")
    unlocked: bool = Field(default=False, validation_alias="unLocked", serialization_alias="unLocked")


class WeaponItem(_PlayerModel):
    """武器展柜中的一项。"""

    element_icon: str = Field(default="", validation_alias="elementIcon", serialization_alias="elementIcon")
    icon: str = ""
    level: int = 0
    name: str
    unlocked: bool = Field(default=False, validation_alias="unLocked", serialization_alias="unLocked")
    weapon_eid: str | None = Field(default=None, validation_alias="weaponEid", serialization_alias="weaponEid")
    weapon_id: int = Field(validation_alias="weaponId", serialization_alias="weaponId")
    skill_level: int = Field(default=0, validation_alias="skillLevel", serialization_alias="skillLevel")


class RoleAchievement(_PlayerModel):
    """角色总览的额外统计项。"""

    param_key: str = Field(validation_alias="paramKey", serialization_alias="paramKey")
    param_value: str = Field(validation_alias="paramValue", serialization_alias="paramValue")


class RoleOverview(_PlayerModel):
    """`defaultRoleForTool` 中 roleShow 的完整 typed 投影。"""

    role_id: str = Field(validation_alias="roleId", serialization_alias="roleId")
    role_name: str = Field(default="", validation_alias="roleName", serialization_alias="roleName")
    level: int | None = None
    params: list[RoleAchievement] = Field(default_factory=list)
    achievement_total: int = Field(default=0, validation_alias="achievementTotal", serialization_alias="achievementTotal")
    role_chars: list[RoleItem] = Field(default_factory=list, validation_alias="roleChars", serialization_alias="roleChars")
    ranged_weapons: list[WeaponItem] = Field(
        default_factory=list,
        validation_alias="langRangeWeapons",
        serialization_alias="langRangeWeapons",
    )
    close_weapons: list[WeaponItem] = Field(default_factory=list, validation_alias="closeWeapons", serialization_alias="closeWeapons")


class RoleAttribute(_PlayerModel):
    """角色面板属性。"""

    skill_range: str = Field(default="", validation_alias="skillRange", serialization_alias="skillRange")
    strong_value: str = Field(default="", validation_alias="strongValue", serialization_alias="strongValue")
    skill_intensity: str = Field(default="", validation_alias="skillIntensity", serialization_alias="skillIntensity")
    weapon_tags: list[str | None] = Field(default_factory=list, validation_alias="weaponTags", serialization_alias="weaponTags")
    defense: int = Field(default=0, validation_alias="def", serialization_alias="def")
    enmity_value: str = Field(default="", validation_alias="enmityValue", serialization_alias="enmityValue")
    skill_efficiency: str = Field(default="", validation_alias="skillEfficiency", serialization_alias="skillEfficiency")
    skill_sustain: str = Field(default="", validation_alias="skillSustain", serialization_alias="skillSustain")
    max_hp: int = Field(default=0, validation_alias="maxHp", serialization_alias="maxHp")
    atk: int = 0
    max_es: int = Field(default=0, validation_alias="maxES", serialization_alias="maxES")
    max_sp: int = Field(default=0, validation_alias="maxSp", serialization_alias="maxSp")


class RoleSkill(_PlayerModel):
    """角色技能。"""

    skill_id: int = Field(validation_alias="skillId", serialization_alias="skillId")
    icon: str = ""
    level: int = 0
    skill_name: str = Field(validation_alias="skillName", serialization_alias="skillName")

    @property
    def skillId(self) -> int:
        return self.skill_id

    @property
    def skillName(self) -> str:
        return self.skill_name


class RoleTrace(_PlayerModel):
    """角色溯源描述。"""

    icon: str = ""
    description: str = ""


class Mode(_PlayerModel):
    """角色或武器的魔之楔。"""

    id: int
    icon: str | None = None
    quality: int | None = None
    name: str | None = None
    level: int | None = 0


class RoleDetail(_PlayerModel):
    """角色详情 API 的完整合法字段。"""

    attribute: RoleAttribute
    skills: list[RoleSkill] = Field(default_factory=list)
    paint: str = ""
    char_id: int = Field(validation_alias="charId", serialization_alias="charId")
    char_name: str = Field(validation_alias="charName", serialization_alias="charName")
    element_icon: str = Field(default="", validation_alias="elementIcon", serialization_alias="elementIcon")
    traces: list[RoleTrace] = Field(default_factory=list)
    current_volume: int = Field(default=0, validation_alias="currentVolume", serialization_alias="currentVolume")
    sum_volume: int = Field(default=0, validation_alias="sumVolume", serialization_alias="sumVolume")
    level: int = 0
    icon: str = ""
    grade_level: int = Field(default=0, validation_alias="gradeLevel", serialization_alias="gradeLevel")
    element_name: str = Field(default="", validation_alias="elementName", serialization_alias="elementName")
    modes: list[Mode] = Field(default_factory=list)
    con_weapon_eid: str | None = Field(default=None, validation_alias="conWeaponEid", serialization_alias="conWeaponEid")
    con_weapon_id: int | None = Field(default=None, validation_alias="conWeaponId", serialization_alias="conWeaponId")

    @property
    def charId(self) -> int:
        return self.char_id

    @property
    def charName(self) -> str:
        return self.char_name

    @property
    def gradeLevel(self) -> int:
        return self.grade_level

    @property
    def elementName(self) -> str:
        return self.element_name

    @property
    def elementIcon(self) -> str:
        return self.element_icon

    @property
    def currentVolume(self) -> int:
        return self.current_volume

    @property
    def sumVolume(self) -> int:
        return self.sum_volume


class WeaponAttribute(_PlayerModel):
    """武器面板属性。"""

    atk: int = 0
    crd: float = 0
    cri: float = 0
    speed: float = 0
    trigger: float = 0


class WeaponDetail(_PlayerModel):
    """武器详情 API 的完整合法字段。"""

    attribute: WeaponAttribute
    current_volume: int = Field(default=0, validation_alias="currentVolume", serialization_alias="currentVolume")
    element_icon: str = Field(default="", validation_alias="elementIcon", serialization_alias="elementIcon")
    element_name: str = Field(default="", validation_alias="elementName", serialization_alias="elementName")
    icon: str = ""
    weapon_id: int = Field(validation_alias="id", serialization_alias="id")
    level: int = 0
    modes: list[Mode] = Field(default_factory=list)
    name: str
    skill_level: int = Field(default=0, validation_alias="skillLevel", serialization_alias="skillLevel")
    sum_volume: int = Field(default=0, validation_alias="sumVolume", serialization_alias="sumVolume")

    @property
    def id(self) -> int:
        return self.weapon_id

    @property
    def elementName(self) -> str:
        return self.element_name

    @property
    def elementIcon(self) -> str:
        return self.element_icon

    @property
    def currentVolume(self) -> int:
        return self.current_volume

    @property
    def sumVolume(self) -> int:
        return self.sum_volume

    @property
    def skillLevel(self) -> int:
        return self.skill_level


class AttributeBag(_PlayerModel):
    """伤害接口属性袋；extra=allow 保留服务端新增属性。"""

    model_config = ConfigDict(extra="allow", populate_by_name=True)

    empty: bool | None = None
    atk: float | None = None
    atk1: float | None = None
    defense: float | None = Field(default=None, validation_alias="def", serialization_alias="def")
    hp: float | None = None
    es: float | None = None
    sp: float | None = None
    se: float | None = None
    si: float | None = None
    sr: float | None = None
    ss: float | None = None
    sv: float | None = None
    ev: float | None = None
    cri: float | None = None
    crd: float | None = None
    tr: float | None = None


class SkillAttribute(_PlayerModel):
    """伤害技能属性；value 可以是服务端数字或格式化字符串。"""

    key: str
    value: str | int | float | None = None
    environment_value: str | int | float | None = Field(
        default=None,
        validation_alias="environmentValue",
        serialization_alias="environmentValue",
    )


class DamageSkill(_PlayerModel):
    """单个技能及其全部普通/伤害属性。"""

    id: int
    name: str
    parent_id: int | None = Field(default=None, validation_alias="parentId", serialization_alias="parentId")
    normal_skill_attributes: list[SkillAttribute] = Field(
        default_factory=list,
        validation_alias="normalSkillAttributes",
        serialization_alias="normalSkillAttributes",
    )
    damage_skill_attributes: list[SkillAttribute] = Field(
        default_factory=list,
        validation_alias="damageSkillAttributes",
        serialization_alias="damageSkillAttributes",
    )


class DamageValues(_PlayerModel):
    """三类武器伤害和环境后的伤害。"""

    close_weapon_damage: str | None = Field(default=None, validation_alias="closeWeaponDamage", serialization_alias="closeWeaponDamage")
    con_weapon_damage: str | None = Field(default=None, validation_alias="conWeaponDamage", serialization_alias="conWeaponDamage")
    ranged_weapon_damage: str | None = Field(
        default=None,
        validation_alias="langRangeWeaponDamage",
        serialization_alias="langRangeWeaponDamage",
    )
    close_weapon_damage_with_environment: str | None = Field(
        default=None,
        validation_alias="closeWeaponDamageWithEnvironment",
        serialization_alias="closeWeaponDamageWithEnvironment",
    )
    con_weapon_damage_with_environment: str | None = Field(
        default=None,
        validation_alias="conWeaponDamageWithEnvironment",
        serialization_alias="conWeaponDamageWithEnvironment",
    )
    ranged_weapon_damage_with_environment: str | None = Field(
        default=None,
        validation_alias="langRangeWeaponDamageWithEnvironment",
        serialization_alias="langRangeWeaponDamageWithEnvironment",
    )


class DamageSnapshot(_PlayerModel):
    """伤害计算成功返回的完整数据。"""

    skills: list[DamageSkill] = Field(default_factory=list)
    damage: DamageValues
    final_attribute: AttributeBag = Field(validation_alias="finalAttribute", serialization_alias="finalAttribute")
    base_attribute: AttributeBag = Field(validation_alias="baseAttribute", serialization_alias="baseAttribute")


@dataclass(frozen=True, slots=True)
class DamageCalculation:
    """伤害计算的成功或可渲染失败结果。"""

    data: DamageSnapshot | None = None
    message: str | None = None

    def __post_init__(self) -> None:
        if self.data is None and not self.message:
            raise ValueError("伤害计算失败结果必须包含 message")
        if self.data is not None and self.message is not None:
            raise ValueError("伤害计算成功结果不得同时包含 message")

    @classmethod
    def success(cls, data: DamageSnapshot) -> DamageCalculation:
        return cls(data=data)

    @classmethod
    def failure(cls, message: str) -> DamageCalculation:
        return cls(message=message)


@dataclass(frozen=True, slots=True)
class PlayerCommandRequest:
    """玩家命令的框架无关输入。"""

    actor: EventActor
    target_user_id: str | None
    parameters: dict[str, Any] = field(default_factory=dict)
    reply_id: str | None = None


class PlayerTransport(Protocol):
    """玩家 use case 所需的最小读取 transport。"""

    async def get_overview(
        self,
        actor: EventActor,
        uid: str,
        *,
        credential_user_id: str,
    ) -> RoleOverview:
        """读取当前 UID 的角色/武器展柜。"""
        ...

    async def get_role_detail(
        self,
        actor: EventActor,
        uid: str,
        char_id: int,
        char_eid: str,
        *,
        credential_user_id: str,
    ) -> RoleDetail:
        """读取一个已拥有角色的详情。"""
        ...

    async def get_weapon_detail(
        self,
        actor: EventActor,
        uid: str,
        weapon_id: int,
        weapon_eid: str,
        *,
        credential_user_id: str,
    ) -> WeaponDetail:
        """读取一个已拥有武器的详情。"""
        ...

    async def calculate_damage(
        self,
        actor: EventActor,
        uid: str,
        role_detail: RoleDetail,
        con_weapon: WeaponDetail | None,
        close_weapon: WeaponDetail | None,
        ranged_weapon: WeaponDetail | None,
        *,
        credential_user_id: str,
    ) -> DamageCalculation:
        """读取伤害配置并计算当前角色方案。"""
        ...


__all__ = [
    "AttributeBag",
    "DamageCalculation",
    "DamageSkill",
    "DamageSnapshot",
    "DamageValues",
    "Mode",
    "PlayerCommandRequest",
    "PlayerFailureKind",
    "PlayerTransport",
    "PlayerTransportError",
    "RoleAttribute",
    "RoleDetail",
    "RoleItem",
    "RoleOverview",
    "RoleSkill",
    "RoleTrace",
    "SkillAttribute",
    "WeaponAttribute",
    "WeaponDetail",
    "WeaponItem",
]
