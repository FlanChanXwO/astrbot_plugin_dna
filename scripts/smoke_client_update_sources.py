"""只读检查客户端更新 registry 中的全部 Source。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.modules.client_updates import ClientUpdateRegistry, ClientUpdateTransport

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _ensure_project_root() -> None:
    """让直接执行脚本时也能导入插件源码。"""

    project_root = str(PROJECT_ROOT)
    if project_root not in sys.path:
        sys.path.insert(0, project_root)


async def _run_smoke(
    transport: ClientUpdateTransport,
    *,
    registry: ClientUpdateRegistry | None = None,
) -> bool:
    """逐个检查 registry Source，并输出不含敏感内容的单行结果。"""

    _ensure_project_root()
    from src.modules.client_updates import (
        CLIENT_UPDATE_REGISTRY,
        ClientUpdateTransportError,
    )

    if registry is None:
        registry = CLIENT_UPDATE_REGISTRY
    passed = True
    for source in registry.sources:
        targets = ",".join(
            target.target_id
            for target in registry.targets
            if target.source_id == source.source_id
        )
        try:
            observation = await transport.get_observation(source.source_id)
        except ClientUpdateTransportError as error:
            passed = False
            status = "none" if error.status_code is None else str(error.status_code)
            print(
                f"FAIL source={source.source_id} provider={source.provider_kind.value} "
                f"targets={targets} kind={error.kind.value} "
                f"resource={error.resource} status={status}"
            )
        else:
            version = observation.current.version_text
            print(
                f"OK source={source.source_id} provider={source.provider_kind.value} "
                f"targets={targets} revision={observation.current.revision_id} "
                f"version={version if version is not None else 'none'}"
            )
    return passed


async def _main() -> int:
    """执行网络 smoke，并以失败 Source 数量决定退出码。"""

    _ensure_project_root()
    from src.infrastructure.http.client_updates import (
        ClientUpdateTransport as HttpClientUpdateTransport,
    )

    passed = await _run_smoke(HttpClientUpdateTransport())
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
