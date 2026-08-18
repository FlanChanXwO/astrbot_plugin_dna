import sys

from ..infrastructure.rendering import payloads as _payloads

sys.modules[__name__] = _payloads
