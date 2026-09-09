"""旧版运行期数据布局检测与启动门禁。"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from .data_layout import RuntimeDataLayout

_LEGACY_LAYOUT_MARKERS: tuple[tuple[str, str], ...] = (
    ("dnaby.sqlite3", "旧数据库文件"),
    ("dnaby.db", "旧数据库文件"),
    ("resource", "旧动态资源目录"),
    ("resource_generations", "旧资源 generation 目录"),
    ("rendered", "旧渲染产物目录"),
    ("other", "旧媒体目录"),
    ("custom", "旧自定义素材目录"),
    ("players", "旧玩家数据目录"),
    ("subscriptions.json", "旧订阅状态文件"),
    ("scheduler_state.json", "旧调度状态文件"),
    ("ann_state.json", "旧公告状态文件"),
    ("ann_delivery_state.json", "旧公告投递状态文件"),
    ("client_update_state.json", "旧客户端更新状态文件"),
    ("alias_custom.json", "旧角色别名文件"),
    ("weapon_alias_custom.json", "旧武器别名文件"),
    ("config.json", "旧配置文件"),
    ("sign_config.json", "旧签到配置文件"),
    ("resources/.git", "旧公共资源仓库位置"),
    ("cache/player_data", "旧玩家数据缓存目录"),
    ("cache/player_card", "旧玩家卡缓存目录"),
    ("cache/mh", "旧密函缓存目录"),
    ("cache/announcement", "旧公告缓存目录"),
)


def _path_exists(path: Path) -> bool:
    """判断路径是否存在，包含断开的符号链接。"""

    return path.is_symlink() or path.exists()


def _contains_legacy_data(path: Path) -> bool:
    """判断旧目录是否包含实际数据，而不是导入副作用留下的空目录。"""

    if path.is_symlink() or path.is_file():
        return True
    if path.is_dir():
        return any(_contains_legacy_data(child) for child in path.iterdir())
    return _path_exists(path)


@dataclass(frozen=True, slots=True)
class LegacyLayoutIssue:
    """一个需要人工迁移或清理的旧布局标记。"""

    relative_path: str
    description: str


class LegacyLayoutError(RuntimeError):
    """启动前发现旧运行期布局时抛出的明确错误。"""

    def __init__(self, issues: Iterable[LegacyLayoutIssue]) -> None:
        self.issues = tuple(issues)
        if not self.issues:
            raise ValueError("旧布局错误至少需要一个问题")
        details = "、".join(
            f"{issue.relative_path}（{issue.description}）" for issue in self.issues
        )
        super().__init__(
            "检测到旧版运行期数据布局："
            f"{details}。请先按迁移文档人工迁移或清理后再启动插件；"
            "插件不会自动复制、移动或双读旧数据。"
        )


class LegacyLayoutDetector:
    """只读检测旧运行期目录，不执行复制、移动或双读。"""

    def __init__(self, layout: RuntimeDataLayout | str | Path) -> None:
        self.layout = (
            layout
            if isinstance(layout, RuntimeDataLayout)
            else RuntimeDataLayout.from_data_dir(layout)
        )

    def detect(self) -> tuple[LegacyLayoutIssue, ...]:
        """返回按稳定顺序发现的旧布局标记。"""

        issues: list[LegacyLayoutIssue] = []
        for relative_path, description in _LEGACY_LAYOUT_MARKERS:
            marker = self.layout.data_dir / relative_path
            # ``resources/.git`` 本身就是旧仓库位置；其他目录只有包含实际
            # 数据时才阻断，避免旧版导入期 mkdir 造成新安装误报。
            found = (
                _path_exists(marker)
                if relative_path == "resources/.git"
                else _contains_legacy_data(marker)
            )
            if found:
                issues.append(LegacyLayoutIssue(relative_path, description))
        return tuple(issues)

    def ensure_compatible(self) -> None:
        """旧布局存在时终止启动，并保留原始数据不变。"""

        issues = self.detect()
        if issues:
            raise LegacyLayoutError(issues)


def ensure_no_legacy_layout(layout: RuntimeDataLayout | str | Path) -> None:
    """校验运行期数据根可用于新布局。"""

    LegacyLayoutDetector(layout).ensure_compatible()


__all__ = [
    "LegacyLayoutDetector",
    "LegacyLayoutError",
    "LegacyLayoutIssue",
    "ensure_no_legacy_layout",
]
