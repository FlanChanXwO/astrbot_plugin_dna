"""公共资源 Git 同步接口。

同步器只调用参数列表形式的 ``git``，不经过 shell；它不会 force checkout、
删除本地目录或覆盖本地修改。首次同步使用浅克隆，后续只允许
``git pull --ff-only``，所有失败通过异常显露给上层。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .manifest import ResourceManifest
from .paths import default_resource_repository_dir, resource_repository_dir

DEFAULT_RESOURCE_REMOTE = "https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git"


class ResourceSyncError(RuntimeError):
    """资源仓库同步失败。"""


class GitUnavailableError(ResourceSyncError):
    """系统未提供 Git 可执行文件。"""

    def __init__(self) -> None:
        super().__init__("未找到 git 可执行文件，无法同步公共资源仓库")


def _redact_git_detail(detail: str) -> str:
    """移除 URL userinfo、常见 query token 和 Bearer 值，避免错误回显凭据。"""

    safe_detail = re.sub(
        r"(https?://)[^/@\s]+@",
        r"\1<redacted>@",
        detail,
        flags=re.IGNORECASE,
    )
    safe_detail = re.sub(
        r"([?&](?:access_token|token|password|secret)=)[^&\s]+",
        r"\1<redacted>",
        safe_detail,
        flags=re.IGNORECASE,
    )
    return re.sub(
        r"(Bearer\s+)[^\s]+",
        r"\1<redacted>",
        safe_detail,
        flags=re.IGNORECASE,
    )


class GitCommandError(ResourceSyncError):
    """Git 子命令返回失败状态。"""

    def __init__(self, operation: str, detail: str) -> None:
        safe_detail = _redact_git_detail(detail).strip()
        suffix = f": {safe_detail}" if safe_detail else ""
        super().__init__(f"资源 Git {operation} 失败（凭据已脱敏）{suffix}")


class ResourceRemoteMismatchError(ResourceSyncError):
    """仓库 origin 与预期公共资源仓库不一致。"""

    def __init__(self) -> None:
        super().__init__("资源 Git origin 与配置的公共资源仓库不一致")


class ResourceLocalChangesError(ResourceSyncError):
    """资源仓库有本地修改，不允许自动覆盖。"""

    def __init__(self, status: str) -> None:
        super().__init__(f"资源仓库存在本地修改，已停止同步，不会覆盖：{status.strip()}")


@dataclass(frozen=True, slots=True)
class GitCommandResult:
    """可注入 Git runner 的最小返回值。"""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


class GitRunner(Protocol):
    def __call__(
        self,
        args: tuple[str, ...],
        cwd: Path | None = None,
    ) -> GitCommandResult: ...


def run_git(args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
    """通过参数列表执行 Git；不把参数拼接为 shell 命令。"""

    executable = shutil.which("git")
    if executable is None:
        raise GitUnavailableError
    operation = args[0] if args else "command"
    try:
        completed = subprocess.run(
            (executable, *args),
            cwd=cwd,
            capture_output=True,
            check=False,
            text=True,
        )
    except OSError as exc:
        raise GitCommandError(operation, str(exc)) from exc
    result = GitCommandResult(
        returncode=completed.returncode,
        stdout=completed.stdout,
        stderr=completed.stderr,
    )
    if result.returncode:
        raise GitCommandError(operation, result.stderr or result.stdout)
    return result


@dataclass(frozen=True, slots=True)
class ResourceSyncResult:
    """一次资源同步后经过校验的结果。"""

    repository: Path
    action: str
    resource_version: str


class ResourceSynchronizer:
    """同步并验证公共资源 Git 仓库。"""

    def __init__(
        self,
        repository: str | Path,
        *,
        remote: str = DEFAULT_RESOURCE_REMOTE,
        runner: GitRunner = run_git,
    ) -> None:
        if not remote or any(character in remote for character in "\0\r\n"):
            raise ValueError("资源 Git remote 不能为空或包含控制字符")
        self.repository = Path(repository)
        self.remote = remote
        self._runner = runner

    def _run(self, args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
        try:
            result = self._runner(args, cwd)
        except ResourceSyncError:
            raise
        except OSError as exc:
            raise GitCommandError(args[0] if args else "command", str(exc)) from exc
        if result.returncode:
            raise GitCommandError(args[0] if args else "command", result.stderr)
        return result

    def _validate_git_state(self) -> None:
        worktree = self._run(
            ("rev-parse", "--is-inside-work-tree"),
            self.repository,
        )
        if worktree.stdout.strip() != "true":
            raise ResourceSyncError("资源目录不是有效的 Git worktree")

        origin = self._run(("remote", "get-url", "origin"), self.repository)
        if origin.stdout.strip() != self.remote:
            raise ResourceRemoteMismatchError

        status = self._run(
            ("status", "--porcelain", "--untracked-files=all"),
            self.repository,
        )
        if status.stdout.strip():
            raise ResourceLocalChangesError(status.stdout)

    def _validate_manifest(self) -> ResourceManifest:
        return ResourceManifest.load(
            self.repository / "resource_manifest.json"
        ).validate_runtime_layout(self.repository)

    def validate(self) -> ResourceManifest:
        """检查 Git 状态、origin 和 manifest，但不拉取远端。"""

        self._validate_git_state()
        return self._validate_manifest()

    def sync(self) -> ResourceSyncResult:
        """首次浅克隆，之后 fast-forward-only 更新并校验 manifest。"""

        if not self.repository.exists():
            self.repository.parent.mkdir(parents=True, exist_ok=True)
            self._run(
                ("clone", "--depth", "1", self.remote, str(self.repository)),
                self.repository.parent,
            )
            action = "cloned"
            self._validate_git_state()
        else:
            self._validate_git_state()
            self._run(("pull", "--ff-only"), self.repository)
            action = "updated"
            self._validate_git_state()

        manifest = self._validate_manifest()
        return ResourceSyncResult(
            repository=self.repository,
            action=action,
            resource_version=manifest.resource_version,
        )


def download_all_resources(
    repository: str | Path | None = None,
    *,
    data_dir: str | Path | None = None,
    remote: str = DEFAULT_RESOURCE_REMOTE,
    runner: GitRunner = run_git,
) -> ResourceSyncResult:
    """下载并验证全部公共资源；首次浅克隆，后续 fast-forward-only 更新。"""

    if repository is not None and data_dir is not None:
        raise ValueError("repository 与 data_dir 只能指定一个")
    target = (
        Path(repository)
        if repository is not None
        else (
            resource_repository_dir(data_dir)
            if data_dir is not None
            else default_resource_repository_dir()
        )
    )
    return ResourceSynchronizer(target, remote=remote, runner=runner).sync()


__all__ = [
    "DEFAULT_RESOURCE_REMOTE",
    "GitCommandError",
    "GitCommandResult",
    "GitUnavailableError",
    "ResourceLocalChangesError",
    "ResourceRemoteMismatchError",
    "ResourceSyncError",
    "ResourceSyncResult",
    "ResourceSynchronizer",
    "download_all_resources",
    "run_git",
]
