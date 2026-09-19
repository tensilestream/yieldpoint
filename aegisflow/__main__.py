"""``python -m aegisflow`` — the same CLI, without needing anything on PATH.

Worth having for one practical reason: an MCP server registered as a bare
``aegisflow`` command fails silently when the console script is not on the
client's PATH, which is common with virtualenvs, conda, and editors launched
from a desktop icon rather than a shell. ``sys.executable -m aegisflow`` always
resolves to the interpreter that installed the package.
"""

from .cli import main

raise SystemExit(main())
