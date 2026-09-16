from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
CHECKBOX_RE = re.compile(r"^-\s*\[[ xX]\]\s*(.+?)\s*$")
HTML_COMMENT_RE = re.compile(r"<!--.*?-->", re.DOTALL)


def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    return Path(path).read_text(encoding="utf-8")


def _headings(text: str) -> list[str]:
    return [
        match.group(2).strip()
        for line in text.splitlines()
        if (match := HEADING_RE.match(line.strip())) is not None
    ]


def _checkbox_labels(text: str) -> list[str]:
    return [
        match.group(1).strip()
        for line in text.splitlines()
        if (match := CHECKBOX_RE.match(line.strip())) is not None
    ]


def _visible_text(text: str) -> str:
    return HTML_COMMENT_RE.sub("", text).strip()


def _section_body(text: str, heading: str, next_heading: str | None) -> str:
    start = text.find(heading)
    if start < 0:
        return ""
    start = text.find("\n", start)
    if start < 0:
        return ""
    end = len(text)
    if next_heading is not None:
        candidate = text.find(next_heading, start + 1)
        if candidate >= 0:
            end = candidate
    return _visible_text(text[start:end])


def validate(template: str, body: str) -> list[str]:
    errors: list[str] = []
    template_headings = _headings(template)
    body_headings = _headings(body)

    cursor = 0
    for heading in template_headings:
        try:
            index = body_headings.index(heading, cursor)
        except ValueError:
            errors.append(f"missing or out-of-order heading: {heading}")
            continue
        cursor = index + 1

    for label in _checkbox_labels(template):
        count = _checkbox_labels(body).count(label)
        if count == 0:
            errors.append(f"missing template checkbox: {label}")
        elif count > 1:
            errors.append(f"duplicate template checkbox: {label}")

    first_heading = template_headings[0] if template_headings else None
    if first_heading is not None:
        marker = f"### {first_heading}"
        prefix = body.split(marker, 1)[0]
        if not _visible_text(prefix):
            errors.append("missing motivation text before the first template section")

    test_heading = next(
        (heading for heading in template_headings if "Test Results" in heading),
        None,
    )
    if test_heading is not None:
        test_index = template_headings.index(test_heading)
        next_heading = (
            f"### {template_headings[test_index + 1]}"
            if test_index + 1 < len(template_headings)
            else None
        )
        if not _section_body(body, f"### {test_heading}", next_heading):
            errors.append(f"empty verification section: {test_heading}")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate a PR body against the repository PR template structure."
    )
    parser.add_argument(
        "--template",
        default=".github/PULL_REQUEST_TEMPLATE.md",
        help="PR template path; use the target branch version.",
    )
    parser.add_argument(
        "--body",
        required=True,
        help="PR body path, or '-' to read the body from stdin.",
    )
    args = parser.parse_args()

    errors = validate(_read_text(args.template), _read_text(args.body))
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print("PR body matches required template structure.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
