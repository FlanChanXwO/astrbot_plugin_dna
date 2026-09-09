"""Structural contracts for the compact built-in login page."""

from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment, select_autoescape

TEMPLATE = Path(__file__).resolve().parents[1] / "src/templates/index.html.j2"


class _LoginParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.form_depth = 0
        self.controls: dict[str, dict[str, str | None]] = {}
        self.form_controls: set[str] = set()
        self.external_scripts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "form":
            self.form_depth += 1
        if identifier := attributes.get("id"):
            self.controls[identifier] = attributes
            if self.form_depth:
                self.form_controls.add(identifier)
        if tag == "script" and attributes.get("src"):
            self.external_scripts.append(str(attributes["src"]))

    def handle_endtag(self, tag: str) -> None:
        if tag == "form":
            self.form_depth -= 1


def _render(*, media: bool = True) -> tuple[str, _LoginParser]:
    environment = Environment(autoescape=select_autoescape(default=True))
    page = environment.from_string(TEMPLATE.read_text(encoding="utf-8")).render(
        plugin_logo="/logo.png",
        userId="not-for-display",
        auth="test-session",
        server_url="/test",
        login_media=(
            {"video_url": "/media/background.mp4", "audio_url": "/media/background.mp3"}
            if media
            else None
        ),
    )
    parser = _LoginParser()
    parser.feed(page)
    return page, parser


def test_media_controls_are_inside_the_form_and_do_not_submit() -> None:
    _, parser = _render()
    for identifier in ("audioToggle", "motionToggle"):
        assert identifier in parser.form_controls
        control = parser.controls[identifier]
        assert control["type"] == "button"
        assert control["aria-label"]
        assert control["aria-pressed"] == "false"
        assert "hidden" in control


def test_page_does_not_load_sdk_or_soundtrack_during_initial_parse() -> None:
    _, parser = _render()
    assert not parser.external_scripts
    for identifier in ("backgroundVideo", "backgroundAudio"):
        assert "src" not in parser.controls[identifier]
        assert parser.controls[identifier]["preload"] == "none"
    assert "playsinline" in parser.controls["backgroundVideo"]
    assert "muted" in parser.controls["backgroundVideo"]


def test_static_mode_has_no_media_elements_or_urls() -> None:
    page, parser = _render(media=False)
    assert (
        not {"backgroundVideo", "backgroundAudio", "audioToggle", "motionToggle"}
        & parser.controls.keys()
    )
    assert "/media/background." not in page
    assert {"phone", "verificationCode", "loginBtn"} <= parser.form_controls


def test_page_keeps_form_semantics_without_walkthrough_or_public_identifier() -> None:
    page, parser = _render()
    assert "verification-guide" not in page
    assert "guide-steps" not in page
    assert "not-for-display" not in page
    assert parser.controls["phone"]["autocomplete"] == "tel-national"
    assert parser.controls["verificationCode"]["autocomplete"] == "one-time-code"
    assert parser.controls["formStatus"]["aria-live"] == "polite"
    assert "backdrop-filter" not in page
    assert "prefers-reduced-motion: reduce" in page
    assert "visibilitychange" in page
