from __future__ import annotations

import hashlib
import unittest
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_BRANDING_SHA256 = (
    "947a6d4d89bf1edee1ccbab0718bc5d81b62f7009ba789f78cb23da72fb867e9"
)


class BrandingAssetsTests(unittest.TestCase):
    def test_logo_and_help_avatar_are_the_new_256px_rgba_asset(self) -> None:
        assets = (ROOT / "ICON.png", ROOT / "logo.png")

        for asset in assets:
            self.assertTrue(asset.is_file(), asset)
            self.assertEqual(
                hashlib.sha256(asset.read_bytes()).hexdigest(),
                EXPECTED_BRANDING_SHA256,
                asset,
            )
            with Image.open(asset) as image:
                self.assertEqual(image.size, (256, 256), asset)
                self.assertEqual(image.mode, "RGBA", asset)

        self.assertEqual(assets[0].read_bytes(), assets[1].read_bytes())

    def test_help_avatar_uses_a_fixed_layout_box(self) -> None:
        template = (ROOT / "src" / "templates" / "cards" / "help.html.j2").read_text(
            encoding="utf-8",
        )

        self.assertIn(
            ".help-card__icon-frame { position: absolute; top: 507px; left: 116px; width: 175px; height: 175px;",
            template,
        )
        self.assertIn(
            "border: 8px solid rgba(255, 255, 255, .85); border-radius: 50%; overflow: hidden;",
            template,
        )
        self.assertIn(
            ".help-card__icon { display: block; width: 100%; height: 100%; object-fit: cover; }",
            template,
        )
        self.assertIn(
            '<div class="help-card__icon-frame">\n  <img class="help-card__icon"',
            template,
        )


if __name__ == "__main__":
    unittest.main()
