"""角色伤害计算区块的 HTML payload 构建。"""

from __future__ import annotations

from ...modules.player.damage_service import (
    RoleDamageBuild,
    get_calculation_skill_levels,
)
from ...utils.api.damage_model import (
    AttributeBag,
    CharacterCalculateData,
    RestraintType,
    SkillResult,
)
from ...utils.api.request_util import DNAApiResp


def _format_number(value: float, *, percent: bool) -> str:
    number = float(value)
    text = f"{int(number):,}" if number.is_integer() else f"{number:,.2f}".rstrip("0").rstrip(".")
    return f"{text}%" if percent else text


def _format_metric(
    base_value: float | None,
    final_value: float | None,
    *,
    percent: bool,
) -> str | None:
    if base_value is None and final_value is None:
        return None
    if final_value is None:
        if base_value is None:
            raise RuntimeError("属性值同时为空")
        return _format_number(base_value, percent=percent)
    final_text = _format_number(final_value, percent=percent)
    if base_value is None or base_value == final_value:
        return final_text
    return f"{_format_number(base_value, percent=percent)} → {final_text}"


def _build_attribute_metrics(base: AttributeBag, final: AttributeBag) -> list[dict[str, str]]:
    specs = (
        ("攻击", base.atk, final.atk, False),
        ("生命", base.hp, final.hp, False),
        ("护盾", base.es, final.es, False),
        ("防御", base.def_, final.def_, False),
        ("最大神志", base.sp, final.sp, False),
        ("技能威力", base.si, final.si, True),
        ("技能范围", base.sr, final.sr, True),
        ("技能耐久", base.ss, final.ss, True),
        ("技能效益", base.se, final.se, True),
        ("昂扬", base.sv, final.sv, True),
        ("背水", base.ev, final.ev, True),
    )
    metrics: list[dict[str, str]] = []
    for label, base_value, final_value, percent in specs:
        value = _format_metric(base_value, final_value, percent=percent)
        if value is not None:
            metrics.append({"label": label, "value": value})
    return metrics


def _format_skill_value(value: object | None, environment_value: object | None) -> str:
    base_text = "—" if value is None else str(value)
    if environment_value is None or environment_value == value:
        return base_text
    return f"{base_text} → {environment_value}"


def _skill_metrics(skill: SkillResult) -> list[dict[str, str]]:
    attributes = skill.normal_skill_attributes + skill.damage_skill_attributes
    if not attributes:
        return [{"label": "技能参数", "value": "暂无"}]
    return [
        {
            "label": attribute.key,
            "value": _format_skill_value(attribute.value, attribute.environment_value),
        }
        for attribute in attributes
    ]


def _lineup(build: RoleDamageBuild) -> list[dict[str, str]]:
    char_name = getattr(build.role_detail, "charName", getattr(build.role_detail, "char_name", ""))
    result = [{"label": "角色", "name": char_name}]
    for label, weapon in (
        ("近战", build.close_weapon_detail),
        ("远程", build.lang_range_weapon_detail),
        ("同律", build.con_weapon_detail),
    ):
        if weapon is not None:
            result.append({"label": label, "name": weapon.name})
    result.extend({"label": "协战", "name": companion.name} for companion in build.companions)
    return result


def _enemy_text(build: RoleDamageBuild) -> str:
    if build.enemy_config_id == 59:
        return "剧目-无尽 · 第31轮"
    return f"敌人配置 {build.enemy_config_id}"


def _restraint_text(build: RoleDamageBuild) -> str:
    return {
        RestraintType.UNRESTRAINED: "非克制",
        RestraintType.NONE: "无克制",
        RestraintType.RESTRAINED: "克制",
    }[build.restraint_type]


def _weapon_value(damage: str, environment_damage: str | None) -> str:
    if environment_damage is None or environment_damage == damage:
        return damage
    return f"{damage} → {environment_damage}"


def _weapon_metrics(
    build: RoleDamageBuild,
    calculation: CharacterCalculateData,
) -> list[dict[str, str]]:
    damage = calculation.damage
    specs = (
        (
            "近战",
            build.close_weapon_detail,
            damage.close_weapon_damage,
            damage.close_weapon_damage_with_environment,
        ),
        (
            "远程",
            build.lang_range_weapon_detail,
            damage.lang_range_weapon_damage,
            damage.lang_range_weapon_damage_with_environment,
        ),
        (
            "同律",
            build.con_weapon_detail,
            damage.con_weapon_damage,
            damage.con_weapon_damage_with_environment,
        ),
    )
    return [
        {
            "label": label,
            "name": f"{label}武器" if weapon is None else weapon.name,
            "value": _weapon_value(value, environment_value),
        }
        for label, weapon, value, environment_value in specs
        if value is not None
    ]


def _skill_panels(build: RoleDamageBuild, skills: list[SkillResult]) -> list[dict[str, object]]:
    skills_by_id = {skill.id: skill for skill in skills}
    children_by_parent: dict[int, list[SkillResult]] = {skill.id: [] for skill in skills}
    roots: list[SkillResult] = []
    for skill in skills:
        if skill.parent_id is None:
            roots.append(skill)
        elif skill.parent_id not in skills_by_id:
            raise RuntimeError(f"派生技能 {skill.id} 缺少父技能 {skill.parent_id}")
        else:
            children_by_parent[skill.parent_id].append(skill)

    levels = get_calculation_skill_levels(build.role_detail, tuple(skill.id for skill in roots))
    panels: list[dict[str, object]] = []
    for skill in roots:
        if skill.id not in levels:
            raise RuntimeError(f"主技能 {skill.id} 缺少角色技能等级")
        panels.append(
            {
                "children": [
                    {"metrics": _skill_metrics(child), "name": child.name}
                    for child in children_by_parent[skill.id]
                ],
                "level": levels[skill.id],
                "metrics": _skill_metrics(skill),
                "name": skill.name,
            }
        )
    return panels


def _success_payload(
    build: RoleDamageBuild,
    calculation: CharacterCalculateData,
) -> dict[str, object]:
    element_name = getattr(build.role_detail, "elementName", getattr(build.role_detail, "element_name", ""))
    return {
        "attributes": _build_attribute_metrics(
            calculation.base_attribute,
            calculation.final_attribute,
        ),
        "element": element_name,
        "enemy": _enemy_text(build),
        "error": None,
        "lineup": _lineup(build),
        "restraint": _restraint_text(build),
        "skills": _skill_panels(build, calculation.skills),
        "weapons": _weapon_metrics(build, calculation),
        "width": 900,
    }


def draw_role_damage_section(
    build: RoleDamageBuild,
    response: DNAApiResp[CharacterCalculateData],
) -> dict[str, object]:
    """保留旧函数名，返回完整伤害面板 payload，不生成中间 PIL 图。"""

    element_name = getattr(build.role_detail, "elementName", getattr(build.role_detail, "element_name", ""))
    if not response.is_success:
        return {
            "attributes": [],
            "element": element_name,
            "enemy": _enemy_text(build),
            "error": response.msg,
            "lineup": _lineup(build),
            "restraint": _restraint_text(build),
            "skills": [],
            "weapons": [],
            "width": 900,
        }
    if response.data is None:
        raise RuntimeError("伤害计算成功响应缺少 data")
    return _success_payload(build, response.data)
