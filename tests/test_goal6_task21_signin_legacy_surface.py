"""Goal 6 / T21：签到配置不再暴露旧全局运行接口。"""

from __future__ import annotations

from src.infrastructure.config.settings import DnabySettings


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
