"""公共资源 Git 同步接口。

同步器只调用参数列表形式的 ``git``，不经过 shell；它不会 force checkout、
删除本地目录或覆盖本地修改。首次同步使用 ``main`` 的浅克隆，后续只允许
``git pull --ff-only --no-tags origin main``，所有失败通过异常显露给上层。
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .acceleration import (
    build_git_instead_of_config,
    normalize_github_repository_url,
    normalize_http_base_url,
)
from .manifest import ResourceManifest
from .paths import default_resource_repository_dir, resource_repository_dir

DEFAULT_RESOURCE_REMOTE = (
    "https://github.com/FlanChanXwO/astrbot_plugin_dna_resources.git"
)


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


class ResourceBranchMismatchError(ResourceSyncError):
    """资源 checkout 未停在唯一受支持的 main 分支。"""

    def __init__(self) -> None:
        super().__init__("资源 Git 当前 checkout 不是 main 分支")


class ResourceLocalChangesError(ResourceSyncError):
    """资源仓库有本地修改，不允许自动覆盖。"""

    def __init__(self, status: str) -> None:
        super().__init__(
            f"资源仓库存在本地修改，已停止同步，不会覆盖：{status.strip()}"
        )


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


def _git_operation(args: tuple[str, ...]) -> str:
    """从可能带临时 ``-c`` 参数的 Git 参数中取得子命令名。"""

    index = 0
    while index < len(args) and args[index] == "-c":
        index += 2
    return args[index] if index < len(args) else "command"


def run_git(args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
    """通过参数列表执行 Git；不把参数拼接为 shell 命令。"""

    executable = shutil.which("git")
    if executable is None:
        raise GitUnavailableError
    operation = _git_operation(args)
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
        acceleration_prefix: str | None = None,
        runner: GitRunner = run_git,
    ) -> None:
        self.repository = Path(repository)
        self.remote = normalize_github_repository_url(remote)
        normalized_prefix = normalize_http_base_url(acceleration_prefix or "")
        self.acceleration_prefix = normalized_prefix or None
        self._runner = runner

    def _configured_args(self, args: tuple[str, ...]) -> tuple[str, ...]:
        # 只有会访问远端的命令需要镜像替换；对 remote get-url 等本地状态查询
        # 注入 insteadOf 会让 Git 输出被改写后的镜像 URL，破坏 origin 契约校验。
        if self.acceleration_prefix is None or _git_operation(args) not in {
            "clone",
            "fetch",
            "pull",
        }:
            return args
        return ("-c", build_git_instead_of_config(self.acceleration_prefix), *args)

    def _run(self, args: tuple[str, ...], cwd: Path | None = None) -> GitCommandResult:
        configured_args = self._configured_args(args)
        try:
            result = self._runner(configured_args, cwd)
        except ResourceSyncError:
            raise
        except OSError as exc:
            raise GitCommandError(_git_operation(args), str(exc)) from exc
        if result.returncode:
            raise GitCommandError(_git_operation(args), result.stderr or result.stdout)
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

        branch = self._run(("symbolic-ref", "--short", "HEAD"), self.repository)
        if branch.stdout.strip() != "main":
            raise ResourceBranchMismatchError

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
                (
                    "clone",
                    "--depth",
                    "1",
                    "--single-branch",
                    "--branch",
                    "main",
                    "--no-tags",
                    self.remote,
                    str(self.repository),
                ),
                self.repository.parent,
            )
            action = "cloned"
            self._validate_git_state()
        else:
            self._validate_git_state()
            self._run(
                ("pull", "--ff-only", "--no-tags", "origin", "main"),
                self.repository,
            )
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
    acceleration_prefix: str | None = None,
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
    return ResourceSynchronizer(
        target,
        remote=remote,
        acceleration_prefix=acceleration_prefix,
        runner=runner,
    ).sync()


__all__ = [
    "DEFAULT_RESOURCE_REMOTE",
    "GitCommandError",
    "GitCommandResult",
    "GitUnavailableError",
    "ResourceBranchMismatchError",
    "ResourceLocalChangesError",
    "ResourceRemoteMismatchError",
    "ResourceSyncError",
    "ResourceSyncResult",
    "ResourceSynchronizer",
    "download_all_resources",
    "run_git",
]
