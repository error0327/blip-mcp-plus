"""
blip-mcp: Model Context Protocol server and CLI for Blip file transfer (blip.net).
Enables seamless zero-click file dispatch from AI agents and terminal directly to mobile devices.
"""

from blip_mcp.core import (
    BlipClient,
    BlipContext,
    Device,
    TransferRecord,
    TransferResult,
)

__version__ = "0.1.0"
__all__ = [
    "BlipClient",
    "BlipContext",
    "Device",
    "TransferRecord",
    "TransferResult",
    "__version__",
]
