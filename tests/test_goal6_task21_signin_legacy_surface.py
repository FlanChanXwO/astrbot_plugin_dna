"""Goal 6 / T21：签到配置不再暴露旧全局运行接口。"""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import pytest

from src.infrastructure.config.settings import DnabySettings
from src.infrastructure.scheduler import SignScheduler
from src.infrastructure.subscriptions import SubscriptionStore


class _CheckinProbe:
    def __init__(self) -> None:
        self.auto_sign_calls = 0

    async def auto_sign_all(self) -> str:
        self.auto_sign_calls += 1
        return "auto-sign"

    async def clear_sign_records_before(self, _record_date: date) -> int:
        return 0


async def _wait_forever(_seconds: float) -> None:
    await asyncio.Event().wait()


def test_sign_in_migration_keeps_only_the_new_runtime_surface() -> None:
    """旧输入仍需迁移，但 typed model 不得继续暴露旧全局开关。"""

    settings = DnabySettings.from_config(
        {
            "sign_in": {
                "enable_all_users": False,
                "scheduled_enabled": False,
            }
        }
    )

    assert settings.sign_in.default_auto_sign_enabled is False
    assert "enable_all_users" not in settings.sign_in.model_dump()
    assert "scheduled_enabled" not in settings.sign_in.model_dump()
    assert not hasattr(settings.sign_in, "enable_all_users")
    assert not hasattr(settings.sign_in, "scheduled_enabled")


@pytest.mark.asyncio
async def test_legacy_scheduled_disabled_does_not_start_auto_sign_task(
    tmp_path: Path,
) -> None:
    """旧配置关闭定时签到时，已有开启自动签到的 UID 也不得被调度。"""

    settings = DnabySettings.from_config(
        {
            "sign_in": {
                "scheduled_enabled": False,
                # 模拟已有绑定仍保留 auto_sign_enabled=True 的升级场景。
                "default_auto_sign_enabled": True,
            }
        }
    )
    checkin = _CheckinProbe()
    scheduler = SignScheduler(
        checkin,
        SubscriptionStore(tmp_path / "subscriptions.json"),
        sign_task_enabled=settings.sign_in.scheduler_enabled_for_runtime,
        sleep=_wait_forever,
    )

    await scheduler.start()
    await asyncio.sleep(0)

    assert [task.get_name() for task in scheduler._tasks] == ["dnaby_sign_cleanup"]
    assert checkin.auto_sign_calls == 0
    await scheduler.stop()
