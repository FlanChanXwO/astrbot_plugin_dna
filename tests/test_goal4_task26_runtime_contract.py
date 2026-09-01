"""Goal 4 / Task 26：真实 Dashboard 目标管理契约回归。"""

from pathlib import Path

from src.infrastructure.subscriptions import Subscription
from src.modules.admin import TaskTarget
from src.modules.notices import messages


ROOT = Path(__file__).resolve().parents[1]


def test_only_verified_announcement_targets_are_dashboard_managed() -> None:
    announcement = TaskTarget.from_subscription(
        Subscription(
            type=messages.ANN_SUBSCRIBE,
            unified_msg_origin="default:GroupMessage:probe",
            group_id="probe",
            bot_id="bot",
            provenance="chat_command",
        )
    )
    unrelated = TaskTarget.from_subscription(
        Subscription(
            type="other_subscription",
            unified_msg_origin="default:GroupMessage:probe",
            group_id="probe",
            bot_id="bot",
            provenance="chat_command",
        )
    )

    assert announcement.managed is True
    assert announcement.to_dict()["type"] == messages.ANN_SUBSCRIBE
    assert unrelated.managed is False


def test_dashboard_uses_backend_managed_flag_instead_of_stale_type_literal() -> None:
    html = (ROOT / "pages" / "dashboard" / "index.html").read_text(encoding="utf-8")

    assert 'v-if="target.managed" class="target-actions"' in html
    assert "target.subscription_type === 'ann_subscribe'" not in html


def test_partial_target_mutation_survives_astrbot_bridge_data_unwrap() -> None:
    import json

    from src.entry.admin_web import _response
    from src.modules.admin import AdminApiResponse, AdminError, AdminErrorCode

    target = TaskTarget.from_subscription(
        Subscription(
            type=messages.ANN_SUBSCRIBE,
            unified_msg_origin="default:GroupMessage:probe",
            group_id="probe",
            bot_id="bot",
            enabled=False,
            provenance="chat_command",
        )
    )
    response = _response(
        AdminApiResponse(
            ok=False,
            data=target,
            error=AdminError(AdminErrorCode.PARTIAL, "internal detail"),
        )
    )
    payload = json.loads(response.body)

    assert response.status_code == 207
    assert payload["data"]["operation_error"] == {
        "code": "partial",
        "message": "操作部分完成，请核对结果后重试",
    }

    bridge = (ROOT / "pages" / "dashboard" / "js" / "bridge.js").read_text(
        encoding="utf-8"
    )
    assert "operation_error" in bridge
