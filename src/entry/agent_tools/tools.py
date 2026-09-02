"""AstrBot Agent Tools 的只读查询适配器。"""

from __future__ import annotations

import inspect
import json
from collections.abc import Mapping, Sequence
from dataclasses import fields, is_dataclass
from datetime import date, datetime
from enum import Enum
from pathlib import Path
from typing import Any

from astrbot.api import logger
from astrbot.api.message_components import Image as AstrImage
from astrbot.api.message_components import Plain as AstrPlain
from astrbot.core.agent.run_context import ContextWrapper
from astrbot.core.agent.tool import FunctionTool
from astrbot.core.astr_agent_context import AstrAgentContext
from astrbot.core.message.message_event_result import MessageChain

from ...modules.agent_tools.contracts import AgentQueryResult
from ...modules.agent_tools.queries import AgentQueryCatalog, build_query_catalog
from ..response import (
    ChainResponse,
    ImageResponse,
    MultiImageResponse,
    PlainTextResponse,
)
from .context import agent_request_from_context


def _object_schema(
    properties: Mapping[str, object] | None = None,
    *,
    required: Sequence[str] = (),
) -> dict[str, Any]:
    schema: dict[str, Any] = {
        "type": "object",
        "properties": dict(properties or {}),
        "additionalProperties": False,
    }
    if required:
        schema["required"] = list(required)
    return schema


def _image_properties() -> dict[str, Any]:
    return {
        "send_image": {
            "type": "boolean",
            "default": False,
            "description": "是否将查询生成的图片直接发送给当前消息用户；默认不发送。",
        }
    }


def _image_schema(
    properties: Mapping[str, object] | None = None,
    *,
    required: Sequence[str] = (),
) -> dict[str, Any]:
    merged = dict(properties or {})
    merged.update(_image_properties())
    return _object_schema(merged, required=required)


def _json_value(value: object) -> object:
    """将非消息 DTO 转为安全 JSON 值；路径和二进制不会被隐式暴露。"""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (Path, bytes, bytearray, memoryview)):
        raise TypeError("Agent 返回值包含不允许序列化的本地数据")
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Enum):
        return _json_value(value.value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        # 保留 Path/bytes 的 Python 类型，交给上面的安全分支拒绝，避免
        # Pydantic 的 JSON mode 先把敏感本地数据隐式转换成字符串。
        return _json_value(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        converted = to_dict()
        if not isinstance(converted, Mapping):
            raise TypeError("Agent 返回值 to_dict 必须返回映射")
        return _json_value(converted)
    if is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: _json_value(getattr(value, field.name))
            for field in fields(value)
        }
    raise TypeError(f"Agent 返回值类型不可序列化: {type(value).__name__}")


def _response_data(response: object) -> object:
    """把框架无关响应转换为不含本地路径的 Agent data。"""

    if isinstance(response, PlainTextResponse):
        return {"type": "text", "text": response.text}
    if isinstance(response, ImageResponse):
        image_available = Path(str(response.image)).is_file()
        return {
            "type": "image",
            "available": image_available,
            "incomplete": response.incomplete,
        }
    if isinstance(response, MultiImageResponse):
        return {
            "type": "images",
            "count": len(response.images),
            "items": [_response_data(image) for image in response.images],
        }
    if isinstance(response, ChainResponse):
        return {
            "type": "chain",
            "items": [_response_data(item) for item in response.components],
        }
    return _json_value(response)


def _result_json(result: AgentQueryResult[Any]) -> str:
    payload = result.to_dict()
    payload["data"] = _response_data(result.data)
    return json.dumps(payload, ensure_ascii=False)


def _response_components(response: object) -> tuple[list[Any], bool]:
    """将响应转成直接发送的消息链，并报告是否含图片。"""

    if isinstance(response, PlainTextResponse):
        return [AstrPlain(response.text)], False
    if isinstance(response, ImageResponse):
        if not Path(str(response.image)).is_file():
            raise ValueError("图片文件不可用")
        return [AstrImage.fromFileSystem(str(response.image))], True
    if isinstance(response, MultiImageResponse):
        components: list[Any] = []
        has_image = False
        for image in response.images:
            nested, nested_has_image = _response_components(image)
            components.extend(nested)
            has_image = has_image or nested_has_image
        return components, has_image
    if isinstance(response, ChainResponse):
        components = []
        has_image = False
        for item in response.components:
            if isinstance(item, (PlainTextResponse, ImageResponse, MultiImageResponse, ChainResponse)):
                nested, nested_has_image = _response_components(item)
                components.extend(nested)
                has_image = has_image or nested_has_image
            else:
                components.append(item)
        return components, has_image
    raise TypeError(f"Agent 图片发送不支持响应类型: {type(response).__name__}")


async def _send_image_response(event: Any, response: object) -> tuple[bool, str]:
    try:
        components, has_image = _response_components(response)
    except (OSError, TypeError, ValueError) as error:
        logger.warning(
            "[dnaby][agent_tools] 图片响应转换失败: %s",
            type(error).__name__,
        )
        return False, "图片响应不可发送"
    if not has_image:
        return False, "查询结果不包含可发送图片"
    send = getattr(event, "send", None)
    if not callable(send):
        return False, "当前事件不支持直接发送图片"
    try:
        result = send(MessageChain(chain=components, type="tool_direct_result"))
        if inspect.isawaitable(result):
            await result
    except Exception as error:  # noqa: BLE001
        logger.warning(
            "[dnaby][agent_tools] 图片发送失败: %s",
            type(error).__name__,
        )
        return False, "图片发送失败"
    return True, ""


class AgentQueryTool(FunctionTool):
    """使用官方 ``FunctionTool.call`` 获得 ``AstrAgentContext.event`` 的工具。"""

    def __init__(
        self,
        *,
        name: str,
        query_name: str,
        description: str,
        parameters: dict[str, Any],
        catalog: AgentQueryCatalog,
        supports_image: bool = False,
        plugin_context: object | None = None,
    ) -> None:
        super().__init__(
            name=name,
            description=description,
            parameters=parameters,
            handler=None,
        )
        self.query_name = query_name
        self.catalog = catalog
        self.supports_image = supports_image
        self.allowed_parameters = frozenset(
            key for key in parameters.get("properties", {}) if key != "send_image"
        )
        if plugin_context is not None:
            module_path = getattr(plugin_context, "__module__", None)
            if isinstance(module_path, str) and module_path:
                self.handler_module_path = module_path

    async def call(
        self,
        context: ContextWrapper[AstrAgentContext],
        **kwargs: Any,
    ) -> str:
        raw_send_image = kwargs.pop("send_image", False)
        if not isinstance(raw_send_image, bool):
            return _result_json(
                AgentQueryResult.failure(
                    kind=self.query_name,
                    error="send_image 必须是 bool",
                )
            )

        try:
            request = agent_request_from_context(context, parameters=kwargs)
        except (TypeError, ValueError) as error:
            logger.warning(
                "[dnaby][agent_tools] 查询请求被拒绝: %s",
                type(error).__name__,
            )
            return _result_json(
                AgentQueryResult.failure(
                    kind=self.query_name,
                    error=str(error),
                )
            )
        unexpected = set(request.parameters) - self.allowed_parameters
        if unexpected:
            names = ", ".join(sorted(unexpected))
            return _result_json(
                AgentQueryResult.failure(
                    kind=self.query_name,
                    error=f"不支持的工具参数: {names}",
                )
            )
        if raw_send_image and not self.supports_image:
            return _result_json(
                AgentQueryResult.failure(
                    kind=self.query_name,
                    error="该工具不支持 send_image",
                )
            )

        try:
            result = await self.catalog.execute(self.query_name, request)
        except Exception as error:  # noqa: BLE001
            # Agent 框架会把未处理异常和 traceback 回传给模型；这里只记录类型，
            # 对外保持固定 envelope，避免暴露本地路径、内部 URL 或实现细节。
            logger.warning(
                "[dnaby][agent_tools] 查询执行失败: %s (%s)",
                self.query_name,
                type(error).__name__,
            )
            return _result_json(
                AgentQueryResult.failure(
                    kind=self.query_name,
                    error="查询执行失败",
                )
            )
        if not raw_send_image or not result.ok:
            return _result_json(result)

        event = context.context.event
        sent, error = await _send_image_response(event, result.data)
        if not sent:
            return _result_json(
                AgentQueryResult.failure(
                    kind=result.kind,
                    data={"image_sent": False},
                    cache=result.cache,
                    error=error,
                )
            )
        return _result_json(
            AgentQueryResult.success(
                kind=result.kind,
                data={"image_sent": True},
                cache=result.cache,
            )
        )


class _ToolDefinition:
    __slots__ = ("description", "name", "parameters", "query_name", "supports_image")

    def __init__(
        self,
        name: str,
        query_name: str,
        description: str,
        parameters: dict[str, Any],
        *,
        supports_image: bool = False,
    ) -> None:
        self.name = name
        self.query_name = query_name
        self.description = description
        self.parameters = parameters
        self.supports_image = supports_image


_TOOL_DEFINITIONS = (
    _ToolDefinition(
        "dnaby_player_overview",
        "player_overview",
        "查询当前消息用户绑定 UID 的角色与武器概览。身份固定来自当前事件，不接受用户 ID 或 UID 参数。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_player_role_detail",
        "player_role_detail",
        "查询当前消息用户指定角色的基础详情与武器信息；先使用角色目录确认名称。",
        _image_schema(
            {
                "char_name": {"type": "string", "description": "角色名称"},
                "weapon_name_1": {"type": "string", "description": "可选近战或远程武器名称"},
                "weapon_name_2": {"type": "string", "description": "可选另一把武器名称"},
            },
            required=("char_name",),
        ),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_stamina",
        "stamina",
        "查询当前消息用户绑定 UID 的实时便笺和体力信息。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_weekly_report_current",
        "weekly_report_current",
        "查询当前消息用户绑定 UID 的本周资源获取周报。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_weekly_report_last",
        "weekly_report_last",
        "查询当前消息用户绑定 UID 的上周资源获取周报。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_calendar",
        "calendar",
        "查询二重螺旋活动日历；这是全局资料，不使用模型提供的身份参数。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_wiki",
        "wiki",
        "按角色、武器或魔之楔名称查询本地图鉴图片。",
        _image_schema(
            {"name": {"type": "string", "description": "图鉴名称"}},
            required=("name",),
        ),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_guide",
        "guide",
        "按角色名称查询攻略图片；名称不确定时先使用角色目录。",
        _image_schema(
            {"char_name": {"type": "string", "description": "角色名称"}},
            required=("char_name",),
        ),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_codes",
        "codes",
        "查询当前可用兑换码及其有效期。",
        _object_schema(),
    ),
    _ToolDefinition(
        "dnaby_role_directory",
        "role_directory",
        "查询全部角色或武器名称目录，供其它角色查询工具选择参数。",
        _object_schema(
            {
                "directory_type": {
                    "type": "string",
                    "enum": ["characters", "weapons"],
                    "default": "characters",
                    "description": "目录类型",
                }
            }
        ),
    ),
    _ToolDefinition(
        "dnaby_mh",
        "mh",
        "查询当前消息用户当前激活 UID 可见的本时段梦魇残声/密函。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_mh_list",
        "mh_list",
        "查询全部可识别的梦魇残声/密函委托名称。",
        _object_schema(),
    ),
    _ToolDefinition(
        "dnaby_mh_subscriptions",
        "mh_subscriptions",
        "查询当前消息用户在当前会话自己的密函订阅，不读取或修改他人订阅。",
        _object_schema(),
    ),
    _ToolDefinition(
        "dnaby_announcement_list",
        "announcement_list",
        "查询完整官方公告列表。需要图片预览时可设置 send_image=true。",
        _image_schema(),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_announcement_detail",
        "announcement_detail",
        "按公告列表中的 1-based index 查询官方公告详情和全部正文图片。",
        _image_schema(
            {"index": {"type": "integer", "minimum": 1, "description": "公告列表中的 1-based 序号"}},
            required=("index",),
        ),
        supports_image=True,
    ),
    _ToolDefinition(
        "dnaby_sign_calendar",
        "sign_calendar",
        "查询当前消息用户当前激活 UID 的签到日历和任务进度；不会执行签到。",
        _image_schema(),
        supports_image=True,
    ),
)

AGENT_TOOL_NAMES = tuple(definition.name for definition in _TOOL_DEFINITIONS)


def build_agent_tools(
    *,
    services: Mapping[str, object] | None = None,
    catalog: AgentQueryCatalog | None = None,
    plugin_context: object | None = None,
) -> list[FunctionTool]:
    """为已注入的领域 service 构造官方 FunctionTool 列表。"""

    if catalog is None:
        if services is None:
            raise TypeError("构造 Agent Tools 需要 services 或 catalog")
        catalog = build_query_catalog(
            player_service=services.get("player_service"),
            encyclopedia_service=services.get("encyclopedia_service"),
            notices_service=services.get("notices_service"),
            checkin_service=services.get("checkin_service"),
        )
    return [
        AgentQueryTool(
            name=definition.name,
            query_name=definition.query_name,
            description=definition.description,
            parameters=definition.parameters.copy(),
            catalog=catalog,
            supports_image=definition.supports_image,
            plugin_context=plugin_context,
        )
        for definition in _TOOL_DEFINITIONS
        if definition.query_name in catalog.names
    ]


def register_agent_tools(
    context: Any,
    *,
    services: Mapping[str, object] | None = None,
    catalog: AgentQueryCatalog | None = None,
    plugin_context: object | None = None,
) -> list[FunctionTool]:
    """通过 AstrBot 官方 Context API 注册已构造的只读工具。"""

    add_llm_tools = getattr(context, "add_llm_tools", None)
    if not callable(add_llm_tools):
        raise TypeError("Agent Tools 注册需要 AstrBot Context.add_llm_tools")
    tools = build_agent_tools(
        services=services,
        catalog=catalog,
        plugin_context=plugin_context,
    )
    add_llm_tools(*tools)
    return tools


__all__ = [
    "AGENT_TOOL_NAMES",
    "AgentQueryTool",
    "build_agent_tools",
    "register_agent_tools",
]
