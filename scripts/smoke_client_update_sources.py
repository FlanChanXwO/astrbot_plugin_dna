"""只读检查客户端更新 registry 中的全部 Source。"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))


async def _main() -> int:
    """执行网络 smoke，并以失败 Source 数量决定退出码。"""

    from src.infrastructure.http.client_updates import ClientUpdateTransport
    from src.modules.client_updates import (
        format_client_update_smoke_result,
        run_client_update_source_smoke,
    )

    results = await run_client_update_source_smoke(ClientUpdateTransport())
    for result in results:
        print(format_client_update_smoke_result(result))
    return 0 if all(result.succeeded for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
