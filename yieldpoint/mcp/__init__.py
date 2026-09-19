"""Model Context Protocol server.

Exposes verification to any MCP-speaking editor or agent. See `tools.py` for
what is offered and `server.py` for the transport.
"""

from .server import serve
from .tools import TOOLS, call

__all__ = ["serve", "TOOLS", "call"]
