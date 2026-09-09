"""Registry-driven 客户端更新 Source 只读 smoke 检查。"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import (
    ClientUpdateFailureKind,
    ClientUpdateTransport,
    ClientUpdateTransportError,
)
from .registry import (
    CLIENT_UPDATE_REGISTRY,
    ClientUpdateProviderKind,
    ClientUpdateRegistry,
)


@dataclass(frozen=True, slots=True)
class ClientUpdateSmokeResult:
    """一个 Source 的安全 smoke 结果，不携带 URL 或响应正文。"""

    source_id: str
    provider_kind: ClientUpdateProviderKind
    revision_id: str | None = None
    version_text: str | None = None
    failure_kind: ClientUpdateFailureKind | None = None
    resource: str | None = None
    status_code: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.source_id, str) or not self.source_id.strip():
            raise ValueError("source_id 必须是非空字符串")
        object.__setattr__(
            self,
            "provider_kind",
            ClientUpdateProviderKind(self.provider_kind),
        )
        succeeded = self.failure_kind is None
        if succeeded:
            if not isinstance(self.revision_id, str) or not self.revision_id.strip():
                raise ValueError("成功结果必须包含 revision_id")
            if not isinstance(self.version_text, str) or not self.version_text.strip():
                raise ValueError("成功结果必须包含 version_text")
            if self.resource is not None or self.status_code is not None:
                raise ValueError("成功结果不能包含失败字段")
            return

        object.__setattr__(
            self,
            "failure_kind",
            ClientUpdateFailureKind(self.failure_kind),
        )
        if not isinstance(self.resource, str) or not self.resource.strip():
            raise ValueError("失败结果必须包含 resource")
        if self.revision_id is not None or self.version_text is not None:
            raise ValueError("失败结果不能包含版本字段")
        if self.status_code is not None and type(self.status_code) is not int:
            raise TypeError("status_code 必须是整数或 None")

    @property
    def succeeded(self) -> bool:
        """是否成功读取该 Source。"""

        return self.failure_kind is None


async def run_client_update_source_smoke(
    transport: ClientUpdateTransport,
    *,
    registry: ClientUpdateRegistry = CLIENT_UPDATE_REGISTRY,
) -> tuple[ClientUpdateSmokeResult, ...]:
    """逐个检查 registry Source；不传 baseline，避免读取补丁清单。"""

    results: list[ClientUpdateSmokeResult] = []
    for source in registry.sources:
        try:
            observation = await transport.get_observation(source.source_id)
        except ClientUpdateTransportError as error:
            results.append(
                ClientUpdateSmokeResult(
                    source_id=source.source_id,
                    provider_kind=source.provider_kind,
                    failure_kind=error.kind,
                    resource=error.resource,
                    status_code=error.status_code,
                )
            )
            continue

        results.append(
            ClientUpdateSmokeResult(
                source_id=source.source_id,
                provider_kind=source.provider_kind,
                revision_id=observation.current.revision_id,
                version_text=observation.current.version_text,
            )
        )
    return tuple(results)


def format_client_update_smoke_result(result: ClientUpdateSmokeResult) -> str:
    """格式化为仅含 registry ID、分类和版本的安全单行文本。"""

    if result.succeeded:
        return (
            f"OK source={result.source_id} provider={result.provider_kind.value} "
            f"revision={result.revision_id} version={result.version_text}"
        )
    status = "none" if result.status_code is None else str(result.status_code)
    return (
        f"FAIL source={result.source_id} provider={result.provider_kind.value} "
        f"kind={result.failure_kind.value} resource={result.resource} status={status}"
    )


__all__ = [
    "ClientUpdateSmokeResult",
    "format_client_update_smoke_result",
    "run_client_update_source_smoke",
]
