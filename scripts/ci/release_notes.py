"""解析根目录 CHANGELOG，并生成统一格式的 GitHub Release 发布说明。"""

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
    r"^## (?P<version>v\d+\.\d+\.\d+) — (?P<date>\d{4}-\d{2}-\d{2})$"
)
_LEGACY_RELEASE_HEADING_RE = re.compile(
    r"^## \[(?P<version>v\d+\.\d+\.\d+)\] - "
    r"(?P<date>\d{4}-\d{2}-\d{2})$"
)
_VERSION_HEADING_HINT_RE = re.compile(r"^##\s+.*v?\d+\.\d+\.\d+")
_CATEGORY_HEADING_RE = re.compile(r"^### (?P<title>.+)$")
_CONTROL_CHARACTER_RE = re.compile(r"[\x00-\x1f\x7f]")
_TAG_PREFIX_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True, slots=True)
class ReleaseNotes:
    """一个正式版本的版本号、日期和 CHANGELOG 正文。"""

    version: str
    date: str
    body: str


@dataclass(frozen=True, slots=True)
class _Heading:
    """内部保存版本标题的行号和解析结果。"""

    line_index: int
    version: str
    date: str


def _normalise_version(version: str) -> str:
    candidate = version.strip()
    if not _VERSION_RE.fullmatch(candidate):
        raise ValueError(f"版本号必须是三段式 SemVer：{version!r}")
    return candidate if candidate.startswith("v") else f"v{candidate}"


def _match_release_heading(line: str) -> re.Match[str] | None:
    return _RELEASE_HEADING_RE.fullmatch(line) or _LEGACY_RELEASE_HEADING_RE.fullmatch(
        line
    )


def _parse_release_headings(lines: Sequence[str]) -> list[_Heading]:
    headings: list[_Heading] = []
    for line_index, line in enumerate(lines):
        match = _match_release_heading(line)
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

        if _VERSION_HEADING_HINT_RE.match(line):
            raise ValueError(f"无法解析 CHANGELOG 版本标题：{line}")

    if not headings:
        raise ValueError(
            "CHANGELOG 中没有符合固定格式的版本标题：## vX.Y.Z — YYYY-MM-DD"
        )

    seen: set[str] = set()
    for heading in headings:
        if heading.version in seen:
            raise ValueError(f"CHANGELOG 中出现重复版本标题：{heading.version}")
        seen.add(heading.version)
    return headings


def parse_all_changelog(text: str) -> list[ReleaseNotes]:
    """按 CHANGELOG 中的顺序解析全部正式版本。"""

    if not text.strip():
        raise ValueError("CHANGELOG 内容为空")

    lines = text.splitlines()
    headings = _parse_release_headings(lines)
    releases: list[ReleaseNotes] = []
    for index, heading in enumerate(headings):
        section_end = (
            headings[index + 1].line_index if index + 1 < len(headings) else len(lines)
        )
        body = "\n".join(lines[heading.line_index + 1 : section_end]).strip()
        if not body:
            raise ValueError(f"版本 {heading.version} 的发布内容为空")
        releases.append(
            ReleaseNotes(version=heading.version, date=heading.date, body=body)
        )
    return releases


def parse_changelog(text: str, *, version: str | None = None) -> ReleaseNotes:
    """解析指定版本；未指定时返回 CHANGELOG 中的首个正式版本。"""

    releases = parse_all_changelog(text)
    if version is None:
        return releases[0]

    target_version = _normalise_version(version)
    release = next(
        (item for item in releases if item.version == target_version),
        None,
    )
    if release is None:
        raise ValueError(f"CHANGELOG 中未找到版本：{target_version}")
    return release


def render_release_notes(release: ReleaseNotes) -> str:
    """把 CHANGELOG 层级转换成与项目 Release 页面一致的独立发布说明。"""

    body_lines: list[str] = []
    for line in release.body.splitlines():
        category = _CATEGORY_HEADING_RE.fullmatch(line)
        if category is not None:
            body_lines.append(f"## {category.group('title')}")
        else:
            body_lines.append(line)
    body = "\n".join(body_lines).strip()
    return f"# {release.version} — {release.date}\n\n{body}\n"


def release_tag(version: str, *, tag_prefix: str = "") -> str:
    """按发布 workflow 约定生成 tag。"""

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


def _write_all_release_notes(
    releases: Sequence[ReleaseNotes],
    *,
    output_dir: Path,
    manifest: Path,
    tag_prefix: str,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest.parent.mkdir(parents=True, exist_ok=True)

    rows: list[str] = []
    for release in releases:
        tag = release_tag(release.version, tag_prefix=tag_prefix)
        notes_file = output_dir / f"{release.version}.md"
        notes_file.write_text(render_release_notes(release), encoding="utf-8")
        rows.append(f"{tag}\t{notes_file}")
    manifest.write_text("\n".join(rows) + "\n", encoding="utf-8")


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
        help="将单个版本的发布正文写入指定文件",
    )
    parser.add_argument(
        "--github-output",
        type=Path,
        help="追加 version/date/tag/notes_file 到 GitHub Actions 输出文件",
    )
    parser.add_argument(
        "--all-output-dir",
        type=Path,
        help="将全部版本的独立发布说明写入指定目录",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        help="写出全部版本的 tag 与发布说明文件清单",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    try:
        text = args.changelog.read_text(encoding="utf-8")
        releases = parse_all_changelog(text)
        release = parse_changelog(text, version=args.version)
        tag = release_tag(release.version, tag_prefix=args.tag_prefix)

        if (args.all_output_dir is None) != (args.manifest is None):
            raise ValueError("批量生成时必须同时提供 --all-output-dir 和 --manifest")
        if args.all_output_dir is not None and args.manifest is not None:
            _write_all_release_notes(
                releases,
                output_dir=args.all_output_dir,
                manifest=args.manifest,
                tag_prefix=args.tag_prefix,
            )

        if args.output is not None:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(render_release_notes(release), encoding="utf-8")
            notes_file = str(args.output)
        else:
            notes_file = ""
            if args.all_output_dir is None:
                print(render_release_notes(release), end="")

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
            f"已解析 {len(releases)} 个版本；当前版本 {release.version} "
            f"（{release.date}），发布标签：{tag}",
            file=sys.stderr,
        )
    except ValueError as error:
        print(f"发布说明解析失败：{error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ReleaseNotes",
    "main",
    "parse_all_changelog",
    "parse_changelog",
    "release_tag",
    "render_release_notes",
]
