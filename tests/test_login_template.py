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
            {"video_url": "/media/background.mp4"}
            if media
            else None
        ),
    )
    parser = _LoginParser()
    parser.feed(page)
    return page, parser


def test_no_audio_or_playback_buttons_rendered_in_login_page() -> None:
    page, parser = _render()
    assert "audioToggle" not in parser.form_controls
    assert "audioToggle" not in parser.controls
    assert "audioToggle" not in page
    assert "motionToggle" not in parser.controls
    assert "motionToggle" not in page
    assert "media-controls" not in page
    assert "backgroundAudio" not in parser.controls
    assert "backgroundAudio" not in page
    assert "开启音乐" not in page
    assert "静音" not in page
    assert "audio_url" not in page


def test_page_renders_video_when_media_present_and_defers_loading() -> None:
    _, parser = _render()
    assert not parser.external_scripts
    assert "backgroundVideo" in parser.controls
    assert "src" not in parser.controls["backgroundVideo"]
    assert parser.controls["backgroundVideo"]["preload"] == "none"
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


def test_captcha_loading_has_no_arbitrary_timeout_and_preserves_error_handlers() -> None:
    page, _ = _render()
    assert "15000" not in page
    assert "clearTimeout" not in page
    assert "script.onerror = fail" in page
    assert "script.async = true" in page
