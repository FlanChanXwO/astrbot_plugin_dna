"""解析根目录 CHANGELOG 的正式版本段并生成发布说明。

该脚本只处理根 CHANGELOG 的固定用户向格式，不读取 docs/porting/ 等历史文档，
供发布 workflow 和本地检查复用。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Iterable, Sequence

_VERSION_RE = re.compile(r"v?\d+\.\d+\.\d+")
_RELEASE_HEADING_RE = re.compile(
    r"^## \[(?P<version>v\d+\.\d+\.\d+)\] - "
    r"(?P<date>\d{4}-\d{2}-\d{2})$"
)
_VERSION_HEADING_HINT_RE = re.compile(r"^##\s+.*v?\d+\.\d+\.\d+")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_TAG_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class ReleaseNotes:
    """一个可发布版本的标题元数据和正文。"""

    version: str
    date: str
    body: str


@dataclass(frozen=True, slots=True)
class _Heading:
    """内部保存 heading 的行号和解析结果。"""

    line_index: int
    version: str
    date: str


def _normalise_version(version: str) -> str:
    candidate = version.strip()
    if not _VERSION_RE.fullmatch(candidate):
        raise ValueError(f"版本号必须是三段式 SemVer：{version!r}")
    return candidate if candidate.startswith("v") else f"v{candidate}"


def _parse_release_headings(lines: Sequence[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    for line_index, line in enumerate(lines):
        match = _RELEASE_HEADING_RE.fullmatch(line)
        if match is not None:
            release_date = match.group("date")
            try:
                date.fromisoformat(release_date)
            except ValueError as error:
                raise ValueError(
                    f"版本 {match.group('version')} 的日期无效：{release_date}"
                ) from error
            headings.append(
                _Heading(
                    line_index=line_index,
                    version=match.group("version"),
                    date=release_date,
                )
            )
            continue

        # 版本 heading 不能因为拼写、日期或括号格式错误而被静默跳过。
        if _VERSION_HEADING_HINT_RE.match(line):
            raise ValueError(f"无法解析 CHANGELOG 版本 heading：{line}")

    if not headings:
        raise ValueError(
            "CHANGELOG 中没有符合固定格式的版本 heading：## [vX.Y.Z] - YYYY-MM-DD"
        )

    seen: set[str] = set()
    for heading in headings:
        if heading.version in seen:
            raise ValueError(f"CHANGELOG 中出现重复版本 heading：{heading.version}")
        seen.add(heading.version)
    return headings


def parse_changelog(text: str, *, version: str | None = None) -> ReleaseNotes:
    """解析指定版本；未指定时解析根 CHANGELOG 的首个正式版本段。"""

    if not text.strip():
        raise ValueError("CHANGELOG 内容为空")

    lines = text.splitlines()
    headings = _parse_release_headings(lines)
    target_version = (
        _normalise_version(version) if version is not None else headings[0].version
    )

    target_index = next(
        (
            index
            for index, heading in enumerate(headings)
            if heading.version == target_version
        ),
        None,
    )
    if target_index is None:
        raise ValueError(f"CHANGELOG 中未找到版本：{target_version}")

    heading = headings[target_index]
    section_end = (
        headings[target_index + 1].line_index
        if target_index + 1 < len(headings)
        else len(lines)
    )
    body = "\n".join(lines[heading.line_index + 1 : section_end]).strip()
    if not body:
        raise ValueError(f"版本 {target_version} 的发布内容为空")

    return ReleaseNotes(version=heading.version, date=heading.date, body=body)


def release_tag(version: str, *, tag_prefix: str = "") -> str:
    """按 workflow 约定生成 tag，并拒绝会破坏输出协议的控制字符。"""

    normalised_version = _normalise_version(version)
    if _CONTROL_CHARACTER_RE.search(tag_prefix):
        raise ValueError("tag 前缀不能包含控制字符")
    if tag_prefix and _TAG_PREFIX_RE.fullmatch(tag_prefix) is None:
        raise ValueError(
            "tag 前缀只能包含 ASCII 字母、数字、点、下划线和连字符，且必须以字母或数字开头"
        )
    if ".." in tag_prefix:
        raise ValueError("tag 前缀不能包含连续点")
    return f"{tag_prefix}{normalised_version[1:]}" if tag_prefix else normalised_version


def _write_github_output(path: Path, values: Iterable[tuple[str, str]]) -> None:
    with path.open("a", encoding="utf-8") as output:
        for key, value in values:
            if "\n" in value or "\r" in value:
                raise ValueError(f"GitHub Actions 输出值 {key!r} 不能包含换行")
            output.write(f"{key}={value}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--changelog",
        type=Path,
        default=Path("CHANGELOG.md"),
        help="要解析的 CHANGELOG 文件，默认是根目录 CHANGELOG.md",
    )
    parser.add_argument(
        "--version",
        help="要发布的版本；省略时使用文件中的首个正式版本",
    )
    parser.add_argument(
        "--tag-prefix",
        default="",
        help="tag 前缀；留空时直接使用 vX.Y.Z",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="将发布正文写入指定文件",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="追加 version/date/tag/notes_file 到 GitHub Actions 输出文件",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        release = parse_changelog(
            args.changelog.read_text(encoding="utf-8"),
            version=args.version,
        )
        tag = release_tag(release.version, tag_prefix=args.tag_prefix)

        if args.output is not None:
            args.output.write_text(f"{release.body}\n", encoding="utf-8")
            notes_file = str(args.output)
        else:
            notes_file = ""
            print(release.body)

        if args.github_output is not None:
            _write_github_output(
                args.github_output,
                (
                    ("version", release.version),
                    ("date", release.date),
                    ("tag", tag),
                    ("notes_file", notes_file),
                ),
            )
        print(
            f"Parsed {release.version} ({release.date}); "
            f"release tag: {tag}; notes file: {notes_file or '<stdout>'}",
            file=sys.stderr,
        )
    except ValueError as error:
        print(f"release_notes: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["ReleaseNotes", "main", "parse_changelog", "release_tag"]
