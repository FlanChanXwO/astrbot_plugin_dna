import sys

from ..infrastructure.rendering import renderer as _renderer

sys.modules[__name__] = _renderer
