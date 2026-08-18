import sys

from ..infrastructure.rendering import assets as _assets

sys.modules[__name__] = _assets
