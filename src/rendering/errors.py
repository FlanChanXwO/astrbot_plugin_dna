import sys

from ..infrastructure.rendering import errors as _errors

sys.modules[__name__] = _errors
