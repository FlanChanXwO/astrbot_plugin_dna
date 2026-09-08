"""插件版本的唯一读取入口。"""

from __future__ import annotations

from pathlib import Path

_METADATA_PATH = Path(__file__).resolve().parents[1] / "metadata.yaml"


def get_plugin_version() -> str:
    """从插件 metadata 读取展示版本，避免模板和 handler 各自硬编码。"""

    for line in _METADATA_PATH.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition(":")
        if separator and key.strip() == "version":
            version = value.strip().strip("\"'")
            if version:
                return version
            break
    raise ValueError(f"metadata.yaml 缺少有效 version: {_METADATA_PATH}")


PLUGIN_VERSION = get_plugin_version()
# legacy 纯逻辑仍使用不带 v 的版本名；值由 metadata 派生，不能单独修改。
DNA_version = PLUGIN_VERSION.removeprefix("v")


__all__ = ["PLUGIN_VERSION", "DNA_version", "get_plugin_version"]
