"""Jinja environment for the built-in login HTTP pages."""

from __future__ import annotations

import base64
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

LOGIN_TEMPLATE_ROOT = Path(__file__).parents[2] / "templates"
_PLUGIN_LOGO_PATH = Path(__file__).parents[3] / "logo.png"

LOGIN_TEMPLATES = Environment(loader=FileSystemLoader(str(LOGIN_TEMPLATE_ROOT)))
LOGIN_TEMPLATES.globals["plugin_logo"] = "data:image/png;base64," + base64.b64encode(
    _PLUGIN_LOGO_PATH.read_bytes()
).decode("ascii")

__all__ = ["LOGIN_TEMPLATES", "LOGIN_TEMPLATE_ROOT"]
